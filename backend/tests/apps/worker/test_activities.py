# SPDX-License-Identifier: Apache-2.0
"""A plugin step's activity (spec §3, parent §6.6), run in Temporal's ActivityEnvironment: no server, no workflow. It
runs one attempt of the node and writes nothing: `RunGraph` counts the attempts and projects their rows."""

import asyncio
import dataclasses
import datetime
import ipaddress
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic_core import PydanticCustomError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from dewpoint.apps.worker.activities import CHECKED_FORMATS, cel_activity, remote_evaluator, step_activity_for
from dewpoint.apps.worker.context import idempotency_key
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import MAPPED, CelInput, CelResult, StepInput, StepResult
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.sdk import Node, SideEffect, StepContext, sensitive
from tests.support.plugins.testkit import AmbiguousSend, Echo, FailN, Reconcile, Sensitive, Slow

IDS = {"tenant_id": str(uuid.UUID(int=1)), "run_id": str(uuid.UUID(int=2)), "step_id": str(uuid.UUID(int=3))}
SECRET = "hunter22"


def _quoting(what: str) -> Callable[[str], str]:
    """A validator whose own message quotes the value, as validators often do."""

    def check(value: str) -> str:
        if value.startswith("bad"):
            raise ValueError(f"{what} {value} isn't accepted")
        return value

    return check


class LiarOutput(BaseModel):
    n: int
    key: str
    _key = field_validator("key")(_quoting("key"))


def _custom(value: str) -> str:
    """A validator whose own error *type* carries the value: pydantic accepts any string there."""
    if value.startswith("bad"):
        raise PydanticCustomError(f"not_{value}", "refused")
    return value


class PinConfig(BaseModel):
    pin: int = Field(ge=1000, le=9999)
    token: str = "ok"
    code: str = "ok"
    _token = field_validator("token")(_quoting("token"))
    _code = field_validator("code")(_custom)


class Liar(Node):
    type = "testkit.liar"
    version = 1
    title = "Liar"
    Config = PinConfig
    Output = LiarOutput

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return {"n": config.pin, "key": f"bad-{SECRET}"}  # an output nobody ever sees, so nothing learns it


class KeyedOutput(BaseModel):
    headers: dict[str, int] = sensitive()
    codes: dict[int, int] = sensitive()


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: int


class Keyed(Node):
    """Its output fails validation under a key that came from the data, and its config refuses unknown keys."""

    type = "testkit.keyed"
    version = 1
    title = "Keyed"
    Config = StrictConfig
    Output = KeyedOutput

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return {"headers": {f"x-{SECRET}": "not-an-int"}, "codes": {428319: "not-an-int"}}


class Constructed(Node):
    """Returns an instance built without validation: `model_construct` holds whatever it's given."""

    type = "testkit.constructed"
    version = 1
    title = "Constructed"
    Output = LiarOutput

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return LiarOutput.model_construct(n="not-an-int", key="ok")


class FormatsConfig(BaseModel):
    valid: bool


class Tagged(BaseModel):
    """A valid output whose field serializer changes the type: an `int` is emitted as text, as its schema says."""

    id: int

    @field_serializer("id")
    def _tag(self, value: int) -> str:
        return f"id-{value}"


class Serialized(Node):
    type = "testkit.serialized"
    version = 1
    title = "Serialized"
    Output = Tagged

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return Tagged(id=3)


class Formatted(BaseModel):
    """Values whose output schema declares a `format`, as pydantic writes it."""

    id: uuid.UUID
    at: datetime.datetime
    on: datetime.date
    ip: ipaddress.IPv4Address


class Formats(Node):
    type = "testkit.formats"
    version = 1
    title = "Formats"
    Config = FormatsConfig
    Output = Formatted

    async def run(self, ctx: StepContext, config: FormatsConfig) -> Any:
        valid = Formatted(
            id=uuid.UUID(int=5), at=datetime.datetime(2026, 9, 27, 10, 0), on=datetime.date(2026, 9, 27), ip="10.0.0.1"
        )
        return valid if config.valid else Formatted.model_construct(**{**dict(valid), "id": "not-a-uuid"})


class Timed(BaseModel):
    precise: datetime.time
    zoned: datetime.time


class Times(Node):
    type = "testkit.times"
    version = 1
    title = "Times"
    Output = Timed

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return Timed(precise=datetime.time(10, 0, 0, 123456), zoned=datetime.time(10, 0, tzinfo=datetime.UTC))


def _buggy(value: str) -> str:
    """A validator with a bug: it raises something other than ValueError, and the error quotes the value."""
    raise KeyError(value)


