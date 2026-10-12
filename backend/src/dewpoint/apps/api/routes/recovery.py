# SPDX-License-Identifier: Apache-2.0
"""The operator's recovery (the owner's rulings on the 2b-4b M3 design, rev 1 and 2), a platform admin's act: on an
active MFA session, and for every change a second factor proven within the reauthentication window, recording that
admin's user id with the change, in its transaction.

- **A command** on an item a pass left for recovery is recorded, pending, for the dispatcher's leader to carry out (the
  API has no Temporal client): only on an item with one of the command's reasons recorded, since when kept with it, and
  with the operator's evidence where the item's history is gone. An operator's idempotency key returns the same
  command again; an item has one pending command of a kind.
- **A release** of a held item, for the kind of work it names, or **in bulk** (a tenant's held items of one kind held
  before a time, oldest first, `RELEASE_MAX` at most), is a command too (2b-4b M4 recovery, task 8; design revisions 7
  and 8): recorded pending with the holds it shows, each with its token (its snapshot, the database's own selection),
  and released by the leader once its operator confirms it, those holds alone. The API releases nothing itself. An item
  not held, or no hold eligible, records nothing.
- **The listings**, across tenants: held items and recovery reasons, as ids, kinds, reasons and times."""

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.auth.sessions import SESSION_COOKIE
from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import active_session, ensure_fresh_reauth, get_db, get_settings_dep, require_platform_admin
from dewpoint.core.models.identity import AuthSession, User
from dewpoint.core.recovery import (
    ABANDON,
    ABANDON_EVIDENCE_LIMIT,
    COMMANDS,
    EVIDENCE_LIMIT,
    INSPECT,
    LOST,
    RELEASE_MAX,
    CommandKind,
    WorkKind,
)
from dewpoint.core.runs.service import sanitize
from dewpoint.core.tenancy import lifecycle
from dewpoint.core.tenancy.lifecycle import FENCED

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

SHOWN = (
    "id, tenant_id, kind, item_id, reason, incident_since, actor_id, status, outcome, requested_at, decided_at, "
    "work_kind, held_before, max_holds"
)


class TemporalResponse(BaseModel):
    """The Temporal response an operator saw, exactly, and when."""

    call: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    observed_at: AwareDatetime


class AbandonEvidence(BaseModel):
    """An abandonment's evidence (task 10): the identifiers (the leader checks each against the record), the Temporal
    response its operator saw, their rationale, and a visibility result if any (recorded, never proof)."""

    tenant_id: uuid.UUID
    request_id: uuid.UUID
    workflow_id: str = Field(min_length=1, max_length=200)
    start_request_id: uuid.UUID | None
    temporal_response: TemporalResponse
    rationale: str = Field(min_length=1, max_length=1000)
    visibility: str | None = Field(default=None, max_length=1000)


class CommandIn(BaseModel):
    kind: CommandKind
    item_id: uuid.UUID
    evidence: str = Field(default="", max_length=EVIDENCE_LIMIT)
    idempotency_key: str = Field(min_length=1, max_length=100)
    abandon: AbandonEvidence | None = None  # an abandonment's, structured


class ReleaseIn(BaseModel):
    kind: WorkKind
    item_id: uuid.UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)  # one made if none


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
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)


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
    if body.kind == ABANDON:  # canonical JSON: what its operator confirms, and the leader checks
        if body.abandon is None:
            raise HTTPException(422, detail={"error": "evidence_required"})
        evidence = json.dumps(body.abandon.model_dump(mode="json", exclude_unset=True), sort_keys=True,
                              separators=(",", ":"))  # fmt: skip
        if len(evidence) > ABANDON_EVIDENCE_LIMIT:
            raise HTTPException(422, detail={"error": "evidence_too_long"})
    if body.kind in LOST and not evidence:
        raise HTTPException(422, detail={"error": "evidence_required"})
    recorded = (await db.execute(text("SELECT reason, since FROM recovery_items WHERE item_id = :i "
                                      "AND reason = ANY(:r) ORDER BY since, reason LIMIT 1"),
                                 {"i": body.item_id, "r": list(COMMANDS[body.kind])})).first()  # fmt: skip
    if body.kind == INSPECT:  # a request's blocker, which the API can't read: the reveal checks it (task 9)
        recorded = None
    elif recorded is None:
        raise HTTPException(409, detail={"error": "not_recoverable"})
    try:
        made = (await db.execute(text(
            "INSERT INTO operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, "
            "idempotency_key, evidence) VALUES (:t, :k, :i, :r, :since, :u, :key, :e) ON CONFLICT DO NOTHING "
            "RETURNING id"),
            {"t": tenant_id, "k": body.kind, "i": body.item_id, "r": recorded and recorded.reason,
             "since": recorded and recorded.since, "u": admin.id, "key": body.idempotency_key,
             "e": evidence})).scalar()  # fmt: skip
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
                       details={"kind": body.kind, "item_id": str(body.item_id),
                                "reason": recorded and recorded.reason, "evidence": evidence})  # fmt: skip
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


def _holds(rows: Any) -> list[dict[str, object]]:
    return [_shown(row) for row in rows]


