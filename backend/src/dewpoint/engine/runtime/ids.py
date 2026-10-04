# SPDX-License-Identifier: Apache-2.0
"""Workflow ids, always built by the server (engine 2b spec §6.1). Every run — root, sub-flow, failure handler — is
`t:<tenant>:run:<run_id>`; a batch appends `/<step>/<iteration>/batch:<start>` to its run's; a schedule (2b-3) is
`t:<tenant>:sched:<schedule_id>`, to which Temporal appends each firing's time. The codec reads a payload's tenant
from its workflow id with `tenant_of`, and an id supplied from outside is never parsed for anything else.

The grammar is exact: a batch's suffix is matched part by part, so a server-built id has a longest form, `ID_MAX`."""

import re

# What the server builds ids from, kept here so the codec's import stays small; tests pin each to its source.
KEY = r"[a-z][a-z0-9_]{0,62}"  # a step key (engine.graph.model.KEY_PATTERN)
MAX_LOOP_DEPTH = 3  # loops nest this deep at most (engine.graph.structure)
ITEM_CAP_MAX = 10_000  # the largest `item_cap` a loop takes (plugins.flow): every index and start is below it

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_INDEX = r"(?:0|[1-9][0-9]{0,3})"  # below ITEM_CAP_MAX, no leading zeros
_ITERATION = rf"(?:{KEY}:{_INDEX}(?:/{KEY}:{_INDEX}){{0,{MAX_LOOP_DEPTH - 2}}})?"
_BATCH = rf"/{_UUID}/{_ITERATION}/batch:{_INDEX}"
_RUN = re.compile(rf"t:({_UUID}):run:({_UUID})(?:{_BATCH})?")  # always matched whole (`fullmatch`)
_SCHEDULE = re.compile(rf"t:({_UUID}):sched:({_UUID})(?:-[^\s/]+)?")

_LONGEST_SEGMENT = 63 + 1 + len(str(ITEM_CAP_MAX - 1))  # `<key>:<index>`
ID_MAX = (
    len("t::run:") + 2 * 36  # the run
    + 1 + 36 + 1  # `/<step>/`
    + (MAX_LOOP_DEPTH - 1) * _LONGEST_SEGMENT + (MAX_LOOP_DEPTH - 2)  # the enclosing iterations, `/` between
    + len("/batch:") + len(str(ITEM_CAP_MAX - 1))
)  # fmt: skip


def run_workflow_id(tenant_id: str, run_id: str) -> str:
    return f"t:{tenant_id}:run:{run_id}"


def batch_workflow_id(tenant_id: str, run_id: str, step_id: str, iteration_key: str, start: int) -> str:
    """A loop's batch: the loop step, its enclosing iterations (`scheduler.iteration_key`), its first item."""
    return f"{run_workflow_id(tenant_id, run_id)}/{step_id}/{iteration_key}/batch:{start}"


def schedule_workflow_id(tenant_id: str, schedule_id: str) -> str:
    """A schedule's Temporal Schedule id, and its action's workflow id: Temporal appends each firing's time to it."""
    return f"t:{tenant_id}:sched:{schedule_id}"


def schedule_of(workflow_id: str) -> tuple[str, str] | None:
    """The tenant and the schedule a schedule's id, or one of its firings', names; None for any other string."""
    m = _SCHEDULE.fullmatch(workflow_id)
    return (m.group(1), m.group(2)) if m else None


def tenant_of(workflow_id: str) -> str | None:
    """The tenant a server-built workflow id names, or None for any other string: nothing is inferred from it."""
    m = _RUN.fullmatch(workflow_id) or _SCHEDULE.fullmatch(workflow_id)
    return m.group(1) if m else None


def run_of(workflow_id: str) -> str | None:
    """The run a run's (or a batch's) workflow id names, or None."""
    m = _RUN.fullmatch(workflow_id)
    return m.group(2) if m else None
