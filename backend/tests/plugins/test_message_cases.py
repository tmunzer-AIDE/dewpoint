# SPDX-License-Identifier: Apache-2.0
"""The renderers' shared cases (editor 4f-1; the message composer design §4.2). The editor's previews mirror the Slack,
Teams and Google Chat renderers in TypeScript and are held to `frontend/src/test/messageCases.json`; this test holds
that file to the renderers. A renderer changed: write the file again with
`uv run dewpoint plugins message-cases > ../frontend/src/test/messageCases.json`."""

import json
from pathlib import Path

from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.plugins.message_cases import document

CASES_FILE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "test" / "messageCases.json"


def test_the_editors_cases_are_what_the_renderers_return() -> None:
    assert json.loads(CASES_FILE.read_text()) == document()


def test_the_command_prints_the_cases() -> None:
    result = CliRunner().invoke(app, ["plugins", "message-cases"])
    assert result.exit_code == 0
    assert json.loads(result.output) == document()


def test_the_cases_reach_what_the_previews_say() -> None:
    """Each cut the previews word is in some case, and Teams and Google Chat each shorten at more than one level."""
    cases = document()["cases"]
    targets = ("slack", "teams", "google_chat")
    cut = {target: {name for c in cases for name in c[target]["truncated"]} for target in targets}
    assert {"text", "fields[0].value", "links[0].label"} <= cut["slack"]
    assert {"text", "title", "fields[0].value", "links[5]"} <= cut["teams"]
    assert {"text", "title", "fields[0].value"} <= cut["google_chat"]
    assert {c["message"].get("severity", "info") for c in cases} == {"info", "success", "warning", "critical"}