async def _released(db: AsyncSession, tenant_id: uuid.UUID, admin: User, response: Response, *, kind: str,
                    work_kind: str, key: str | None, item_id: uuid.UUID | None = None,
                    held_before: datetime | None = None,
                    max_holds: int | None = None) -> dict[str, object]:  # fmt: skip
    """A release recorded as a command (task 8): pending, with the holds it shows, for its operator to confirm. The
    same key returns the same command again; nothing held records nothing."""
    key = key or f"{kind}:{uuid.uuid4()}"
    asked = (kind, work_kind, item_id, held_before, max_holds)

    async def again(mine: Any) -> dict[str, object]:
        if (mine.kind, mine.work_kind, mine.item_id, mine.held_before, mine.max_holds) != asked:
            raise HTTPException(409, detail={"error": "idempotency_key_reused"})
        response.status_code = 200
        shown = await db.execute(text("SELECT kind, item_id, hold_id FROM operator_command_holds_shown(:c)"),
                                 {"c": mine.id})  # fmt: skip
        return _shown(mine) | {"holds": _holds(shown)}

    mine = await _mine(db, admin.id, key)
    if mine is not None:
        return await again(mine)
    try:
        made = (await db.execute(text(
            "INSERT INTO operator_commands (tenant_id, kind, item_id, work_kind, held_before, max_holds, actor_id, "
            "idempotency_key) VALUES (:t, :k, :i, :w, :b, :n, :u, :key) ON CONFLICT DO NOTHING RETURNING id"),
            {"t": tenant_id, "k": kind, "i": item_id, "w": work_kind, "b": held_before, "n": max_holds, "u": admin.id,
             "key": key})).scalar()  # fmt: skip
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) == FENCED:
            raise HTTPException(409, detail={"error": "tenant_erased"}) from None
        raise
    if made is None:  # the same key, recorded meanwhile; else one pending for the item
        mine = await _mine(db, admin.id, key)
        if mine is not None:
            return await again(mine)
        pending = await _command(db, "kind = :k AND item_id = :i AND status = 'pending'", k=kind, i=item_id)
        raise HTTPException(
            409, detail={"error": "command_pending", "command_id": str(pending.id) if pending else None}
        )
    holds = (await db.execute(text("SELECT kind, item_id, hold_id, held_at FROM operator_command_holds_snapshot(:c)"),
                              {"c": made})).all()  # fmt: skip
    if not holds:  # the request's transaction rolls the command back
        raise HTTPException(404, detail={"error": "not_held"})
    await audit.record(db, tenant_id=tenant_id, actor_id=admin.id, action="operator.command.request",
                       target_type="operator_command", target_id=str(made),
                       details={"kind": kind, "work_kind": work_kind, "item_id": item_id and str(item_id),
                                "held_before": held_before and held_before.isoformat(), "max_holds": max_holds,
                                "holds": len(holds)})  # fmt: skip
    return _shown(await _command(db, "id = :c", c=made)) | {"holds": _holds(holds)}


@router.post("/tenants/{tenant_id}/held/release", status_code=202)
async def release(
    tenant_id: uuid.UUID,
    body: ReleaseIn,
    response: Response,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A held item's release, recorded as a command with the hold it shows; released once its operator confirms it."""
    ensure_fresh_reauth(sess, settings)
    await _tenant(db, tenant_id)
    return await _released(db, tenant_id, admin, response, kind="release_held", work_kind=body.kind,
                           key=body.idempotency_key, item_id=body.item_id)  # fmt: skip


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


@router.post("/tenants/{tenant_id}/held/release-many", status_code=202)
async def release_many(
    tenant_id: uuid.UUID,
    body: ReleaseManyIn,
    response: Response,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A bulk release (the owner's rulings on the M3 checkpoints), bounded by tenant, kind, `held_before` and `max`,
    never all of them across tenants: recorded as a command with the holds it shows, oldest first, released once its
    operator confirms it, those alone (task 8)."""
    ensure_fresh_reauth(sess, settings)
    await _tenant(db, tenant_id)
    return await _released(db, tenant_id, admin, response, kind="release_held_many", work_kind=body.kind,
                           key=body.idempotency_key, held_before=body.held_before, max_holds=body.max)  # fmt: skip


@router.get("/held")
async def held(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(text("SELECT * FROM work_failures_held(:n)"), {"n": limit})
    return {"items": [_shown(row) for row in found]}


@router.get("/recovery/unresolved-sends/counts")
async def unresolved_counts(
    request: Request,
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """Unresolved sends, counted (task 9): per state, with open sends and the oldest, and the erasures they hold. The
    database checks the caller's session itself (`admin_session`) and returns no identifier."""
    try:
        found = await db.execute(text("SELECT * FROM unresolved_sends_counts(:t)"),
                                 {"t": request.cookies.get(SESSION_COOKIE)})  # fmt: skip
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) == "42501":  # insufficient_privilege
            raise HTTPException(403, detail={"error": "forbidden"}) from None
        raise
    return {"states": [_shown(row) for row in found]}


@router.get("/recovery")
async def recovery(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(text("SELECT * FROM recovery_items_listed(:n)"), {"n": limit})
    return {"items": [_shown(row) for row in found]}
