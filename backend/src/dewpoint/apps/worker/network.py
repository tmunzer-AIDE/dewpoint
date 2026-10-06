# SPDX-License-Identifier: Apache-2.0
"""A step attempt's network (plugins-3 D4, D5, D7, D9, D10): `ctx.http`, `ctx.net` and `ctx.connection()`.

- A step opens only a connection its own node names, as a literal of a field its node type marks, in its run's version,
  which publish also recorded in `connection_ids`; of a type the node declares; in the activity's tenant. Anything else
  is `ConnectionUnavailable`, before anything is sent.
- The secret is read and decrypted on every call, never cached; its strings join the run tree's secret index before
  anything is sent; the runtime applies it (the plugin never holds it, nor can it change the credentials or the
  origin).
- Every request through a connection takes a token from each of its quota scopes, or fails `Cooldown` having sent
  nothing. A provider's `Retry-After` blocks the scopes for every run; a node whose requests may be repeated waits out
  a short one inside the attempt, any other fails `RateLimited`.
- A simulated step sends nothing. The attempt's connections are one pool, closed when the attempt ends.
- The attempt remembers once a request may have left it (`may_have_sent`): the wrapper then never lets an ambiguous
  node's failure be retried, whatever the failure that ended it."""

import asyncio
import email.utils
import json
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
from dewpoint.core.connections.declared import DeclaredType, InvalidValueError
from dewpoint.core.connections.service import PURPOSE as SECRET_PURPOSE
from dewpoint.core.crypto.keys import KeySource, key_unreadable
from dewpoint.core.db import tenant_scope, unavailable
from dewpoint.core.egress.guard import (
    EgressRefusedError,
    Guard,
    InvalidRequestError,
    MaybeSentError,
    NotSentError,
    TlsVerificationError,
)
from dewpoint.core.egress.http import (
    GuardedHttp,
    HttpLimits,
    HttpResponse,
    RedirectRefusedError,
    ResponseTooLargeError,
    ResponseUnreadableError,
)
from dewpoint.core.egress.net import GuardedNet, GuardedStream, NetLimits
from dewpoint.core.models.connections import Connection as ConnectionRow
from dewpoint.core.models.runs import Run
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.ratelimit import scopes as rate_scopes
from dewpoint.core.ratelimit.buckets import CooldownError, Scope, acquire, block
from dewpoint.sdk import (
    ConnectionType,
    ConnectionUnavailable,
    Cooldown,
    EgressRefused,
    InvalidRequest,
    MaybeSent,
    Node,
    NotSent,
    Plugin,
    RateLimited,
    ReadOnly,
    RedirectRefused,
    ResponseTooLarge,
    ResponseUnreadable,
    SideEffect,
    SimulationSendsNothing,
    TlsVerificationFailed,
    TransportError,
)
from dewpoint.sdk.fields import CONNECTION

_log = structlog.get_logger("dewpoint.worker")
IN_ATTEMPT_WAIT_S = 20.0  # the longest Retry-After a node whose requests may repeat waits out in its attempt (D10)
IN_ATTEMPT_RETRIES = 3  # and how many times at most, each wait at least MIN_WAIT_S
MIN_WAIT_S = 1.0
MAX_RETRY_AFTER_S = 3600  # a provider's wait past an hour is read as an hour (a block's cap)
# Nodes that may resend inside their attempt: a reconcilable node's retry checks for its effect first (`reconcile()`),
# which only the engine's next attempt does; an ambiguous node never resends.
RESENDS = (SideEffect.NONE, SideEffect.IDEMPOTENT, SideEffect.KEYED)
NOTHING_SENT = (NotSentError, EgressRefusedError, InvalidRequestError, TlsVerificationError)
SCOPE_WAIT_S = 10.0  # the longest wait for a quota token before `Cooldown` (D9)
MIN_SECRET = 4  # the secret index's shortest string (engine 2b spec §3.7)
URL_PART = 8  # a secret URL's path segments and query values this long are secrets too
type Remember = Callable[[str, str, Sequence[str]], Awaitable[object]]


def mapped(error: Exception) -> TransportError:
    """A core network failure as the SDK names it: what happened to the request, never the host or an address."""
    if isinstance(error, EgressRefusedError):
        return EgressRefused()
    if isinstance(error, TlsVerificationError):
        return TlsVerificationFailed()
    if isinstance(error, InvalidRequestError):
        return InvalidRequest()
    if isinstance(error, NotSentError):
        return NotSent()
    if isinstance(error, RedirectRefusedError):
        return RedirectRefused()
    if isinstance(error, ResponseTooLargeError):
        return ResponseTooLarge()
    if isinstance(error, ResponseUnreadableError):
        return ResponseUnreadable()
    if isinstance(error, CooldownError):
        return Cooldown()
    return MaybeSent()


