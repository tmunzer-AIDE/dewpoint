# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.apps.api.responses import ConnectionDetailOut, ConnectionOut, ConnectionTypeOut
from dewpoint.core.authz.permissions import P
from dewpoint.core.connections import service
from dewpoint.core.connections.types import CONNECTION_TYPES, MIST_CLOUDS
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext, active_session, get_db, require
from dewpoint.core.models.connections import Connection

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


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http  # type: ignore[no-any-return]


def _invalid(exc: ValidationError) -> HTTPException:
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
async def connection_types() -> list[dict[str, object]]:
    return [
        {
            "key": t.key,
            "label": t.label,
            "config_schema": t.config_model.model_json_schema(),
            "secret_fields": list(t.secret_model.model_fields),
            **({"clouds": MIST_CLOUDS} if t.key == "mist" else {}),
        }
        for t in CONNECTION_TYPES.values()
    ]


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
    except ValidationError as e:
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
    except ValidationError as e:
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
    try:
        conn = await service.verify_connection(db, keyring, ctx, await _get(db, ctx, connection_id), _http(request))
    except service.StaleVerificationError:
        await db.commit()  # keep the verify_discarded audit entry
        raise HTTPException(409, detail={"error": "changed_during_verification"}) from None
    except service.ConnectionGoneError:
        await db.commit()  # keep the verify_discarded audit entry
        raise HTTPException(404, detail={"error": "not_found"}) from None
    return service.to_out(conn)