class BuggyOutput(BaseModel):
    key: str
    _key = field_validator("key")(_buggy)


class BuggyConfig(BaseModel):
    key: str = "k"
    _key = field_validator("key")(_buggy)


class BuggySend(Node):
    """Sends, then its output's validator fails with a bug: after the request went out."""

    type = "testkit.buggy_send"
    version = 1
    title = "Buggy send"
    Output = BuggyOutput
    side_effect = SideEffect.AMBIGUOUS

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return {"key": SECRET}


class BuggyConfigured(Node):
    type = "testkit.buggy_configured"
    version = 1
    title = "Buggy config"
    Config = BuggyConfig

    async def run(self, ctx: StepContext, config: BuggyConfig) -> Any:
        return {}


class Broken(Node):
    type = "testkit.broken"
    version = 1
    title = "Broken"

    async def run(self, ctx: StepContext, config: Any) -> Any:
        raise ConnectionError(f"https://api.example/?token={SECRET} refused")


class BrokenSend(Broken):
    type = "testkit.broken_send"
    side_effect = SideEffect.AMBIGUOUS


def step(ref: str, config: dict[str, Any] | None = None, **extra: Any) -> StepInput:
    return StepInput(**IDS, node_key="s", iteration_key="l:0", ref=ref, config=config or {}, **extra)


def activity_env() -> ActivityEnvironment:
    """An activity of IDS's run: its workflow id names the tenant (engine 2b spec §6.1)."""
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=run_workflow_id(IDS["tenant_id"], IDS["run_id"]))
    return env


async def call(fn: Callable[[StepInput], Awaitable[StepResult]], data: StepInput) -> StepResult:
    return await activity_env().run(fn, data)


async def failure(fn: Callable[[StepInput], Awaitable[StepResult]], data: StepInput) -> Any:
    with pytest.raises(ApplicationError) as e:
        await call(fn, data)
    return e.value


async def test_a_step_returns_its_output_dumped_by_alias() -> None:
    assert await call(step_activity_for(Echo), step("testkit.echo@1", {"value": 5})) == StepResult(
        {"value": 5}, "applied"
    )


async def test_config_and_output_are_checked_without_echoing_the_values() -> None:
    """Review findings: pydantic's messages quote the input, and so does a validator's own prose (even with
    `include_input=False`). The projection is tenant-readable: name the field and the rule's code, nothing else."""
    bad_pin = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": SECRET}))
    bad_token = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": 1234, "token": f"bad-{SECRET}"}))
    bad_output = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": 1234}))
    assert {(e.type, e.non_retryable) for e in (bad_pin, bad_token)} == {("config_invalid", True)}
    assert (bad_output.type, bad_output.non_retryable) == ("output_schema_violation", True)
    assert bad_pin.message == "The config doesn't match `testkit.liar@1`: pin (int_parsing)."
    assert bad_token.message == "The config doesn't match `testkit.liar@1`: token (value_error)."
    assert bad_output.message == "The output doesn't match `testkit.liar@1`: key (value_error)."
    assert all(SECRET not in e.message for e in (bad_pin, bad_token, bad_output))


async def test_a_location_names_only_declared_fields() -> None:
    """Review finding: a location can hold a map key or an unknown key, taken from the data. A failed output is never
    learned, so the key would reach the projection. Declared names and list indexes stay; anything else is `*`."""
    bad_output = await failure(step_activity_for(Keyed), step("testkit.keyed@1", {"pin": 1}))
    bad_config = await failure(step_activity_for(Keyed), step("testkit.keyed@1", {"pin": 1, f"x-{SECRET}": 2}))
    listed = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": [SECRET]}))
    both = "headers.* (int_parsing); codes.* (int_parsing)"  # a numeric key isn't a list index
    assert bad_output.message == f"The output doesn't match `testkit.keyed@1`: {both}."
    assert bad_config.message == "The config doesn't match `testkit.keyed@1`: * (extra_forbidden)."
    assert listed.message == "The config doesn't match `testkit.liar@1`: pin (int_type)."
    assert all(SECRET not in e.message and "428319" not in e.message for e in (bad_output, bad_config, listed))


async def test_a_rule_code_is_one_pydantic_defines() -> None:
    """A custom error's type is whatever its validator made it, the value included: only pydantic's own codes show."""
    custom = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": 1234, "code": f"bad-{SECRET}"}))
    assert custom.message == "The config doesn't match `testkit.liar@1`: code (custom_error)."


