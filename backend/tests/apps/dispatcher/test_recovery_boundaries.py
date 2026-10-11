# SPDX-License-Identifier: Apache-2.0
"""The recovery's boundaries, interrupted (the owner's gate-B review of the recovery plan's tasks 3 to 5).

- The owed slot is reserved in the transaction that settles the late `started`: stopped between them, neither stays,
  and the next pass does both.
- Identification, and the late start, are retried on every sighting of the chain while they're owed, not only while
  the root's evidence has no run: a continued chain whose first lookup failed is identified (or terminated) later.
- A late start's record (identified, `late_start`, its audit entry) commits before the termination: a failed record
  terminates nothing, and a failed termination is retried on the next sighting, its audit entry written once."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import dispatch, evidence, reconcile
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import begin, reasons
from tests.apps.dispatcher.test_blocker_store import store
from tests.apps.dispatcher.test_blocker_transitions import _landed, _late_started
from tests.apps.dispatcher.test_reconcile import aged, once
from tests.apps.dispatcher.test_start_classification import _rechecked_long_ago, _state
from tests.apps.dispatcher.test_unresolved_requests import _audited, _slots, _spent_unresolved
from tests.core.erasure.test_fence import erasure_at

pytestmark = pytest.mark.usefixtures("development_deployment")
RETENTION = timedelta(days=1)
Outcome, Sent = dispatch.Outcome, dispatch.Sent


# --- the owed slot, atomic with its settlement ---------------------------------------------------------------------


async def test_an_interrupted_late_settlement_never_loses_the_owed_slot(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env, monkeypatch
) -> None:
    ctx, _, request = queued
    starting = await _spent_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    armed = [True]

    def interrupting(original: Any) -> Any:
        async def owed(*args: Any, **kwargs: Any) -> Any:
            if armed[0]:
                raise RuntimeError("stopped between the settlement and the owed slot")
            return await original(*args, **kwargs)

        return owed

    for module in (dispatch, reconcile):  # wherever the slot is reserved
        if hasattr(module, "_owed"):
            monkeypatch.setattr(module, "_owed", interrupting(module._owed))
    handle = await _landed(env, starting, starting.start_request_id)
    try:
        await aged(owner_sessionmaker, request.id)
        assert await once(dispatch_sessionmaker, env.client, api_settings) == {"error": 1}
        assert (await _state(owner_sessionmaker, request.id))["status"] == "starting"  # nothing of it committed
        assert await _slots(owner_sessionmaker, ctx.tenant_id) == []
        armed[0] = False
        await _rechecked_long_ago(owner_sessionmaker, request.id)
        async with owner_sessionmaker() as s, s.begin():  # its failure's wait, passed (D10: a minute after the first)
            await s.execute(text("update work_failures set due_at = now() where item_id = :i"), {"i": request.id})
        assert (await once(dispatch_sessionmaker, env.client, api_settings)).get("started") == 1
        assert (await _state(owner_sessionmaker, request.id))["status"] == "started"
        assert await _slots(owner_sessionmaker, ctx.tenant_id) == [request.id]
    finally:
        await handle.terminate()


# --- a continued chain, a fake Temporal ----------------------------------------------------------------------------


@dataclass
class Chain:
    """A root's chain as Temporal shows it: its first run continued as a second, live until terminated. Its identity
    lookups fail `lookup_failures` times first; its terminations, `terminate_failures` times."""

    lookup_failures: int = 0
    mismatches: int = 0  # lookups that show another request id first
    terminate_failures: int = 0
    live: bool = True
    terminated: list[str] = field(default_factory=list)

    def described(self, run_id: str | None) -> Any:
        info = SimpleNamespace(workflow_execution_info=SimpleNamespace(first_run_id="first"))
        if run_id is None:
            status = WorkflowExecutionStatus.RUNNING if self.live else WorkflowExecutionStatus.TERMINATED
            return SimpleNamespace(status=status, run_id="second", raw_description=info,
                                   close_time=None if self.live else datetime.now(UTC))  # fmt: skip
        return SimpleNamespace(status=WorkflowExecutionStatus.CONTINUED_AS_NEW, run_id="first", raw_description=info,
                               close_time=datetime.now(UTC) - timedelta(minutes=1))  # fmt: skip

    async def started_by(self, client: Any, workflow_id: str, request_id: Any) -> Any:
        if self.lookup_failures:
            self.lookup_failures -= 1
            raise RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
        if self.mismatches:
            self.mismatches -= 1
            return None
        return SimpleNamespace(execution=SimpleNamespace(run_id="first"))

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None,
                            first_execution_run_id: str | None = None, **_: Any) -> Any:  # fmt: skip
        chain = self

        class Handle:
            async def terminate(self, *args: Any, **kwargs: Any) -> None:
                if chain.terminate_failures:
                    chain.terminate_failures -= 1
                    raise RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
                assert first_execution_run_id == "first", "a termination names the chain's first run"
                chain.terminated.append(first_execution_run_id)
                chain.live = False

        return Handle()


def _faked(monkeypatch: Any, chain: Chain) -> None:
    async def described(client: Any, workflow_id: str, run_id: str | None) -> Any:
        return chain.described(run_id)

    monkeypatch.setattr(evidence, "_described", described)
    monkeypatch.setattr(dispatch, "started_by", chain.started_by)


async def _pass(dsm: Any, chain: Chain) -> dict[str, int]:
    return await evidence.check_evidence(dsm, chain, retention=RETENTION)  # type: ignore[arg-type]


async def _first_run_read(owner: Any, request: Any) -> None:
    """The root's evidence after its first visit resolved the chain's first run: that run read, the row due again."""
    async with owner() as s, s.begin():
        await s.execute(text("update execution_evidence set read_at = now(), next_check_at = now() "
                             "where workflow_id = :w"),
                        {"w": run_workflow_id(str(request.tenant_id), str(request.id))})  # fmt: skip


async def _due(owner: Any) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update execution_evidence set next_check_at = now()"))


async def test_a_continued_chains_identity_is_retried_after_a_failed_lookup(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None))
    chain = Chain(lookup_failures=1)
    _faked(monkeypatch, chain)
    await _pass(dispatch_sessionmaker, chain)  # resolves the chain's first run; its lookup failed
    assert (await store(owner_sessionmaker, request.id))[0] == ("unresolved", False, None)
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)  # the root's row now names its first run
    assert (await store(owner_sessionmaker, request.id))[0] == ("identified", False, "first")
    assert chain.terminated == []  # its request is still `starting`: no late start


async def test_a_continued_late_start_is_terminated_after_a_failed_lookup(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    _, _, request = queued
    await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    chain = Chain(lookup_failures=1)
    _faked(monkeypatch, chain)
    await _pass(dispatch_sessionmaker, chain)
    assert chain.terminated == [] and await _audited(owner_sessionmaker, request.id) == 0
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)
    assert chain.terminated == ["first"]
    assert await _audited(owner_sessionmaker, request.id) == 1
    assert "late_start" in await reasons(owner_sessionmaker, request.id)
    assert (await store(owner_sessionmaker, request.id))[0] == ("identified", False, "first")


# --- a late start's record before its termination ------------------------------------------------------------------


async def test_a_late_start_whose_record_fails_is_never_terminated_unrecorded(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    _, _, request = queued
    await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    chain = Chain()
    _faked(monkeypatch, chain)
    original = evidence.audit.record
    failing = [True]

    async def record(*args: Any, **kwargs: Any) -> Any:
        if failing[0]:
            failing[0] = False
            raise RuntimeError("the record's commit failed")
        return await original(*args, **kwargs)

    monkeypatch.setattr(evidence.audit, "record", record)
    assert (await _pass(dispatch_sessionmaker, chain)).get("failed") == 1
    assert chain.terminated == [] and chain.live  # nothing terminated without its record
    assert "late_start" not in await reasons(owner_sessionmaker, request.id)
    await _due(owner_sessionmaker)
    await _pass(dispatch_sessionmaker, chain)
    assert chain.terminated == ["first"]
    assert await _audited(owner_sessionmaker, request.id) == 1
    assert "late_start" in await reasons(owner_sessionmaker, request.id)


async def test_a_late_start_whose_termination_fails_is_recorded_then_terminated_once(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    _, _, request = queued
    await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    chain = Chain(terminate_failures=1)
    _faked(monkeypatch, chain)
    await _pass(dispatch_sessionmaker, chain)
    assert chain.terminated == [] and chain.live
    assert "late_start" in await reasons(owner_sessionmaker, request.id)  # recorded first
    assert await _audited(owner_sessionmaker, request.id) == 1
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)  # still live: terminated now
    assert chain.terminated == ["first"]
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)  # closed: never again
    assert chain.terminated == ["first"]
    assert await _audited(owner_sessionmaker, request.id) == 1  # its audit entry, once


# --- the record under the erasure's fence (the owner's second gate-B review) ----------------------------------------


async def _late_record(owner: Any, request_id: Any) -> tuple[Any, ...]:
    """The blocker's own late-start record (0055): unfenced, it outlives the erasure."""
    async with owner() as s:
        row = await s.execute(text("select late_start, late_start_at is not null from unresolved_sends "
                                   "where request_id = :r"), {"r": request_id})  # fmt: skip
        return tuple(row.one())


