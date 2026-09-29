# SPDX-License-Identifier: Apache-2.0
"""The replay gate's history check (spec §7): `uv run python -m tests.engine.replay.gate <base>`.

A recorded history is never changed or removed: a run of its build may still be open, and must replay. New histories
go only into this build's directory, so a new directory appears only with a new build ID (a new `ENGINE_ABI`, or a
new version). Replaying them is the suite's part (test_replay.py): every directory of this build's ABI."""

import subprocess
import sys
from pathlib import Path

from tests.engine.replay.record import build_dir

REPO = Path(__file__).parents[4]
REPLAY = "backend/tests/engine/replay/"


def problems(changes: list[tuple[str, str]], current: str) -> list[str]:
    """What breaks the rules, one line each. `changes`: the replay directory's changes since the base, as git names
    them (status, path); `current`: this build's directory."""
    out: list[str] = []
    for status, path in changes:
        parts = path.removeprefix(REPLAY).split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            continue  # not a history: the recorder, the scenarios, the tests
        if not status.startswith("A"):
            out.append(f"{path}: a recorded history is never changed or removed ({status})")
        elif parts[0] != current:
            out.append(f"{path}: new histories go into this build's directory, {current}")
    return out


def changes(base: str, repo: Path = REPO) -> list[tuple[str, str]]:
    """The replay directory's changes since `base`'s merge base with HEAD. A rename is a removal and an addition."""
    done = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD", "--", REPLAY],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return [(status, path) for status, path in (line.split("\t", 1) for line in done.stdout.splitlines() if line)]


def main(argv: list[str]) -> int:
    found = problems(changes(argv[1]), build_dir().name)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