CORE_ERRORS = (
    EgressRefusedError,
    TlsVerificationError,
    InvalidRequestError,
    NotSentError,
    MaybeSentError,
    RedirectRefusedError,
    ResponseTooLargeError,
    ResponseUnreadableError,
)


@dataclass(frozen=True)
class StoredConnection:
    type: str
    config: Mapping[str, Any]
    secret_ct: bytes | None
    revision: int = 0


@dataclass(frozen=True)
class WorkerType:
    """A connection type as the worker uses it (plugins-3 D11): the declaration the API also reads, from which base URL,
    credentials and quota scopes are computed the same way on both sides, and the plugin's code (its models,
    `verify()`)."""

    declared: DeclaredType
    code: ConnectionType


def worker_types(plugins: Iterable[Plugin]) -> dict[str, WorkerType]:
    """The connection types the installed plugins declare, by key."""
    return {
        kind.key: WorkerType(DeclaredType.from_manifest(plugin.name, kind.manifest()), kind)
        for plugin in plugins
        for kind in plugin.connection_types
    }


class ConnectionSource(Protocol):
    async def named_by(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, step_id: uuid.UUID, node: type[Node]
    ) -> frozenset[uuid.UUID]: ...

    async def load(self, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> StoredConnection | None: ...


def connection_fields(node: type[Node]) -> list[str]:
    """The node type's connection fields: top-level config properties it marks (`connection_field`)."""
    props = node.Config.model_json_schema(mode="validation").get("properties", {})
    return [name for name, prop in props.items() if isinstance(prop, dict) and prop.get(CONNECTION)]


class DbConnections:
    """Connections as the worker role reads them, within the activity's tenant (RLS)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def named_by(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, step_id: uuid.UUID, node: type[Node]
    ) -> frozenset[uuid.UUID]:
        """The connections the step's node names in its run's version, which publish also recorded."""
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            found = await s.execute(
                select(WorkflowVersion.graph, WorkflowVersion.connection_ids)
                .join(Run, Run.workflow_version_id == WorkflowVersion.id)
                .where(Run.id == run_id, Run.tenant_id == tenant_id)
            )
            row = found.first()
        if row is None:
            return frozenset()
        graph, recorded = row
        nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
        mine = next((n for n in nodes if isinstance(n, dict) and n.get("id") == str(step_id)), None)
        if mine is None or mine.get("type") != f"{node.type}@{node.version}":
            return frozenset()
        written = mine.get("config")
        config: dict[str, Any] = written if isinstance(written, dict) else {}
        named: set[uuid.UUID] = set()
        for name in connection_fields(node):
            value = config.get(name)
            if not isinstance(value, str):
                continue
            try:
                named.add(uuid.UUID(value))
            except ValueError:
                continue
        return frozenset(named & set(recorded or ()))

    async def load(self, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> StoredConnection | None:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            found = await s.execute(
                select(ConnectionRow.type, ConnectionRow.config, ConnectionRow.secret_ct, ConnectionRow.revision).where(
                    ConnectionRow.id == connection_id, ConnectionRow.tenant_id == tenant_id
                )
            )
            row = found.first()
        return StoredConnection(row[0], dict(row[1]), row[2], row[3]) if row is not None else None


def secret_strings(secret: Mapping[str, Any]) -> list[str]:
    """Every string of a secret the index must know (D5): each value, and a secret URL's path and long parts."""
    out: list[str] = []
    for text in secret.values():
        if not isinstance(text, str) or len(text) < MIN_SECRET:
            continue
        out.append(text)
        if text.startswith(("http://", "https://")):
            try:
                url = httpx.URL(text)
            except (httpx.InvalidURL, ValueError):
                continue
            parts = [url.path, *url.path.split("/"), *(v for _, v in url.params.multi_items())]
            out.extend(p for p in parts if len(p) >= URL_PART)
    return sorted(set(out))


def retry_after_s(value: str | None, now: datetime) -> float | None:
    """A `Retry-After` header's wait in seconds, at most an hour: ASCII delta-seconds or an HTTP date; None when absent
    or unreadable. Nothing a provider sends raises."""
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(min(int(value[:10]), MAX_RETRY_AFTER_S)) if len(value) <= 10 else float(MAX_RETRY_AFTER_S)
    try:
        when = email.utils.parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return min(max(0.0, (when - now).total_seconds()), float(MAX_RETRY_AFTER_S))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


@dataclass(frozen=True)
class Network:
    """What the worker's steps and plugin calls reach the network with: one per process, an attempt's or a call's
    resources made from it. `types`: the installed plugins' connection types; a connection of any other is
    unavailable."""

    guard: Guard
    connections: ConnectionSource
    sessionmaker: async_sessionmaker[AsyncSession]
    keys: KeySource
    ssl_context: Any = None
    http_limits: HttpLimits = field(default_factory=HttpLimits)
    net_limits: NetLimits = field(default_factory=NetLimits)
    types: Mapping[str, WorkerType] = field(default_factory=dict)

    def attempt(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        step_id: uuid.UUID,
        root_run_id: uuid.UUID,
        node: type[Node],
        simulated: bool,
        remember: Remember,
        beat: Callable[[], None],
    ) -> "AttemptNetwork":
        return AttemptNetwork(self, tenant_id, run_id, step_id, root_run_id, node, simulated, remember, beat)


class Channel(Protocol):
    """What a connection's HTTP sends through: a step attempt's network, or a plugin call's (read-only)."""

    network: Network
    tenant_id: uuid.UUID

    @property
    def resends(self) -> bool: ...  # whether a request may be repeated after a short `Retry-After`

    @property
    def scope_wait_s(self) -> float: ...  # the longest wait for a quota token before `Cooldown`

    @property
    def read_only(self) -> bool: ...  # GET and HEAD only, refused before anything is sent

    def beat(self) -> None: ...

    async def send[T](self, call: Callable[[], Awaitable[T]]) -> T: ...

    def core_http(self) -> GuardedHttp: ...


READ_METHODS = frozenset({"GET", "HEAD"})


def _check_method(channel: Channel, method: str) -> None:
    if channel.read_only and (not isinstance(method, str) or method.upper() not in READ_METHODS):
        raise ReadOnly()


class PlainHttp:
    def __init__(self, attempt: Channel) -> None:
        self._attempt = attempt

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        json: Any = None,
        follow_same_origin: int = 0,
    ) -> HttpResponse:
        _check_method(self._attempt, method)
        return await self._attempt.send(
            lambda: self._attempt.core_http().request(
                method, url, headers=headers, params=params, content=content, json=json,
                follow_same_origin=follow_same_origin,
            )
        )  # fmt: skip


