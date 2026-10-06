# SPDX-License-Identifier: Apache-2.0
"""The worker serves plugin calls (plugins-3 D3): a node's `options()` and a connection type's `verify()`, for the API.

- It claims only calls for node refs and connection types this build has, one at a time per call (a fresh token and a
  lease, under `SKIP LOCKED`), and answers only while the claim holds (`core.plugins.calls`).
- The hook runs read-only: `http` and a connection's `http` send GET and HEAD only, refused (`read_only`) before
  anything is sent; there is no `net`. It may open only the call's connection, of a type the node declares (or the
  type being verified), in the call's tenant, at the revision the API read; anything else is `connection_unavailable`,
  or `connection_changed`, and nothing is sent. A quota token is waited for briefly, and nothing is resent.
- The answer is checked (its shape and size, and that no string of the connection's secret is in it) and sealed under
  the tenant's data key; otherwise the call fails with a fixed code. Logs name an exception's type, never its text.
- Workers wake on a notification, and poll as a fallback; expired calls are swept."""

import asyncio
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dewpoint.apps.worker import logs
from dewpoint.apps.worker.network import (
    CORE_ERRORS,
    Network,
    OpenedConnection,
    PlainHttp,
    credential_key,
    mapped,
    secret_strings,
    unseal,
)
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope, unavailable
from dewpoint.core.egress.http import GuardedHttp
from dewpoint.core.plugins import calls
from dewpoint.sdk import (
    ConnectionUnavailable,
    Node,
    NotSent,
    Option,
    OptionsQuery,
    Plugin,
    TransportError,
    VerifyResult,
)
from dewpoint.sdk import calls as sdk_calls
from dewpoint.sdk import net as sdk_net
from dewpoint.sdk.manifest import options_fields

log = structlog.get_logger("dewpoint.worker")
CALL_TIMEOUT_S = 10.0  # the API waits as long (D3)
SCOPE_WAIT_S = 2.0  # a call outside a run waits briefly for a quota token, then fails `cooldown`
MARGIN_S = 1.0  # a hook ends this long before its lease or the call's expiry
SWEEP_S = 60.0
MAX_OPTIONS = 1000
MAX_VALUE = 1000
MAX_LABEL = 200
MAX_ANSWER = 256 * 1024
DETAIL_RE = re.compile(r"^[a-z0-9_]{1,40}$")  # `connections.status_detail`
MAX_PRIVILEGE = 40  # `connections.privilege`
# The SDK's own transport errors: only their fixed codes are ever shown (a plugin's subclass can't widen them).
_SDK_ERRORS = frozenset(
    cls for module in (sdk_net, sdk_calls) for cls in vars(module).values()
    if isinstance(cls, type) and issubclass(cls, TransportError)
)  # fmt: skip


class _Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CallNetwork:
    """One plugin call's network: read-only, through the call's connection only, nothing resent."""

    resends = False
    read_only = True
    scope_wait_s = SCOPE_WAIT_S

    def __init__(self, network: Network, claimed: calls.Claimed, allowed: frozenset[str]) -> None:
        self.network, self.tenant_id, self._claimed, self._allowed = network, claimed.tenant_id, claimed, allowed
        self._http: GuardedHttp | None = None
        self.secrets: list[str] = []  # every string of the secrets this call opened: never in its answer
        self.changed = False  # the connection changed since the API read it

    def beat(self) -> None:
        return None

    async def send[T](self, call: Callable[[], Awaitable[T]]) -> T:
        try:
            return await call()
        except CORE_ERRORS as e:
            raise mapped(e) from None

    def core_http(self) -> GuardedHttp:
        if self._http is None:
            self._http = GuardedHttp(
                self.network.guard, self.tenant_id, ssl_context=self.network.ssl_context,
                limits=self.network.http_limits,
            )  # fmt: skip
        return self._http

    @property
    def http(self) -> Any:
        return PlainHttp(self)

    async def connection(self, connection_id: uuid.UUID) -> OpenedConnection:
        if connection_id != self._claimed.connection_id:
            raise ConnectionUnavailable()
        try:
            stored = await self.network.connections.load(self.tenant_id, connection_id)
        except Exception as e:
            if unavailable(e):
                raise NotSent() from None
            raise
        if stored is None:
            raise ConnectionUnavailable()
        if stored.revision != self._claimed.revision:
            self.changed = True
            raise ConnectionUnavailable()
        unsealed = await unseal(self.network, self.tenant_id, connection_id, stored, self._allowed)
        self.secrets.extend(secret_strings(unsealed.secret))
        return unsealed.opened(self, lambda: credential_key(self.network, self.tenant_id))

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()


