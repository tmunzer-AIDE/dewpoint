# SPDX-License-Identifier: Apache-2.0
"""Every authenticated attempt goes through `record_inbound_events` (engine 2b spec §8.3), which spends the endpoint's
and the tenant's rate budget, refuses or records all or nothing, and says what it did; its outcome is the response,
given only once its transaction has committed."""

import uuid
from typing import Any

from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.apps.ingress.batch import Batch

RECORD = text(
    "select record_inbound_events(:e, :refusal, :read, cast(:ids as uuid[]), cast(:sealed as bytea[]), "
    "cast(:versions as integer[]), cast(:dedupe as bytea[]), cast(:digests as bytea[]))"
)
UNKNOWN = "unknown"  # the endpoint or its tenant stopped serving since it was resolved: the caller's 401


async def record(
    sessions: async_sessionmaker[AsyncSession], endpoint_id: uuid.UUID, *, read: int, batch: Batch | None = None,
    refusal: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    """The function's outcome, committed. `refusal` (`too_large` or `malformed`) records nothing but pays."""
    given = batch or Batch([], [], [], [], [])
    params = {
        "e": endpoint_id, "refusal": refusal, "read": read, "ids": given.ids, "sealed": given.sealed,
        "versions": given.versions, "dedupe": given.dedupe, "digests": given.digests,
    }  # fmt: skip
    async with sessions() as s, s.begin():
        outcome: dict[str, Any] = (await s.execute(RECORD, params)).scalar_one()
    return dict(outcome)


def _error(status: int, code: str, retry_after: int | None = None) -> Response:
    headers = {"retry-after": str(retry_after)} if retry_after is not None else None
    return JSONResponse({"error": code}, status_code=status, headers=headers)


def respond(outcome: dict[str, Any]) -> Response:
    """The response for every outcome but `unknown`, whose 401 the caller gives (and counts)."""
    match outcome["outcome"]:
        case "recorded":
            return JSONResponse({"accepted": outcome["accepted"], "duplicates": outcome["duplicates"]})
        case "rate_limited":
            return _error(429, "rate_limited", retry_after=int(outcome["retry_after"]))
        case "too_large":
            return _error(413, "too_large")
        case "malformed":
            return _error(400, "malformed")
        case "event_id_reused":
            return _error(409, "event_id_reused")
        case "quota_exceeded":
            return _error(429, "quota_exceeded", retry_after=int(outcome["retry_after"]))
        case "retained_full":
            return _error(429, "retained_full")  # nothing frees it before 2b-4: no Retry-After
        case "environment":
            return _error(503, "unavailable")
    raise ValueError("an outcome the recording function doesn't give")