class _Stream:
    def __init__(self, attempt: "AttemptNetwork", stream: GuardedStream) -> None:
        self._attempt, self._stream = attempt, stream

    async def send(self, data: bytes) -> None:
        await self._attempt.send(lambda: self._stream.send(data))

    async def receive(self, max_bytes: int = 65_536) -> bytes:
        try:
            return await self._stream.receive(max_bytes)
        except CORE_ERRORS as e:
            raise mapped(e) from None

    async def close(self) -> None:
        await self._stream.close()


class _PlainNet:
    def __init__(self, attempt: "AttemptNetwork") -> None:
        self._attempt = attempt

    async def open_tcp(self, host: str, port: int, *, tls: bool) -> _Stream:
        try:  # connecting sends no request: only `send` counts
            return _Stream(self._attempt, await self._attempt.core_net().open_tcp(host, port, tls=tls))
        except CORE_ERRORS as e:
            raise mapped(e) from None

    async def send_udp(self, host: str, port: int, data: bytes) -> None:
        await self._attempt.send(lambda: self._attempt.core_net().send_udp(host, port, data))


class _Refused:
    """The network of a simulated step: every call fails `SimulationSendsNothing`."""

    async def request(self, *args: Any, **kwargs: Any) -> HttpResponse:
        raise SimulationSendsNothing()

    async def open_tcp(self, *args: Any, **kwargs: Any) -> _Stream:
        raise SimulationSendsNothing()

    async def send_udp(self, *args: Any, **kwargs: Any) -> None:
        raise SimulationSendsNothing()


@dataclass(frozen=True)
class OpenedConnection:
    id: uuid.UUID
    type: str
    config: Mapping[str, Any]
    http: "ConnectionHttp"


