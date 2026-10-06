# SPDX-License-Identifier: Apache-2.0
"""Every request, slot and row transition of engine 2b spec §7.8, with a tenant limit of 1 (M5's proofs): after each,
the tenant's next request starts exactly when the slot is free. The first request is `first`, the next `second`."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import cancels
from dewpoint.apps.dispatcher import dispatch
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.plugins import lifecycle
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.runtime.activities import ProjectInput, RunSummary
from tests.apps.dispatcher.support import begin, state, workers
from tests.apps.test_admission import KEYS, admit, current, published
from tests.apps.test_workflow_ops import update

pytestmark = pytest.mark.usefixtures("development_deployment")


@pytest.fixture
async def limited(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    """A tenant limited to one run at a time, with two admitted requests, the first older."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1)"),
                        {"t": ctx.tenant_id})  # fmt: skip
    first = (await admit(api_sessionmaker, ctx, wf, key="first")).request
    second = (await admit(api_sessionmaker, ctx, wf, key="second")).request
    return ctx, wf, first, second


async def started(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
    found = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(found, dispatch.Starting), found
    return found


async def second_starts(dispatch_sessionmaker: Any, second: Any, settings: Any) -> bool:
    """Whether the tenant's next request starts now; it's put back as it was either way, for the next look."""
    found = await begin(dispatch_sessionmaker, second, settings)
    if isinstance(found, dispatch.Starting):
        assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("throttled")) == "throttled"
        return True
    assert found == dispatch.Waiting("no_slot"), found
    return False


async def due(owner: Any, request_id: uuid.UUID) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request_id})


async def row(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...] | None:
    async with owner() as s:
        found = await s.execute(text("select status, error_code, started_at from runs where id = :i"), {"i": run_id})
        first = found.first()
        return tuple(first) if first else None


async def end_write(worker: Any, ctx: Any, run_id: uuid.UUID, status: str = "succeeded") -> None:
    summary = RunSummary(str(run_id), status, datetime.now(UTC).isoformat())
    await DbRunStore(worker, KEYS).project(ProjectInput(str(ctx.tenant_id), [], summary))


