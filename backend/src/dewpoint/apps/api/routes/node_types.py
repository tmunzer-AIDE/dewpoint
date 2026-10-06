# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.apps.api.responses import OptionsOut
from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
from dewpoint.core.connections.declared import declared_types
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext, active_session, get_db, require
from dewpoint.core.models.connections import Connection
from dewpoint.core.plugins import asking, calls, registry

router = APIRouter(prefix="/api/v1", tags=["node-types"])
MAX_OPTIONS, MAX_VALUE, MAX_LABEL = 1000, 1000, 200  # the ruled limits, checked again on the API's side


@router.get("/node-types", dependencies=[Depends(active_session)])
async def node_types(db: AsyncSession = Depends(get_db, scope="function")) -> list[dict[str, object]]:
    """The editor's palette: node types that new versions may use (active) or still carry (deprecated)."""
    return [
        {
            "ref": row.ref,
            "type": row.type,
            "version": row.version,
            "kind": row.kind,
            "state": row.state,
            "title": row.manifest.get("title"),
            "description": row.manifest.get("description", ""),
            "icon": row.manifest.get("icon"),
            "ports": row.manifest.get("ports", []),
            "dynamic_ports": row.manifest.get("dynamic_ports"),
            "config_schema": row.manifest.get("config_schema"),
            "output_schema": row.manifest.get("output_schema"),
            "options": row.manifest.get("options", []),
        }
        for row in await registry.list_node_types(db)
    ]


class OptionsIn(BaseModel):
    field: str = Field(min_length=1, max_length=64)
    connection_id: uuid.UUID | None = None
    query: str = Field(default="", max_length=200)


def options_reply(outcome: asking.Outcome) -> dict[str, Any]:
    """A worker's answer as the API shows it (plugins-3 D3), checked again; a failure as its fixed code."""
    if outcome.timed_out:
        raise HTTPException(504, detail={"error": "plugin_call_timeout"})
    if outcome.gone or outcome.error == "connection_unavailable":
        raise HTTPException(422, detail={"error": "connection_unavailable"})
    if outcome.error == "connection_changed":
        raise HTTPException(409, detail={"error": "connection_changed"})
    if outcome.error is not None:
        raise HTTPException(502, detail={"error": calls.shown(outcome.error)})
    found = (outcome.answer or {}).get("options")
    if (
        not isinstance(found, list)
        or len(found) > MAX_OPTIONS
        or not all(
            isinstance(o, dict)
            and set(o) == {"value", "label"}
            and type(o["value"]) is str
            and type(o["label"]) is str
            and len(o["value"]) <= MAX_VALUE
            and 0 < len(o["label"]) <= MAX_LABEL
            for o in found
        )
    ):
        raise HTTPException(502, detail={"error": "invalid_result"})
    return {"options": found}


async def ask_and_wait(
    request: Request, db: AsyncSession, keyring: Keyring, tenant_id: uuid.UUID, ask: Any
) -> asking.Outcome:
    """Ends the request's transaction, then asks: the wait holds no pooled connection and no lock (the 3a-2 review's
    finding 2). Nothing is read through `db` afterwards."""
    await db.commit()
    try:
        return await asking.ask_and_wait(request.app.state.sessionmaker, keyring, tenant_id, ask)
    except asking.BusyError:
        raise HTTPException(503, detail={"error": "plugin_calls_busy"}) from None
    except asking.TooManyCallsError:
        raise HTTPException(429, detail={"error": "too_many_plugin_calls"}) from None


async def still_current(request: Request, tenant_id: uuid.UUID, connection_id: uuid.UUID, revision: int) -> None:
    """Options are returned only while their connection is still the revision asked through (the owner's review of
    3a-2, finding 3): otherwise 409 `connection_changed`."""
    async with request.app.state.sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        found = await s.execute(
            select(Connection.revision).where(Connection.id == connection_id, Connection.tenant_id == tenant_id)
        )
        current = found.scalar_one_or_none()
    if current != revision:
        raise HTTPException(409, detail={"error": "connection_changed"})


@router.post("/t/{tenant_id}/node-types/{ref}/options", response_model=OptionsOut)
async def node_options(
    ref: str,
    body: OptionsIn,
    request: Request,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, Any]:
    """The choices for one of a node type's options fields, from its `options()` on a worker (plugins-3 D3), through
    the connection the editor names, which the person must be allowed to use."""
    try:
        rows = await registry.load_node_types(db, [ref])
    except ValueError:
        rows = []
    row = next((r for r in rows if r.state != "retired"), None)
    if row is None:
        raise HTTPException(404, detail={"error": "unknown_node_type"})
    if body.field not in row.manifest.get("options", []):
        raise HTTPException(422, detail={"error": "not_an_options_field"})
    revision: int | None = None
    type_hash: str | None = None
    if body.connection_id is not None:
        if P.CONNECTION_USE not in ROLE_PERMISSIONS[ctx.role]:
            raise HTTPException(403, detail={"error": "forbidden"})
        conn = (
            await db.execute(
                select(Connection).where(Connection.id == body.connection_id, Connection.tenant_id == ctx.tenant_id)
            )
        ).scalar_one_or_none()
        kind = (await declared_types(db)).get(conn.type) if conn is not None else None
        if conn is None or kind is None or conn.type not in row.manifest.get("credentials", []):
            raise HTTPException(422, detail={"error": "connection_unavailable"})
        revision, type_hash = conn.revision, kind.hash

    async def ask(s: AsyncSession) -> uuid.UUID:
        return await calls.ask_options(
            s, ctx.tenant_id, node_ref=row.ref, field=body.field, connection_id=body.connection_id, revision=revision,
            query=body.query, type_hash=type_hash,
        )  # fmt: skip

    reply = options_reply(await ask_and_wait(request, db, keyring, ctx.tenant_id, ask))
    if body.connection_id is not None and revision is not None:
        await still_current(request, ctx.tenant_id, body.connection_id, revision)
    return reply
