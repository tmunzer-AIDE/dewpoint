# SPDX-License-Identifier: Apache-2.0
"""Schedules (engine 2b spec §8.2): their timing, checked against Temporal's own reading.

A cron expression is accepted only in the forms whose meaning `test_temporal_contract.py` pins on the dev server (the
owner's ruling 9): five fields (minute, hour, day of the month, month, day of the week), each `*`, a number, a range,
`*/step` or `a-b/step`, or a list of those; months and days of the week also by name, in any case, and Sunday as 0 or
7. A day of the month and a day of the week restricted together is refused: Temporal requires both to match, where
cron usually takes either, and Dewpoint never accepts an expression under a meaning of its own. A time zone's changes
skip a local time that doesn't exist and fire a repeated one once, at its second occurrence (pinned too). An interval
is at least 60 s, so with cron's minutes every tick's nominal time is its own (§8.2's tick key)."""

import functools
import json
import re
import uuid
import zoneinfo
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.inputs import FORGED, RESERVED_INPUT, reasons
from dewpoint.core.audit import service as audit
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.models.schedules import Schedule, ScheduleIncarnation, ScheduleInterval
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.engine.graph.csv import RESERVED, trigger_schema
from dewpoint.engine.handles import contains_marker

INPUT_PURPOSE = "schedule.input"  # the fixed input, sealed with the schedule's id as context
TIMING = ("cron", "every_s", "offset_s", "time_zone", "catchup_window_s")
MIN_INTERVAL = 60
MAX_INTERVAL = 366 * 24 * 3600
CATCHUP_MIN, CATCHUP_MAX, CATCHUP_DEFAULT = 60, 24 * 3600, 600  # §15: provisional
TIMING_CODES = frozenset(
    {"cron_fields", "cron_syntax", "cron_range", "cron_day_fields", "timing_missing", "timing_both",
     "interval_too_short", "interval_too_long", "interval_offset", "time_zone_unknown", "catchup_window"}
)  # fmt: skip

_MONTHS = {m: i for i, m in enumerate(("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC").split(), start=1)}
_DAYS = {d: i for i, d in enumerate(("SUN MON TUE WED THU FRI SAT").split())}
_NONE: dict[str, int] = {}
_FIELDS: tuple[tuple[int, int, dict[str, int]], ...] = (
    (0, 59, _NONE), (0, 23, _NONE), (1, 31, _NONE), (1, 12, _MONTHS), (0, 7, _DAYS)
)  # min, max, names  # fmt: skip
_ATOM = r"(?:[0-9]{1,2}|[A-Za-z]{3})"
_PART = re.compile(
    rf"(?:\*(?:/(?P<every>[0-9]{{1,2}}))?|(?P<a>{_ATOM})(?:-(?P<b>{_ATOM})(?:/(?P<step>[0-9]{{1,2}}))?)?)"
)


class _Bad(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _value(atom: str, low: int, high: int, names: dict[str, int]) -> int:
    if atom.isdigit():
        value = int(atom)
    elif atom.upper() in names:
        value = names[atom.upper()]
    else:
        raise _Bad("cron_syntax")
    if not low <= value <= high:
        raise _Bad("cron_range")
    return value


def _field(text: str, low: int, high: int, names: dict[str, int]) -> None:
    for part in text.split(","):
        found = _PART.fullmatch(part)
        if found is None:
            raise _Bad("cron_syntax")
        step = found["every"] or found["step"]
        if step is not None and int(step) == 0:
            raise _Bad("cron_range")
        if found["a"] is None:
            continue  # `*`, `*/step`
        a = _value(found["a"], low, high, names)
        if found["b"] is not None and _value(found["b"], low, high, names) < a:
            raise _Bad("cron_range")


def cron_problems(cron: str) -> list[str]:
    """Why `cron` isn't one of the forms Dewpoint accepts, as one code; empty when it is."""
    fields = cron.split()
    if len(fields) != 5:
        return ["cron_fields"]
    try:
        for text, (low, high, names) in zip(fields, _FIELDS, strict=True):
            _field(text, low, high, names)
    except _Bad as bad:
        return [bad.code]
    if fields[2] != "*" and fields[4] != "*":
        return ["cron_day_fields"]
    return []


@functools.cache
def _zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones() | {"UTC"})