async def test_errors_map_to_retries_and_outcomes() -> None:
    retry = await failure(step_activity_for(FailN), step("testkit.fail_n@1", {"failures": 1}))
    fatal = await failure(step_activity_for(AmbiguousSend), step("testkit.ambiguous_send@1", {"outcome": "rejected"}))
    unknown = await failure(step_activity_for(AmbiguousSend), step("testkit.ambiguous_send@1", {"outcome": "unknown"}))
    assert (retry.type, retry.non_retryable, retry.details) == (
        "testkit.transient",
        False,
        ({"outcome": None, MAPPED: True},),
    )
    assert (fatal.type, fatal.non_retryable) == ("testkit.rejected", True)
    assert (unknown.type, unknown.non_retryable, unknown.details) == (
        "testkit.timeout_after_send",
        True,
        ({"outcome": "outcome_unknown", MAPPED: True},),
    )


async def test_an_unexpected_exception_is_retried_unless_the_request_may_have_been_sent() -> None:
    plain = await failure(step_activity_for(Broken), step("testkit.broken@1"))
    sent = await failure(step_activity_for(BrokenSend), step("testkit.broken_send@1"))
    assert (plain.type, plain.non_retryable, plain.details) == (
        "unexpected_error",
        False,
        ({"outcome": None, MAPPED: True},),
    )
    assert (sent.type, sent.non_retryable, sent.details) == (
        "outcome_unknown",
        True,
        ({"outcome": "outcome_unknown", MAPPED: True},),
    )
    assert plain.message == "The node raised ConnectionError." and SECRET not in sent.message  # the text goes to logs


async def test_a_validator_bug_is_mapped_never_retried_and_quotes_nothing() -> None:
    """Final review: a validator raising something other than ValueError escaped the mapping. The SDK made it a
    retryable failure carrying its text: an ambiguous send was repeated, and the message quoted the data."""
    output = await failure(step_activity_for(BuggySend), step("testkit.buggy_send@1"))
    config = await failure(step_activity_for(BuggyConfigured), step("testkit.buggy_configured@1", {"key": SECRET}))
    assert (output.type, output.non_retryable, output.details) == (
        "output_schema_violation",
        True,
        ({"outcome": None, MAPPED: True},),
    )
    assert output.message == "The output doesn't match `testkit.buggy_send@1`: checking it raised KeyError."
    assert (config.type, config.non_retryable) == ("config_invalid", True)
    assert config.message == "The config doesn't match `testkit.buggy_configured@1`: checking it raised KeyError."


async def test_the_attempt_comes_from_the_workflow() -> None:
    """RunGraph counts attempts (each is one activity execution), so a reconcilable node checks on the second."""
    first = await failure(step_activity_for(Reconcile), step("testkit.reconcile@1"))
    second = await call(step_activity_for(Reconcile), step("testkit.reconcile@1", attempt=2))
    assert first.type == "testkit.lost_reply" and second == StepResult({"found": True}, "applied")
    passed = await call(step_activity_for(FailN), step("testkit.fail_n@1", {"failures": 1}, attempt=2))
    assert passed == StepResult({}, "applied")


async def test_simulation_calls_simulate_or_says_it_cannot() -> None:
    echoed = await call(step_activity_for(Echo), step("testkit.echo@1", {"value": 1}, mode="simulate"))
    refused = await failure(step_activity_for(Sensitive), step("testkit.sensitive@1", mode="simulate"))
    assert echoed == StepResult({"value": {"simulated": 1}}, "simulated")
    assert (refused.type, refused.non_retryable) == ("simulation_unavailable", True)


async def test_a_cancelled_step_stops() -> None:
    env = activity_env()
    task = asyncio.create_task(env.run(step_activity_for(Slow), step("testkit.slow@1", {"seconds": 30})))
    await asyncio.sleep(0.1)
    env.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_idempotency_key_is_per_step_and_iteration_not_per_attempt() -> None:
    key = idempotency_key("r", "s", "l:0")
    assert key == idempotency_key("r", "s", "l:0") and len(key) == 64
    others = {idempotency_key("r", "s", "l:1"), idempotency_key("r", "t", "l:0"), idempotency_key("q", "s", "l:0")}
    assert len({key, *others}) == 4


def test_the_workflow_sends_the_attempt_and_nothing_to_project() -> None:
    names = [f.name for f in dataclasses.fields(StepInput)]
    assert names[-2:] == ["mode", "attempt"] and "cel_mode" not in names


