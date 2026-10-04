# SPDX-License-Identifier: Apache-2.0
"""`ScheduleTick` (engine 2b spec §8.2): the workflow a Temporal Schedule's action starts, with the schedule's id as its
only argument. It reads its nominal time (`TemporalScheduledStartTime`, set by Temporal, deterministic under replay and
catch-up, whole seconds) once, builds the tick key from it and passes both to its one activity, which it retries without
limit: a platform-wide failure waits (§2.5), and only the activity's own non-retryable codes end a tick unadmitted.

Unversioned and outside the engine's Worker Deployment: it holds no engine logic, and its replay test pins its short
contract, whatever `ENGINE_ABI` is."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from dewpoint.apps.dispatcher.tick import TICK, TickInput, tick_key

SCHEDULED = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")
NO_NOMINAL_TIME = "tick_no_nominal_time"
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=1)
)


@workflow.defn(name="ScheduleTick")
class ScheduleTick:
    @workflow.run
    async def run(self, schedule_id: str) -> str:
        nominal = workflow.info().typed_search_attributes.get(SCHEDULED)
        if nominal is None:  # not started by a schedule: there's no tick to key
            raise ApplicationError("A tick without its nominal time.", type=NO_NOMINAL_TIME, non_retryable=True)
        key, stamp = tick_key(schedule_id, nominal)
        outcome: str = await workflow.execute_activity(
            TICK, TickInput(schedule_id, key, stamp), result_type=str, start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY,
        )  # fmt: skip
        return outcome