async def test_a_late_start_under_the_erasure_fence_is_recorded_on_its_blocker_and_audited_once(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """At stage 60 the fence refuses the `late_start` recovery item (the erasure removes it anyway). The record before
    the termination is the blocker's own, which the fence doesn't refuse; its audit entry is written once on it."""
    _, _, request = queued
    await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    await erasure_at(owner_sessionmaker, request.tenant_id, 60)  # picked while active, fenced since
    chain = Chain(terminate_failures=1)
    _faked(monkeypatch, chain)
    await _pass(dispatch_sessionmaker, chain)
    assert await _audited(owner_sessionmaker, request.id) == 1
    assert "late_start" not in await reasons(owner_sessionmaker, request.id)  # fenced
    assert chain.terminated == [] and chain.live
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)  # still live: terminated now, audited no more
    assert chain.terminated == ["first"]
    assert await _audited(owner_sessionmaker, request.id) == 1
    assert await _late_record(owner_sessionmaker, request.id) == ("matched", True)


async def _late_record_at(owner: Any, request_id: Any) -> tuple[Any, ...]:
    async with owner() as s:
        row = await s.execute(text("select late_start, late_start_at from unresolved_sends where request_id = :r"),
                              {"r": request_id})  # fmt: skip
        return tuple(row.one())


