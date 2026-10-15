# SPDX-License-Identifier: Apache-2.0
"""A draft simulation's steps, summarized on the server (B8; the simulation design §6.6, §7.4): per step of the graph it
ran, its instances' final attempts counted by status and by the port they took, a single instance's final attempt, and
where its data came from; and a step's instances, one per iteration, paged in their iterations' own order. The general
run detail stays unpaged until 4e (§9)."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnExpressionArgument, Integer, Select, cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from dewpoint.core.models.runs import RunStep
from dewpoint.core.runs.service import HISTORY_LOST
from dewpoint.engine.registry.control import CONTROL_TYPES, DELAY, WAIT_UNTIL
from dewpoint.engine.runtime.execution import INTERNAL_ERROR, TERMINATED

# D-a5: a run that ended outside the workflow (a bug, a termination, a lost history) never recorded what it would have
NOT_RECORDED = frozenset({INTERNAL_ERROR, TERMINATED, HISTORY_LOST})


def origin(type_ref: str, statuses: Mapping[str, int], *, ended: bool, error_code: str | None) -> str:
    """Where a step's data came from (§7.4), from its instances' final attempts: one that began and wasn't stopped
    says what made it (a timer that wasn't waited, an evaluation, or a plugin's fixture: nothing was sent); else the
    instances say why none did. With none, where the run is: not reached yet while it runs; after its end, not
    recorded in D-a5's cases, else it didn't run."""
    if any(statuses.get(status) for status in ("succeeded", "failed", "running")):
        if type_ref in (DELAY, WAIT_UNTIL):
            return "evaluated_not_waited"
        return "evaluated" if type_ref in CONTROL_TYPES else "fixture_not_sent"
    for status in ("cancelled", "not_started", "skipped"):
        if statuses.get(status):
            return status
    if not ended:
        return "not_reached_yet"
    return "not_recorded" if error_code in NOT_RECORDED else "didnt_run"


@dataclass
class Summarized:
    """A step of the graph a simulation ran, as §6.6 summarizes it."""

    step_id: uuid.UUID
    key: str
    type: str
    origin: str
    statuses: dict[str, int] = field(default_factory=dict)  # its instances, by their final attempt's status
    ports: dict[str, int] = field(default_factory=dict)  # and by the port it took (an `if`'s, a `switch`'s)
    final: RunStep | None = None  # a single instance's final attempt
    first_at: datetime | None = None  # when it first began, or ended without beginning: its place in run order

    @property
    def instances(self) -> int:
        return sum(self.statuses.values())


def _finals(run_id: uuid.UUID) -> Select[Any]:
    """Each instance's final attempt: the latest, retries included."""
    return (
        select(RunStep)
        .where(RunStep.run_id == run_id)
        .ext(distinct_on(RunStep.step_id, RunStep.iteration_key))
        .order_by(RunStep.step_id, RunStep.iteration_key, RunStep.attempt.desc())
    )


async def summarize(
    s: AsyncSession, run_id: uuid.UUID | None, nodes: Sequence[Mapping[str, Any]], *, ended: bool,
    error_code: str | None,
) -> list[Summarized]:  # fmt: skip
    """The steps `nodes` (the snapshot's, or a step test's target) of the run `run_id` (None: not written yet), in run
    order: the steps that began or ended by when they first did, then the others in the graph's order."""
    found = {uuid.UUID(n["id"]): Summarized(uuid.UUID(n["id"]), n["key"], n["type"], "") for n in nodes}
    if run_id is not None:
        final = _finals(run_id).subquery()
        port = final.c.effect_preview["port"].astext
        counts = await s.execute(
            select(final.c.step_id, final.c.status, port, func.count()).group_by(final.c.step_id, final.c.status, port)
        )
        for step_id, status, taken, n in counts:
            if (step := found.get(step_id)) is not None:
                step.statuses[status] = step.statuses.get(status, 0) + n
                if taken is not None:
                    step.ports[taken] = step.ports.get(taken, 0) + n
        firsts = await s.execute(
            select(RunStep.step_id, func.min(func.coalesce(RunStep.started_at, RunStep.ended_at)))
            .where(RunStep.run_id == run_id)
            .group_by(RunStep.step_id)
        )
        for step_id, first_at in firsts:
            if (step := found.get(step_id)) is not None:
                step.first_at = first_at
        singles = [step.step_id for step in found.values() if step.instances == 1]
        if singles:
            rows = await s.execute(_finals(run_id).where(RunStep.step_id.in_(singles)))
            for row in rows.scalars():
                found[row.step_id].final = row
    for step in found.values():
        step.origin = origin(step.type, step.statuses, ended=ended, error_code=error_code)
    order = {step_id: n for n, step_id in enumerate(found)}
    return sorted(found.values(), key=lambda x: (x.first_at is None, x.first_at or datetime.min, order[x.step_id]))


def _numbered(key: ColumnExpressionArgument[str]) -> ColumnElement[Any]:
    """An iteration key's indexes as numbers, outermost first: `l:2` before `l:10` (the engine writes `loop:index`,
    joined by `/`, as `samples.newest` reads them; a step's instances all share its loops)."""
    return cast(func.string_to_array(func.regexp_replace(key, "[a-z][a-z0-9_]*:", "", "g"), "/"), ARRAY(Integer))


async def instances(
    s: AsyncSession, run_id: uuid.UUID, step_id: uuid.UUID, *, within: str | None, offset: int, limit: int
) -> tuple[int, list[RunStep]]:
    """A step's instances, each its final attempt, in iteration order: their total and the page from `offset`; within
    the iteration `within` (itself, and every iteration nested in it) when given."""
    query = _finals(run_id).where(RunStep.step_id == step_id)
    if within is not None:
        query = query.where(
            or_(RunStep.iteration_key == within, RunStep.iteration_key.startswith(f"{within}/", autoescape=True))
        )
    final = query.subquery()
    total = (await s.execute(select(func.count()).select_from(final))).scalar_one()
    one = aliased(RunStep, final)
    page = await s.execute(
        select(one).order_by(_numbered(one.iteration_key), one.iteration_key).offset(offset).limit(limit)
    )
    return total, list(page.scalars())
