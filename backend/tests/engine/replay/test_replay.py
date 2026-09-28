# SPDX-License-Identifier: Apache-2.0
"""This build's golden histories replay against this build's workflows (spec §7): every execution a scenario ran,
its continued runs and its children included. The Replayer needs no server."""

import asyncio
import re
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.engine.replay.record import build_dir
from tests.engine.replay.scenarios import scenarios

HISTORIES = sorted(build_dir().glob("*.json"))


def test_every_scenario_is_recorded_for_this_build() -> None:
    recorded = {p.stem.split("--")[0] for p in HISTORIES}
    assert recorded == set(scenarios()), "run `uv run python -m tests.engine.replay.record`"


def test_recorded_histories_carry_no_host_data() -> None:
    for path in HISTORIES:
        text = path.read_text()
        assert set(re.findall(r'"identity": "([^"]*)"', text)) <= {"replay-recorder"}, path.name
        assert not re.search(r'"stackTrace": "[^"]', text), path.name


@pytest.mark.parametrize("path", HISTORIES, ids=lambda p: p.stem)
async def test_a_golden_history_replays(path: Path) -> None:
    history = WorkflowHistory.from_json(path.stem, await asyncio.to_thread(path.read_text))
    await Replayer(workflows=[RunGraph, LoopBatch]).replay_workflow(history)
