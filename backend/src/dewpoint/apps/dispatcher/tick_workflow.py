# SPDX-License-Identifier: Apache-2.0
"""`ScheduleTick` (engine 2b spec §8.2): the workflow a Temporal Schedule's action starts, without an argument: its
schedule is the one its workflow id names (the owner's M3 ruling; an action synced before carried the schedule's id,
sealed, which a legacy tick still receives and ignores). It reads its nominal time (`TemporalScheduledStartTime`, set by
Temporal, deterministic under replay and catch-up, whole seconds) once, builds the tick key from it and passes both to
its one activity, which it retries without limit: a platform-wide failure waits (§2.5), and only the activity's own
non-retryable codes end a tick unadmitted. What it carries in Temporal is the tick contract's, unsealed
(`apps.tick_contract`): no tick holds a payload under a tenant's data key.

Unversioned and outside the engine's Worker Deployment: it holds no engine logic, and its replay test pins its short
contract, whatever `ENGINE_ABI` is."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from dewpoint.apps.dispatcher.tick import TICK, TickInput, tick_key
    from dewpoint.apps.tick_contract import NO_NOMINAL_TIME, TICK_IDENTITY
    from dewpoint.engine.runtime.ids import schedule_of

SCHEDULED = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=1)
)


@workflow.defn(name="ScheduleTick")
class ScheduleTick:
    @workflow.run
    async def run(self, legacy: str | None = None) -> str:
        """`legacy`: the argument an action synced before the tick contract carried; the workflow id names the
        schedule, as it always decided."""
        named = schedule_of(workflow.info().workflow_id)
        if named is None:  # a schedule's firings only
            raise ApplicationError("A tick of no schedule.", type=TICK_IDENTITY, non_retryable=True)
        nominal = workflow.info().typed_search_attributes.get(SCHEDULED)
        if nominal is None:  # not started by a schedule: there's no tick to key
            raise ApplicationError("A tick without its nominal time.", type=NO_NOMINAL_TIME, non_retryable=True)
        schedule_id = named[1]
        key, stamp = tick_key(schedule_id, nominal)
        outcome: str = await workflow.execute_activity(
            TICK, TickInput(schedule_id, key, stamp), result_type=str, start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY,
        )  # fmt: skip
        return outcome
