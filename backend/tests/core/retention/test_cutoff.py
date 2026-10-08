# SPDX-License-Identifier: Apache-2.0
"""The cutoff's own judgments (engine 2b spec §10.1): a request that started follows its run's tree, and one with no run
to follow fails closed, past the cutoff, rather than being presumed retained (the owner's M2 review)."""

import pytest

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.retention import cutoff
from tests.core.retention.support import OLD, RECENT, request, run, tenant


@pytest.mark.parametrize(("ran", "kept"), [(None, False), (OLD, False), (RECENT, True), ("running", True)])
async def test_a_started_request_follows_its_run_and_fails_closed_without_one(
    owner_sessionmaker, api_sessionmaker, ran: object, kept: bool
) -> None:
    ctx = await tenant(owner_sessionmaker)
    rid = await request(owner_sessionmaker, ctx, "started", None)
    if ran is not None:
        await run(owner_sessionmaker, ctx, None if ran == "running" else ran, run_id=rid)  # type: ignore[arg-type]
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx["t"])
        found = await s.get(RunRequest, rid)
        assert found is not None
        assert await cutoff.request_kept(s, await cutoff.cutoff(s, ctx["t"]), found) is kept
