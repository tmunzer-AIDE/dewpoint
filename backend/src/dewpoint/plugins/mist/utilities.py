# SPDX-License-Identifier: Apache-2.0
"""One node type per device utility (plugins-3 D27, D28), made from the map's reviews and the vendored OAS. A utility
is a curated operation (`MistOperation`): the map allows it to its node, its site is the connection's org's, its path
values are checked; and its device is read first (a probe, which the map must allow too) to check its type is one the
review names. Its config holds only the body parameters its review permits, within their maxima, and, streaming, its
maximum duration; its output is its contract's:

- a diagnostic streams (`stream`): subscribe, POST, and the session's output, ended by terminal evidence, idle or the
  maximum duration; a condition unmet after the POST is retried, the diagnostic being reviewed as repeatable;
- a disruptive utility only POSTs: `{accepted: true, completion_known: false}`, and the session when its answer has one.
  It's ambiguous, so a failure after sending is never retried."""

import asyncio
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, ClassVar

from pydantic import BaseModel

from dewpoint.plugins.mist import oas, policy, routing, stream
from dewpoint.plugins.mist.client import InvalidAnswer, MistClient
from dewpoint.plugins.mist.nodes import MistOperation, OperationUnavailable, _class_name, _description, _title
from dewpoint.plugins.mist.schemas import converted, with_defs
from dewpoint.sdk import (
    FatalError,
    MaybeSent,
    Node,
    NodeError,
    OutcomeUnknownError,
    RateLimited,
    RedirectRefused,
    ResponseTooLarge,
    ResponseUnreadable,
    RetryableError,
    SideEffect,
    StepContext,
    declared_model,
)
from dewpoint.sdk.fields import CONNECTION, LITERAL, OPTIONS

DEVICE_CHECK = "getSiteDevice"  # the read that checks the device's type (reviews.DEVICE_CHECK)
DEFAULT_DURATION = {"bounded_collection": 60, "stream_terminal_evidence": 120}  # seconds, within the review's maximum
SIMULATED_SESSION = "00000000-0000-4000-8000-000000000000"
MARGIN_S = 30.0  # a collection ends this long before the step's timeout, whatever the checks before it took (L6)
# Free text a utility sends reaches a device's command line through Mist: one token of a host name, an address, an
# interface, a prefix or a name (review M2). `all` as a selector would mean every port, session or neighbor (M1).
ONE_WORD = r"^[A-Za-z0-9._:/@-]{1,253}$"
EVERY = {"pattern": "^[Aa][Ll][Ll]$"}
CONTRACT_TEXT = {
    "bounded_collection": " Returns the output received until it goes quiet or the maximum duration passes: never"
    " proof that the command finished.",
    "stream_terminal_evidence": " Succeeds only once the device's table says it finished.",
    "acceptance_only": " Succeeds once Mist accepted the command: its effect on the device isn't confirmed, and a"
    " failure after sending is never retried.",
}


