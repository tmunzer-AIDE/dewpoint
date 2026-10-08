# SPDX-License-Identifier: Apache-2.0
"""The operator's recovery (the owner's rulings on the 2b-4b M3 design, rev 1 and 2), a platform admin's act: on an
active MFA session, and for every change a second factor proven within the reauthentication window, recording that
admin's user id with the change, in its transaction.

- **A command** on an item a pass left for recovery is recorded, pending, for the dispatcher's leader to carry out (the
  API has no Temporal client): only on an item with one of the command's reasons recorded, since when kept with it, and
  with the operator's evidence where the item's history is gone. An operator's idempotency key returns the same
  command again; an item has one pending command of a kind.
- **A release** of a held item, for the kind of work it names, at once, through a guarded function: never another
  kind's hold, nor a count that isn't held.
- **The listings**, across tenants: held items and recovery reasons, as ids, kinds, reasons and times."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import active_session, ensure_fresh_reauth, get_db, get_settings_dep, require_platform_admin
from dewpoint.core.models.identity import AuthSession, User
from dewpoint.core.recovery import COMMANDS, EVIDENCE_LIMIT, LOST, CommandKind, WorkKind
from dewpoint.core.runs.service import sanitize
from dewpoint.core.tenancy.lifecycle import FENCED

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

SHOWN = "id, tenant_id, kind, item_id, reason, incident_since, actor_id, status, outcome, requested_at, decided_at"


class CommandIn(BaseModel):
    kind: CommandKind
    item_id: uuid.UUID
    evidence: str = Field(default="", max_length=EVIDENCE_LIMIT)
    idempotency_key: str = Field(min_length=1, max_length=100)


class ReleaseIn(BaseModel):
    kind: WorkKind
    item_id: uuid.UUID


def _shown(row: Any) -> dict[str, object]:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v.isoformat() if isinstance(v, datetime) else v)
            for k, v in row._mapping.items()}  # fmt: skip


async def _command(db: AsyncSession, query: str, **params: object) -> Any:
    return (await db.execute(text(f"SELECT {SHOWN} FROM operator_commands WHERE {query}"), params)).first()  # noqa: S608


async def _tenant(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    await tenant_scope(db, tenant_id)
    if (await db.execute(text("SELECT 1 FROM tenants WHERE id = :t"), {"t": tenant_id})).scalar() is None:
        raise HTTPException(404, detail={"error": "not_found"})


@router.post("/tenants/{tenant_id}/commands", status_code=202)
async def ask(
    tenant_id: uuid.UUID,
    body: CommandIn,
    response: Response,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    ensure_fresh_reauth(sess, settings)
    await _tenant(db, tenant_id)
    mine = await _command(db, "actor_id = :u AND idempotency_key = :k", u=admin.id, k=body.idempotency_key)
    if mine is not None:  # asked again: the same command, whatever became of it
        if (mine.kind, mine.item_id) != (body.kind, body.item_id):
            raise HTTPException(409, detail={"error": "idempotency_key_reused"})
        response.status_code = 200
        return _shown(mine)
    evidence = (sanitize(body.evidence) or "").strip()
    if body.kind in LOST and not evidence:
        raise HTTPException(422, detail={"error": "evidence_required"})
    recorded = (await db.execute(text("SELECT reason, since FROM recovery_items WHERE item_id = :i "
                                      "AND reason = ANY(:r) ORDER BY since, reason LIMIT 1"),
                                 {"i": body.item_id, "r": list(COMMANDS[body.kind])})).first()  # fmt: skip
    if recorded is None:
        raise HTTPException(409, detail={"error": "not_recoverable"})
    try:
        made = (await db.execute(text(
            "INSERT INTO operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, "
            "idempotency_key, evidence) VALUES (:t, :k, :i, :r, :since, :u, :key, :e) ON CONFLICT DO NOTHING "
            "RETURNING id"),
            {"t": tenant_id, "k": body.kind, "i": body.item_id, "r": recorded.reason, "since": recorded.since,
             "u": admin.id, "key": body.idempotency_key, "e": evidence})).scalar()  # fmt: skip
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) == FENCED:
            raise HTTPException(409, detail={"error": "tenant_erased"}) from None
        raise
    if made is None:  # one already pending for the item and kind (or the same key, just recorded by another request)
        pending = await _command(db, "kind = :k AND item_id = :i AND status = 'pending'", k=body.kind, i=body.item_id)
        raise HTTPException(
            409, detail={"error": "command_pending", "command_id": str(pending.id) if pending else None}
        )
    await audit.record(db, tenant_id=tenant_id, actor_id=admin.id, action="operator.command.request",
                       target_type="operator_command", target_id=str(made),
                       details={"kind": body.kind, "item_id": str(body.item_id), "reason": recorded.reason,
                                "evidence": evidence})  # fmt: skip
    return _shown(await _command(db, "id = :c", c=made))


@router.get("/tenants/{tenant_id}/commands/{command_id}")
async def command(
    tenant_id: uuid.UUID,
    command_id: uuid.UUID,
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    await tenant_scope(db, tenant_id)
    found = await _command(db, "id = :c", c=command_id)
    if found is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return _shown(found)


@router.post("/tenants/{tenant_id}/held/release")
async def release(
    tenant_id: uuid.UUID,
    body: ReleaseIn,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    ensure_fresh_reauth(sess, settings)
    await _tenant(db, tenant_id)
    freed = await db.execute(text("SELECT work_failure_release(:k, :i)"), {"k": body.kind, "i": body.item_id})
    if not freed.scalar_one():
        raise HTTPException(404, detail={"error": "not_held"})
    await audit.record(db, tenant_id=tenant_id, actor_id=admin.id, action="work_failure.release",
                       target_type="work_item", target_id=str(body.item_id),
                       details={"kind": body.kind, "item_id": str(body.item_id)})  # fmt: skip
    return {"released": True, "kind": body.kind, "item_id": str(body.item_id)}


@router.get("/held")
async def held(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(text("SELECT * FROM work_failures_held(:n)"), {"n": limit})
    return {"items": [_shown(row) for row in found]}


@router.get("/recovery")
async def recovery(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(text("SELECT * FROM recovery_items_listed(:n)"), {"n": limit})
    return {"items": [_shown(row) for row in found]}
