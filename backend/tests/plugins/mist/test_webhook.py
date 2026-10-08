# SPDX-License-Identifier: Apache-2.0
"""The Mist webhook trigger (plugins-3 D17): a delivery is one `{topic, events}` envelope, recorded whole (no events
pointer, no event ids) on a bearer endpoint; bindings filter on `/topic`; each of the OAS's 30 topics types a
workflow's trigger with its envelope's schema, which publish accepts as an input schema."""

from typing import Any

import pytest

from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN
from dewpoint.plugins.mist.schemas import OUTGROWN
from dewpoint.plugins.mist.webhook import WEBHOOK
from tests.plugins.mist.test_nodes import walk
from tests.support.catalog import catalog
from tests.support.graphs import G, ref
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(FLOW, TESTKIT)


def test_the_plugin_declares_the_trigger() -> None:
    assert PLUGIN.triggers == (WEBHOOK,)
    m = WEBHOOK.manifest()
    assert (m["key"], m["endpoint"], m["topic_pointer"]) == (
        "mist.webhook", {"auth": "bearer", "events_pointer": None, "id_source": "none"}, "/topic"
    )  # fmt: skip
    assert len(m["topics"]) == 30 and {"alarms", "client-join", "device-updowns", "audits"} <= set(m["topics"])


@pytest.mark.parametrize("topic", sorted(WEBHOOK.topics))
def test_each_topic_types_a_trigger_and_publish_accepts_it(topic: str) -> None:
    schema: dict[str, Any] = dict(WEBHOOK.topics[topic])
    assert schema["properties"]["topic"] == {"type": "string", "const": topic}
    events = schema["properties"]["events"]
    while "$ref" in events:
        events = schema["$defs"][events["$ref"].removeprefix("#/$defs/")]
    assert events["type"] == "array" and set(schema["required"]) == {"topic", "events"}
    g = G().node("a", "testkit.echo@1", {"value": ref("trigger.events")})
    g.settings["input_schema"] = schema
    found = validate(g.build(), ValidationContext(catalog=CAT))
    assert [d.code for d in found.diagnostics if d.code.startswith(("settings.", "sensitive."))] == [], topic
    assert not any(d.code.startswith("ref.") for d in found.diagnostics), topic


def test_topic_schemas_drop_what_a_provider_outgrows_but_the_topic() -> None:
    for topic, schema in WEBHOOK.topics.items():
        for s in walk(schema):
            assert not OUTGROWN & set(s) or s == {"type": "string", "const": topic}, topic
            assert "examples" not in s and s.get("additionalProperties") is not False, topic
