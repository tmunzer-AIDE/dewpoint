# SPDX-License-Identifier: Apache-2.0
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from dewpoint.sdk import (
    FatalError,
    ManifestError,
    Node,
    NodeKind,
    Plugin,
    RetryDefaults,
    SideEffect,
    StepContext,
    literal_only,
    node_manifest,
    sensitive,
    value_kinds,
)
from dewpoint.sdk.fields import KINDS, LITERAL, SENSITIVE


class SendConfig(BaseModel):
    target: str
    retries: int = literal_only(2, ge=0, le=5)
    body: str = value_kinds("literal", "template", default="")


class SendOutput(BaseModel):
    message_id: str
    token_hint: str = sensitive()


class Send(Node):
    type = "demo.send"
    version = 2
    title = "Send"
    Config = SendConfig
    Output = SendOutput
    side_effect = SideEffect.KEYED
    retry = RetryDefaults(max_attempts=4, non_retryable=("demo.bad_request",))
    timeout = timedelta(seconds=30)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        return SendOutput(message_id="m1", token_hint="t")


async def _run(self: Node, ctx: StepContext, config: Any) -> BaseModel:
    raise FatalError("demo.unused", "unused")


def _node(**attrs: Any) -> type[Node]:
    base: dict[str, Any] = {"type": "demo.x", "version": 1, "title": "X"}
    base.update(attrs)
    return type("X", (Node,), base)


def test_node_manifest_carries_schemas_and_markers() -> None:
    m = node_manifest(Send)
    assert (m["type"], m["version"], m["kind"], m["ports"]) == ("demo.send", 2, "action", ["out"])
    props = m["config_schema"]["properties"]
    assert props["retries"][LITERAL] is True
    assert props["body"][KINDS] == ["literal", "template"]
    assert m["output_schema"]["properties"]["token_hint"][SENSITIVE] is True
    assert m["retry"] == {
        "max_attempts": 4,
        "initial_interval_s": 1.0,
        "backoff": 2.0,
        "max_interval_s": 60.0,
        "non_retryable": ["demo.bad_request"],
    }
    assert m["timeout_s"] == 30.0 and m["side_effect"] == "keyed"


class Nested(BaseModel):
    name: str


class OpenOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    nested: Nested


def test_output_schemas_say_which_objects_are_closed() -> None:
    closed = node_manifest(Send)["output_schema"]
    assert closed["additionalProperties"] is False  # serialization never emits undeclared fields
    opened = node_manifest(_node(run=_run, Output=OpenOut))["output_schema"]
    assert opened["additionalProperties"] is True  # extra="allow" keeps its extras
    assert opened["$defs"]["Nested"]["additionalProperties"] is False


def test_manifest_problems() -> None:
    cases = [
        (_node(type="Demo", run=_run), "type must look like"),
        (_node(version=0, run=_run), "version must be an integer"),
        (_node(ports=("out", "error"), run=_run), "invalid port 'error'"),
        (_node(ports=("a", "a"), run=_run), "duplicate ports"),
        (_node(dynamic_ports="cases", run=_run), "unknown config field"),
        (_node(), "must implement run()"),
        (_node(run=_run, side_effect=SideEffect.RECONCILABLE), "must implement reconcile()"),
        (_node(run=_run, retry=RetryDefaults(max_attempts=0)), "retry.max_attempts must be between 1 and 20"),
        (_node(run=_run, retry=RetryDefaults(max_attempts=21)), "retry.max_attempts must be between 1 and 20"),
        (
            _node(run=_run, retry=RetryDefaults(initial_interval=timedelta(0))),
            "retry.initial_interval must be positive",
        ),
        (_node(run=_run, retry=RetryDefaults(backoff=0.0)), "retry.backoff must be a finite number ≥ 1"),
        (_node(run=_run, retry=RetryDefaults(backoff=float("nan"))), "retry.backoff must be a finite number ≥ 1"),
        (
            _node(run=_run, retry=RetryDefaults(max_interval=timedelta(milliseconds=500))),
            "retry.max_interval must be ≥ retry.initial_interval",
        ),
        (_node(run=_run, retry=RetryDefaults(non_retryable=("",))), "retry.non_retryable must list error codes"),
    ]
    for node, fragment in cases:
        with pytest.raises(ManifestError) as e:
            node_manifest(node)
        assert fragment in str(e.value), (fragment, e.value.problems)


def test_control_nodes_need_no_run() -> None:
    assert node_manifest(_node(kind=NodeKind.CONTROL))["kind"] == "control"


def test_plugin_manifest_checks_prefix_and_duplicates() -> None:
    ok = Plugin(name="demo", version="1.0.0", nodes=(Send,))
    manifest = ok.manifest()
    assert manifest["nodes"][0]["type"] == "demo.send"
    assert manifest["sdk_version"] == "0.1.0"
    with pytest.raises(ManifestError, match="must start with 'other.'"):
        Plugin(name="other", version="1", nodes=(Send,)).manifest()
    with pytest.raises(ManifestError, match="duplicate"):
        Plugin(name="demo", version="1", nodes=(Send, Send)).manifest()


def test_value_kinds_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="value_kinds"):
        value_kinds("python")
