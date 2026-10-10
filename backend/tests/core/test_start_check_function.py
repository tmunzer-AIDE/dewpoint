# SPDX-License-Identifier: Apache-2.0
"""The database's start check (0052, the 2b-4b M4 start-check slice): `start_permitted(workflow_id, request_id)`, which
D12's authorizer asks before it lets a root run start on the engine queue. True only for an eligible dispatcher
request, matched by its workflow id and its recorded start request id; false for anything else, malformed input
included, never an error. Run as a LOGIN member of `dewpoint_start_check`, the authorizer's role, which may run the
function and read nothing."""

import asyncio
import secrets
import time
import uuid
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from tests.apps.test_admission import admit, ready  # noqa: F401 - `ready`: the fixture
from tests.conftest import _url_for

pytestmark = pytest.mark.usefixtures("development_deployment")  # admission needs a recorded environment
CHECK = "SELECT start_permitted($1, $2)"
TERMINAL = ("cancelled", "refused", "dead")  # 0017's: only these have an `ended_at`
WAIT_S = 10.0


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _as(pg_url: str, role: str | None) -> asyncpg.Connection:
    return await asyncpg.connect(_dsn(_url_for(pg_url, role) if role else pg_url))


async def _check(pg_url: str, workflow_id: str | None, request_id: str | None) -> Any:
    c = await _as(pg_url, "dewpoint_start_check")
    try:
        return await c.fetchval(CHECK, workflow_id, request_id)
    finally:
        await c.close()


async def starting(owner: Any, api: Any, ready: Any, *, status: str = "starting", sends: int = 1,  # noqa: F811
                   evidence: bool = True, cancelled: bool = False) -> tuple[str, str, uuid.UUID]:  # fmt: skip
    """A request the dispatcher is starting: admitted, then moved to `status`, with its start request id recorded,
    `sends` counted and its root evidence written. Its workflow id, its start request id and its id. The table's own
    checks hold: `starting` has its `starting_at`, and only a terminal status (`cancelled`, `refused`, `dead`) has its
    `ended_at`, so a `starting` request is never ended."""
    ctx, wf = ready
    request = (await admit(api, ctx, wf, key=str(uuid.uuid4()))).request
    start_request_id = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("UPDATE run_requests SET status = :status, sends = :sends, start_request_id = :rid, "
                 "starting_at = now(), cancel_requested_at = CASE WHEN :cancelled THEN now() END, "
                 "ended_at = CASE WHEN :ended THEN now() END WHERE id = :id"),
            {"status": status, "sends": sends, "rid": start_request_id, "cancelled": cancelled,
             "ended": status in TERMINAL, "id": request.id},
        )  # fmt: skip
        workflow_id = f"t:{ctx.tenant_id}:run:{request.id}"
        if evidence:
            await s.execute(
                text("INSERT INTO execution_evidence (tenant_id, workflow_id, started_at) VALUES (:t, :w, now())"),
                {"t": ctx.tenant_id, "w": workflow_id},
            )
    return workflow_id, str(start_request_id), request.id


async def test_an_eligible_request_matched_by_both_ids_is_permitted(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
) -> None:
    workflow_id, request_id, _ = await starting(owner_sessionmaker, api_sessionmaker, ready)
    assert await _check(pg_url, workflow_id, request_id) is True


@pytest.mark.parametrize(
    "case",
    [
        {"status": "queued"}, {"status": "started"}, {"status": "cancelled"}, {"status": "dead"},
        {"cancelled": True}, {"sends": 0}, {"sends": 11}, {"evidence": False},
    ],
    ids=lambda c: "-".join(f"{k}={v}" for k, v in c.items()),
)  # fmt: skip
async def test_an_ineligible_request_is_refused(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
    case,
) -> None:
    workflow_id, request_id, _ = await starting(owner_sessionmaker, api_sessionmaker, ready, **case)
    assert await _check(pg_url, workflow_id, request_id) is False


async def test_another_start_request_id_an_unknown_request_and_a_fenced_tenant_are_refused(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
) -> None:
    ctx, _ = ready
    workflow_id, request_id, _ = await starting(owner_sessionmaker, api_sessionmaker, ready)
    assert await _check(pg_url, workflow_id, str(uuid.uuid4())) is False
    assert await _check(pg_url, f"t:{ctx.tenant_id}:run:{uuid.uuid4()}", request_id) is False
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("INSERT INTO tenant_erasures (tenant_id, requested_by, fenced_at) VALUES (:t, :u, now())"),
                        {"t": ctx.tenant_id, "u": ctx.user.id})  # fmt: skip
    assert await _check(pg_url, workflow_id, request_id) is False


