# SPDX-License-Identifier: Apache-2.0
"""What this deployment is (engine 2b spec §2.1): production or development, and the Temporal namespace it uses,
recorded once. A process that talks to Temporal checks its configured namespace against the record before it starts,
so a development database can't drive a namespace it wasn't set up for, and a production database can't either. The
label proves nothing about the data: keeping development's database and namespace apart from production's is the
operator's job. Its engine worker instances record what they can do (§2.7)."""

import json
import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.models.platform import DispatcherReport, PlatformSettings, WorkerInstance
from dewpoint.core.models.requests import CurrentBuild

PRODUCTION = "production"
DEVELOPMENT = "development"
ENVIRONMENTS = (PRODUCTION, DEVELOPMENT)
NOT_RECORDED = (
    "This deployment's environment isn't recorded: run `dewpoint platform init-environment` (Compose's migrate step "
    "does) before starting anything that talks to Temporal."
)


class EnvironmentNotRecordedError(Exception):
    def __init__(self) -> None:
        super().__init__(NOT_RECORDED)


class EnvironmentMismatchError(Exception):
    pass


async def set_ingress_capacity(
    s: AsyncSession, *, starts_per_s: float | None, headroom: float | None, queue_wait_s: int | None,
    actor_id: uuid.UUID | None,
) -> None:  # fmt: skip
    """The deployment's ingress capacity (the owner's ruling 2 on the 2b-4b M3 checkpoint 2), as `dewpoint_admin`, in
    the caller's transaction, audited with what it was: the sustained starts measured on its own Temporal, the share
    of them ingress may use (above 0, at most 1), and the agreed wait a tenant's queued webhook requests may stand for
    (seconds). None unsets one: ingress keeps its configured rates (development-only) until the first two are set, and
    a development-only cap until all three are. Raises ValueError for a value out of range."""
    if (
        (starts_per_s is not None and not starts_per_s > 0)
        or (headroom is not None and not 0 < headroom <= 1)
        or (queue_wait_s is not None and not queue_wait_s > 0)
    ):
        raise ValueError("The ingress capacity needs starts above 0, a headroom above 0 and at most 1, a wait above 0.")
    found = await s.execute(text("select set_ingress_capacity(:s, :h, :w)::text"),
                            {"s": starts_per_s, "h": headroom, "w": queue_wait_s})  # fmt: skip
    after = {"starts_per_s": starts_per_s, "headroom": headroom, "queue_wait_s": queue_wait_s}
    await audit.record(s, tenant_id=None, actor_id=actor_id, action="platform.ingress_capacity.set",
                       target_type="platform", target_id="ingress_capacity",
                       details={"before": json.loads(found.scalar_one()), "after": after})  # fmt: skip


async def recorded(s: AsyncSession) -> PlatformSettings | None:
    return await s.get(PlatformSettings, 1)


async def record_environment(s: AsyncSession, *, environment: str, namespace: str) -> PlatformSettings:
    """Record it once. Recording the same values again changes nothing; other values are refused: a deployment never
    changes environment or namespace (a trigger enforces it too)."""
    if environment not in ENVIRONMENTS:
        raise ValueError(f"The environment is `production` or `development`, not `{environment}`.")
    if not namespace:
        raise ValueError("The Temporal namespace can't be empty.")
    existing = await recorded(s)
    if existing is None:
        row = PlatformSettings(id=1, environment=environment, temporal_namespace=namespace)
        s.add(row)
        await s.flush()
        return row
    if (existing.environment, existing.temporal_namespace) != (environment, namespace):
        raise EnvironmentMismatchError(
            f"This deployment is recorded as {existing.environment}, with the Temporal namespace "
            f"`{existing.temporal_namespace}`. Neither can change."
        )
    return existing


async def check_namespace(s: AsyncSession, configured: str) -> PlatformSettings:
    """The record, when this process's namespace is the recorded one. Raises otherwise: the process must not start."""
    row = await recorded(s)
    if row is None:
        raise EnvironmentNotRecordedError()
    if row.temporal_namespace != configured:
        raise EnvironmentMismatchError(
            f"This deployment uses the Temporal namespace `{row.temporal_namespace}`, but this process is configured "
            f"for `{configured}` (DEWPOINT_TEMPORAL_NAMESPACE). It won't start."
        )
    return row


