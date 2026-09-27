# SPDX-License-Identifier: Apache-2.0
"""Client for the CEL evaluator, and the core of the `cel.evaluate` activity (spec §5.7). The Temporal activity
wrapper, its task queue per profile and the identity-gated polling arrive with the worker in 2a-3.

Evaluation outcomes (timeout, limits, errors) come back as values and are recorded. Only infrastructure failures
raise EvaluatorUnavailable, which the activity lets Temporal retry: unreachable socket, dropped connection, `busy`, or
a reply the protocol doesn't allow."""

import asyncio
from typing import Any

from dewpoint.engine.cel import evaluate, ipc

CLIENT_SECONDS = 15.0  # longer than one queued plus one running evaluation (2 x 5 s)


class EvaluatorUnavailable(Exception):
    """An infrastructure failure: retried, never recorded as the step's outcome."""


async def call(socket_path: str, message: dict[str, Any], *, seconds: float = CLIENT_SECONDS) -> dict[str, Any]:
    try:
        async with asyncio.timeout(seconds):
            reader, writer = await asyncio.open_unix_connection(socket_path)
            try:
                writer.write(ipc.encode(message))
                await writer.drain()
                return await ipc.read_frame(reader, ipc.MAX_RESPONSE)
            finally:
                writer.close()
    except (OSError, TimeoutError, asyncio.IncompleteReadError, ipc.FrameError) as e:
        raise EvaluatorUnavailable(f"{type(e).__name__}: {e}") from e


async def identity(socket_path: str) -> str:
    response = await call(socket_path, ipc.IdentityRequest().to_json())
    served = response.get("profile")
    if not isinstance(served, str):
        raise EvaluatorUnavailable("the evaluator didn't report its profile")
    return served


async def evaluate_remote(
    socket_path: str, request: ipc.EvaluateRequest, *, served_profile: str
) -> list[evaluate.Outcome]:
    """One outcome per binding set. Fails closed: no other profile ever evaluates the expression."""
    count = len(request.bindings)

    def every(code: str, message: str = "") -> list[evaluate.Outcome]:
        return [evaluate.Outcome(error=code, message=message)] * count

    if request.profile != served_profile:
        return every(evaluate.PROFILE_UNAVAILABLE, f"this worker serves {served_profile}")
    message = request.to_json()
    if len(ipc.encode(message)) - 4 > ipc.MAX_REQUEST:
        return every(evaluate.INPUT_TOO_LARGE, "the referenced values exceed the 4 MiB request limit")
    try:
        reply = ipc.parse_reply(await call(socket_path, message), count)
    except ipc.FrameError as e:
        raise EvaluatorUnavailable(f"the evaluator's reply breaks the protocol: {e}") from e
    if reply.error is None:
        return list(reply.outcomes)
    if reply.error == "busy":
        raise EvaluatorUnavailable("the evaluator is busy")
    if reply.error == "profile_mismatch":
        return every(evaluate.PROFILE_UNAVAILABLE, reply.message)
    return every(reply.error, reply.message)