def timing_problems(
    *, cron: str | None, every_s: int | None, offset_s: int, time_zone: str, catchup_s: int
) -> list[dict[str, Any]]:
    """What's wrong with a schedule's timing, each as its field and a code (`TIMING_CODES`)."""
    problems: list[dict[str, Any]] = []
    if cron is None and every_s is None:
        problems.append({"field": "cron", "code": "timing_missing"})
    elif cron is not None and every_s is not None:
        problems.append({"field": "every_s", "code": "timing_both"})
    elif cron is not None:
        problems += [{"field": "cron", "code": code} for code in cron_problems(cron)]
    elif every_s is not None:
        if every_s < MIN_INTERVAL:
            problems.append({"field": "every_s", "code": "interval_too_short"})
        elif every_s > MAX_INTERVAL:
            problems.append({"field": "every_s", "code": "interval_too_long"})
        elif not 0 <= offset_s < every_s:
            problems.append({"field": "offset_s", "code": "interval_offset"})
    if every_s is None and not 0 <= offset_s <= MAX_INTERVAL:  # a cron's, which the sync doesn't use: never a 500
        problems.append({"field": "offset_s", "code": "interval_offset"})
    if time_zone not in _zones():
        problems.append({"field": "time_zone", "code": "time_zone_unknown"})
    if not CATCHUP_MIN <= catchup_s <= CATCHUP_MAX:
        problems.append({"field": "catchup_window_s", "code": "catchup_window"})
    return problems


class ScheduleRefusedError(Exception):
    """A schedule the API refuses to write: the HTTP status and the fixed detail to answer with."""

    def __init__(self, status: int, detail: dict[str, Any]) -> None:
        super().__init__(detail["error"])
        self.status, self.detail = status, detail


async def _active_version(s: AsyncSession, workflow_id: uuid.UUID) -> WorkflowVersion:
    workflow = await s.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
    if workflow is None:
        raise ScheduleRefusedError(404, {"error": "not_found"})
    version = await s.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
    if version is None:
        raise ScheduleRefusedError(409, {"error": "not_active"})
    if (version.graph.get("settings") or {}).get("csv"):
        raise ScheduleRefusedError(409, {"error": "csv_required"})  # its rows come from an upload only (§8.1)
    return version


def _checked_input(version: WorkflowVersion, value: Mapping[str, Any]) -> None:
    """The fixed input against the active version, as admission checks a trigger: a tick checks it again."""
    if any(name in value for name in RESERVED):
        raise ScheduleRefusedError(422, {"error": "input_invalid", "messages": [RESERVED_INPUT]})
    refused = reasons(trigger_schema(version.graph.get("settings") or {}), value)
    if refused:
        raise ScheduleRefusedError(422, {"error": "input_invalid", "messages": refused})
    if contains_marker(value):
        raise ScheduleRefusedError(422, {"error": "input_invalid", "messages": [FORGED]})


def _checked_timing(timing: Mapping[str, Any]) -> None:
    problems = timing_problems(cron=timing["cron"], every_s=timing["every_s"], offset_s=timing["offset_s"],
                               time_zone=timing["time_zone"], catchup_s=timing["catchup_window_s"])  # fmt: skip
    if problems:
        raise ScheduleRefusedError(422, {"error": "schedule_invalid", "problems": problems})