class CallContext:
    """The `CallContext` a hook receives."""

    def __init__(self, net: CallNetwork, log: logs.StepLog) -> None:
        self._net, self.log = net, log
        self.tenant_id = net.tenant_id

    async def connection(self, connection_id: uuid.UUID) -> Any:
        return await self._net.connection(connection_id)

    @property
    def http(self) -> Any:
        return self._net.http


def _strings(value: Any) -> Iterable[str]:
    if type(value) is str:  # exactly: a subclass could answer `in` as it likes
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _options_answer(found: Any) -> dict[str, Any]:
    if not isinstance(found, list | tuple) or not all(isinstance(o, Option) for o in found):
        raise _Refused("invalid_result")
    if len(found) > MAX_OPTIONS:
        raise _Refused("result_too_large")
    for o in found:
        if type(o.value) is not str or type(o.label) is not str or not 0 < len(o.label) <= MAX_LABEL:
            raise _Refused("invalid_result")  # exactly `str`: a subclass could answer the secret check as it likes
        if len(o.value) > MAX_VALUE:
            raise _Refused("result_too_large")
    return {"options": [{"value": o.value, "label": o.label} for o in found]}


def _verify_answer(found: Any) -> dict[str, Any]:
    if (
        not isinstance(found, VerifyResult)
        or not isinstance(found.ok, bool)
        or not isinstance(found.detail, str)
        or not DETAIL_RE.match(found.detail)
        or not (
            found.privilege is None
            or (
                isinstance(found.privilege, str)
                and len(found.privilege) <= MAX_PRIVILEGE
                and found.privilege.isprintable()
            )
        )
    ):
        raise _Refused("invalid_result")
    return {"ok": found.ok, "detail": found.detail, "privilege": found.privilege}


