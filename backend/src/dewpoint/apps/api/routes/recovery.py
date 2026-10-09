# SPDX-License-Identifier: Apache-2.0
"""The operator's recovery (the owner's rulings on the 2b-4b M3 design, rev 1 and 2), a platform admin's act: on an
active MFA session, and for every change a second factor proven within the reauthentication window, recording that
admin's user id with the change, in its transaction.

- **A command** on an item a pass left for recovery is recorded, pending, for the dispatcher's leader to carry out (the
  API has no Temporal client): only on an item with one of the command's reasons recorded, since when kept with it, and
  with the operator's evidence where the item's history is gone. An operator's idempotency key returns the same
  command again; an item has one pending command of a kind.
- **A release** of a held item, for the kind of work it names, at once, through a guarded function: never another
  kind's hold, nor a count that isn't held. **In bulk**, a tenant's held items of one kind held before a time, counted
  first, then released oldest first, `RELEASE_MAX` at most a request, audited once: never all of them across tenants.
- **The listings**, across tenants: held items and recovery reasons, as ids, kinds, reasons and times."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import active_session, ensure_fresh_reauth, get_db, get_settings_dep, require_platform_admin
from dewpoint.core.models.identity import AuthSession, User
from dewpoint.core.recovery import AUDITED_IDS, COMMANDS, EVIDENCE_LIMIT, LOST, RELEASE_MAX, CommandKind, WorkKind
from dewpoint.core.runs.service import sanitize
from dewpoint.core.tenancy import lifecycle
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


_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")  # a date and a time: never a bare number, nor a date alone


def _text(value: object) -> object:
    if not isinstance(value, str) or not _ISO.match(value):
        raise ValueError("an ISO 8601 timestamp with its offset")
    return value


def _utc(at: datetime) -> datetime:
    try:
        return at.astimezone(UTC)
    except OverflowError:  # past UTC's range once normalized: refused as any other bad value is (a 422, never a 500)
        raise ValueError("a timestamp within UTC's range") from None


# An ISO 8601 timestamp with an explicit offset, in UTC from then on (the owner's ruling on the M3 checkpoint 2): a
# naive one, a date or a number is refused
HeldBefore = Annotated[AwareDatetime, BeforeValidator(_text), AfterValidator(_utc)]


class ReleaseManyIn(BaseModel):
    """A tenant's held items of one kind, held before `held_before`: `max` of them at most, oldest first."""

    kind: WorkKind
    held_before: HeldBefore
    max: int = Field(ge=1, le=RELEASE_MAX)


def _shown(row: Any) -> dict[str, object]:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v.isoformat() if isinstance(v, datetime) else v)
            for k, v in row._mapping.items()}  # fmt: skip


async def _command(db: AsyncSession, query: str, **params: object) -> Any:
    return (await db.execute(text(f"SELECT {SHOWN} FROM operator_commands WHERE {query}"), params)).first()  # noqa: S608


async def _mine(db: AsyncSession, actor_id: uuid.UUID, key: str) -> Any:
    """The command this operator asked under `key` in the scoped tenant, or None."""
    return await _command(db, "actor_id = :u AND idempotency_key = :k", u=actor_id, k=key)


async def _tenant(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """A change's tenant, fenced as require() fences a member's write: its lifecycle lock, shared, in the request's
    transaction, before its status is read; refused unless it's active (an erasure's step 1, which takes the lock
    exclusively, waits for the change to commit, or the change sees `erasing`)."""
    await lifecycle.hold_shared(db, tenant_id)
    await tenant_scope(db, tenant_id)
    status = (await db.execute(text("SELECT status FROM tenants WHERE id = :t"), {"t": tenant_id})).scalar()
    if status is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if status != "active":
        raise HTTPException(409, detail={"error": "tenant_erasing"})


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
    mine = await _mine(db, admin.id, body.idempotency_key)
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
    if made is None:  # the same key, recorded by a request that committed meanwhile; else one pending for the item
        mine = await _mine(db, admin.id, body.idempotency_key)  # the insert waited for it: this statement sees it
        if mine is not None:
            if (mine.kind, mine.item_id) != (body.kind, body.item_id):
                raise HTTPException(409, detail={"error": "idempotency_key_reused"})
            response.status_code = 200
            return _shown(mine)
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


@router.get("/tenants/{tenant_id}/held/count")
async def held_count(
    tenant_id: uuid.UUID,
    kind: WorkKind,
    held_before: HeldBefore,
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """What a bulk release would free: the tenant's held items of `kind` held before `held_before`."""
    await tenant_scope(db, tenant_id)
    return {"kind": kind, "held_before": held_before.isoformat(), "held": await _held(db, kind, held_before)}


async def _held(db: AsyncSession, kind: str, held_before: datetime) -> int:
    found = await db.execute(text("SELECT work_failures_held_count(:k, :b)"), {"k": kind, "b": held_before})
    return int(found.scalar_one())


@router.post("/tenants/{tenant_id}/held/release-many")
async def release_many(
    tenant_id: uuid.UUID,
    body: ReleaseManyIn,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A bulk release (the owner's rulings on the M3 checkpoints): bounded by tenant, kind, `held_before` and `max`,
    never all of them across tenants; audited in its own transaction with the exact items it released, oldest first,
    `AUDITED_IDS` an entry (the count previewed may have changed meanwhile); what's still held answered."""
    ensure_fresh_reauth(sess, settings)
    await _tenant(db, tenant_id)
    found = await db.execute(text("SELECT item_id FROM work_failures_release_many(:k, :b, :n)"),
                             {"k": body.kind, "b": body.held_before, "n": body.max})  # fmt: skip
    ids = list(map(str, found.scalars().all()))
    parts = [ids[n : n + AUDITED_IDS] for n in range(0, len(ids), AUDITED_IDS)] or [[]]
    asked = {"kind": body.kind, "held_before": body.held_before.isoformat(), "max": body.max, "released": len(ids)}
    for n, part in enumerate(parts, start=1):
        await audit.record(db, tenant_id=tenant_id, actor_id=admin.id, action="work_failure.release_many",
                           target_type="tenant", target_id=str(tenant_id),
                           details=asked | {"part": n, "parts": len(parts), "item_ids": part})  # fmt: skip
    return {"kind": body.kind, "held_before": body.held_before.isoformat(), "released": len(ids),
            "held": await _held(db, body.kind, body.held_before)}  # fmt: skip


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
