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
- A simulated step sends nothing. The attempt's connections are one pool, closed when the attempt ends."""

import asyncio
import email.utils
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
from dewpoint.core.connections.service import PURPOSE as SECRET_PURPOSE
from dewpoint.core.connections.types import CONNECTION_TYPES, ConnectionType
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
)
from dewpoint.core.egress.net import GuardedNet, GuardedStream, NetLimits
from dewpoint.core.models.connections import Connection as ConnectionRow
from dewpoint.core.models.runs import Run
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.ratelimit.buckets import CooldownError, Scope, acquire, block
from dewpoint.core.ratelimit.scopes import credential_hasher
from dewpoint.sdk import (
    ConnectionUnavailable,
    Cooldown,
    EgressRefused,
    InvalidRequest,
    MaybeSent,
    Node,
    NotSent,
    RateLimited,
    RedirectRefused,
    ResponseTooLarge,
    SideEffect,
    SimulationSendsNothing,
    TlsVerificationFailed,
    TransportError,
)
from dewpoint.sdk.fields import CONNECTION

IN_ATTEMPT_WAIT_S = 20.0  # the longest Retry-After a node whose requests may repeat waits out in its attempt (D10)
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
    if isinstance(error, CooldownError):
        return Cooldown()
    return MaybeSent()


_CORE_ERRORS = (
    EgressRefusedError,
    TlsVerificationError,
    InvalidRequestError,
    NotSentError,
    MaybeSentError,
    RedirectRefusedError,
    ResponseTooLargeError,
)


@dataclass(frozen=True)
class StoredConnection:
    type: str
    config: Mapping[str, Any]
    secret_ct: bytes | None


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
                select(ConnectionRow.type, ConnectionRow.config, ConnectionRow.secret_ct).where(
                    ConnectionRow.id == connection_id, ConnectionRow.tenant_id == tenant_id
                )
            )
            row = found.first()
        return StoredConnection(row[0], dict(row[1]), row[2]) if row is not None else None


