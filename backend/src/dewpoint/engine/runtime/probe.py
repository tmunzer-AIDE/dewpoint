# SPDX-License-Identifier: Apache-2.0
"""Proto only (2b-1b go/no-go): what each execution's scheduler measured, by workflow id, for the harness to read in
the same process. Passed through the sandbox, so every workflow writes the one dict."""

from typing import Any

PEAKS: dict[str, dict[str, int]] = {}


def note(workflow_id: str, probe: dict[str, Any]) -> None:
    current = PEAKS.setdefault(workflow_id, {})
    for key, value in probe.items():
        current[key] = max(current.get(key, 0), int(value))
