# SPDX-License-Identifier: Apache-2.0
import decimal
import enum
import ipaddress
import pathlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, TypedDict

import pytest
from jsonschema import Draft202012Validator
from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    SecretStr,
    WrapSerializer,
    computed_field,
    field_serializer,
    model_serializer,
)

from dewpoint.sdk import (
    FatalError,
    ManifestError,
    Node,
    NodeKind,
    Plugin,
    RetryDefaults,
    SideEffect,
    StepContext,
    dump_output,
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
    assert manifest["sdk_version"] == "0.4.0"
    with pytest.raises(ManifestError, match="must start with 'other.'"):
        Plugin(name="other", version="1", nodes=(Send,)).manifest()
    with pytest.raises(ManifestError, match="duplicate"):
        Plugin(name="demo", version="1", nodes=(Send, Send)).manifest()


def test_value_kinds_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="value_kinds"):
        value_kinds("python")


class Defaults(BaseModel):
    name: str
    count: int = 0
    note: str | None = None


class Sparse(TypedDict, total=False):
    maybe: int


class DefaultsOut(BaseModel):
    kept: Defaults = Defaults(name="x")
    sparse: Sparse = {}
    token_hint: str = Field(default="t", alias="tokenHint")
    only_out: int = Field(default=1, serialization_alias="onlyOut")

    @computed_field
    @property
    def doubled(self) -> int:
        return self.only_out * 2

    @field_serializer("only_out")
    def _plus(self, value: int) -> int:
        return value + 1  # field serializers transform values; they can't drop keys


def test_output_schemas_require_every_field_serialization_emits() -> None:
    """dump_output emits defaulted fields, aliases and computed fields, so none of them is possibly missing; TypedDict
    keys that aren't required may be absent, so they stay optional."""
    m = node_manifest(_node(run=_run, Output=DefaultsOut))["output_schema"]
    assert m["required"] == ["kept", "sparse", "tokenHint", "onlyOut", "doubled"]
    assert m["$defs"]["Defaults"]["required"] == ["name", "count", "note"]
    assert "required" not in m["$defs"]["Sparse"]
    config = node_manifest(Send)["config_schema"]
    assert config["required"] == ["target"]  # validation schemas are unchanged: defaults stay optional


def test_dump_output_is_what_the_output_schema_describes() -> None:
    schema = node_manifest(_node(run=_run, Output=DefaultsOut))["output_schema"]
    dumped = dump_output(DefaultsOut())
    assert sorted(dumped) == sorted(schema["properties"])  # aliases, not field names
    assert list(Draft202012Validator(schema).iter_errors(dumped)) == []
    plain = DefaultsOut().model_dump(mode="json")  # without by_alias, the names don't match the schema
    assert list(Draft202012Validator(schema).iter_errors(plain)) != []


class SelfSerializing(BaseModel):
    a: int
    b: int = 0

    @model_serializer(mode="wrap")
    def _drop(self, handler: Any) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        out.pop("b")
        return out


class Wrapper(BaseModel):
    inner: SelfSerializing


@pytest.mark.parametrize("output", [SelfSerializing, Wrapper])
def test_outputs_that_serialize_themselves_are_refused(output: type[BaseModel]) -> None:
    """A @model_serializer can drop a field the schema requires (here: b), anywhere inside the output."""
    with pytest.raises(ManifestError, match="output type SelfSerializing uses @model_serializer"):
        node_manifest(_node(run=_run, Output=output))


class UntypedLabel(BaseModel):
    value: int

    @field_serializer("value")
    def _label(self, value):  # type: ignore[no-untyped-def]  # no return type: the schema would still say integer
        return f"v-{value}"


class UntypedAnnotated(BaseModel):
    value: Annotated[int, PlainSerializer(lambda v: f"v-{v}")]


class UntypedWrap(BaseModel):
    value: Annotated[int, WrapSerializer(lambda v, handler: handler(v))]


class HoldsUntyped(BaseModel):
    inner: list[UntypedLabel]


@pytest.mark.parametrize(
    ("output", "where"),
    [
        (UntypedLabel, "UntypedLabel.value"),
        (UntypedAnnotated, "UntypedAnnotated.value"),
        (UntypedWrap, "UntypedWrap.value"),
        (HoldsUntyped, "UntypedLabel.value"),
    ],
)
def test_serializers_must_declare_what_they_emit(output: type[BaseModel], where: str) -> None:
    """Without a return type, pydantic keeps the field's own type in the schema while the dump emits whatever the
    serializer returns (here: `value: integer`, emitted as "v-1")."""
    with pytest.raises(ManifestError, match=f"{where} has a serializer without a declared return type"):
        node_manifest(_node(run=_run, Output=output))


class TypedLabel(BaseModel):
    value: int
    other: Annotated[int, PlainSerializer(lambda v: f"o-{v}", return_type=str)] = 0

    @field_serializer("value")
    def _label(self, value: int) -> str:
        return f"v-{value}"


class Hue(enum.Enum):
    RED = "red"


class PydanticTypes(BaseModel):
    at: datetime
    day: date
    span: timedelta
    id: uuid.UUID
    amount: decimal.Decimal
    hue: Hue
    ip: ipaddress.IPv4Address
    net: ipaddress.IPv4Network
    path: pathlib.Path
    secret: SecretStr
    url: AnyUrl


@pytest.mark.parametrize(
    "value",
    [
        TypedLabel(value=1),
        PydanticTypes(
            at=datetime(2026, 1, 1, tzinfo=UTC),
            day=date(2026, 1, 1),
            span=timedelta(seconds=90),
            id=uuid.UUID(int=1),
            amount=decimal.Decimal("1.5"),
            hue=Hue.RED,
            ip=ipaddress.IPv4Address("10.0.0.1"),
            net=ipaddress.IPv4Network("10.0.0.0/8"),
            path=pathlib.Path("reports/x.csv"),
            secret=SecretStr("s"),
            url=AnyUrl("https://example.com/x"),
        ),
    ],
)
def test_declared_and_pydantic_serializers_match_their_schema(value: BaseModel) -> None:
    """A declared return type is the schema; pydantic's own serializers (dates, paths, addresses, URLs, secrets)
    describe what they emit through their types."""
    schema = node_manifest(_node(run=_run, Output=type(value)))["output_schema"]
    assert list(Draft202012Validator(schema).iter_errors(dump_output(value))) == []


def _with_connection(credentials: tuple[str, ...], nested: bool = False) -> type:
    import uuid as _uuid

    from pydantic import BaseModel as _Base

    from dewpoint.sdk import connection_field

    class Inner(_Base):
        connection: _uuid.UUID = connection_field("mist")

    if nested:

        class NestedConfig(_Base):
            inner: Inner

        config: type = NestedConfig
    else:

        class FlatConfig(_Base):
            connection: _uuid.UUID = connection_field("mist")

        config = FlatConfig

    class UsesConnection(Node):
        type = "x.uses_connection"
        version = 1
        title = "Uses a connection"
        Config = config

        async def run(self, ctx, config):  # type: ignore[no-untyped-def]
            return None

    UsesConnection.credentials = credentials
    return UsesConnection


def test_a_connection_field_is_top_level_and_its_type_is_a_credential() -> None:
    from dewpoint.sdk.fields import CONNECTION

    manifest = node_manifest(_with_connection(("mist",)))
    assert manifest["config_schema"]["properties"]["connection"][CONNECTION] == "mist"
    with pytest.raises(ManifestError, match="credentials"):
        node_manifest(_with_connection(()))
    with pytest.raises(ManifestError, match="top-level"):
        node_manifest(_with_connection(("mist",), nested=True))