def secret_strings(secret: BaseModel) -> list[str]:
    """Every string of a secret the index must know (D5): each value, and a secret URL's path and long parts."""
    out: list[str] = []
    for value in secret.model_dump().values():
        text = value.get_secret_value() if isinstance(value, SecretStr) else value
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
    """A `Retry-After` header's wait in seconds: delta-seconds or an HTTP date; None when absent or unreadable."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(int(value))
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


@dataclass(frozen=True)
class Network:
    """What the worker's steps reach the network with: one per process, an attempt's resources made from it."""

    guard: Guard
    connections: ConnectionSource
    sessionmaker: async_sessionmaker[AsyncSession]
    keys: KeySource
    ssl_context: Any = None
    http_limits: HttpLimits = field(default_factory=HttpLimits)
    net_limits: NetLimits = field(default_factory=NetLimits)

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


class _PlainHttp:
    def __init__(self, attempt: "AttemptNetwork") -> None:
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
        http = self._attempt.core_http()
        try:
            return await http.request(
                method, url, headers=headers, params=params, content=content, json=json,
                follow_same_origin=follow_same_origin,
            )  # fmt: skip
        except _CORE_ERRORS as e:
            raise mapped(e) from None


class _Stream:
    def __init__(self, stream: GuardedStream) -> None:
        self._stream = stream

    async def send(self, data: bytes) -> None:
        try:
            await self._stream.send(data)
        except _CORE_ERRORS as e:
            raise mapped(e) from None

    async def receive(self, max_bytes: int = 65_536) -> bytes:
        try:
            return await self._stream.receive(max_bytes)
        except _CORE_ERRORS as e:
            raise mapped(e) from None

    async def close(self) -> None:
        await self._stream.close()


class _PlainNet:
    def __init__(self, attempt: "AttemptNetwork") -> None:
        self._attempt = attempt

    async def open_tcp(self, host: str, port: int, *, tls: bool) -> _Stream:
        try:
            return _Stream(await self._attempt.core_net().open_tcp(host, port, tls=tls))
        except _CORE_ERRORS as e:
            raise mapped(e) from None

    async def send_udp(self, host: str, port: int, data: bytes) -> None:
        try:
            await self._attempt.core_net().send_udp(host, port, data)
        except _CORE_ERRORS as e:
            raise mapped(e) from None


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
        attempt: "AttemptNetwork",
        base: httpx.URL,
        credentials: Mapping[str, str],
        scopes: Sequence[Scope],
    ) -> None:
        self._attempt, self._base, self._credentials, self._scopes = attempt, base, dict(credentials), list(scopes)

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
        target = self._target(url)
        reserved = {name.lower() for name in self._credentials}
        if any(name.lower() in reserved for name in headers or {}):
            raise InvalidRequest()
        sent_headers = {**(headers or {}), **self._credentials}
        attempt = self._attempt
        repeatable = attempt.node.side_effect != SideEffect.AMBIGUOUS
        waited = 0.0
        while True:
            try:
                await acquire(
                    attempt.network.sessionmaker, attempt.tenant_id, self._scopes, max_wait_s=SCOPE_WAIT_S,
                    beat=attempt.beat,
                )  # fmt: skip
            except CooldownError:
                raise Cooldown() from None
            try:
                answer = await attempt.core_http().request(
                    method, target, headers=sent_headers, params=params, content=content, json=json,
                    follow_same_origin=follow_same_origin,
                )  # fmt: skip
            except _CORE_ERRORS as e:
                raise mapped(e) from None
            if answer.status_code not in (429, 503):
                return answer
            wait = retry_after_s(answer.header("retry-after"), datetime.now(UTC))
            if wait is not None:
                await self._block(wait)
            if answer.status_code == 503 and wait is None:
                return answer  # a plain server error: the node reads it
            if repeatable and wait is not None and waited + wait <= IN_ATTEMPT_WAIT_S:
                attempt.beat()
                await asyncio.sleep(wait)
                waited += wait
                continue
            raise RateLimited()

    async def _block(self, wait_s: float) -> None:
        if not self._scopes:
            return
        until = datetime.now(UTC) + timedelta(seconds=wait_s)
        async with self._attempt.network.sessionmaker() as s, s.begin():
            await tenant_scope(s, self._attempt.tenant_id)
            await block(s, self._attempt.tenant_id, self._scopes, until)


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
        self._http: GuardedHttp | None = None
        self._net: GuardedNet | None = None
        self._named: frozenset[uuid.UUID] | None = None

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
        return _Refused() if self.simulated else _PlainHttp(self)

    @property
    def net(self) -> Any:
        return _Refused() if self.simulated else _PlainNet(self)

    async def _credential_key(self) -> Callable[[str], str]:
        _, digest = await self.network.keys.digest_key(str(self.tenant_id), None)
        return credential_hasher(digest, self.tenant_id)

    async def connection(self, connection_id: uuid.UUID) -> OpenedConnection:
        if self.simulated:
            raise SimulationSendsNothing()
        if self._named is None:
            self._named = await self.network.connections.named_by(self.tenant_id, self.run_id, self.step_id, self.node)
        if connection_id not in self._named:
            raise ConnectionUnavailable()
        stored = await self.network.connections.load(self.tenant_id, connection_id)
        kind: ConnectionType | None = CONNECTION_TYPES.get(stored.type) if stored is not None else None
        if stored is None or kind is None or stored.type not in self.node.credentials or kind.base_url is None:
            raise ConnectionUnavailable()
        if stored.secret_ct is None:
            raise ConnectionUnavailable()
        try:
            raw = await ClaimCipher(self.network.keys, purpose=SECRET_PURPOSE).open(
                str(self.tenant_id), str(connection_id), stored.secret_ct
            )
            secret = kind.secret_model.model_validate_json(raw)
            config = kind.config_model.model_validate(stored.config)
        except (ClaimUnreadableError, ValidationError, ValueError):
            raise ConnectionUnavailable() from None
        except Exception as e:
            if key_unreadable(e) or unavailable(e):
                raise NotSent() from None  # the keyring didn't answer: nothing was sent, a retry may succeed
            raise
        await self._remember(str(self.tenant_id), str(self.root_run_id), secret_strings(secret))
        fields = {k: (v.get_secret_value() if isinstance(v, SecretStr) else v) for k, v in secret.model_dump().items()}
        credentials = {kind.auth.header: kind.auth.template.format(**fields)} if kind.auth is not None else {}
        scopes = kind.rate_scopes(config, await self._credential_key(), secret) if kind.rate_scopes else []
        try:
            base = httpx.URL(kind.base_url(config, secret))
        except (httpx.InvalidURL, ValueError):
            raise ConnectionUnavailable() from None
        if base.scheme not in ("http", "https") or not base.host:  # plain http still needs an allowlist entry
            raise ConnectionUnavailable()
        return OpenedConnection(
            connection_id, stored.type, MappingProxyType(dict(stored.config)),
            ConnectionHttp(self, base, credentials, scopes),
        )  # fmt: skip

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        if self._net is not None:
            await self._net.aclose()
