# SPDX-License-Identifier: Apache-2.0
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.connections.types import CONNECTION_TYPES, ConnectionType
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext
from dewpoint.core.models.connections import Connection

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


async def delete_connection(s: AsyncSession, ctx: TenantContext, conn: Connection) -> None:
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
