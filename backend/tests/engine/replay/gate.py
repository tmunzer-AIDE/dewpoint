# SPDX-License-Identifier: Apache-2.0
"""The replay gate's history check (spec §7): `uv run python -m tests.engine.replay.gate <base>`, or, in CI,
`... gate --event <event> --ref <ref> --pr-base <sha> --before <sha>`, which chooses the base (`base_for`).

A recorded history is never changed or removed: a run of its build may still be open, and must replay. New histories
go only into this build's directory, so a new directory appears only with a new build ID (a new `ENGINE_ABI`, or a
new version). Replaying them is the suite's part (test_replay.py): every directory of this build's ABI."""

import argparse
import subprocess
import sys
from pathlib import Path

from tests.engine.replay.record import build_dir

REPO = Path(__file__).parents[4]
REPLAY = "backend/tests/engine/replay/"
MAIN = "origin/main"
NO_COMMIT = "0" * 40  # a push's `before` when there was no commit before it


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


def base_for(event: str, ref: str, *, pr_base: str = "", before: str = "", main: str = MAIN) -> str:
    """What CI compares with. A pull request: its base. A push to main: the commit before it. Any other push: its
    merge base with main (`changes` compares from there), not the branch's previous push, so a history rewritten by
    an earlier push stays visible on every later one until it's undone."""
    if event == "pull_request":
        return pr_base
    if ref == "refs/heads/main" and before and before != NO_COMMIT:
        return before
    return main


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.engine.replay.gate")
    parser.add_argument("base", nargs="?", help="the commit to compare with (default: as CI chooses, from --event)")
    for option in ("--event", "--ref", "--pr-base", "--before"):
        parser.add_argument(option, default="")
    args = parser.parse_args(argv[1:])
    base = args.base or base_for(args.event, args.ref, pr_base=args.pr_base, before=args.before)
    found = problems(changes(base), build_dir().name)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
