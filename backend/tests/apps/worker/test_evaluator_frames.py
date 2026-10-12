# SPDX-License-Identifier: Apache-2.0
"""`cel.evaluate` sends its resolved binding sets to the evaluator in calls within its frame limit (the review of the
2b-4b M2 checkpoint, C1): resolved, #26's 1,000 sets each carry the shared value its claim kept out of the workflow's
request, about 65 MB, which one call can't carry. And a claim the sets share is fetched once a call (I1)."""

import asyncio
from typing import Any

from dewpoint.apps.worker import claims
from dewpoint.engine.canonical import canonical_json

REQUEST = {"profile": "p", "expr": "size(s) > item", "declarations": {}}


def test_resolved_sets_go_in_calls_within_the_frame_and_one_too_large_is_refused_alone() -> None:
    big, huge = "x" * 600_000, "y" * (claims.FRAME_BYTES + 1)
    ready = [(i, {"s": huge if i == 3 else big, "item": i}) for i in range(20)]
    calls = claims._within_frame({**REQUEST, "bindings": []}, ready)
    sent = [i for chunk, _ in calls for i, _ in chunk]
    refused = [i for _, r in calls for i in r]
    assert refused == [3] and sent == [i for i in range(20) if i != 3]  # in order, the oversized one alone refused
    for chunk, _ in calls:
        assert len(canonical_json({**REQUEST, "bindings": [b for _, b in chunk]})) <= claims.FRAME_BYTES
    assert len(calls) > 1


def test_a_claim_the_sets_share_is_fetched_once_a_call() -> None:
    fetched: list[str] = []

    async def fetch(claim_id: str) -> Any:
        fetched.append(claim_id)
        return claim_id

    cached = claims._cached(fetch)

    async def run() -> None:
        for _ in range(1_000):
            await cached("c1")
        await cached("c2")

    asyncio.run(run())
    assert fetched == ["c1", "c2"]