async def test_a_mismatch_shown_matched_later_is_promoted_keeping_its_record_and_dropping_its_obsolete_item(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """The owner's third gate-B review: `unmatched` then `matched` keeps the record's first time, and the obsolete
    `late_start_unmatched` item goes in the transaction that records the match; a failure there changes nothing."""
    _, _, request = queued
    await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    chain = Chain(mismatches=1)
    _faked(monkeypatch, chain)
    await _pass(dispatch_sessionmaker, chain)
    unmatched = await _late_record_at(owner_sessionmaker, request.id)
    assert unmatched[0] == "unmatched" and unmatched[1] is not None
    assert set(await reasons(owner_sessionmaker, request.id)) == {"late_start_unmatched"}
    original = evidence.audit.record
    failing = [True]

    async def record(*args: Any, **kwargs: Any) -> Any:
        if failing[0]:
            failing[0] = False
            raise RuntimeError("the promotion's commit failed")
        return await original(*args, **kwargs)

    monkeypatch.setattr(evidence.audit, "record", record)
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)  # matched now, its record's commit fails: nothing changed
    assert await _late_record_at(owner_sessionmaker, request.id) == unmatched
    assert set(await reasons(owner_sessionmaker, request.id)) == {"late_start_unmatched"}
    assert chain.terminated == []
    await _first_run_read(owner_sessionmaker, request)
    await _pass(dispatch_sessionmaker, chain)
    assert await _late_record_at(owner_sessionmaker, request.id) == ("matched", unmatched[1])  # its first time kept
    assert set(await reasons(owner_sessionmaker, request.id)) == {"late_start"}  # the obsolete item gone
    assert await _audited(owner_sessionmaker, request.id) == 1
    assert chain.terminated == ["first"]
