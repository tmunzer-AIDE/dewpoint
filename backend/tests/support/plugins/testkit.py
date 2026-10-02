# SPDX-License-Identifier: Apache-2.0
"""Engine test fixtures. Lives under tests/, so it is never packaged or registered in production."""

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

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

    async def simulate(self, ctx: StepContext, config: EchoConfig) -> EchoOutput:
        return EchoOutput(value={"simulated": config.value})


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
    """Takes `seconds`, heartbeating each second. `beats` records each heartbeat's run and time, for the tests."""

    type = "testkit.slow"
    version = 1
    title = "Slow"
    Config = SlowConfig
    beats: ClassVar[list[tuple[str, datetime]]] = []

    async def run(self, ctx: StepContext, config: SlowConfig) -> Empty:
        remaining = config.seconds
        while remaining > 0 and not ctx.cancelled:
            step = min(remaining, 1.0)
            await asyncio.sleep(step)
            remaining -= step
            ctx.heartbeat(remaining)
            Slow.beats.append((str(ctx.run_id), datetime.now(UTC)))
        return Empty()


class Login(BaseModel):
    user: str
    password: str = sensitive()


class SensitiveOutput(BaseModel):
    public: str
    secret_value: str = sensitive()
    login: Login  # a nested model: its schema sits behind a $ref


class Sensitive(Node):
    type = "testkit.sensitive"
    version = 1
    title = "Sensitive"
    Output = SensitiveOutput

    async def run(self, ctx: StepContext, config: Empty) -> SensitiveOutput:
        return SensitiveOutput(
            public="visible", secret_value="s3cr3t-value", login=Login(user="ops", password="pa55word")
        )


class AmbiguousConfig(BaseModel):
    outcome: Literal["sent", "unknown", "rejected"] = "sent"
    detail: str = ""  # appended to the rejection: a receiver that echoes what it was sent
    token: str = sensitive(default="")  # and a credential it echoes too


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
            detail = (f": {config.detail}" if config.detail else "") + (f" for {config.token}" if config.token else "")
            raise FatalError("testkit.rejected", "the receiver rejected the request" + detail)
        return Empty()


class SlowSendConfig(BaseModel):
    seconds: float = Field(ge=0, le=600)


class SlowSend(Node):
    """Sends at once, then takes `seconds` to hear back. Past its timeout the request went out, but no reply came:
    the case a retry would duplicate. `sent` counts the sends, for the tests."""

    type = "testkit.slow_send"
    version = 1
    title = "Slow send"
    Config = SlowSendConfig
    side_effect = SideEffect.AMBIGUOUS
    sent: ClassVar[list[str]] = []

    async def run(self, ctx: StepContext, config: SlowSendConfig) -> Empty:
        SlowSend.sent.append(str(ctx.run_id))
        await asyncio.sleep(config.seconds)
        return Empty()


class ReconcileOutput(BaseModel):
    found: bool


class Reconcile(Node):
    """Its first attempt applies the effect and then loses the reply; `reconcile()` finds the effect on a retry."""

    type = "testkit.reconcile"
    version = 1
    title = "Reconcilable"
    Output = ReconcileOutput
    side_effect = SideEffect.RECONCILABLE

    async def run(self, ctx: StepContext, config: Empty) -> ReconcileOutput:
        raise RetryableError("testkit.lost_reply", "the effect happened, but the reply was lost")

    async def reconcile(self, ctx: StepContext, config: Empty) -> ReconcileOutput | None:
        return ReconcileOutput(found=True)


class BlobConfig(BaseModel):
    size: int = Field(ge=0, le=4 * 1024 * 1024)


class BlobOutput(BaseModel):
    value: str  # declared, so plain: a sub-flow can take it into a field it doesn't mark sensitive (spec §4.5)


class Blob(Node):
    """An output of `size` characters from a small config: what a step returns can pass Temporal's payload limit
    when what it was sent doesn't (engine 2b spec §5.2)."""

    type = "testkit.blob"
    version = 1
    title = "Blob"
    Config = BlobConfig
    Output = BlobOutput

    async def run(self, ctx: StepContext, config: BlobConfig) -> BlobOutput:
        return BlobOutput(value="x" * config.size)

    async def simulate(self, ctx: StepContext, config: BlobConfig) -> BlobOutput:
        return BlobOutput(value="x" * config.size)


class SecretBlobConfig(BaseModel):
    seed: str
    size: int = Field(ge=0, le=4 * 1024 * 1024)


class SecretBlobOutput(BaseModel):
    token: str = sensitive()


class SecretBlob(Node):
    """A sensitive output of `size` characters, starting with `seed` so each step's is its own: the run learns it,
    and carries it to be masked wherever it reappears (engine 2b spec §5.2)."""

    type = "testkit.secret_blob"
    version = 1
    title = "Secret blob"
    Config = SecretBlobConfig
    Output = SecretBlobOutput

    async def run(self, ctx: StepContext, config: SecretBlobConfig) -> SecretBlobOutput:
        return SecretBlobOutput(token=(config.seed + "s" * config.size)[: config.size])

    async def simulate(self, ctx: StepContext, config: SecretBlobConfig) -> SecretBlobOutput:
        return await self.run(ctx, config)


class SlowEchoConfig(BaseModel):
    seconds: float = Field(ge=0, le=600)
    value: Any = None
    fail: bool = False
    crash: bool = False  # raises an unexpected error quoting it: a plugin's bug


class SlowEcho(Node):
    """Takes `seconds`, then returns `value`, or fails quoting it (or crashes, quoting it): what it returns or says
    comes from its input, and the run may have learned it's sensitive meanwhile (engine 2b spec §3.7)."""

    type = "testkit.slow_echo"
    version = 1
    title = "Slow echo"
    Config = SlowEchoConfig
    Output = EchoOutput

    async def run(self, ctx: StepContext, config: SlowEchoConfig) -> EchoOutput:
        await asyncio.sleep(config.seconds)
        if config.fail:
            raise FatalError("echo_failed", f"failed on {config.value}")
        if config.crash:
            raise RuntimeError(f"crashed on {config.value}")
        return EchoOutput(value=config.value)


TESTKIT = Plugin(
    name="testkit",
    version="0.0.0",
    nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend, SlowSend, Reconcile, Blob, SecretBlob, SlowEcho),
)
