# SPDX-License-Identifier: Apache-2.0
"""What a schedule tick may carry in Temporal, unsealed: §6.2's one exception (the owner's M3 ruling).

A `ScheduleTick` execution holds no payload under a tenant's data key, so retiring a key never waits for a tick: a tick
retries its admission without limit (§8.2) and can stay open for as long as a platform failure lasts. Its schedule
comes from its workflow id; its action carries no argument. What it does carry, in its workflow's and its activity's
contexts only, is this reviewed allowlist, which the codec enforces on every write and every read:
- its activity's input: the schedule its workflow id names, its tick key and its nominal time (UTC, whole seconds);
- its outcome, its activity's and its workflow's: one of `OUTCOMES`, fixed codes;
- its failures: a code of `FAILURES` as their message and type, no details and no stack trace (the codec's failure
  converter reduces every failure, whatever raised it).

No schedule input, claim, credential, exception text or stack trace. The codes are literal, so the codec imports
nothing heavier (a test keeps them in step with admission's and the tick's)."""

import json
import re
from typing import Any

from temporalio.api.common.v1 import Payload

WORKFLOW = "ScheduleTick"
# In a dispatcher's Temporal identity: it runs ticks under this contract. `keys tick-cutover` refuses while the
# admission queue shows a poller without it (a dispatcher from before, still sealing its ticks' payloads).
IDENTITY = "dewpoint-tick-contract/1"
_REFUSALS = (
    "schedule_paused", "schedule_deleted", "schedule_catchup_expired",  # the tick's own
    "tenant_erasing", "production_runs_disabled", "environment_not_recorded", "workflow_disabled", "not_active",
    "no_current_build", "version_unusable", "node_type_retired", "cel_profile_retired", "csv_not_declared",
    "csv_mapping_invalid", "upload_not_found", "upload_expired", "upload_consumed", "input_invalid",
    "secret_index_limit",  # admission's
)  # fmt: skip
OUTCOMES = frozenset({"queued", "recorded", "refused", "skipped", "other", "skipped:tenant_erasing",
                      *(f"refused:{reason}" for reason in _REFUSALS)})  # fmt: skip
TICK_IDENTITY = "tick_identity"
SCHEDULE_UNKNOWN = "schedule_unknown"
NO_NOMINAL_TIME = "tick_no_nominal_time"
FAILED = "tick_failed"  # any other failure: a platform's, an exception's, a cancellation
FAILURES = frozenset({TICK_IDENTITY, SCHEDULE_UNKNOWN, NO_NOMINAL_TIME, FAILED})
_NOMINAL = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def outcome(raw: str) -> str:
    """`raw` if it's in the contract, else its status alone (`refused`, `skipped`) or `other`: a tick's own codec never
    refuses its outcome, which its request row records in full."""
    if raw in OUTCOMES:
        return raw
    status = raw.partition(":")[0]
    return status if status in OUTCOMES else "other"


def allowed(payload: Payload, schedule_id: str) -> bool:
    """Whether `payload` is in the contract for a tick of `schedule_id`: JSON, and an outcome or its input exactly."""
    if payload.metadata.get("encoding") != b"json/plain" or set(payload.metadata) != {"encoding"}:
        return False
    try:
        value: Any = json.loads(payload.data)
    except ValueError:
        return False
    if isinstance(value, str):
        return value in OUTCOMES
    if not isinstance(value, dict) or set(value) != {"schedule_id", "key", "nominal"}:
        return False
    nominal = value["nominal"]
    return (
        value["schedule_id"] == schedule_id and isinstance(nominal, str) and _NOMINAL.fullmatch(nominal) is not None
        and value["key"] == f"sched:{schedule_id}:{nominal}"
    )  # fmt: skip