class DeviceTypeUnsupported(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.device_type_unsupported", "The device isn't of a type this utility was reviewed for.")


class DeviceCheckFailed(RetryableError):
    def __init__(self) -> None:
        super().__init__("mist.device_check_failed", "The device couldn't be read to check its type: nothing was sent.")


def failure(unmet: stream.Unmet, *, repeatable: bool) -> NodeError:
    """An unmet condition after the POST (D27): retried for a reviewed repeatable diagnostic, of unknown outcome for any
    other utility, never retried."""
    if repeatable:
        return RetryableError(unmet.code, unmet.message)
    return OutcomeUnknownError(unmet.code, unmet.message)


class MistUtility(MistOperation):
    """A device utility's node. Generated subclasses set the class attributes below and MistOperation's."""

    review: ClassVar[policy.UtilityReview]
    answers_session: ClassVar[bool]  # its OAS answer holds a `session`
    default_duration: ClassVar[int | None]

    def _checked(self, config: Any) -> tuple[dict[str, Any], Any, list[str]]:
        values, body, clear = super()._checked(config)
        if policy.load().read(self.operation, self.type, DEVICE_CHECK) is None:
            raise OperationUnavailable()  # the device check is a read the map must allow, as the site check is
        return values, body, clear

    async def simulate(self, ctx: StepContext, config: Any) -> BaseModel:
        """The contract's output, never a request: the connection isn't even opened."""
        self._checked(config)
        simulated: Any = fixture(self)
        return self.Output.model_construct(simulated)

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        until = asyncio.get_running_loop().time() + self.timeout.total_seconds() - MARGIN_S  # the step's time, at most
        values, body, _ = self._checked(config)
        connection = await ctx.connection(uuid.UUID(values["connection"]))
        client = MistClient(connection)
        path = client.path(self.path, values)
        await client.check_site(values["site_id"])
        await self._check_device(client, values)
        sent = (body or {}) if "requestBody" in oas.operations()[self.operation].spec else None
        if self.review.stream:
            try:
                found: Any = await stream.collect(
                    ctx, connection, client, path, sent, channel=stream.channel(values["site_id"], values["device_id"]),
                    terminal=self.review.contract == "stream_terminal_evidence",
                    max_duration_s=float(values.get("max_duration_s", self.default_duration or 1)), until=until,
                )  # fmt: skip
            except stream.Unmet as e:
                raise failure(e, repeatable=self.side_effect == SideEffect.IDEMPOTENT) from None
            return self.Output.model_construct(found)
        answer = await client.call("POST", path, body=sent)
        accepted: Any = {"accepted": True, "completion_known": False}
        if self.answers_session:
            session = answer.body.get("session") if isinstance(answer.body, Mapping) else None
            if not isinstance(session, str) or not session:
                raise InvalidAnswer()
            accepted["session"] = session
        return self.Output.model_construct(accepted)

    async def _check_device(self, client: MistClient, values: Mapping[str, Any]) -> None:
        """The device is of a type the review names: one GET, a probe (a read before the effect)."""
        entry = policy.load().read(self.operation, self.type, DEVICE_CHECK)
        if entry is None:
            raise OperationUnavailable()
        try:
            found = await client.call("GET", client.path(entry.path, values), probe=True)
        except (MaybeSent, RateLimited, RedirectRefused, ResponseTooLarge, ResponseUnreadable):
            raise DeviceCheckFailed() from None  # it may have reached Mist, but it's a read: retrying repeats nothing
        kind = found.body.get("type") if isinstance(found.body, Mapping) else None
        if kind not in self.review.device_types:  # a device that names no type is refused too
            raise DeviceTypeUnsupported()


def fixture(node: type[MistUtility] | MistUtility) -> dict[str, Any]:
    """A simulated run's output: the contract's shape, saying no command was sent."""
    if node.review.stream:
        terminal = node.review.contract == "stream_terminal_evidence"
        return {
            "accepted": True, "session": SIMULATED_SESSION, "lines": ["(simulated: no command was sent)"],
            "received": 1, "ended_by": "finished" if terminal else "idle", "completion_known": terminal,
            "truncated": False,
        }  # fmt: skip
    return {"accepted": True, "completion_known": False} | ({"session": SIMULATED_SESSION}
                                                              if node.answers_session else {})  # fmt: skip


def _body(doc: Mapping[str, Any], op: oas.Operation) -> Mapping[str, Any]:
    found = op.spec.get("requestBody")
    if found is None:
        return {}
    content = oas.resolve(doc, found).get("content") or {}
    schema = oas.resolve(doc, content.get("application/json", {}).get("schema", {}))
    return schema if isinstance(schema, Mapping) else {}


def config_schema(
    doc: Mapping[str, Any], op: oas.Operation, review: policy.UtilityReview, pickers: Mapping[str, str],
    default_duration: int | None,
) -> dict[str, Any]:  # fmt: skip
    """The connection, the path values, the body's permitted parameters within their maxima, and, streaming, the
    maximum duration."""
    props: dict[str, Any] = {
        "connection": {"type": "string", "format": "uuid", "title": "Connection", LITERAL: True, CONNECTION: "mist"}
    }
    required = ["connection"]
    roots: list[Any] = []
    for p in op.parameters:
        if p["in"] == "path" and p["name"] != "org_id":
            props[p["name"]] = {
                "title": _title(p["name"]),
                **converted(p.get("schema", {}), output=False),
                "pattern": f"^{routing.value_pattern(op.id, p['name'])}$",
            }
            if p["name"] in pickers:
                props[p["name"]][OPTIONS] = True
            required.append(p["name"])
            roots.append(p.get("schema", {}))
    if review.parameters:
        body = _body(doc, op)
        declared = body.get("properties", {})
        permitted: dict[str, Any] = {}
        for name in review.parameters:
            permitted[name] = _parameter(doc, declared[name], review.bounds.get(name), name in review.selectors)
            roots.append(declared[name])
        props["body"] = {"type": "object", "title": "Body", "properties": permitted, "additionalProperties": False}
        needed = [r for r in body.get("required", []) if r in review.parameters]
        needed += [s for s in review.selectors if s not in needed]
        if needed:
            props["body"]["required"] = needed
            required.append("body")
    if review.stream:
        props["max_duration_s"] = {
            "type": "integer", "minimum": 1, "maximum": review.bounds["max_duration_s"], "default": default_duration,
            "title": "Seconds to collect output, at most",
        }  # fmt: skip
    out = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    return with_defs(doc, out, roots, output=False, partial=False)


def _token(doc: Mapping[str, Any], declared: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """A string without an enum as one token (review M2); any other schema as it is."""
    target = oas.resolve(doc, declared)
    if target.get("type") != "string" or "enum" in target:
        return schema
    if "pattern" in schema:
        return {**schema, "allOf": [{"pattern": ONE_WORD}]}
    return {**schema, "pattern": ONE_WORD}


def _parameter(doc: Mapping[str, Any], declared: Any, bound: int | None, selector: bool) -> dict[str, Any]:
    """A permitted body parameter's schema: the OAS's, a bounded integer within 1 and its maximum, free text one token,
    a selector never empty nor `all`."""
    target = oas.resolve(doc, declared)
    sub = _token(doc, declared, dict(converted(declared, output=False)))
    if bound is not None:
        sub["maximum"] = min(bound, target.get("maximum", bound))
        sub["minimum"] = max(1, target.get("minimum", 1))  # 0 is "unlimited" to some pings
    if target.get("type") == "array":
        items = target.get("items", {})
        sub["items"] = _token(doc, items, dict(converted(items, output=False)))
        if selector:
            sub["minItems"] = 1
            sub["items"] = {**sub["items"], "not": EVERY}
    elif selector:
        sub["not"] = EVERY
    return sub


def output_schema(review: policy.UtilityReview, answers_session: bool) -> dict[str, Any]:
    """The contract's output (D27): a stream's collected lines, or a command accepted with its completion unknown."""
    if review.stream:
        terminal = review.contract == "stream_terminal_evidence"
        props: dict[str, Any] = {
            "accepted": {"const": True},
            "session": {"type": "string"},
            "lines": {"type": "array", "items": {"type": "string"}},
            "received": {"type": "integer", "minimum": 1},
            "ended_by": {"const": "finished"} if terminal else {"enum": ["finished", "idle", "max_duration"]},
            "completion_known": {"const": True} if terminal else {"type": "boolean"},
            "truncated": {"type": "boolean"},
        }
    else:
        props = {"accepted": {"const": True}, "completion_known": {"const": False}}
        if answers_session:
            props["session"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": sorted(props), "additionalProperties": False}


def _answers_session(doc: Mapping[str, Any], op: oas.Operation) -> bool:
    answer = oas.answer(doc, op)
    return answer is not None and "session" in oas.resolve(doc, answer).get("properties", {})


def build() -> tuple[type[Node], ...]:
    """Every reviewed utility's node, in the map's order."""
    doc, ops, entries = oas.document(), oas.operations(), policy.load().entries
    lists = {e.path: op_id for op_id, e in sorted(entries.items()) if e.state == "allowed"
             and routing.is_list(doc, ops[op_id])}  # fmt: skip
    out: list[type[Node]] = []
    for op_id, entry in sorted(entries.items()):
        review = entry.utility
        if entry.state != "allowed" or review is None or entry.side_effect is None or entry.scope is None:
            continue
        op, type_ = ops[op_id], entry.nodes[0]
        pickers = {f: o for f, o in routing.pickers(op.path, entry.scope, lists).items() if o in entry.reads}
        answers, default = _answers_session(doc, op), DEFAULT_DURATION.get(review.contract)
        if review.stream and not answers:  # its output couldn't be told from another command's (review L5)
            raise ValueError(f"{op_id}: a stream from an answer without a session")
        name = _class_name(type_)
        attrs: dict[str, Any] = {
            "__module__": __name__,
            "__qualname__": name,
            "type": type_,
            "version": 1,
            "title": _title(op_id),
            "description": _description(op) + CONTRACT_TEXT[review.contract],
            "Config": declared_model(
                f"{name}Config", config_schema(doc, op, review, pickers, default), formats=(), checked=False
            ),
            "Output": declared_model(f"{name}Output", output_schema(review, answers), formats=(), checked=False),
            "side_effect": SideEffect(entry.side_effect),
            "capabilities": frozenset({entry.capability}),
            "timeout": timedelta(minutes=5 if review.stream else 1),
            "operation": op_id,
            "method": op.method,
            "path": op.path,
            "scope": entry.scope,
            "shape": "utility",
            "pickers": pickers,
            "review": review,
            "answers_session": answers,
            "default_duration": default,
        }
        out.append(type(name, (MistUtility,), attrs))
    return tuple(out)


NODES = build()
