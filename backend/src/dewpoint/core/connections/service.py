# SPDX-License-Identifier: Apache-2.0
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, SecretStr
from sqlalchemy import any_, literal, select, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dewpoint.core.audit.service import record
from dewpoint.core.connections.types import CONNECTION_TYPES, ConnectionType
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext
from dewpoint.core.models.connections import Connection
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.workflows import Workflow, WorkflowVersion

PURPOSE = "connection.secret"


class UnknownTypeError(ValueError): ...


def _type(key: str) -> ConnectionType:
    if key not in CONNECTION_TYPES:
        raise UnknownTypeError(key)
    return CONNECTION_TYPES[key]


def _secret_json(model: BaseModel) -> bytes:
    data = {k: (v.get_secret_value() if isinstance(v, SecretStr) else v) for k, v in model}
    return json.dumps(data).encode()


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
    ct = _type(type_key)
    cfg, sec = ct.config_model.model_validate(config), ct.secret_model.model_validate(secret)
    conn = Connection(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        type=type_key,
        name=name,
        config=cfg.model_dump(mode="json"),
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
    ct = _type(conn.type)
    changed: list[str] = []
    if name is not None:
        conn.name = name
        changed.append("name")
    if config is not None:
        conn.config = ct.config_model.model_validate(config).model_dump(mode="json")
        changed.append("config")
    if secret is not None:
        conn.secret_ct = await keyring.encrypt(
            s,
            tenant_id=ctx.tenant_id,
            purpose=PURPOSE,
            context=str(conn.id),
            plaintext=_secret_json(ct.secret_model.model_validate(secret)),
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
    found = await s.execute(
        select(Connection).where(Connection.id == connection_id, Connection.tenant_id == tenant_id).with_for_update()
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


async def load_secret(s: AsyncSession, keyring: Keyring, conn: Connection) -> BaseModel:
    raw = await keyring.decrypt(
        s, tenant_id=conn.tenant_id, purpose=PURPOSE, context=str(conn.id), blob=conn.secret_ct or b""
    )
    return _type(conn.type).secret_model.model_validate_json(raw)


class StaleVerificationError(Exception):
    """The connection's config or secret changed while it was being verified; the result was discarded."""


class ConnectionGoneError(Exception):
    """The connection was deleted while it was being verified; the result was discarded."""


async def verify_connection(
    s: AsyncSession, keyring: Keyring, ctx: TenantContext, conn: Connection, http: httpx.AsyncClient
) -> Connection:
    """Verify the credentials as loaded, then record the result only if they are still the current revision.
    Raises StaleVerificationError (after auditing it) when an edit committed while the check was in flight."""
    ct, loaded_revision = _type(conn.type), conn.revision
    try:
        secret = await load_secret(s, keyring, conn)
    except (InvalidTag, ValueError):
        status, detail, privilege = "error", "secret_unreadable", None
    else:
        result = await ct.verify(ct.config_model.model_validate(conn.config), secret, http)
        status, detail, privilege = ("ok" if result.ok else "error"), result.detail, result.privilege
    applied = await s.execute(
        update(Connection)
        .where(Connection.id == conn.id, Connection.revision == loaded_revision)
        .values(status=status, status_detail=detail, privilege=privilege, last_verified_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    if getattr(applied, "rowcount", 0) == 1:
        # Our UPDATE holds the row lock until commit, so the row can't vanish before this refresh.
        await s.refresh(conn)  # current row, including concurrent non-credential edits such as a rename
        await _audit_verify(s, ctx, conn.id, "connection.verify", status, loaded_revision, None)
        return conn
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
