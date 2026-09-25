# SPDX-License-Identifier: Apache-2.0
import builtins
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from dewpoint.sdk.context import StepContext

TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
PORT_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
RESERVED_PORTS = frozenset({"error"})  # added by the engine when a step routes errors to a port
MAX_RETRY_ATTEMPTS = 20  # same ceiling as a step's max_attempts override in the graph


class NodeKind(StrEnum):
    ACTION = "action"  # runs as a versioned activity
    CONTROL = "control"  # executed by the engine itself (flow plugin only)


class SideEffect(StrEnum):
    NONE = "none"
    IDEMPOTENT = "idempotent"
    KEYED = "keyed"
    RECONCILABLE = "reconcilable"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RetryDefaults:
    max_attempts: int = 3
    initial_interval: timedelta = timedelta(seconds=1)
    backoff: float = 2.0
    max_interval: timedelta = timedelta(minutes=1)
    non_retryable: tuple[str, ...] = ()


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node:
    """Base class for node types. Subclasses set the class attributes; action nodes implement run()."""

    type: ClassVar[str]
    version: ClassVar[int]
    title: ClassVar[str]
    description: ClassVar[str] = ""
    kind: ClassVar[NodeKind] = NodeKind.ACTION
    # `builtins.type`: inside this class body, `type` names the class attribute above.
    Config: ClassVar[builtins.type[BaseModel]] = Empty
    Output: ClassVar[builtins.type[BaseModel]] = Empty
    ports: ClassVar[tuple[str, ...]] = ("out",)
    dynamic_ports: ClassVar[str | None] = None  # a config field whose entries each declare a `port`
    credentials: ClassVar[tuple[str, ...]] = ()
    capabilities: ClassVar[frozenset[str]] = frozenset()
    side_effect: ClassVar[SideEffect] = SideEffect.NONE
    retry: ClassVar[RetryDefaults] = RetryDefaults()
    timeout: ClassVar[timedelta] = timedelta(minutes=1)

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        raise NotImplementedError

    async def simulate(self, ctx: StepContext, config: Any) -> BaseModel:
        raise NotImplementedError

    async def reconcile(self, ctx: StepContext, config: Any) -> BaseModel | None:
        raise NotImplementedError
