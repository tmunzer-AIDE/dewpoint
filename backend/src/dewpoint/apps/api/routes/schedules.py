# SPDX-License-Identifier: Apache-2.0
"""Schedules (engine 2b spec §8.2): written with `trigger.manage`, read with `workflow.view`, never with their input.
The API writes a schedule's wanted state and raises its generation; the dispatcher's sync keeps Temporal in step with
it, so the API needs no Temporal client."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import schedules
from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
from dewpoint.core.authz.permissions import P
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.schedules import Schedule

router = APIRouter(prefix="/api/v1", tags=["schedules"])


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cron: str | None = Field(default=None, max_length=120)
    every_s: int | None = None
    offset_s: int = 0
    time_zone: str = Field(default="UTC", max_length=64)
    catchup_window_s: int = schedules.CATCHUP_DEFAULT
    mode: Literal["live", "simulate"] = "live"
    input: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SchedulePatch(BaseModel):
    """Only the fields given change; `cron` or `every_s` given as null switches the timing's kind."""

    model_config = ConfigDict(extra="forbid")
    cron: str | None = Field(default=None, max_length=120)
    every_s: int | None = None
    offset_s: int | None = None
    time_zone: str | None = Field(default=None, max_length=64)
    catchup_window_s: int | None = None
    mode: Literal["live", "simulate"] | None = None
    input: dict[str, Any] | None = None
    enabled: bool | None = None


def _refused(e: schedules.ScheduleRefusedError) -> HTTPException:
    return HTTPException(e.status, detail=e.detail)


@router.post("/t/{tenant_id}/workflows/{workflow_id}/schedules", status_code=201)
async def create_schedule(
    workflow_id: uuid.UUID,
    given: ScheduleIn,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    try:
        created = await schedules.create(
            db, keys, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=workflow_id,
            timing={k: getattr(given, k) for k in schedules.TIMING}, mode=given.mode, input=given.input,
            enabled=given.enabled,
        )  # fmt: skip
    except schedules.ScheduleRefusedError as e:
        raise _refused(e) from None
    except Exception as e:
        raise key_unusable(e) from None
    return schedules.body(created)


@router.get("/t/{tenant_id}/workflows/{workflow_id}/schedules")
async def list_schedules(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(
        select(Schedule)
        .where(Schedule.workflow_id == workflow_id, Schedule.deleted_at.is_(None))
        .order_by(Schedule.created_at, Schedule.id)
    )
    return {"schedules": [schedules.body(s) for s in found.scalars()]}


@router.get("/t/{tenant_id}/schedules/{schedule_id}")
async def get_schedule(
    schedule_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    schedule = await db.get(Schedule, schedule_id)  # row-level security: the caller's tenant's only
    if schedule is None or schedule.deleted_at is not None:
        raise HTTPException(404, detail={"error": "not_found"})
    return schedules.body(schedule)


@router.patch("/t/{tenant_id}/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: uuid.UUID,
    given: SchedulePatch,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    changes = {k: getattr(given, k) for k in given.model_fields_set}
    try:
        schedule = await schedules.found(db, schedule_id)
        updated = await schedules.update(db, keys, actor_id=ctx.user.id, schedule=schedule, changes=changes)
    except schedules.ScheduleRefusedError as e:
        raise _refused(e) from None
    except Exception as e:
        raise key_unusable(e) from None
    return schedules.body(updated)


@router.delete("/t/{tenant_id}/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    try:
        await schedules.delete(db, actor_id=ctx.user.id, schedule=await schedules.found(db, schedule_id))
    except schedules.ScheduleRefusedError as e:
        raise _refused(e) from None
    return Response(status_code=204)