@asynccontextmanager
async def evaluator(reply: dict[str, Any]) -> AsyncIterator[str]:
    """A fake cel-evaluator on a Unix socket, answering every request with `reply`."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await ipc.read_frame(reader, ipc.MAX_REQUEST)
        writer.write(ipc.encode(reply))
        await writer.drain()
        writer.close()

    with tempfile.TemporaryDirectory(dir="/tmp") as d:  # AF_UNIX paths are limited to about 100 bytes
        path = os.path.join(d, "cel.sock")
        async with await asyncio.start_unix_server(handle, path=path):
            yield path


REQUEST = CelInput(ipc.EvaluateRequest(CURRENT_CEL_PROFILE, "x + 1", {"x": T.DYN}, ({"x": 1},)).to_json())


async def test_cel_evaluate_records_outcomes_and_retries_an_unavailable_evaluator(tmp_path: Path) -> None:
    reply = {"schema": ipc.SCHEMA, "results": [{"ok": 2}]}
    async with evaluator(reply) as path:
        answered = await ActivityEnvironment().run(cel_activity(remote_evaluator(path, CURRENT_CEL_PROFILE)), REQUEST)
    assert answered == CelResult([{"ok": 2}])
    nowhere = cel_activity(remote_evaluator(str(tmp_path / "nowhere.sock"), CURRENT_CEL_PROFILE))
    with pytest.raises(ApplicationError) as unavailable:
        await ActivityEnvironment().run(nowhere, REQUEST)
    assert (unavailable.value.type, unavailable.value.non_retryable) == ("evaluator_unavailable", False)
    with pytest.raises(ApplicationError) as invalid:
        await ActivityEnvironment().run(nowhere, CelInput({"schema": "nope"}))
    assert (invalid.value.type, invalid.value.non_retryable) == ("invalid_request", True)


async def test_an_output_instance_is_validated_too() -> None:
    """Checkpoint-2 finding: an instance of the node's own Output was trusted as it stood, but pydantic validates
    instances only when they're built through it. It's checked like any other output."""
    bad = await failure(step_activity_for(Constructed), step("testkit.constructed@1"))
    assert (bad.type, bad.non_retryable) == ("output_schema_violation", True)
    assert bad.message == "The output doesn't match `testkit.constructed@1`: n (type)."  # the output schema's rule


async def test_an_instance_breaking_a_format_is_refused_and_valid_formats_pass() -> None:
    """Checkpoint-2 re-review: without a format checker, `format: uuid` held nothing. The formats checked are the ones
    whose checks agree with what pydantic emits: a naive datetime is valid output, so `date-time` isn't checked."""
    bad = await failure(step_activity_for(Formats), step("testkit.formats@1", {"valid": False}))
    assert (bad.type, bad.message) == (
        "output_schema_violation",
        "The output doesn't match `testkit.formats@1`: id (format).",
    )
    assert set(FormatChecker(formats=CHECKED_FORMATS).checkers) == set(CHECKED_FORMATS)  # each one really checked
    good = await call(step_activity_for(Formats), step("testkit.formats@1", {"valid": True}))
    assert good.output == {
        "id": str(uuid.UUID(int=5)),
        "at": "2026-09-27T10:00:00",
        "on": "2026-09-27",
        "ip": "10.0.0.1",
    }


async def test_times_pydantic_emits_are_valid_output() -> None:
    """Final review: without an optional library, jsonschema checks `time` as `HH:MM:SS` and refuses the
    fractions and zones pydantic writes for valid times; with it, it wants a zone. `time` isn't checked."""
    assert await call(step_activity_for(Times), step("testkit.times@1")) == StepResult(
        {"precise": "10:00:00.123456", "zoned": "10:00:00Z"}, "applied"
    )
    assert "time" not in CHECKED_FORMATS


async def test_a_field_serializer_emits_what_the_output_schema_declares() -> None:
    """Checkpoint-2 re-review: an instance is checked as it's emitted, against the declared output schema, not
    against the model's input types, which a typed field serializer may change."""
    assert await call(step_activity_for(Serialized), step("testkit.serialized@1")) == StepResult(
        {"id": "id-3"}, "applied"
    )


async def test_an_activity_refuses_an_input_of_another_tenant() -> None:
    """Engine 2b spec §6.1: the store scopes every write by the input's tenant, so it must be the one the workflow id
    names. The failure isn't the node's: it isn't `MAPPED`."""
    other = dataclasses.replace(step("testkit.echo@1", {"value": 1}), tenant_id=str(uuid.UUID(int=9)))
    refused = await failure(step_activity_for(Echo), other)
    assert (refused.type, refused.non_retryable, refused.details) == ("internal_error", True, ())
