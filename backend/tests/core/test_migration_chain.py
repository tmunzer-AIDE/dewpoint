# SPDX-License-Identifier: Apache-2.0
"""The migrations form one chain: `alembic upgrade head`, which every deployment and the test database run, needs a
single head. Slot numbers name ownership, not order (ledger, 4b ruling 72), so a migration written on a branch is
chained after the head it meets when it merges, never left on the head it was written from (the owner's review of #60:
0047 still chained from 0042 met main's 0044)."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_db() -> None:
    """No database here: the suite's own `clean_db` migrates one to head first, so a second head would fail that
    setup and never reach these assertions (the owner's review of 5c6d802). These read Alembic's scripts alone."""


def script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def test_the_chain_has_one_head() -> None:
    assert script().get_heads() == ["0047"]


def test_runs_workflow_last_comes_after_the_orphan_backoff() -> None:
    assert script().get_revision("0047").down_revision == "0044"
