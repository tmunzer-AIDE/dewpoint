# SPDX-License-Identifier: Apache-2.0
"""Workflow ids (engine 2b spec §6.1): the server builds them, and reads back only the tenant and run it put in."""

import uuid

import pytest

from dewpoint.engine.runtime.ids import ID_MAX, batch_workflow_id, run_of, run_workflow_id, tenant_of

TENANT = "8f14e45f-ceea-467a-9575-8f6a1b2c3d4e"  # letters too: the server writes uuids in lower case
RUN = str(uuid.UUID(int=2))
ROOT = run_workflow_id(TENANT, RUN)


def test_a_runs_id_names_its_tenant_and_run() -> None:
    assert ROOT == f"t:{TENANT}:run:{RUN}"
    assert (tenant_of(ROOT), run_of(ROOT)) == (TENANT, RUN)


STEP = str(uuid.UUID(int=3))
LONGEST_KEY = "k" + "_" * 62


@pytest.mark.parametrize(
    "iteration",
    ["", "l:0", "outer:9999/inner:12", f"{LONGEST_KEY}:9999/{LONGEST_KEY}:9999"],
)
def test_a_batch_names_the_run_it_belongs_to(iteration: str) -> None:
    batch = batch_workflow_id(TENANT, RUN, STEP, iteration, 1000)
    assert batch == f"{ROOT}/{STEP}/{iteration}/batch:1000"
    assert (tenant_of(batch), run_of(batch)) == (TENANT, RUN)
    assert len(batch) <= ID_MAX


def test_the_longest_id_is_id_max() -> None:
    """Every index and start is below the largest item cap, and a loop's batch has at most MAX_LOOP_DEPTH - 1
    enclosing iterations, each a step key of at most 63 characters (§6.1)."""
    longest = batch_workflow_id(TENANT, RUN, STEP, f"{LONGEST_KEY}:9999/{LONGEST_KEY}:9999", 9999)
    assert len(longest) == ID_MAX


@pytest.mark.parametrize(
    "suffix",
    [
        f"/{STEP}/a:1/b:2/c:3/batch:0",  # deeper than a loop can nest
        f"/{STEP}/A:1/batch:0",  # a step key is lower case
        f"/{STEP}/1a:1/batch:0",
        f"/{STEP}/{LONGEST_KEY}x:1/batch:0",  # 64 characters
        f"/{STEP}/l:07/batch:0",  # no leading zeros
        f"/{STEP}/l:10000/batch:0",  # past the largest item cap
        f"/{STEP}//batch:10000",
        f"/{STEP}//batch:-1",
        f"/{STEP}//batch:",
        f"/{STEP}/l:1/batch:0/",
        f"/{STEP}/l:1//batch:0",
        f"/{STEP}/l:1",
        f"/{TENANT.upper()}//batch:0",  # a uuid in upper case
        "/not-a-uuid//batch:0",
        f"/{STEP}//batch:0/more",
        f"/{STEP}//Batch:0",
    ],
)
def test_a_batch_suffix_is_matched_part_by_part(suffix: str) -> None:
    assert (tenant_of(ROOT + suffix), run_of(ROOT + suffix)) == (None, None)


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


def test_the_grammars_limits_are_the_engines() -> None:
    """The ids module keeps its own copies, so the codec imports little: each matches what it copies."""
    from annotated_types import Le

    from dewpoint.engine.graph.model import KEY_PATTERN
    from dewpoint.engine.graph.structure import MAX_LOOP_DEPTH
    from dewpoint.engine.runtime import ids
    from dewpoint.plugins.flow.nodes import LoopConfig

    assert f"^{ids.KEY}$" == KEY_PATTERN
    assert ids.MAX_LOOP_DEPTH == MAX_LOOP_DEPTH
    caps = [m.le for m in LoopConfig.model_fields["item_cap"].metadata if isinstance(m, Le)]
    assert caps == [ids.ITEM_CAP_MAX]
