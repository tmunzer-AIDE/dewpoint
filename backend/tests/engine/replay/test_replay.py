# SPDX-License-Identifier: Apache-2.0
"""The golden histories of this build's ABI replay against this build's workflows (spec §7): every execution a
scenario ran, its continued runs and its children included. A build that keeps the ABI (a new version) must replay
the previous build's histories too. The Replayer needs no server."""

import asyncio
import base64
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from dewpoint.apps.codec import ENCODING
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.engine.replay.record import HERE, build_dir
from tests.engine.replay.scenarios import scenarios
from tests.support.keys import FIXTURE_CONVERTER

HISTORIES = sorted(HERE.glob(f"*+abi{ENGINE_ABI}/*.json"))


def test_every_scenario_is_recorded_for_this_build() -> None:
    recorded = {p.stem.split("--")[0] for p in build_dir().glob("*.json")}
    assert recorded == set(scenarios()), "run `uv run python -m tests.engine.replay.record`"


def test_recorded_histories_carry_no_host_data() -> None:
    for path in HISTORIES:
        text = path.read_text()
        assert set(re.findall(r'"identity": "([^"]*)"', text)) <= {"replay-recorder"}, path.name
        assert not re.search(r'"stackTrace": "[^"]', text), path.name


# What the SDK's core records beside a local activity's result, in plain JSON and never through a codec: its own
# bookkeeping, no value of the run's (engine 2b spec §4.6, visible metadata).
LOCAL_ACTIVITY_MARKER = {
    "seq",
    "attempt",
    "activity_id",
    "activity_type",
    "complete_time",
    "backoff",
    "original_schedule_time",
}


def payloads(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if isinstance(value.get("metadata"), dict) and "encoding" in value["metadata"]:
            yield path, value
        for key, inner in value.items():
            yield from payloads(inner, f"{path}/{key}")
    elif isinstance(value, list):
        for inner in value:
            yield from payloads(inner, path)


def test_recorded_payloads_are_encrypted() -> None:
    """Engine 2b spec §12: this ABI's histories are recorded with the codec and fixture keys, so every payload in them
    is encrypted, but for the SDK's own local-activity bookkeeping."""
    for path in HISTORIES:
        for where, p in payloads(json.loads(path.read_text())):
            encoding = base64.b64decode(p["metadata"]["encoding"])
            if where.endswith("/markerRecordedEventAttributes/details/data/payloads"):
                assert encoding == b"json/plain", (path.name, where)
                assert set(json.loads(base64.b64decode(p["data"]))) <= LOCAL_ACTIVITY_MARKER, (path.name, where)
            else:
                assert encoding == ENCODING, (path.name, where)


@pytest.mark.parametrize(
    "path", HISTORIES, ids=lambda p: p.stem if p.parent == build_dir() else f"{p.parent.name}/{p.stem}"
)
async def test_a_golden_history_replays(path: Path) -> None:
    data = json.loads(await asyncio.to_thread(path.read_text))
    history = WorkflowHistory.from_json(data.pop("workflowId"), data)  # the id it ran under (see `record`)
    await Replayer(workflows=[RunGraph, LoopBatch], data_converter=FIXTURE_CONVERTER).replay_workflow(history)
