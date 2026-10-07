# SPDX-License-Identifier: Apache-2.0
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidTag
from sqlalchemy import any_, literal, select, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from dewpoint.core.audit.service import record
from dewpoint.core.connections.declared import DeclaredType, declared_types
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.models.connections import Connection
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins import asking, calls
from dewpoint.core.ratelimit import scopes as rate_scopes
from dewpoint.core.ratelimit.buckets import current_cooldowns

PURPOSE = "connection.secret"


class UnknownTypeError(ValueError): ...


class SecretRequiredError(ValueError):
    """The edit moves the connection to another host: its secret must be written again (the 3a-2 review's finding 1)."""


async def declared(s: AsyncSession, key: str) -> DeclaredType:
    """The type as the synced manifests declare it (plugins-3 D11): unknown until `plugins sync` registered it."""
    found = (await declared_types(s)).get(key)
    if found is None:
        raise UnknownTypeError(key)
    return found


def _secret_json(secret: dict[str, Any]) -> bytes:
    return json.dumps(secret).encode()


async def create_connection(
    s: AsyncSession,
    keyring: Keyring,
    ctx: TenantContext,
    *,
    type_key: str,
    name: str,
    config: dict[str, Any],
    secret: dict[str, Any],
) -> Connection:
    kind = await declared(s, type_key)
    cfg, sec = kind.config(config), kind.secret(secret)
    conn = Connection(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        type=type_key,
        name=name,
        config=cfg,
        created_by=ctx.user.id,
    )
    conn.secret_ct = await keyring.encrypt(
        s, tenant_id=ctx.tenant_id, purpose=PURPOSE, context=str(conn.id), plaintext=_secret_json(sec)
    )
    s.add(conn)
    await s.flush()
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.create",
        target_type="connection",
        target_id=str(conn.id),
        details={"type": type_key, "name": name},
    )
    return conn


async def update_connection(
    s: AsyncSession,
    keyring: Keyring,
    ctx: TenantContext,
    conn: Connection,
    *,
    name: str | None,
    config: dict[str, Any] | None,
    secret: dict[str, Any] | None,
) -> Connection:
    """`conn` is locked (`get_for_update`): the host rule compares with the config this edit replaces."""
    kind = await declared(s, conn.type)
    new_config = kind.config(config) if config is not None else None
    field = kind.host.get("field") if kind.host is not None else None
    if (
        new_config is not None
        and secret is None
        and field is not None
        and kind.secret_schema.get("properties")
        and new_config.get(field) != (conn.config or {}).get(field)
    ):
        raise SecretRequiredError()  # the stored secret never follows a host the person who wrote it didn't choose
    changed: list[str] = []
    if name is not None:
        conn.name = name
        changed.append("name")
    if new_config is not None:
        conn.config = new_config
        changed.append("config")
    if secret is not None:
        conn.secret_ct = await keyring.encrypt(
            s,
            tenant_id=ctx.tenant_id,
            purpose=PURPOSE,
            context=str(conn.id),
            plaintext=_secret_json(kind.secret(secret)),
        )
        changed.append("secret")
    if {"config", "secret"} & set(changed):
        conn.status, conn.status_detail, conn.privilege = "unverified", "", None
        conn.revision = Connection.revision + 1  # in SQL: concurrent edits can't collapse into one revision
    await s.flush()
    await s.refresh(conn)  # load the SQL-computed revision (no lazy loads in async code)
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.update",
        target_type="connection",
        target_id=str(conn.id),
        details={"changed": changed},
    )
    return conn


class ConnectionInUseError(Exception):
    """An enabled workflow's active closure, or a request that hasn't started, names the connection (plugins-3 D6)."""


