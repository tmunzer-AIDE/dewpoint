# SPDX-License-Identifier: Apache-2.0
"""A plugin's triggers (plugins-3 D12, D17): a kind of event its provider delivers to a Dewpoint webhook endpoint. It
says how such an endpoint is set up (its authentication, where its events are; no event ids), where each event names
its topic, and each topic's event schema, which types a workflow's trigger. A trigger is data: Dewpoint receives
the events through its ingress unchanged, and the plugin runs no code for them."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dewpoint.sdk.connections import TYPE_KEY_RE

TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
AUTHS = ("bearer", "hmac")  # the endpoint's authentication, as ingress offers it
MAX_TOPICS = 256
TRIGGER_KEYS = frozenset({"key", "label", "endpoint", "topic_pointer", "topics"})
ENDPOINT_KEYS = frozenset({"auth", "events_pointer", "id_source"})


def _pointer(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("/") and len(value) <= 256


def trigger_problems(plugin: str, t: Any) -> list[str]:
    """What's wrong with a trigger received as data (its manifest), for the SDK and the catalog alike."""
    key = t.get("key") if isinstance(t, Mapping) else None
    name = f"trigger {key!r}"
    if not isinstance(key, str) or not TYPE_KEY_RE.match(key) or (key != plugin and not key.startswith(f"{plugin}.")):
        return [f"{name} must be named {plugin!r} or start with '{plugin}.'"]
    assert isinstance(t, Mapping)  # noqa: S101 - a key was read from it
    if set(t) != TRIGGER_KEYS:
        return [f"{name}: needs exactly {sorted(TRIGGER_KEYS)}"]
    out: list[str] = []
    label = t["label"]
    if not isinstance(label, str) or not 0 < len(label) <= 100:
        out.append(f"{name}: label must be 1-100 characters")
    endpoint = t["endpoint"]
    if (
        not isinstance(endpoint, Mapping)
        or set(endpoint) != ENDPOINT_KEYS
        or endpoint["auth"] not in AUTHS
        or endpoint["id_source"] != "none"
    ):
        out.append(f"{name}: endpoint must be {{auth: bearer or hmac, events_pointer, id_source: none}}")
    elif endpoint["events_pointer"] is not None and not _pointer(endpoint["events_pointer"]):
        out.append(f"{name}: events_pointer must be a JSON pointer or null")
    if not _pointer(t["topic_pointer"]):
        out.append(f"{name}: topic_pointer must be a JSON pointer")
    topics = t["topics"]
    if not isinstance(topics, Mapping) or not 0 < len(topics) <= MAX_TOPICS:
        return [*out, f"{name}: topics must name 1-{MAX_TOPICS} topics"]
    for topic, schema in topics.items():
        where = f"{name}: topic {topic!r}"
        if not isinstance(topic, str) or not TOPIC_RE.match(topic):
            out.append(f"{where} must be lowercase letters, digits, '_', '.' and '-'")
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            out.append(f"{where}: not a valid JSON Schema ({e.message})")
            continue
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            out.append(f"{where}: its schema must describe an object")
    return out


@dataclass(frozen=True)
class Trigger:
    key: str
    label: str
    auth: str
    topic_pointer: str  # where an event names its topic: bindings filter on it
    topics: Mapping[str, Mapping[str, Any]]  # each topic's event, as a run's trigger receives it
    events_pointer: str | None = None  # where a delivery's events are; None: the delivery is one event

    def manifest(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "endpoint": {"auth": self.auth, "events_pointer": self.events_pointer, "id_source": "none"},
            "topic_pointer": self.topic_pointer,
            "topics": {topic: dict(schema) for topic, schema in self.topics.items()},
        }