class ConnectionHttp:
    """HTTP through one connection: its origin only, its credentials applied by the runtime, its quota scopes
    charged."""

    def __init__(
        self,
        attempt: Channel,
        base: httpx.URL,
        credentials: Mapping[str, str],
        scopes: Callable[[], Awaitable[list[Scope]]],
    ) -> None:
        self._attempt, self._base, self._credentials = attempt, base, dict(credentials)
        self._scopes_of, self._scopes = scopes, list[Scope]()  # read at the first request, with its first token

    def _target(self, url: str) -> str:
        try:
            target = self._base.join(url)
        except (httpx.InvalidURL, ValueError, TypeError):
            raise InvalidRequest() from None
        if (target.scheme, target.host, target.port) != (self._base.scheme, self._base.host, self._base.port):
            raise InvalidRequest()
        return str(target)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        json: Any = None,
        follow_same_origin: int = 0,
    ) -> HttpResponse:
        _check_method(self._attempt, method)
        target = self._target(url)
        reserved = {name.lower() for name in self._credentials}
        if any(name.lower() in reserved for name in headers or {}):
            raise InvalidRequest()
        sent_headers = {**(headers or {}), **self._credentials}
        attempt = self._attempt
        resends = attempt.resends
        waited, retries = 0.0, 0
        while True:
            try:
                if not self._scopes:
                    self._scopes = await self._scopes_of()
                await acquire(
                    attempt.network.sessionmaker, attempt.tenant_id, self._scopes, max_wait_s=attempt.scope_wait_s,
                    beat=attempt.beat,
                )  # fmt: skip
            except CooldownError:
                raise Cooldown() from None
            except Exception as e:
                if unavailable(e):  # the budget couldn't be read: nothing was sent
                    raise NotSent() from None
                raise
            answer = await attempt.send(
                lambda: attempt.core_http().request(
                    method, target, headers=sent_headers, params=params, content=content, json=json,
                    follow_same_origin=follow_same_origin,
                )
            )  # fmt: skip
            if answer.status_code not in (429, 503):
                return answer
            wait = retry_after_s(answer.header("retry-after"), datetime.now(UTC))
            if wait is not None:
                await self._block(wait)
            if answer.status_code == 503 and wait is None:
                return answer  # a plain server error: the node reads it
            pause = max(wait, MIN_WAIT_S) if wait is not None else None
            if resends and pause is not None and retries < IN_ATTEMPT_RETRIES and waited + pause <= IN_ATTEMPT_WAIT_S:
                attempt.beat()
                await asyncio.sleep(pause)
                waited, retries = waited + pause, retries + 1
                continue
            raise RateLimited()

    async def _block(self, wait_s: float) -> None:
        """Best effort: a block that can't be recorded changes nothing about this request's outcome."""
        if not self._scopes or wait_s <= 0:
            return
        until = datetime.now(UTC) + timedelta(seconds=min(wait_s, MAX_RETRY_AFTER_S))
        try:
            async with self._attempt.network.sessionmaker() as s, s.begin():
                await tenant_scope(s, self._attempt.tenant_id)
                await block(s, self._attempt.tenant_id, self._scopes, until)
        except Exception as e:
            _log.warning("rate_block_unrecorded", error=type(e).__name__)


async def credential_key(network: Network, tenant_id: uuid.UUID) -> Callable[[str], str]:
    """The tenant's scope key (made the first time): the same whichever data-key version this worker holds."""
    sealer = ClaimCipher(network.keys, purpose=rate_scopes.PURPOSE)
    async with network.sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        key = await rate_scopes.scope_key(s, sealer, tenant_id, create=True)
    assert key is not None  # noqa: S101 - made when missing
    return rate_scopes.credential_hasher(key)


@dataclass(frozen=True)
class Unsealed:
    """A connection opened for one use: its validated config, its secret (which only the runtime holds), and what the
    runtime sends with it."""

    id: uuid.UUID
    type: str
    kind: WorkerType
    stored_config: Mapping[str, Any]
    config: Mapping[str, Any]
    secret: Mapping[str, Any]
    base: httpx.URL
    credentials: Mapping[str, str]

    def opened(self, channel: Channel, mac: Callable[[], Awaitable[Callable[[str], str]]]) -> OpenedConnection:
        async def scopes() -> list[Scope]:
            return self.kind.declared.scopes(self.stored_config, self.secret, await mac())

        return OpenedConnection(
            self.id, self.type, MappingProxyType(dict(self.config)),
            ConnectionHttp(channel, self.base, self.credentials, scopes),
        )  # fmt: skip


