# SPDX-License-Identifier: Apache-2.0
"""What each control node decides once its config is resolved (spec §6)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from dewpoint.engine.runtime.nodes import MAX_DELAY_S, Decision, LoopStart, SubflowStart, decide
from dewpoint.engine.runtime.scheduler import Failure, RunEnd
from tests.engine.runtime.support import MANIFESTS


@pytest.mark.parametrize(
    ("ref", "config", "decision"),
    [
        ("flow.if@1", {"condition": True}, Decision(output={}, ports=("true",))),
        ("flow.if@1", {"condition": False}, Decision(output={}, ports=("false",))),
        (
            "flow.switch@1",
            {"cases": [{"port": "a", "when": False}, {"port": "b", "when": True}, {"port": "c", "when": True}]},
            Decision(output={}, ports=("b",)),  # the first match wins
        ),
        ("flow.switch@1", {"cases": [{"port": "a", "when": False}]}, Decision(output={}, ports=("default",))),
        ("flow.set_variables@1", {"assignments": {"n": 2}}, Decision(output={}, variables={"n": 2})),
        ("flow.transform@1", {"fields": {"y": 1}}, Decision(output={"y": 1})),
        ("flow.stop@1", {}, Decision(output={}, end=RunEnd("succeeded", stopped=True))),
        (
            "flow.fail@1",
            {"message": "no"},
            Decision(output={}, end=RunEnd("failed", Failure("workflow_failed", "no"))),
        ),
        ("flow.delay@1", {"duration_s": 60}, Decision(output={}, wait_s=60.0)),
        ("flow.delay@1", {"duration_s": 30 * 86_400}, Decision(output={}, wait_s=30 * 86_400.0)),
        (
            "flow.wait_until@1",
            {"until": "2027-01-01T01:00:00+01:00"},
            Decision(output={}, wait_until=datetime(2027, 1, 1, tzinfo=UTC)),
        ),
        (
            "flow.wait_until@1",
            {"until": "2027-01-01T00:00:00Z"},
            Decision(output={}, wait_until=datetime(2027, 1, 1, tzinfo=UTC)),
        ),
        (
            "flow.loop@1",
            {"items": [1, 2], "concurrency": 2, "on_item_error": "continue"},
            Decision(loop=LoopStart([1, 2], 2, stop_on_error=False)),
        ),
        ("flow.loop@1", {"items": []}, Decision(loop=LoopStart([], 1, stop_on_error=True))),
        (
            "flow.loop@1",
            {"items": list(range(101)), "concurrency": 3},
            Decision(loop=LoopStart(list(range(101)), 3, stop_on_error=True, batch=100)),  # batches of child workflows
        ),
        ("flow.run_workflow@1", {"workflow_id": "w", "input": {"n": 1}}, Decision(subflow=SubflowStart({"n": 1}, "w"))),
        ("flow.run_workflow@1", {"workflow_id": "w"}, Decision(subflow=SubflowStart({}, "w"))),
        ("flow.filter@1", {"items": ["a"]}, Decision(filter_items=["a"])),
    ],
)
def test_a_control_node_decides(ref: str, config: dict[str, Any], decision: Decision) -> None:
    assert decide(ref, config) == decision


@pytest.mark.parametrize(
    ("ref", "config", "code"),
    [
        ("flow.if@1", {"condition": "yes"}, "type_mismatch"),  # open data publish couldn't type
        ("flow.switch@1", {"cases": [{"port": "a", "when": 1}]}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": True}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": -1}, "type_mismatch"),
        # Final review: a value from the run, unbounded by the node's schema, overflowed the timer: `internal_error`
        ("flow.delay@1", {"duration_s": 30 * 86_400 + 1}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": 1e300}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": float("nan")}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": float("inf")}, "type_mismatch"),
        ("flow.wait_until@1", {"until": "0001-01-01T00:00:00+01:00"}, "type_mismatch"),  # before year 1 in UTC
        ("flow.wait_until@1", {"until": "9999-12-31T23:59:59-01:00"}, "type_mismatch"),  # after year 9999 in UTC
        ("flow.wait_until@1", {"until": 5}, "type_mismatch"),
        ("flow.wait_until@1", {"until": "tomorrow"}, "type_mismatch"),  # a ref to open data
        ("flow.wait_until@1", {"until": "2027-01-01T09:00:00"}, "type_mismatch"),  # no zone: whose 9 o'clock?
        ("flow.loop@1", {"items": {"a": 1}}, "type_mismatch"),
        ("flow.filter@1", {"items": "abc"}, "type_mismatch"),
        ("flow.loop@1", {"items": [1, 2, 3], "item_cap": 2}, "item_cap_exceeded"),
        ("flow.run_workflow@1", {"workflow_id": "w", "input": ["not", "an", "object"]}, "type_mismatch"),
    ],
)
def test_a_control_node_refuses(ref: str, config: dict[str, Any], code: str) -> None:
    failure = decide(ref, config).failure
    assert failure is not None and failure.code == code


def test_a_delay_is_bounded_as_the_node_declares() -> None:
    assert MAX_DELAY_S == MANIFESTS["flow.delay@1"]["config_schema"]["properties"]["duration_s"]["maximum"]


def test_a_loop_of_exactly_a_hundred_items_runs_inline() -> None:
    loop = decide("flow.loop@1", {"items": list(range(100))}).loop
    assert loop is not None and loop.batch == 0


def test_only_control_nodes_are_decided() -> None:
    with pytest.raises(ValueError, match="isn't a control node"):
        decide("testkit.echo@1", {})
