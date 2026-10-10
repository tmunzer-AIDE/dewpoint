# SPDX-License-Identifier: Apache-2.0
"""A proof run's projects, removed after its pytest was killed (2b-4b M4; the owner's review of the fixture's cleanup):
the run's outer runner names a file (DEWPOINT_PROOF_PROJECTS) where the harness records each project before its first
`up`, and runs this once the pytest process has ended, however it ended:

    PYTHONPATH=src .venv/bin/python -m tests.proofs.cleanup <the recorded projects' file>

Each recorded project is removed by its exact name (`environment.remove_project`); one already removed by the run's
own teardown lists nothing. A missing file means nothing was brought up."""

import sys
from pathlib import Path

from tests.proofs import environment


def main(argv: list[str]) -> int:
    path = Path(argv[0])
    recorded = path.read_text().split() if path.exists() else []
    failed = 0
    for project in dict.fromkeys(recorded):  # each once, in the order recorded
        try:
            removed = environment.remove_project(project)
        except (RuntimeError, ValueError) as e:
            print(f"{project}: not removed: {e}")
            failed += 1
            continue
        print(f"{project}: removed {len(removed)} ({', '.join(removed) or 'nothing left'})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
