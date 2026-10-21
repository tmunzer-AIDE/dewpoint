# SPDX-License-Identifier: Apache-2.0
"""The renderers' shared cases (editor 4f-1; the message composer design §4.2): made-up messages, each as Slack, Teams
and Google Chat render it. The editor's previews mirror those renderers in TypeScript and are held to the same cases
(`frontend/src/test/messageCases.json`, written by `dewpoint plugins message-cases`), so a renderer that changes fails
a test until the file is written again. Nothing here is real data."""

from typing import Any

from dewpoint.plugins import google_chat, slack, teams
from dewpoint.sdk.messages import Message

_LINK = "https://example.test/runbook"

# Each case: its name, and the message as a step's config holds it (the connection aside).
CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("the text alone", {"text": "Access point AP-12 stopped reporting."}),
    ("an empty title", {"title": "", "text": "No title is shown."}),
    (
        "a whole message",
        {
            "title": "AP offline at HQ",
            "text": "Access point AP-12 stopped reporting.\n\nLast seen by switch SW-3, port 12.",
            "fields": [{"label": "Site", "value": "HQ"}, {"label": "Model", "value": "AP45"}],
            "links": [{"label": "Open in Mist", "url": "https://manage.mist.test/admin/?site_id=1"}],
            "severity": "warning",
        },
    ),
    (
        "what each target escapes",
        {
            "title": "<b> & </b>",
            "text": "a < b && c > d <@U123> <!here> *bold* _it_ [x](https://example.test)",
            "fields": [{"label": "x<y", "value": "<users/all> & more"}],
            "links": [{"label": "a|b", "url": "https://example.test/a|b"}],
            "severity": "critical",
        },
    ),
    ("text past Slack's 3,000 characters", {"text": "x" * 3500, "severity": "success"}),
    ("an escape where Slack cuts", {"text": "x" * 2996 + "&&&&"}),
    (
        "a field's value and a button past Slack's",
        {
            "text": "Details below.",
            "fields": [{"label": "Note", "value": "v" * 2500}],
            "links": [{"label": "b" * 100, "url": _LINK}],
        },
    ),
    (
        # Counted in code points, as Python counts: 75 of these are 150 UTF-16 units, within Slack's 75 for a button.
        "characters of several bytes",
        {"title": "Zürich — 東京 𝄞", "text": "Ünïcödé ✓ 日本語 " * 20, "links": [{"label": "𝄞" * 75, "url": _LINK}]},
    ),
    ("control characters", {"text": "a tab\there, a bell\u0007 and the end"}),
    (
        "as many fields and links as a message takes",
        {
            "text": "Twenty-five fields, ten links.",
            "fields": [{"label": f"Field {i}", "value": f"value {i}"} for i in range(25)],
            "links": [{"label": f"Link {i}", "url": f"{_LINK}/{i}"} for i in range(10)],
        },
    ),
    (
        "big enough for Teams and Google Chat to shorten it",
        {
            "title": "T" * 1000,
            "text": "é" * 10_000,
            "fields": [{"label": f"Field {i}", "value": "v" * 1000} for i in range(25)],
            "links": [{"label": f"Link {i}", "url": f"{_LINK}/{i}"} for i in range(10)],
            "severity": "warning",
        },
    ),
)


def rendered(message: Message) -> dict[str, Any]:
    """The message as each target sends it: its body, and the names of the values it cut."""
    out: dict[str, Any] = {}
    for name, target in (("slack", slack), ("teams", teams), ("google_chat", google_chat)):
        body, truncated = target.render(message)
        out[name] = {"body": body, "truncated": truncated}
    return out


def document() -> dict[str, Any]:
    """Every case with what each target makes of it: the file the editor's tests read."""
    return {
        "about": (
            "The renderers' shared cases (editor 4f-1). Written by `dewpoint plugins message-cases`; held to the "
            "plugins' renderers by backend/tests/plugins/test_message_cases.py. Never edit by hand."
        ),
        "cases": [{"name": name, "message": raw, **rendered(Message.model_validate(raw))} for name, raw in CASES],
    }