async def record_worker(
    s: AsyncSession, *, instance_id: uuid.UUID, build_id: str, capabilities: Sequence[str], healthy: bool
) -> None:
    """An engine worker instance's row, written at startup and after each self-check (engine 2b spec §2.7)."""
    values = {"build_id": build_id, "capabilities": list(capabilities), "healthy": healthy}
    statement = insert(WorkerInstance).values(instance_id=instance_id, **values)
    await s.execute(
        statement.on_conflict_do_update(index_elements=["instance_id"], set_={**values, "checked_at": func.now()})
    )


LIVE_WINDOW = timedelta(seconds=90)  # an instance that hasn't checked in since isn't live (engine 2b spec §2.7)


async def workers_ready(s: AsyncSession, build_id: str, required: Sequence[str]) -> list[str]:
    """What holds `build_id` back from running new work, empty when nothing does (engine 2b spec §2.7): every live
    instance of it (checked within LIVE_WINDOW, by the statement's clock) is healthy and holds every capability in
    `required`, and at least one exists. One fresh healthy row can't hide another live instance that lacks one."""
    live = (
        (
            await s.execute(
                select(WorkerInstance).where(
                    WorkerInstance.build_id == build_id,
                    WorkerInstance.checked_at >= func.statement_timestamp() - LIVE_WINDOW,
                )
            )
        )
        .scalars()
        .all()
    )
    if not live:
        return [f"No live engine worker instance of build {build_id}."]
    problems = []
    for instance in sorted(live, key=lambda i: str(i.instance_id)):
        missing = sorted(set(required) - set(instance.capabilities))
        if not instance.healthy:
            problems.append(f"Engine worker instance {instance.instance_id} of build {build_id} isn't healthy.")
        elif missing:
            problems.append(
                f"Engine worker instance {instance.instance_id} of build {build_id} lacks {', '.join(missing)}."
            )
    return problems


async def record_current_build(s: AsyncSession, build_id: str, engine_abi: int) -> None:
    """The current build as the dispatcher just read it from Temporal, and when: admission's ABI check (the owner's
    ruling on 2b-2), which fails closed once the record is stale."""
    values = {"build_id": build_id, "engine_abi": engine_abi, "observed_at": func.statement_timestamp()}
    statement = insert(CurrentBuild).values(id=1, **values)
    await s.execute(statement.on_conflict_do_update(index_elements=["id"], set_=values))


async def record_dispatcher(
    s: AsyncSession, *, instance_id: uuid.UUID, kind: str, build_id: str, details: dict[str, object]
) -> None:
    """A dispatcher instance's report, written each cycle (engine 2b spec §10.6)."""
    statement = insert(DispatcherReport).values(instance_id=instance_id, kind=kind, build_id=build_id, details=details)
    await s.execute(
        statement.on_conflict_do_update(
            index_elements=["instance_id"],
            set_={"kind": kind, "build_id": build_id, "details": details, "reported_at": func.now()},
        )
    )


async def record_run_duration(s: AsyncSession, days: int) -> None:
    """A maximum run duration the dispatcher sets deadlines with, kept for good (engine 2b spec §6.4)."""
    await s.execute(text("INSERT INTO run_duration_limits (days) VALUES (:d) ON CONFLICT DO NOTHING"), {"d": days})


async def longest_run_duration_days(s: AsyncSession) -> int | None:
    """The longest maximum run duration ever recorded, or None when none is: the payload floor can't be reckoned."""
    found = (await s.execute(text("SELECT max(days) FROM run_duration_limits"))).scalar()
    return None if found is None else int(found)


async def inventory_cut_over(s: AsyncSession) -> bool:
    """Whether the schedule inventory's cutover is recorded (`schedules inventory-cutover`): only from it may a
    dispatcher pass or an erasure stage rely on every Temporal id a schedule may have. Before it, a dispatcher from
    before migration 0040 may still sync a schedule under its own id (the owner's D15 ruling on the 2b-4b M1
    checkpoint)."""
    return bool(await s.scalar(text("SELECT EXISTS (SELECT 1 FROM schedule_inventory_cutover)")))
