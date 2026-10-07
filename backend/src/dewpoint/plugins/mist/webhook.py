# SPDX-License-Identifier: Apache-2.0
"""The Mist webhook trigger (plugins-3 D17), on 2b-3b's ingress unchanged: Mist posts one `{topic, events}` envelope a
delivery (the OAS's `webhooks`, 30 topics), which the endpoint records whole: no events pointer, no event ids. A
binding filters on `/topic`, and each topic's envelope schema types a workflow's trigger. Authentication is a bearer
token Mist sends in the webhook's custom `headers`; whether Mist sends `Authorization` is unverified, so the trigger
isn't supported in production until a real delivery confirms it (2b-4 D13). Dewpoint writes nothing to Mist: it shows
the endpoint's URL and header for a person to paste.

Each schema keeps the OAS's shape and drops what a provider outgrows, as a node's output does (`schemas`), with its
`topic` fixed to the topic's name."""

from collections.abc import Mapping
from typing import Any

from dewpoint.plugins.mist import oas
from dewpoint.plugins.mist.schemas import converted, resolved, with_defs
from dewpoint.sdk import Trigger


def _topic(doc: Mapping[str, Any], item: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    body = oas.resolve(doc, item["post"]["requestBody"])
    top = resolved(doc, body["content"]["application/json"]["schema"])
    names = resolved(doc, top["properties"]["topic"]).get("enum", [])
    if len(names) != 1 or not isinstance(names[0], str):
        raise ValueError("a webhook whose topic isn't one name")
    envelope = converted(top, output=True)
    envelope["type"] = "object"
    envelope["properties"]["topic"] = {"type": "string", "const": names[0]}
    envelope["required"] = sorted({*envelope.get("required", ()), "topic", "events"})
    return names[0], with_defs(doc, envelope, [top["properties"]["events"]], output=True, partial=False)


def topics() -> dict[str, dict[str, Any]]:
    doc = oas.document()
    return dict(sorted(_topic(doc, item) for item in doc["webhooks"].values()))


WEBHOOK = Trigger(key="mist.webhook", label="Mist webhook", auth="bearer", topic_pointer="/topic", topics=topics())
