# SPDX-License-Identifier: Apache-2.0
import asyncio
from typing import Any

import pytest

from dewpoint.engine.cel import evaluate as E
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel import types as T

P = "cel-cpp-0.1.3/fn-1/cls-1"


def request(expr: str, *bindings: dict[str, Any], decls: dict[str, str] | None = None) -> ipc.EvaluateRequest:
    return ipc.EvaluateRequest(P, expr, decls or {"x": T.DYN}, tuple(bindings))


async def _roundtrip(frame: bytes, limit: int) -> dict[str, Any]:
    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()
    return await ipc.read_frame(reader, limit)


async def test_frames_round_trip_and_are_bounded() -> None:
    message = request("x + 1", {"x": 1}).to_json()
    assert await _roundtrip(ipc.encode(message), ipc.MAX_REQUEST) == message
    with pytest.raises(ipc.FrameError, match="exceeds"):
        await _roundtrip(ipc.encode(message), 10)
    with pytest.raises(ipc.FrameError):
        await _roundtrip(b"\x00\x00\x00\x02[]", 100)


@pytest.mark.parametrize(
    "message",
    [
        {"schema": ipc.SCHEMA, "kind": "evaluate"},
        {**request("x", {"x": 1}).to_json(), "declarations": {"x": "list(dyn)"}},
        {**request("x", {"x": 1}).to_json(), "bindings": []},
        {**request("x", {"x": 1}).to_json(), "bindings": [{"y": 1}]},
        {**request("x", {"x": 1}).to_json(), "expr": ""},
        {**request("x", {"x": 1}).to_json(), "extra": 1},
    ],
)
def test_malformed_requests_are_refused(message: dict[str, Any]) -> None:
    with pytest.raises(ipc.FrameError):
        ipc.parse_request(message)


def test_each_binding_set_is_its_own_evaluation() -> None:
    req = ipc.parse_request(request("x > 1", {"x": 1}, {"x": 2}, {"x": "a"}).to_json())
    assert isinstance(req, ipc.EvaluateRequest)
    results = ipc.evaluate_request(req)["results"]
    assert results[:2] == [{"ok": False}, {"ok": True}]
    assert results[2]["error"] == E.EVALUATION_ERROR


def test_the_evaluator_rechecks_types_and_order_safety() -> None:
    typed = request("x.map(i, i)", {"x": {"a": 1}}, decls={"x": T.LIST})
    assert ipc.evaluate_request(typed)["results"][0]["error"] == E.TYPE_MISMATCH
    leak = request("x.map(k, k)", {"x": {"a": 1}}, decls={"x": T.MAP})
    assert ipc.evaluate_request(leak)["error"] == "rejected"
    assert ipc.evaluate_request(request("x +", {"x": 1}))["error"] == "invalid_request"


def test_oversized_batches_of_results_are_refused_as_a_whole() -> None:
    big = request("x + x", *({"x": "y" * 1_000} for _ in range(300)))
    assert ipc.evaluate_request(big)["error"] == E.OUTPUT_TOO_LARGE
