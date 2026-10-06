# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.apps.api.responses import ConnectionDetailOut, ConnectionOut, ConnectionTypeOut
from dewpoint.core.authz.permissions import P
from dewpoint.core.connections import service
from dewpoint.core.connections.declared import InvalidValueError, declared_types
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext, active_session, get_db, require
from dewpoint.core.models.connections import Connection
from dewpoint.core.plugins import asking

router = APIRouter(prefix="/api/v1", tags=["connections"])


class ConnectionCreateIn(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, Any]
    secret: dict[str, Any]


class ConnectionPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] | None = None
    secret: dict[str, Any] | None = None


def _invalid(exc: ValidationError | InvalidValueError) -> HTTPException:
    if isinstance(exc, InvalidValueError):
        return HTTPException(422, detail={"error": "invalid", "fields": exc.fields})
    return HTTPException(
        422, detail={"error": "invalid", "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}
    )


async def _get(db: AsyncSession, ctx: TenantContext, connection_id: uuid.UUID) -> Connection:
    conn = (
        await db.execute(
            select(Connection).where(Connection.id == connection_id, Connection.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return conn


@router.get(
    "/connection-types",
    dependencies=[Depends(active_session)],
    response_model=list[ConnectionTypeOut],
    response_model_exclude_unset=True,
)
async def connection_types(db: AsyncSession = Depends(get_db, scope="function")) -> list[dict[str, object]]:
    """The types the synced plugins declare (plugins-3 D11), by key."""
    return [t.listing() for _, t in sorted((await declared_types(db)).items())]


@router.get("/t/{tenant_id}/connections", response_model=list[ConnectionOut])
async def list_connections(
    ctx: TenantContext = Depends(require(P.CONNECTION_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, object]]:
    rows = await db.execute(select(Connection).where(Connection.tenant_id == ctx.tenant_id).order_by(Connection.name))
    return [service.to_out(c) for c in rows.scalars()]


@router.post("/t/{tenant_id}/connections", status_code=201, response_model=ConnectionOut)
async def create(
    body: ConnectionCreateIn,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    try:
        conn = await service.create_connection(
            db, keyring, ctx, type_key=body.type, name=body.name, config=body.config, secret=body.secret
        )
    except service.UnknownTypeError:
        raise HTTPException(422, detail={"error": "unknown_type"}) from None
    except (ValidationError, InvalidValueError) as e:
        raise _invalid(e) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return service.to_out(conn)


@router.get("/t/{tenant_id}/connections/{connection_id}", response_model=ConnectionDetailOut)
async def get_one(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.CONNECTION_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    conn = await _get(db, ctx, connection_id)
    return {**service.to_out(conn), "cooldowns": await service.cooldowns(db, keyring, conn)}


@router.patch("/t/{tenant_id}/connections/{connection_id}", response_model=ConnectionOut)
async def patch(
    connection_id: uuid.UUID,
    body: ConnectionPatchIn,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    conn = await _get(db, ctx, connection_id)
    try:
        conn = await service.update_connection(
            db, keyring, ctx, conn, name=body.name, config=body.config, secret=body.secret
        )
    except service.UnknownTypeError:
        raise HTTPException(422, detail={"error": "unknown_type"}) from None
    except service.SecretRequiredError:
        raise HTTPException(422, detail={"error": "secret_required"}) from None
    except (ValidationError, InvalidValueError) as e:
        raise _invalid(e) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return service.to_out(conn)


@router.delete("/t/{tenant_id}/connections/{connection_id}", status_code=204)
async def delete(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    conn = await service.get_for_update(db, ctx.tenant_id, connection_id)
    if conn is None:
        raise HTTPException(404, detail={"error": "not_found"})
    try:
        await service.delete_connection(db, ctx, conn)
    except service.ConnectionInUseError:
        raise HTTPException(409, detail={"error": "connection_in_use"}) from None
    return Response(status_code=204)


@router.post("/t/{tenant_id}/connections/{connection_id}/verify", response_model=ConnectionOut)
async def verify(
    connection_id: uuid.UUID,
    request: Request,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    """Verified by the type's `verify()` on a worker (plugins-3 D3): the API sends nothing itself."""

    async def ask(call: Any) -> asking.Outcome:
        try:
            return await asking.ask_and_wait(request.app.state.sessionmaker, keyring, ctx.tenant_id, call)
        except asking.BusyError:
            raise HTTPException(503, detail={"error": "plugin_calls_busy"}) from None
        except asking.TooManyCallsError:
            raise HTTPException(429, detail={"error": "too_many_plugin_calls"}) from None

    try:
        conn = await service.verify_connection(
            db, request.app.state.sessionmaker, keyring, ctx, await _get(db, ctx, connection_id), ask
        )
    except service.UnknownTypeError:
        raise HTTPException(422, detail={"error": "unknown_type"}) from None
    except service.VerificationUnansweredError:
        raise HTTPException(504, detail={"error": "plugin_call_timeout"}) from None
    except service.StaleVerificationError:  # its verify_discarded audit entry is committed
        raise HTTPException(409, detail={"error": "changed_during_verification"}) from None
    except service.ConnectionGoneError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    return service.to_out(conn)
