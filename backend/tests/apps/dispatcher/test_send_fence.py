# SPDX-License-Identifier: Apache-2.0
"""The fence against older dispatchers (2b-4b M4 recovery, task 3; the owner's ruling 2): from migration 0054 on, a
transaction that makes a request `starting`, or counts another of its sends, commits only with that send's intent
recorded in it (`start_sends`, its `intent_xid` the transaction's own). A dispatcher from before 0052 (status only) or
from before 0054 (`sends` counted, nothing recorded) can no longer commit its starting transaction, and both send only
after it. The dispatcher's own holds (`Held`: back to `starting`, nothing sent) say so in their transaction."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.engine.runtime.ids import run_workflow_id
from tests.support.starting import mark_starting

pytestmark = pytest.mark.usefixtures("development_deployment")
COUNTED = "update run_requests set status = 'starting', starting_at = now(), sends = sends + 1 where id = :i"


async def _intent(s: Any, request: Any, attempt: int) -> None:
    await s.execute(
        text("insert into unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, state) "
             "values (:r, :t, :w, gen_random_uuid(), 'pending') on conflict (request_id) do nothing"),
        {"r": request.id, "t": request.tenant_id, "w": run_workflow_id(str(request.tenant_id), str(request.id))},
    )  # fmt: skip
    await s.execute(text("insert into start_sends (request_id, attempt) values (:r, :n)"),
                    {"r": request.id, "n": attempt})  # fmt: skip


async def _status(owner: Any, request: Any) -> tuple[str, int]:
    async with owner() as s:
        row = (await s.execute(text("select status, sends from run_requests where id = :i"), {"i": request.id})).one()
        return row.status, row.sends


async def test_a_starting_transaction_without_its_intent_never_commits(queued, owner_sessionmaker) -> None:
    _, _, request = queued
    with pytest.raises(DBAPIError, match="run_requests_send_recorded"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(COUNTED), {"i": request.id})
    assert await _status(owner_sessionmaker, request) == ("queued", 0)


async def test_an_intent_recorded_by_another_transaction_doesnt_count(queued, owner_sessionmaker) -> None:
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await _intent(s, request, 1)
    with pytest.raises(DBAPIError, match="run_requests_send_recorded"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(COUNTED), {"i": request.id})
    assert await _status(owner_sessionmaker, request) == ("queued", 0)


async def test_a_starting_transaction_with_its_intent_commits(queued, owner_sessionmaker) -> None:
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        assert await mark_starting(s, request.id) == 1
    assert await _status(owner_sessionmaker, request) == ("starting", 1)
    async with owner_sessionmaker() as s, s.begin():  # another send counted while `starting`: its own intent
        await _intent(s, request, 2)
        await s.execute(text("update run_requests set sends = 2 where id = :i"), {"i": request.id})
    assert await _status(owner_sessionmaker, request) == ("starting", 2)


@pytest.mark.parametrize(
    "older",
    ["update run_requests set status = 'starting', starting_at = now() where id = :i",  # before 0052: status only
     "update run_requests set status = 'starting', starting_at = now(), sends = sends + 1, "
     "start_request_id = gen_random_uuid() where id = :i"],  # 0052's: counted, never recorded
    ids=["before 0052", "before 0054"],
)  # fmt: skip
async def test_an_older_dispatchers_starting_transaction_is_refused(
    queued, owner_sessionmaker, dispatch_sessionmaker, older: str
) -> None:
    _, _, request = queued
    for maker in (owner_sessionmaker, dispatch_sessionmaker):  # whoever runs it: the fence isn't a grant
        with pytest.raises(DBAPIError, match="run_requests_send_recorded"):
            async with maker() as s, s.begin():
                await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(request.tenant_id)})
                await s.execute(text(older), {"i": request.id})
    assert await _status(owner_sessionmaker, request) == ("queued", 0)


async def test_the_dispatchers_own_hold_commits_and_never_counts_a_send(queued, owner_sessionmaker) -> None:
    """`Held`: back to `starting` with nothing sent, said in its own transaction (`dewpoint.start_held`). Saying so
    never lets a send be counted unrecorded."""
    _, _, request = queued
    with pytest.raises(DBAPIError, match="run_requests_send_recorded"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("select set_config('dewpoint.start_held', 'on', true)"))
            await s.execute(text(COUNTED), {"i": request.id})
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("select set_config('dewpoint.start_held', 'on', true)"))
        await s.execute(text("update run_requests set status = 'starting', starting_at = now() where id = :i"),
                        {"i": request.id})  # fmt: skip
    assert await _status(owner_sessionmaker, request) == ("starting", 0)


async def test_the_api_reads_neither_table(api_sessionmaker) -> None:
    for table in ("unresolved_sends", "start_sends"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with api_sessionmaker() as s:
                await s.execute(text(f"select 1 from {table} limit 1"))  # noqa: S608