async def unseal(
    network: Network, tenant_id: uuid.UUID, connection_id: uuid.UUID, stored: StoredConnection, allowed: frozenset[str]
) -> Unsealed:
    """The connection, if it's of a type the caller may use and the installed plugins declare, its stored values are
    ones that type accepts, and its secret opens: else `ConnectionUnavailable`, or `NotSent` when the keyring didn't
    answer. Nothing is sent."""
    kind = network.types.get(stored.type)
    if kind is None or stored.type not in allowed or stored.secret_ct is None:
        raise ConnectionUnavailable()
    try:
        raw = await ClaimCipher(network.keys, purpose=SECRET_PURPOSE).open(
            str(tenant_id), str(connection_id), stored.secret_ct
        )
        secret = kind.declared.secret(json.loads(raw))
        stored_config = kind.declared.config(stored.config)
        config = kind.code.Config.model_validate(stored_config).model_dump(mode="json")
    except (ClaimUnreadableError, InvalidValueError, ValidationError, ValueError):
        raise ConnectionUnavailable() from None
    except Exception as e:
        if key_unreadable(e) or unavailable(e):
            raise NotSent() from None  # the keyring didn't answer: nothing was sent, a retry may succeed
        raise
    url = kind.declared.base_url(stored_config)
    try:
        base = httpx.URL(url) if url is not None else None
    except (httpx.InvalidURL, ValueError, TypeError):
        base = None
    if base is None or base.scheme not in ("http", "https") or not base.host:  # plain http still needs an entry
        raise ConnectionUnavailable()
    return Unsealed(
        connection_id, stored.type, kind, stored_config, config, secret, base, kind.declared.credentials(secret)
    )


class AttemptNetwork:
    """One attempt's network for one step of one tenant's run."""

    def __init__(
        self,
        network: Network,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        step_id: uuid.UUID,
        root_run_id: uuid.UUID,
        node: type[Node],
        simulated: bool,
        remember: Remember,
        beat: Callable[[], None],
    ) -> None:
        self.network, self.tenant_id, self.run_id, self.step_id = network, tenant_id, run_id, step_id
        self.root_run_id, self.node, self.simulated, self.beat = root_run_id, node, simulated, beat
        self._remember = remember
        self.may_have_sent = False  # once a request may have left this attempt
        self._in_flight = 0  # transport calls under way: each may have sent already
        self._http: GuardedHttp | None = None
        self._net: GuardedNet | None = None
        self._named: frozenset[uuid.UUID] | None = None

    @property
    def resends(self) -> bool:
        return self.node.side_effect in RESENDS

    @property
    def scope_wait_s(self) -> float:
        return SCOPE_WAIT_S

    @property
    def read_only(self) -> bool:
        return False

    @property
    def uncertain(self) -> bool:
        """Whether a request of this attempt may have left it: one that did, or one still under way (a concurrent call
        may fail first while another's request has already arrived; the second review's finding 1)."""
        return self.may_have_sent or self._in_flight > 0

    async def send[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """Runs a transport call; unless it failed having sent nothing, a request may now have left the attempt."""
        self._in_flight += 1
        try:
            result = await call()
        except CORE_ERRORS as e:
            if not isinstance(e, NOTHING_SENT):
                self.may_have_sent = True
            raise mapped(e) from None
        except BaseException:
            self.may_have_sent = True
            raise
        finally:
            self._in_flight -= 1
        self.may_have_sent = True
        return result

    def core_http(self) -> GuardedHttp:
        if self._http is None:
            self._http = GuardedHttp(
                self.network.guard, self.tenant_id, ssl_context=self.network.ssl_context,
                limits=self.network.http_limits,
            )  # fmt: skip
        return self._http

    def core_net(self) -> GuardedNet:
        if self._net is None:
            self._net = GuardedNet(
                self.network.guard, self.tenant_id, ssl_context=self.network.ssl_context,
                limits=self.network.net_limits,
            )  # fmt: skip
        return self._net

    @property
    def http(self) -> Any:
        return _Refused() if self.simulated else PlainHttp(self)

    @property
    def net(self) -> Any:
        return _Refused() if self.simulated else _PlainNet(self)

    async def _credential_key(self) -> Callable[[str], str]:
        return await credential_key(self.network, self.tenant_id)

    async def connection(self, connection_id: uuid.UUID) -> OpenedConnection:
        if self.simulated:
            raise SimulationSendsNothing()
        try:
            if self._named is None:
                self._named = await self.network.connections.named_by(
                    self.tenant_id, self.run_id, self.step_id, self.node
                )
            stored = await self.network.connections.load(self.tenant_id, connection_id)
        except Exception as e:
            if unavailable(e):  # the database didn't answer: nothing was sent
                raise NotSent() from None
            raise
        if connection_id not in self._named or stored is None:
            raise ConnectionUnavailable()
        unsealed = await unseal(self.network, self.tenant_id, connection_id, stored, frozenset(self.node.credentials))
        await self._remember(str(self.tenant_id), str(self.root_run_id), secret_strings(unsealed.secret))
        return unsealed.opened(self, self._credential_key)

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        if self._net is not None:
            await self._net.aclose()
