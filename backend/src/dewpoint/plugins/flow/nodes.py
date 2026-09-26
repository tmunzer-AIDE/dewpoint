# SPDX-License-Identifier: Apache-2.0
"""Control nodes. The engine executes them itself (kind=CONTROL); these classes declare only their contract."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dewpoint.sdk import Node, NodeKind, literal_only, value_kinds


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenOutput(BaseModel):
    """Output whose fields are defined per step (sub-flow outputs, transform fields)."""

    model_config = ConfigDict(extra="allow")


class _Control(Node):
    kind = NodeKind.CONTROL


class IfConfig(_Strict):
    condition: bool


class If(_Control):
    type = "flow.if"
    version = 1
    title = "If"
    description = "Continues on `true` or `false`."
    Config = IfConfig
    ports = ("true", "false")


class SwitchCase(_Strict):
    port: str = literal_only(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    when: bool


class SwitchConfig(_Strict):
    cases: list[SwitchCase] = Field(min_length=1, max_length=20)


class Switch(_Control):
    type = "flow.switch"
    version = 1
    title = "Switch"
    description = "Continues on the first case whose condition holds, otherwise on `default`."
    Config = SwitchConfig
    ports = ("default",)
    dynamic_ports = "cases"


class LoopConfig(_Strict):
    items: list[Any]
    concurrency: int = literal_only(1, ge=1, le=10)
    item_cap: int = literal_only(10_000, ge=1, le=10_000)
    on_item_error: Literal["stop", "continue"] = literal_only("stop")
    collect: Any = None


class LoopFailure(BaseModel):
    index: int
    code: str
    message: str


class LoopOutput(BaseModel):
    items: list[Any]
    failures: list[LoopFailure]
    count: int


class Loop(_Control):
    type = "flow.loop"
    version = 1
    title = "Loop"
    description = "Runs the `body` region once per item, then continues on `done`."
    Config = LoopConfig
    Output = LoopOutput
    ports = ("body", "done")


class FilterConfig(_Strict):
    items: list[Any]
    predicate: bool = value_kinds("cel")


class FilterOutput(BaseModel):
    items: list[Any]
    count: int


class Filter(_Control):
    type = "flow.filter"
    version = 1
    title = "Filter"
    description = "Keeps the items for which the predicate holds. Each item is a separate evaluation."
    Config = FilterConfig
    Output = FilterOutput


class SetVariablesConfig(_Strict):
    assignments: dict[str, Any] = Field(min_length=1, max_length=50)


class SetVariables(_Control):
    type = "flow.set_variables"
    version = 1
    title = "Set variables"
    Config = SetVariablesConfig


class DelayConfig(_Strict):
    duration_s: int = Field(ge=0, le=30 * 86_400)


class Delay(_Control):
    type = "flow.delay"
    version = 1
    title = "Delay"
    Config = DelayConfig


class WaitUntilConfig(_Strict):
    until: datetime


class WaitUntil(_Control):
    type = "flow.wait_until"
    version = 1
    title = "Wait until"
    Config = WaitUntilConfig


class Stop(_Control):
    type = "flow.stop"
    version = 1
    title = "Stop"
    description = "Ends the run as succeeded."
    ports = ()


class FailConfig(_Strict):
    message: str = Field(min_length=1, max_length=500)


class Fail(_Control):
    type = "flow.fail"
    version = 1
    title = "Fail"
    description = "Ends the run as failed."
    Config = FailConfig
    ports = ()


class RunWorkflowConfig(_Strict):
    workflow_id: uuid.UUID = literal_only()
    input: dict[str, Any] = Field(default_factory=dict)


class RunWorkflow(_Control):
    type = "flow.run_workflow"
    version = 1
    title = "Run workflow"
    description = "Runs another workflow's version pinned at publish, and returns its outputs."
    Config = RunWorkflowConfig
    Output = OpenOutput


class TransformConfig(_Strict):
    fields: dict[str, Any] = Field(min_length=1, max_length=100)


class Transform(_Control):
    type = "flow.transform"
    version = 1
    title = "Transform"
    description = "Builds an object from values, references and expressions."
    Config = TransformConfig
    Output = OpenOutput


NODES: tuple[type[Node], ...] = (
    If,
    Switch,
    Loop,
    Filter,
    SetVariables,
    Delay,
    WaitUntil,
    Stop,
    Fail,
    RunWorkflow,
    Transform,
)