async def test_a_workflow_id_that_isnt_exactly_a_root_runs_is_refused(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
) -> None:
    workflow_id, request_id, _ = await starting(owner_sessionmaker, api_sessionmaker, ready)
    _, tenant, _, run = workflow_id.split(":")
    for other in (f"{workflow_id}/{uuid.uuid4()}/k/batch:0", f"{workflow_id}x", f"{workflow_id}\n", f" {workflow_id}",
                  workflow_id.upper(), workflow_id.replace(":run:", ":sched:"),
                  f"t:{tenant.upper()}:run:{run}", f"t:{tenant}:run:{run.upper()}"):  # fmt: skip  # upper case: never
        assert await _check(pg_url, other, request_id) is False, other
    for other in (request_id.upper(), f"{request_id}\n", f"{{{request_id}}}", request_id.replace("-", ""), "", None):
        assert await _check(pg_url, workflow_id, other) is False, other
    assert await _check(pg_url, None, request_id) is False


def _malformed(u: str) -> list[str]:
    """36 characters each, none a canonical UUID: what a `[0-9a-f-]{36}` pattern, or PostgreSQL's lenient uuid input,
    would let through."""
    hexed = u.replace("-", "")
    shifted = u[:7] + "-" + u[7] + u[9:]  # a hyphen moved one place left
    cases = ["-" * 36, shifted, u[:-1] + "g", "{" + hexed + "ab" + "}", hexed + "abcd"]
    assert all(len(c) == 36 and c != u for c in cases)
    return cases


async def test_malformed_36_character_values_are_refused_in_every_position_and_none_raises(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
) -> None:
    workflow_id, request_id, _ = await starting(owner_sessionmaker, api_sessionmaker, ready)
    _, tenant, _, run = workflow_id.split(":")
    for bad in _malformed(tenant):
        assert await _check(pg_url, f"t:{bad}:run:{run}", request_id) is False, bad
    for bad in _malformed(run):
        assert await _check(pg_url, f"t:{tenant}:run:{bad}", request_id) is False, bad
    for bad in _malformed(request_id):
        assert await _check(pg_url, workflow_id, bad) is False, bad


async def test_the_role_runs_the_function_and_reads_nothing_and_no_other_role_runs_it(pg_url) -> None:
    checker = await _as(pg_url, "dewpoint_start_check")
    try:
        assert await checker.fetchval(CHECK, f"t:{uuid.uuid4()}:run:{uuid.uuid4()}", str(uuid.uuid4())) is False
        for table in ("run_requests", "execution_evidence", "tenant_erasures", "runs"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await checker.fetchval(f"SELECT 1 FROM {table} LIMIT 1")  # noqa: S608 - fixed names
    finally:
        await checker.close()
    for role in ("dewpoint_api", "dewpoint_dispatch", "dewpoint_worker"):
        other = await _as(pg_url, role)
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await other.fetchval(CHECK, f"t:{uuid.uuid4()}:run:{uuid.uuid4()}", str(uuid.uuid4()))
        finally:
            await other.close()


async def _waiting_on_advisory(watcher: asyncpg.Connection, pid: int) -> bool:
    until = time.monotonic() + WAIT_S
    while time.monotonic() < until:
        if await watcher.fetchval("SELECT count(*) FROM pg_locks WHERE pid = $1 AND locktype = 'advisory' "
                                  "AND NOT granted", pid):  # fmt: skip
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.parametrize("cancelled", [True, False], ids=["a cancel committed meanwhile", "no cancel"])
async def test_the_check_reads_what_is_committed_when_it_runs_not_when_its_statement_began(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
    cancelled,
) -> None:
    """The authorizer's statement takes its snapshot first, then waits on an advisory lock the test holds; only once
    it's seen waiting does the test commit a cancel, then release the lock. A function that read the statement's
    snapshot (STABLE) would still find the request eligible; the check must find it cancelled."""
    workflow_id, request_id, request = await starting(owner_sessionmaker, api_sessionmaker, ready)
    key = secrets.randbelow(2**62) + 1
    holder, checker = await _as(pg_url, None), await _as(pg_url, "dewpoint_start_check")
    try:
        await holder.execute("SELECT pg_advisory_lock($1)", key)
        pid = await checker.fetchval("SELECT pg_backend_pid()")
        checked = asyncio.create_task(checker.fetchval(
            "WITH w AS MATERIALIZED (SELECT pg_advisory_lock($3)) SELECT start_permitted($1, $2) FROM w",
            workflow_id, request_id, key,
        ))  # fmt: skip
        assert await _waiting_on_advisory(holder, pid), "the check's statement never reached the lock's wait"
        assert not checked.done()
        if cancelled:
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text("UPDATE run_requests SET cancel_requested_at = now() WHERE id = :id"),
                                {"id": request})  # fmt: skip
        await holder.execute("SELECT pg_advisory_unlock($1)", key)
        assert await asyncio.wait_for(checked, WAIT_S) is (not cancelled)
    finally:
        await holder.close()
        await checker.close()
