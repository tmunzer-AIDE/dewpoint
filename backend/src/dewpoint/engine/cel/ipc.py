# SPDX-License-Identifier: Apache-2.0
"""The `cel.evaluate.v1` protocol between the CEL activity and the evaluator (spec §5.7, §7): length-prefixed frames
of canonical JSON, strict request validation, and the evaluation of one request (run inside the evaluator's child).

A request carries one expression and 1 to 1,000 binding sets; each set is its own evaluation with its own budget
(filter batches, spec §6). Limits: requests ≤ 4 MiB, responses ≤ 256 KiB plus a small envelope."""

import asyncio
import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.cel import bind, classify, evaluate, runtime
from dewpoint.engine.cel import types as T

SCHEMA = "cel.evaluate.v1"
MAX_REQUEST = 4 * 1024 * 1024
MAX_RESPONSE = 256 * 1024 + 16 * 1024
MAX_BATCH = 1_000
MAX_EXPR = 16_384
_HEADER = struct.Struct(">I")


class FrameError(ValueError):
    """A malformed or oversized frame: the connection is closed without a reply."""


def encode(message: Mapping[str, Any]) -> bytes:
    body = canonical_json(message)
    return _HEADER.pack(len(body)) + body


async def read_frame(reader: asyncio.StreamReader, limit: int) -> dict[str, Any]:
    header = await reader.readexactly(_HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length > limit:
        raise FrameError(f"frame of {length} bytes exceeds {limit}")
    body = await reader.readexactly(length)
    try:
        message = json.loads(body)
    except (ValueError, RecursionError) as e:  # not UTF-8 or not JSON, too many digits, nested too deep
        raise FrameError("frame isn't JSON this protocol can read") from e
    if not isinstance(message, dict) or message.get("schema") != SCHEMA:
        raise FrameError(f"frame isn't a {SCHEMA} message")
    return message


@dataclass(frozen=True)
class IdentityRequest:
    def to_json(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "kind": "identity"}


@dataclass(frozen=True)
class EvaluateRequest:
    profile: str
    expr: str
    declarations: Mapping[str, str]
    bindings: tuple[Mapping[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "kind": "evaluate",
            "profile": self.profile,
            "expr": self.expr,
            "declarations": dict(self.declarations),
            "bindings": [dict(b) for b in self.bindings],
        }


def parse_request(message: Mapping[str, Any]) -> IdentityRequest | EvaluateRequest:
    kind = message.get("kind")
    if kind == "identity" and set(message) == {"schema", "kind"}:
        return IdentityRequest()
    if kind != "evaluate" or set(message) != {"schema", "kind", "profile", "expr", "declarations", "bindings"}:
        raise FrameError("unknown request")
    profile, expr, decls, bindings = (message[k] for k in ("profile", "expr", "declarations", "bindings"))
    if not isinstance(profile, str) or not isinstance(expr, str) or not 0 < len(expr) <= MAX_EXPR:
        raise FrameError("bad profile or expression")
    if not isinstance(decls, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v in T.SIGNATURES for k, v in decls.items()
    ):
        raise FrameError("bad declarations")
    if not isinstance(bindings, list) or not 0 < len(bindings) <= MAX_BATCH:
        raise FrameError(f"between 1 and {MAX_BATCH} binding sets")
    if not all(isinstance(b, dict) and set(b) <= set(decls) for b in bindings):
        raise FrameError("bindings must name declared identifiers")
    return EvaluateRequest(profile, expr, decls, tuple(bindings))


def identity_response(profile: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "profile": profile}


def error_response(code: str, message: str = "") -> dict[str, Any]:
    return {"schema": SCHEMA, "error": code, "message": message}


def results_response(outcomes: list[evaluate.Outcome]) -> dict[str, Any]:
    return {"schema": SCHEMA, "results": [o.to_json() for o in outcomes]}


# What a reply may record: an evaluation's outcome codes, per binding set or for the whole request, and the
# request-level refusals. `busy` and `profile_mismatch` are answers the client acts on.
RESULT_ERRORS = frozenset(
    {
        evaluate.ITERATION_BUDGET, evaluate.TYPE_MISMATCH, evaluate.EVALUATION_ERROR, evaluate.NON_JSON,
        evaluate.OUTPUT_TOO_LARGE, evaluate.INPUT_TOO_LARGE, evaluate.MEMORY_LIMIT, evaluate.CPU_LIMIT,
        evaluate.TIMEOUT, evaluate.CRASHED,
    }
)  # fmt: skip
REPLY_ERRORS = RESULT_ERRORS | {"invalid_request", "rejected", "busy", "profile_mismatch"}


@dataclass(frozen=True)
class EvaluateReply:
    outcomes: tuple[evaluate.Outcome, ...] = ()  # one per binding set, unless `error` answers the whole request
    error: str | None = None
    message: str = ""


def _error(data: Mapping[str, Any], allowed: frozenset[str], envelope: set[str]) -> tuple[str, str] | None:
    code, text = data.get("error"), data.get("message", "")
    if set(data) not in ({"error"} | envelope, {"error", "message"} | envelope):
        return None
    return (code, text) if isinstance(code, str) and code in allowed and isinstance(text, str) else None


def parse_reply(message: Mapping[str, Any], count: int) -> EvaluateReply:
    """The evaluator's answer to a request with `count` binding sets, strictly: FrameError for anything else,
    including a number of results other than `count`. The client retries it; it is never recorded."""
    if set(message) == {"schema", "results"}:
        results = message["results"]
        if not isinstance(results, list) or len(results) != count:
            raise FrameError(f"a reply must carry {count} results")
        outcomes = []
        for r in results:
            if isinstance(r, dict) and set(r) == {"ok"}:
                outcomes.append(evaluate.Outcome(value=r["ok"]))
            elif isinstance(r, dict) and (found := _error(r, RESULT_ERRORS, set())) is not None:
                outcomes.append(evaluate.Outcome(error=found[0], message=found[1]))
            else:
                raise FrameError("a result must be {ok} or {error, message} with a known code")
        return EvaluateReply(tuple(outcomes))
    if (found := _error(message, REPLY_ERRORS, {"schema"})) is not None:
        return EvaluateReply(error=found[0], message=found[1])
    raise FrameError("a reply must be {results} or {error, message} with a known code")


def _checked_bindings(request: EvaluateRequest, values: Mapping[str, Any]) -> evaluate.Outcome | None:
    for name, value in values.items():
        if not T.conforms(request.declarations[name], value):
            return evaluate.Outcome(error=evaluate.TYPE_MISMATCH, message=f"`{name}` doesn't match its declared type")
        try:
            bind.check_json(name, value)
        except bind.BindingError as e:
            return evaluate.Outcome(error=evaluate.TYPE_MISMATCH, message=str(e))
    return None


def evaluate_request(request: EvaluateRequest) -> dict[str, Any]:
    """The evaluator child's work for one request. Re-checks what publish proved (defence in depth)."""
    try:
        program = runtime.compile_checked(request.expr, request.declarations)
    except runtime.CompileError as e:
        return error_response("invalid_request", str(e))
    if classify.order_problems(program.checked):
        return error_response("rejected", "the expression iterates a value that isn't proven a list")
    outcomes = []
    for values in request.bindings:
        refused = _checked_bindings(request, values)
        outcomes.append(refused if refused is not None else evaluate.run(program, values))
    response = results_response(outcomes)
    if len(canonical_json(response)) > MAX_RESPONSE:
        return error_response(evaluate.OUTPUT_TOO_LARGE, "the results are larger than the response limit")
    return response