async def _sealed(keys: KeySource, tenant_id: uuid.UUID, schedule_id: uuid.UUID, value: Mapping[str, Any]) -> bytes:
    plaintext = json.dumps(dict(value), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return await ClaimCipher(keys, purpose=INPUT_PURPOSE).seal(str(tenant_id), str(schedule_id), plaintext)


async def _audited(s: AsyncSession, action: str, actor_id: uuid.UUID, schedule: Schedule) -> None:
    details = {"schedule_id": str(schedule.id), "workflow_id": str(schedule.workflow_id),
               "generation": schedule.generation}  # fmt: skip
    await audit.record(s, tenant_id=schedule.tenant_id, actor_id=actor_id, action=action, target_type="schedule",
                       target_id=str(schedule.id), details=details)  # fmt: skip


async def create(
    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, workflow_id: uuid.UUID,
    timing: Mapping[str, Any], mode: str, input: Mapping[str, Any], enabled: bool,
) -> Schedule:  # fmt: skip
    """A schedule of the workflow's active version, its timing and its fixed input checked, the input sealed."""
    version = await _active_version(s, workflow_id)
    _checked_timing(timing)
    _checked_input(version, input)
    schedule_id = uuid.uuid4()
    schedule = Schedule(
        id=schedule_id, tenant_id=tenant_id, workflow_id=workflow_id, mode=mode, enabled=enabled, generation=1,
        synced_generation=0, input=await _sealed(keys, tenant_id, schedule_id, input), created_by=actor_id,
        **{k: timing[k] for k in TIMING},
    )  # fmt: skip
    s.add(schedule)
    await s.flush()
    await _audited(s, "schedule.create", actor_id, schedule)
    await s.refresh(schedule)
    return schedule


async def found(s: AsyncSession, schedule_id: uuid.UUID) -> Schedule:
    """A schedule of the caller's tenant that isn't a tombstone, locked for the change the caller makes."""
    schedule = (
        await s.execute(
            select(Schedule)
            .where(Schedule.id == schedule_id, Schedule.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise ScheduleRefusedError(404, {"error": "not_found"})
    return schedule


async def update(
    s: AsyncSession, keys: KeySource, *, actor_id: uuid.UUID, schedule: Schedule, changes: Mapping[str, Any]
) -> Schedule:
    """`changes` applied (the timing as a whole checked again, a new input against the active version), and the
    generation raised, which the sync follows."""
    timing = {k: changes.get(k, getattr(schedule, k)) for k in TIMING}
    _checked_timing(timing)
    if "input" in changes:
        _checked_input(await _active_version(s, schedule.workflow_id), changes["input"])
        schedule.input = await _sealed(keys, schedule.tenant_id, schedule.id, changes["input"])
    for key in TIMING:
        setattr(schedule, key, timing[key])
    for key in ("mode", "enabled"):
        if key in changes:
            setattr(schedule, key, changes[key])
    schedule.generation += 1
    schedule.updated_at = func.now()
    await s.flush()
    await _audited(s, "schedule.update", actor_id, schedule)
    await s.refresh(schedule)
    return schedule


async def delete(s: AsyncSession, *, actor_id: uuid.UUID, schedule: Schedule) -> None:
    """A tombstone: its fixed input cleared, its generation raised for the sync to delete it from Temporal; its
    tenant, id, workflow and mode kept, so a late tick still records `schedule_deleted`."""
    schedule.input = None
    schedule.deleted_at = func.now()
    schedule.generation += 1
    schedule.updated_at = func.now()
    await s.flush()
    await _audited(s, "schedule.delete", actor_id, schedule)


@dataclass(frozen=True)
class Accounting:
    """A schedule's missed-firing accounting (D3f; the owner's ruling B and its review): complete only when no span of
    its life is possibly missed, unknown or still pending; those spans, uncounted, in order, with their bounds (`to`
    None while one is open) and fixed reasons."""

    uncounted: list[dict[str, str | None]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.uncounted


async def accounting(s: AsyncSession, schedule_id: uuid.UUID) -> Accounting:
    """The recorded spans that are possibly missed or unknown, and the wait of its current Temporal id while it has no
    span yet: pending, open until the first update lands (`awaiting_first_update`, from the schedule's creation for a
    schedule never synced or its first id, else the id's recording), then until its count is recorded
    (`count_pending`, to that landing)."""
    found = await s.execute(
        select(ScheduleInterval)
        .where(ScheduleInterval.schedule_id == schedule_id,
               ScheduleInterval.class_.in_(("possibly_missed", "unknown")))
    )  # fmt: skip
    spans: list[tuple[datetime, dict[str, str | None]]] = [
        (i.starts_at, {"from": i.starts_at.isoformat(), "to": i.ends_at.isoformat(), "class": i.class_,
                       "reason": i.reason}) for i in found.scalars()
    ]  # fmt: skip
    ids = (await s.execute(select(ScheduleIncarnation).where(ScheduleIncarnation.schedule_id == schedule_id)
                           .order_by(ScheduleIncarnation.number))).scalars().all()  # fmt: skip
    current = ids[-1] if ids else None
    counted = current is not None and bool(await s.scalar(
        select(func.count()).select_from(ScheduleInterval)
        .where(ScheduleInterval.temporal_id == current.temporal_id, ScheduleInterval.kind == "creation")
    ))  # fmt: skip
    if current is None or not (current.backfilled or counted):
        created = await s.scalar(select(Schedule.created_at).where(Schedule.id == schedule_id))
        start = current.recorded_at if current is not None and len(ids) > 1 else created
        landed = current.landed_at if current is not None else None
        if start is not None:
            spans.append((start, {"from": start.isoformat(), "to": landed.isoformat() if landed else None,
                                  "class": "pending",
                                  "reason": "count_pending" if landed else "awaiting_first_update"}))  # fmt: skip
    return Accounting([span for _, span in sorted(spans, key=lambda pair: pair[0])])


def body(schedule: Schedule, accounted: Accounting) -> dict[str, object]:
    """A schedule as the API shows it: never its input."""
    return {
        "id": str(schedule.id),
        "workflow_id": str(schedule.workflow_id),
        **{k: getattr(schedule, k) for k in TIMING},
        "mode": schedule.mode,
        "enabled": schedule.enabled,
        "generation": schedule.generation,
        "synced_generation": schedule.synced_generation,
        "misses": schedule.misses + schedule.creation_misses,  # every firing certainly missed, both kinds (D3f)
        "missed_while_created": schedule.creation_misses,  # due while it waited, created paused, for its unpause
        # Temporal's count, read every five minutes: `misses` as of then (a deletion reads it last, paused, D3f)
        "misses_read_at": schedule.misses_checked_at.isoformat() if schedule.misses_checked_at else None,
        "accounting_complete": accounted.complete,  # false: some span's firings are possibly missed, unknown or pending
        "uncounted_intervals": accounted.uncounted,  # those spans, never in `misses`
        "sync_error": schedule.sync_error,
        "created_at": schedule.created_at.isoformat(),
        "updated_at": schedule.updated_at.isoformat(),
    }