async def get_for_update(s: AsyncSession, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> Connection | None:
    """The connection, locked until the transaction ends, as it is once the lock is held."""
    found = await s.execute(
        select(Connection)
        .where(Connection.id == connection_id, Connection.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return found.scalar_one_or_none()


async def named(s: AsyncSession, tenant_id: uuid.UUID, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The tenant's connections among `ids`, with their types, locked FOR SHARE until the transaction ends, so a
    deletion either sees the version that names them or waits for it (plugins-3 D6)."""
    if not ids:
        return {}
    rows = await s.execute(
        select(Connection.id, Connection.type)
        .where(Connection.tenant_id == tenant_id, Connection.id.in_(ids))
        .with_for_update(read=True)
    )
    return {cid: type_key for cid, type_key in rows.all()}


async def in_use(s: AsyncSession, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> bool:
    """Whether an enabled workflow's active closure, or a request that hasn't started, names the connection."""
    named_here = literal(connection_id, PgUUID(as_uuid=True))
    active, closure = aliased(WorkflowVersion), aliased(WorkflowVersion)
    enabled = (
        select(literal(1))
        .select_from(Workflow)
        .join(active, active.id == Workflow.active_version_id)
        .join(closure, closure.id == any_(active.closure_version_ids))
        .where(Workflow.tenant_id == tenant_id, Workflow.enabled.is_(True), named_here == any_(closure.connection_ids))
        .limit(1)
    )
    frozen, frozen_closure = aliased(WorkflowVersion), aliased(WorkflowVersion)
    unstarted = (
        select(literal(1))
        .select_from(RunRequest)
        .join(frozen, frozen.id == RunRequest.workflow_version_id)
        .join(frozen_closure, frozen_closure.id == any_(frozen.closure_version_ids))
        .where(
            RunRequest.tenant_id == tenant_id,
            RunRequest.status.in_(("queued", "starting")),
            named_here == any_(frozen_closure.connection_ids),
        )
        .limit(1)
    )
    return (await s.execute(enabled)).first() is not None or (await s.execute(unstarted)).first() is not None


async def delete_connection(s: AsyncSession, ctx: TenantContext, conn: Connection) -> None:
    """Refused (ConnectionInUseError) while an enabled workflow's active closure, or a request that hasn't started,
    names the connection. The row is locked first, so a publish naming it either waits or is seen."""
    await s.execute(select(Connection.id).where(Connection.id == conn.id).with_for_update())
    if await in_use(s, ctx.tenant_id, conn.id):
        raise ConnectionInUseError()
    await s.delete(conn)
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.delete",
        target_type="connection",
        target_id=str(conn.id),
    )


async def _secret_readable(s: AsyncSession, keyring: Keyring, conn: Connection, kind: DeclaredType) -> bool:
    try:
        raw = await keyring.decrypt(
            s, tenant_id=conn.tenant_id, purpose=PURPOSE, context=str(conn.id), blob=conn.secret_ct or b""
        )
        kind.secret(json.loads(raw))
    except (InvalidTag, ValueError):
        return False
    return True


class StaleVerificationError(Exception):
    """The connection's config or secret changed while it was being verified; the result was discarded."""


class ConnectionGoneError(Exception):
    """The connection was deleted while it was being verified; the result was discarded."""


class VerificationUnansweredError(Exception):
    """No worker answered in time: nothing was recorded."""


type Asker = Callable[[Callable[[AsyncSession], Awaitable[uuid.UUID]]], Awaitable[asking.Outcome]]
DETAIL_RE = re.compile(r"^[a-z0-9_]{1,40}$")  # what `status_detail` holds


def shown_code(code: str | None) -> str:
    """A worker's failure code as a connection's status shows it: one of the fixed codes, else `unavailable`."""
    return calls.shown(code)


def _checked(answer: dict[str, Any] | None) -> tuple[str, str, str | None]:
    """A worker's verification answer, checked again: (status, detail, privilege)."""
    ok, detail, privilege = (answer or {}).get("ok"), (answer or {}).get("detail"), (answer or {}).get("privilege")
    if (
        not isinstance(ok, bool)
        or not isinstance(detail, str)
        or not DETAIL_RE.fullmatch(detail)
        or not (privilege is None or (isinstance(privilege, str) and len(privilege) <= 40 and privilege.isprintable()))
    ):
        return "error", "invalid_result", None
    return ("ok" if ok else "error"), detail, privilege


async def verify_connection(
    s: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    keyring: Keyring,
    ctx: TenantContext,
    conn: Connection,
    ask: Asker,
) -> Connection:
    """Asks a worker to verify the credentials (plugins-3 D3), then records the result only if they are still the
    revision verified. Raises StaleVerificationError (after auditing it) when an edit committed while the check was in
    flight, ConnectionGoneError when the connection was deleted, VerificationUnansweredError when no worker
    answered.

    Before asking, it ends the request's transaction (`s`), so the wait holds no pooled connection and no lock (the
    3a-2 review's finding 2); the result is then recorded in a transaction of its own."""
    kind, loaded_revision = await declared(s, conn.type), conn.revision
    local: tuple[str, str, str | None] | None = None
    if not await _secret_readable(s, keyring, conn, kind):
        local = ("error", "secret_unreadable", None)
    elif not kind.verify:
        local = ("error", "unverifiable", None)
    if local is not None:  # nothing to ask: recorded in the request's own transaction
        try:
            return await _record(s, ctx, conn, loaded_revision, local, discarded=False)
        except (StaleVerificationError, ConnectionGoneError):
            await s.commit()  # keep the verify_discarded audit entry
            raise
    await s.commit()
    outcome = await ask(
        lambda inner: calls.ask_verify(
            inner,
            ctx.tenant_id,
            connection_type=conn.type,
            connection_id=conn.id,
            revision=loaded_revision,
            type_hash=kind.hash,
        )  # fmt: skip
    )
    if outcome.timed_out:
        raise VerificationUnansweredError()
    discarded = outcome.gone or outcome.error == "connection_changed"
    result = ("error", shown_code(outcome.error), None) if outcome.error is not None else _checked(outcome.answer)
    failure: Exception | None = None
    async with sessionmaker() as fresh, fresh.begin():
        await tenant_scope(fresh, ctx.tenant_id)
        try:
            return await _record(fresh, ctx, conn, loaded_revision, result, discarded=discarded)
        except (StaleVerificationError, ConnectionGoneError) as e:
            failure = e  # raised once the discard's audit entry is committed
    assert failure is not None  # noqa: S101 - set whenever the block didn't return
    raise failure


async def _record(
    s: AsyncSession,
    ctx: TenantContext,
    conn: Connection,
    loaded_revision: int,
    result: tuple[str, str, str | None],
    *,
    discarded: bool,
) -> Connection:
    """The verification's result, applied only to the revision verified (compare-and-set), and audited either way."""
    status, detail, privilege = result
    applied = None
    if not discarded:
        applied = await s.execute(
            update(Connection)
            .where(Connection.id == conn.id, Connection.revision == loaded_revision)
            .values(status=status, status_detail=detail, privilege=privilege, last_verified_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
    if applied is not None and getattr(applied, "rowcount", 0) == 1:
        # Our UPDATE holds the row lock until commit, so the row can't vanish before this read.
        current = (await s.execute(select(Connection).where(Connection.id == conn.id))).scalar_one()
        await s.refresh(current)  # current row, including concurrent non-credential edits such as a rename
        await _audit_verify(s, ctx, conn.id, "connection.verify", status, loaded_revision, None)
        return current
    # Not applied: the connection was deleted, or its credentials changed, while the check was in flight.
    exists = (await s.execute(select(Connection.id).where(Connection.id == conn.id))).first() is not None
    reason = "edited" if exists else "deleted"
    await _audit_verify(s, ctx, conn.id, "connection.verify_discarded", status, loaded_revision, reason)
    if not exists:
        raise ConnectionGoneError()
    raise StaleVerificationError()


async def _audit_verify(
    s: AsyncSession,
    ctx: TenantContext,
    connection_id: uuid.UUID,
    action: str,
    status: str,
    revision: int,
    reason: str | None,
) -> None:
    details: dict[str, object] = {"status": status, "verified_revision": revision}
    if reason:
        details["reason"] = reason
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action=action,
        target_type="connection",
        target_id=str(connection_id),
        details=details,
    )


class _KeyringSealer:
    """The keyring as a `Sealer` for the scope key: the claim cipher's layout, within the API's transaction."""

    def __init__(self, s: AsyncSession, keyring: Keyring) -> None:
        self._s, self._keyring = s, keyring

    async def seal(self, tenant_id: str, context: str, plaintext: bytes) -> bytes:
        return await self._keyring.encrypt(
            self._s, tenant_id=uuid.UUID(tenant_id), purpose=rate_scopes.PURPOSE, context=context, plaintext=plaintext
        )

    async def open(self, tenant_id: str, context: str, blob: bytes) -> bytes:
        return await self._keyring.decrypt(
            self._s, tenant_id=uuid.UUID(tenant_id), purpose=rate_scopes.PURPOSE, context=context, blob=blob
        )


async def cooldowns(s: AsyncSession, keyring: Keyring, conn: Connection) -> list[dict[str, str]] | None:
    """Each of the connection's quota scopes now cooling down (plugins-3 D10), its stream's included (D26): its kind and
    its current cooldown, a live value that can change, not a record of a failed attempt's deadline; never the scope's
    key. None when the scopes can't be computed (an unknown type, an unreadable secret)."""
    try:
        kind = await declared(s, conn.type)
    except UnknownTypeError:
        return None
    if not kind.rate_scopes and not kind.stream:
        return []
    try:
        config = kind.config(conn.config)  # first: a config the declaration refuses never meets the secret
        raw = await keyring.decrypt(
            s, tenant_id=conn.tenant_id, purpose=PURPOSE, context=str(conn.id), blob=conn.secret_ct or b""
        )
        secret = kind.secret(json.loads(raw))
        key = await rate_scopes.scope_key(s, _KeyringSealer(s, keyring), conn.tenant_id, create=False)
        # No scope key yet: no worker has charged a credential scope, so none can be cooling down; others still count.
        hasher = rate_scopes.credential_hasher(key) if key is not None else (lambda credential: "-")
        scopes = kind.scopes(config, secret, hasher) + kind.stream_scopes(config, secret, hasher)  # D26: a stream's
    except (InvalidTag, ValueError, KeyError, TypeError):
        return None
    found = await current_cooldowns(s, conn.tenant_id, [scope.key for scope in scopes])
    return sorted(
        ({"scope": key.split(":", 1)[0], "until": until.isoformat()} for key, until in found.items()),
        key=lambda x: (x["scope"], x["until"]),
    )


def to_out(conn: Connection) -> dict[str, object]:
    return {
        "id": str(conn.id),
        "type": conn.type,
        "name": conn.name,
        "revision": conn.revision,
        "config": conn.config,
        "secret_set": conn.secret_ct is not None,
        "status": conn.status,
        "status_detail": conn.status_detail,
        "privilege": conn.privilege,
        "last_verified_at": conn.last_verified_at.isoformat() if conn.last_verified_at else None,
    }
