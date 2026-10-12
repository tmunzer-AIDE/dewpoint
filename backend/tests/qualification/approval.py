# SPDX-License-Identifier: Apache-2.0
"""What every qualification procedure shares: its approval, checked before anything else; its test credentials, from
the environment alone; and its record, one JSON line per observation, then its result."""

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APPROVAL = "DEWPOINT_QUALIFICATION_APPROVED"
_APPROVAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,99}")


def approved() -> str:
    """The approval's id, before the procedure reads its arguments; without a valid one, exit 2, having done nothing."""
    approval = os.environ.get(APPROVAL, "").strip()
    if not _APPROVAL_ID.fullmatch(approval):
        print(f"refused: {APPROVAL}=<approval id> is required: a target's qualification runs under its own approval, "
              "never otherwise", file=sys.stderr)  # fmt: skip
        raise SystemExit(2)
    return approval


def secret(name: str) -> str:
    """A test credential, from the environment alone (never an argument: it would be in the shell's history)."""
    value = os.environ.get(name, "")
    if not value:
        print(f"refused: {name} must hold the test credential (never a real one)", file=sys.stderr)
        raise SystemExit(2)
    return value


class Record:
    """The procedure's record: one JSON line per observation, appended to `out`, each with its approval."""

    def __init__(self, out: Path, procedure: str, approval: str) -> None:
        self.out, self.procedure, self.approval = out, procedure, approval
        self.failures: list[str] = []

    def write(self, **fields: Any) -> None:
        line = {"at": datetime.now(UTC).isoformat(), "procedure": self.procedure, "approval": self.approval, **fields}
        with self.out.open("a") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def check(self, ok: bool, what: str, **fields: Any) -> None:
        """An observation, recorded; a failed one counted."""
        self.write(check=what, ok=ok, **fields)
        if not ok:
            self.failures.append(what)

    def finished(self) -> int:
        """The result, recorded and printed: 0 when every check passed, else 1."""
        self.write(result="passed" if not self.failures else "failed", failures=self.failures)
        verdict = "passed" if not self.failures else f"FAILED ({len(self.failures)}): " + "; ".join(self.failures)
        print(f"{self.procedure}: {verdict} (record: {self.out})")
        return 0 if not self.failures else 1