async def test_queued_to_starting_reserves_the_slot_and_writes_the_row(
    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, first, second = limited
    await started(dispatch_sessionmaker, first, api_settings)
    assert await state(owner_sessionmaker, first.id) == {
        "request": ("starting", None, 0), "run": ("running", None, first.queued_at), "slot": 1,
    }  # fmt: skip
    await due(owner_sessionmaker, second.id)
    assert not await second_starts(dispatch_sessionmaker, second, api_settings)


async def test_starting_to_started_keeps_the_slot_until_the_roots_end_write(
    limited, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    ctx, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
    assert not await second_starts(dispatch_sessionmaker, second, api_settings)
    await end_write(worker_sessionmaker, ctx, first.id)
    assert await second_starts(dispatch_sessionmaker, second, api_settings)


async def test_an_uncertain_start_keeps_its_slot(
    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("uncertain")) == "uncertain"
    assert (await state(owner_sessionmaker, first.id))["request"][0] == "starting"
    assert not await second_starts(dispatch_sessionmaker, second, api_settings)


@pytest.mark.parametrize("outcome", ["refused", "absent"])
async def test_back_to_the_queue_frees_the_slot_at_once_and_keeps_the_row_hidden(
    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings, outcome
) -> None:
    _, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome(outcome)) == outcome
    after = await state(owner_sessionmaker, first.id)
    assert (after["request"][0], after["slot"], after["run"][0]) == ("queued", 0, "running")
    assert after["request"][2] == (1 if outcome == "refused" else 0)  # only a confirmed refusal is an attempt
    assert await second_starts(dispatch_sessionmaker, second, api_settings)


@pytest.mark.parametrize("cause", ["tenth_refusal", "collision"])
async def test_dead_frees_the_slot_and_fails_the_row(
    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings, cause
) -> None:
    _, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    if cause == "tenth_refusal":
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update run_requests set attempts = 9 where id = :i"), {"i": first.id})
    outcome = dispatch.Outcome("refused" if cause == "tenth_refusal" else "collision")
    assert await dispatch.settle(dispatch_sessionmaker, found, outcome) == "dead"
    reason = "start_refused" if cause == "tenth_refusal" else "id_collision"
    assert (await state(owner_sessionmaker, first.id))["request"][:2] == ("dead", reason)
    assert (await row(owner_sessionmaker, first.id))[:2] == ("failed", "start_failed")
    assert await second_starts(dispatch_sessionmaker, second, api_settings)


async def test_a_users_cancel_of_a_queued_request_ends_an_earlier_attempts_row(
    limited, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("refused")) == "refused"
    async with api_sessionmaker() as s, s.begin():
        assert await cancels.cancel_request(s, tenant_id=ctx.tenant_id, request_id=first.id,
                                            actor_id=ctx.user.id) == "cancelled"  # fmt: skip
    assert (await row(owner_sessionmaker, first.id))[:2] == ("cancelled", "user_cancelled")
    assert await second_starts(dispatch_sessionmaker, second, api_settings)


async def test_a_build_of_another_abi_cancels_a_queued_request_holding_nothing(
    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    from dewpoint.apps.dispatcher.observe import Build

    _, _, first, second = limited
    other = Build(f"dewpoint-9.9.9+abi{ENGINE_ABI + 1}", ENGINE_ABI + 1)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update worker_instances set build_id = :b"), {"b": other.build_id})
    assert await begin(dispatch_sessionmaker, first, api_settings, build=other) == dispatch.Cancelled(
        "engine_abi_changed"
    )
    assert (await state(owner_sessionmaker, first.id))["slot"] == 0


async def test_a_forced_retirement_cancels_a_queued_request_and_an_earlier_attempts_row(
    limited, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("refused")) == "refused"
    await update(api_sessionmaker, ctx, wf, enabled=False)
    async with admin_sessionmaker() as s, s.begin():
        assert (await lifecycle.retire(s, lifecycle.Entry("node", "testkit.echo@1"), force=True, confirm=True)).applied
    after = await state(owner_sessionmaker, first.id)
    assert (after["request"][:2], after["slot"]) == (("cancelled", "node_type_retired"), 0)
    assert (await row(owner_sessionmaker, first.id))[:2] == ("cancelled", "node_type_retired")


async def test_a_durable_sources_refusal_holds_no_slot_and_writes_no_row(
    limited, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, _, second = limited
    await update(api_sessionmaker, ctx, wf, enabled=False)
    refused = (await admit(api_sessionmaker, ctx, wf, key="tick", source="schedule")).request
    assert (refused.status, refused.reason) == ("refused", "workflow_disabled")
    assert await state(owner_sessionmaker, refused.id) == {
        "request": ("refused", "workflow_disabled", 0), "run": None, "slot": 0,
    }  # fmt: skip


async def test_a_fast_completion_before_the_starts_reply_is_never_undone(
    limited, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    """§7.8: the run finishes, its end write making its row terminal and freeing the slot, before the start's reply is
    settled. Confirming then only sets the request's status and a null start time: the row stays ended, and no slot
    comes back, so the tenant's next request starts."""
    ctx, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    await end_write(worker_sessionmaker, ctx, first.id)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
    after = await state(owner_sessionmaker, first.id)
    assert (after["request"][0], after["slot"], after["run"][0]) == ("started", 0, "succeeded")
    assert after["run"][1] is not None
    assert await second_starts(dispatch_sessionmaker, second, api_settings)


async def test_an_ended_runs_request_back_in_the_queue_goes_to_starting_holding_nothing(
    limited, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    """The recovery transition the owner accepted for revision 7's §7.8: `queued` -> `starting` without a slot, for a
    request whose run already ended."""
    ctx, _, first, second = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("absent")) == "absent"
    await end_write(worker_sessionmaker, ctx, first.id)  # a late end write
    assert await begin(dispatch_sessionmaker, first, api_settings) == dispatch.Held("run_ended")
    after = await state(owner_sessionmaker, first.id)
    assert (after["request"][0], after["slot"]) == ("starting", 0)
    assert await second_starts(dispatch_sessionmaker, second, api_settings)


async def test_a_start_found_absent_is_due_at_once_whatever_the_dispatchers_clock(
    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """Back in the queue "due at once" is due by the clock `begin` reads, the database's: stamped by the dispatcher's
    own, ahead of the database's (Docker Desktop's VM clock lags the host's, 66 to 678 ms measured, #38), it waited
    out the offset, and a start retried at once found nothing (M4's full-suite failures, accounted for)."""
    import datetime as real

    class Ahead(real.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
            return real.datetime.now(tz) + real.timedelta(seconds=1)

    monkeypatch.setattr(dispatch, "datetime", Ahead)
    _, _, first, _ = limited
    found = await started(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("absent")) == "absent"
    assert isinstance(await begin(dispatch_sessionmaker, first, api_settings), dispatch.Starting)