class PluginCallServer:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        network: Network,
        plugins: Sequence[Plugin],
        *,
        concurrency: int = 8,
        poll_s: float = 1.0,
        call_timeout_s: float = CALL_TIMEOUT_S,
        engine: AsyncEngine | None = None,
    ) -> None:
        self._sessionmaker, self._network = sessionmaker, network
        self._nodes: dict[str, type[Node]] = {
            f"{node.type}@{node.version}": node for p in plugins for node in p.nodes if options_fields(node)
        }
        self._types = sorted(key for key, kind in network.types.items() if kind.code.verify is not None)
        self._slots = asyncio.Semaphore(concurrency)
        self._concurrency, self._poll_s, self._timeout_s = concurrency, poll_s, call_timeout_s
        self._engine = engine if engine is not None else sessionmaker.kw.get("bind")
        self._wake, self._stopped = asyncio.Event(), asyncio.Event()
        self.listening = asyncio.Event()  # set while a LISTEN wakes this server
        self._busy: set[asyncio.Task[None]] = set()

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()

    async def run(self) -> None:
        listener = asyncio.create_task(self._listen())
        swept = 0.0
        try:
            while not self._stopped.is_set():
                loop = asyncio.get_running_loop()
                if loop.time() - swept >= SWEEP_S:
                    swept = loop.time()
                    await self._sweep()
                try:
                    await self._round()
                except Exception as e:  # the database didn't answer: the next round tries again
                    log.warning("plugin_calls_round_failed", error=type(e).__name__)
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), self._poll_s)
                except TimeoutError:
                    pass
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            await asyncio.gather(*self._busy, return_exceptions=True)

    async def serve_once(self) -> int:
        """One round, waiting for the calls it took: how many it took."""
        taken = await self._round()
        await asyncio.gather(*self._busy, return_exceptions=True)
        return taken

    async def _round(self) -> int:
        free = self._concurrency - len(self._busy)
        if free <= 0 or (not self._nodes and not self._types):
            return 0
        hashes = sorted(kind.declared.hash for kind in self._network.types.values())
        async with self._sessionmaker() as s, s.begin():
            due = await calls.candidates(s, sorted(self._nodes), self._types, hashes, free)
        for tenant_id, call_id in due:
            task = asyncio.create_task(self._serve(tenant_id, call_id))
            self._busy.add(task)
            task.add_done_callback(self._busy.discard)
        return len(due)

    async def _sweep(self) -> None:
        try:
            async with self._sessionmaker() as s, s.begin():
                await calls.sweep(s)
        except Exception as e:
            log.warning("plugin_calls_sweep_failed", error=type(e).__name__)

    async def _listen(self) -> None:
        """Wakes the server on every notification; on any failure it polls, and listens again a little later."""
        while not self._stopped.is_set():
            try:
                if self._engine is None:
                    return
                async with self._engine.connect() as conn:
                    raw = await conn.get_raw_connection()
                    driver: Any = raw.driver_connection

                    def woken(*_: object) -> None:
                        self._wake.set()

                    await driver.add_listener(calls.CHANNEL, woken)
                    self.listening.set()
                    try:
                        await self._stopped.wait()
                    finally:
                        self.listening.clear()
                        await driver.remove_listener(calls.CHANNEL, woken)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("plugin_calls_listen_failed", error=type(e).__name__)
                await asyncio.sleep(5)

    async def _serve(self, tenant_id: uuid.UUID, call_id: uuid.UUID) -> None:
        async with self._slots:
            try:
                async with self._sessionmaker() as s, s.begin():
                    await tenant_scope(s, tenant_id)
                    claimed = await calls.claim(s, tenant_id, call_id)
            except Exception as e:
                log.warning("plugin_call_claim_failed", error=type(e).__name__)
                return
            if claimed is None:
                return  # another worker has it, or it's no longer due
            try:
                answer = await self._answer(claimed)
                sealed = await ClaimCipher(self._network.keys, purpose=calls.PURPOSE).seal(
                    str(claimed.tenant_id), str(claimed.id), answer
                )
            except _Refused as e:
                await self._finish(claimed, None, e.code)
                return
            except Exception as e:
                log.warning("plugin_call_unsealed", kind=claimed.kind, error=logs.error_class(e))
                await self._finish(claimed, None, "unavailable")
                return
            await self._finish(claimed, sealed, None)

    async def _finish(self, claimed: calls.Claimed, sealed: bytes | None, error: str | None) -> None:
        try:
            async with self._sessionmaker() as s, s.begin():
                await tenant_scope(s, claimed.tenant_id)
                if sealed is not None:
                    taken = await calls.answer(s, claimed.tenant_id, claimed.id, claimed.token, sealed)
                else:
                    taken = await calls.refuse(s, claimed.tenant_id, claimed.id, claimed.token, error or "unavailable")
        except Exception as e:
            log.warning("plugin_call_unanswered", kind=claimed.kind, error=type(e).__name__)
            return
        if not taken:  # the claim lapsed, the call expired or the API abandoned it: nothing was taken
            log.info("plugin_call_unanswered", kind=claimed.kind, reason="claim_lost")
        elif error is not None:
            log.info("plugin_call_refused", kind=claimed.kind, code=error)

    def _deadline_s(self, claimed: calls.Claimed) -> float:
        now = datetime.now(UTC)
        left = min((claimed.lease_until - now).total_seconds(), (claimed.expires_at - now).total_seconds())
        return min(self._timeout_s, left - MARGIN_S)

    async def _answer(self, claimed: calls.Claimed) -> bytes:
        hook, allowed, module = self._hook(claimed)
        deadline = self._deadline_s(claimed)
        if deadline <= 0:
            raise _Refused("timeout")
        net = CallNetwork(self._network, claimed, allowed)
        ctx = CallContext(net, logs.StepLog(logs.literals(module), call_id=str(claimed.id)))
        try:
            async with asyncio.timeout(deadline):
                found = await hook(ctx)
        except TimeoutError:
            raise _Refused("timeout") from None
        except TransportError as e:
            if net.changed:
                raise _Refused("connection_changed") from None
            raise _Refused(type(e).code if type(e) in _SDK_ERRORS else "plugin_failed") from None
        except Exception as e:
            log.warning("plugin_call_failed", kind=claimed.kind, error=logs.error_class(e))
            raise _Refused("connection_changed" if net.changed else "plugin_failed") from None
        finally:
            await net.aclose()
        if net.changed:
            raise _Refused("connection_changed")
        answer = _options_answer(found) if claimed.kind == "options" else _verify_answer(found)
        if any(secret in text for text in _strings(answer) for secret in net.secrets):
            raise _Refused("result_refused")
        encoded = json.dumps(answer, separators=(",", ":")).encode()
        if len(encoded) > MAX_ANSWER:
            raise _Refused("result_too_large")
        return encoded

    def _hook(self, claimed: calls.Claimed) -> tuple[Callable[[Any], Awaitable[Any]], frozenset[str], str]:
        if claimed.kind == "options":
            node = self._nodes.get(claimed.node_ref or "")
            if node is None:
                raise _Refused("unavailable")
            if claimed.field not in options_fields(node):
                raise _Refused("invalid_field")
            query = OptionsQuery(text=claimed.query, connection_id=claimed.connection_id)
            field = claimed.field

            async def options(ctx: Any) -> Any:
                return await node().options(ctx, field, query)

            return options, frozenset(node.credentials), node.__module__
        kind = self._network.types.get(claimed.connection_type or "")
        verify = kind.code.verify if kind is not None else None
        if kind is None or verify is None or claimed.connection_id is None:
            raise _Refused("unavailable")
        connection_id = claimed.connection_id

        async def check(ctx: Any) -> Any:
            return await verify(ctx, await ctx.connection(connection_id))

        return check, frozenset({kind.code.key}), verify.__module__
