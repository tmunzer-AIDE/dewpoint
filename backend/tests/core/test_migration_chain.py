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
    assert script().get_heads() == ["0074"]


def test_runs_workflow_last_comes_after_the_orphan_backoff() -> None:
    assert script().get_revision("0047").down_revision == "0044"


def test_the_samples_record_comes_after_the_workflows_list_index() -> None:
    """Slot 0045 (B7) is chained after main's head when it was written, 0047: slot numbers name ownership, not order."""
    assert script().get_revision("0045").down_revision == "0047"


def test_the_endpoint_sender_comes_after_the_samples_record() -> None:
    """Slot 0070 (4c-3a) is chained after main's head when it was written, 0045: slot numbers name ownership, not
    order."""
    assert script().get_revision("0070").down_revision == "0045"


def test_2b_4bs_migrations_come_after_the_endpoint_sender() -> None:
    """2b-4b's first, 0048, was written on 0044 and chained, when it met main, after main's head then, 0070."""
    assert script().get_revision("0048").down_revision == "0070"


def test_the_step_instance_ends_come_after_2b_4bs_last() -> None:
    """Slot 0071 (4d-1a, B4b) is chained after main's head when it was written, 0065 (2b-4b's last)."""
    assert script().get_revision("0071").down_revision == "0065"


def test_the_draft_snapshots_come_after_the_step_instance_ends() -> None:
    """Slot 0072 (4d-1b, B8) is chained after main's head when it was written, 0071 (4d-1a's)."""
    assert script().get_revision("0072").down_revision == "0071"


def test_the_request_origins_come_after_the_draft_snapshots() -> None:
    """Slot 0073 (4e-1a; the runs design §8) is chained after main's head when it was written, 0072 (4d-1b's)."""
    assert script().get_revision("0073").down_revision == "0072"


def test_the_picked_names_come_after_the_request_origins() -> None:
    """Slot 0074 (4f-3a; the start-form pickers design §4.6) is chained after main's head when it was written, 0073."""
    assert script().get_revision("0074").down_revision == "0073"
