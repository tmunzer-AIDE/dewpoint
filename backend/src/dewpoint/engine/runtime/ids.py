# SPDX-License-Identifier: Apache-2.0
"""Workflow ids, always built by the server (engine 2b spec §6.1). Every run — root, sub-flow, failure handler — is
`t:<tenant>:run:<run_id>`; a batch appends `/<step>/<iteration>/batch:<start>` to its run's; a schedule (2b-3) is
`t:<tenant>:sched:<schedule_id>`, to which Temporal appends each firing's time. The codec reads a payload's tenant
from its workflow id with `tenant_of`, and an id supplied from outside is never parsed for anything else."""

import re

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_RUN = re.compile(rf"t:({_UUID}):run:({_UUID})(?:/[^\s]+)?")  # always matched whole (`fullmatch`)
_SCHEDULE = re.compile(rf"t:({_UUID}):sched:({_UUID})(?:-[^\s/]+)?")


def run_workflow_id(tenant_id: str, run_id: str) -> str:
    return f"t:{tenant_id}:run:{run_id}"


def tenant_of(workflow_id: str) -> str | None:
    """The tenant a server-built workflow id names, or None for any other string: nothing is inferred from it."""
    m = _RUN.fullmatch(workflow_id) or _SCHEDULE.fullmatch(workflow_id)
    return m.group(1) if m else None


def run_of(workflow_id: str) -> str | None:
    """The run a run's (or a batch's) workflow id names, or None."""
    m = _RUN.fullmatch(workflow_id)
    return m.group(2) if m else None
