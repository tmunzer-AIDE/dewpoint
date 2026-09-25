# SPDX-License-Identifier: Apache-2.0
"""Engine test fixtures. Lives under tests/, so it is never packaged or registered in production."""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from dewpoint.sdk import (
    Empty,
    FatalError,
    Node,
    OutcomeUnknownError,
    Plugin,
    RetryableError,
    SideEffect,
    StepContext,
    sensitive,
)


class EchoConfig(BaseModel):
    value: Any = None


class EchoOutput(BaseModel):
    value: Any


class Echo(Node):
    type = "testkit.echo"
    version = 1
    title = "Echo"
    Config = EchoConfig
    Output = EchoOutput

    async def run(self, ctx: StepContext, config: EchoConfig) -> EchoOutput:
        return EchoOutput(value=config.value)


class FailNConfig(BaseModel):
    failures: int = Field(ge=0, le=10)


class FailN(Node):
    type = "testkit.fail_n"
    version = 1
    title = "Fail N times"
    Config = FailNConfig
    side_effect = SideEffect.IDEMPOTENT

    async def run(self, ctx: StepContext, config: FailNConfig) -> Empty:
        if ctx.attempt <= config.failures:
            raise RetryableError("testkit.transient", f"attempt {ctx.attempt} fails on purpose")
        return Empty()


class SlowConfig(BaseModel):
    seconds: float = Field(ge=0, le=600)


class Slow(Node):
    type = "testkit.slow"
    version = 1
    title = "Slow"
    Config = SlowConfig

    async def run(self, ctx: StepContext, config: SlowConfig) -> Empty:
        remaining = config.seconds
        while remaining > 0 and not ctx.cancelled:
            step = min(remaining, 1.0)
            await asyncio.sleep(step)
            remaining -= step
            ctx.heartbeat(remaining)
        return Empty()


class SensitiveOutput(BaseModel):
    public: str
    secret_value: str = sensitive()


class Sensitive(Node):
    type = "testkit.sensitive"
    version = 1
    title = "Sensitive"
    Output = SensitiveOutput

    async def run(self, ctx: StepContext, config: Empty) -> SensitiveOutput:
        return SensitiveOutput(public="visible", secret_value="s3cr3t-value")


class AmbiguousConfig(BaseModel):
    outcome: Literal["sent", "unknown", "rejected"] = "sent"


class AmbiguousSend(Node):
    type = "testkit.ambiguous_send"
    version = 1
    title = "Ambiguous send"
    Config = AmbiguousConfig
    side_effect = SideEffect.AMBIGUOUS

    async def run(self, ctx: StepContext, config: AmbiguousConfig) -> Empty:
        if config.outcome == "unknown":
            raise OutcomeUnknownError("testkit.timeout_after_send", "the request may have been delivered")
        if config.outcome == "rejected":
            raise FatalError("testkit.rejected", "the receiver rejected the request")
        return Empty()


TESTKIT = Plugin(name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend))
