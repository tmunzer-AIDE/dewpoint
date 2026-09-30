# SPDX-License-Identifier: Apache-2.0
"""Workflow ids (engine 2b spec §6.1): the server builds them, and reads back only the tenant and run it put in."""

import uuid

import pytest

from dewpoint.engine.runtime.ids import run_of, run_workflow_id, tenant_of

TENANT = "8f14e45f-ceea-467a-9575-8f6a1b2c3d4e"  # letters too: the server writes uuids in lower case
RUN = str(uuid.UUID(int=2))
ROOT = run_workflow_id(TENANT, RUN)


def test_a_runs_id_names_its_tenant_and_run() -> None:
    assert ROOT == f"t:{TENANT}:run:{RUN}"
    assert (tenant_of(ROOT), run_of(ROOT)) == (TENANT, RUN)


def test_a_batch_names_the_run_it_belongs_to() -> None:
    batch = f"{ROOT}/{uuid.UUID(int=3)}/l:0/batch:1000"
    assert (tenant_of(batch), run_of(batch)) == (TENANT, RUN)


def test_a_schedules_firing_names_its_tenant_and_no_run() -> None:
    firing = f"t:{TENANT}:sched:{uuid.UUID(int=4)}-2026-09-29T10:00:00Z"
    assert (tenant_of(firing), run_of(firing)) == (TENANT, None)


@pytest.mark.parametrize(
    "workflow_id",
    [
        RUN,  # an id from before 2b-1a
        f"t:{TENANT}:run:{RUN}\n",  # nothing may follow the id, not even a line end
        f"t:{TENANT.upper()}:run:{RUN}",
        f"t:{TENANT}:run:{RUN}x",
        f"t:{TENANT}:run:{RUN}/",  # a batch's suffix is never empty
        f"t:{TENANT}:run:{RUN}/a b",
        f"t:{TENANT}:runs:{RUN}",
        f"x:{TENANT}:run:{RUN}",
        f"t:{TENANT}:sched:{RUN}/batch:0",
        "",
    ],
)
def test_any_other_string_names_nothing(workflow_id: str) -> None:
    assert (tenant_of(workflow_id), run_of(workflow_id)) == (None, None)
