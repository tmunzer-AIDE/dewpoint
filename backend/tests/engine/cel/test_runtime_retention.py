# SPDX-License-Identifier: Apache-2.0
"""An evaluation keeps nothing it passed to, or got back from, one of our functions (fn-1).

cel-expr-python 0.1.3 never releases the argument tuple it builds for a call to a Python function, nor the value the
function returns (its `PyCelFunctionAdapter::Invoke`); the cel-gates process held 1,200 copies of one load's map
argument, 241,000 lists that every later full collection walked. The patched runtime (deploy/cel-runtime) releases
both. Counted in objects and bytes, never timed."""

import gc
import tracemalloc
from collections.abc import Callable
from typing import Any

from dewpoint.engine.cel import evaluate, ipc, profile, runtime
from dewpoint.engine.cel import types as T

KEPT = "0-kept"  # a key and an item only these tests' values hold; it sorts first
TIMES = 20


def kept(found: Callable[[Any], bool]) -> int:
    """Objects the collector tracks that match `found`, after a full collection."""
    gc.collect()
    return sum(1 for o in gc.get_objects() if found(o))


def added(found: Callable[[Any], bool], run: Callable[[], None]) -> int:
    """How many more objects match `found` once `run` is done: what it kept, whatever ran before it."""
    before = kept(found)
    run()
    return kept(found) - before


def map_copies(original: dict[str, Any]) -> Callable[[Any], bool]:
    return lambda o: type(o) is dict and KEPT in o and o is not original


def key_lists(o: Any) -> bool:
    return type(o) is list and len(o) == 2 and o[0] == KEPT


def test_a_maps_copies_and_the_keys_returned_are_not_kept() -> None:
    m = {KEPT: [1, 2, 3], "b": [4, 5]}
    program = runtime.compile_checked("size(sortedKeys(m)) == 2", {"m": T.MAP})

    def run() -> None:
        for _ in range(TIMES):
            assert runtime.evaluate(program, {"m": m}) == runtime.RawResult("value", True, "BOOL")

    assert added(lambda o: map_copies(m)(o) or key_lists(o), run) == 0


def test_a_list_returned_as_it_came_is_not_kept() -> None:
    items = [KEPT, "b", "c"]
    program = runtime.compile_checked("size(asList(l)) == 3", {"l": T.LIST})

    def run() -> None:
        for _ in range(TIMES):
            assert runtime.evaluate(program, {"l": items}).value is True

    assert added(lambda o: type(o) is list and o[:1] == [KEPT] and o is not items, run) == 0


# Any traced window shows a few KB that don't grow with the calls (blocks allocated before tracing starts, reallocated
# inside it): 400 calls put that over 8 B a call on Linux; 4000 put it near 1 B, against about 156 B a call leaked.
def bytes_kept_per_evaluation(expr: str, values: dict[str, Any], times: int = 4000) -> float:
    program = runtime.compile_checked(expr, dict.fromkeys(values, T.STRING))
    for _ in range(20):  # caches warm first
        runtime.evaluate(program, values)
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(times):
            runtime.evaluate(program, values)
        gc.collect()
        return (tracemalloc.get_traced_memory()[0] - before) / times
    finally:
        tracemalloc.stop()


def test_calls_with_strings_and_failing_calls_keep_nothing() -> None:
    assert bytes_kept_per_evaluation('ipInCidr(s, "10.0.0.0/8")', {"s": "10.1.2.3"}) < 8
    assert bytes_kept_per_evaluation("macNormalize(s)", {"s": "00:1A:2B:3C:4D:5E"}) < 8
    assert bytes_kept_per_evaluation("macOui(s)", {"s": "not a mac address"}) < 8  # a CEL error value


def test_the_interpreters_local_evaluations_keep_nothing() -> None:
    m = {KEPT: [1], "b": [2]}
    program = evaluate.compiled("sortedKeys(m)", {"m": T.MAP})

    def run() -> None:
        for _ in range(TIMES):
            assert evaluate.run(program, {"m": m}) == evaluate.Outcome(value=[KEPT, "b"])

    assert added(lambda o: map_copies(m)(o) or key_lists(o), run) == 0


def test_the_evaluators_requests_keep_nothing() -> None:
    """The evaluator child's work for one request (its process exits after each; within one, nothing piles up)."""
    m = {KEPT: [1], "b": [2]}
    request = ipc.EvaluateRequest(
        profile.CURRENT_CEL_PROFILE, "sortedKeys(m)", {"m": T.MAP}, tuple({"m": m} for _ in range(TIMES))
    )
    expected = ipc.results_response([evaluate.Outcome(value=[KEPT, "b"])] * TIMES)

    def run() -> None:
        assert ipc.evaluate_request(request) == expected

    assert added(lambda o: map_copies(m)(o) or key_lists(o), run) == 0
