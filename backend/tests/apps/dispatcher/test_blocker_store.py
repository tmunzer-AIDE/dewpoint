# SPDX-License-Identifier: Apache-2.0
"""Each counted send, and its own answer (2b-4b M4 recovery, task 3; the owner's rulings 1, 3, 8 and 9).

The starting transaction records the send's intent (`start_sends`, its attempt the request's `sends`) and its request's
blocker (`unresolved_sends`, `pending` on the first) before the call. Only the call's own direct result closes its own
row, once (`Sent`, built by the dispatcher alone): never `verify()`, a sighting, or the reconciler's settlement. The
blocker goes only on a clean start (ruling 1): every intent answered by its own call, none uncertain, and the request
settled `started` on a send whose own answer is `started`, or settled without starting on answers that all created
nothing. A late answer closes its own row and nothing else (ruling 8); a late `started` leaves its blocker
`unresolved`, never `identified` from the reply alone."""

import ast
import uuid
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.codec import data_converter
from dewpoint.apps.dispatcher import dispatch
from tests.apps.dispatcher.support import BUILD, begin
from tests.apps.test_admission import KEYS

pytestmark = pytest.mark.usefixtures("development_deployment")
SRC = Path(__file__).resolve().parents[3] / "src"
Outcome, Sent = dispatch.Outcome, dispatch.Sent


async def store(owner: Any, request_id: uuid.UUID) -> tuple[tuple[Any, ...] | None, list[tuple[Any, ...]]]:
    """The request's blocker (state, legacy, identified run) and its sends (attempt, answer, run, answered)."""
    async with owner() as s:
        blocker = (await s.execute(text("select state, legacy_unknown, identified_run_id from unresolved_sends "
                                        "where request_id = :r"), {"r": request_id})).first()  # fmt: skip
        sends = await s.execute(text("select attempt, answer, run_id, answered_at is not null from start_sends "
                                     "where request_id = :r order by attempt"), {"r": request_id})  # fmt: skip
        return (tuple(blocker) if blocker else None), [tuple(row) for row in sends]


async def request_row(owner: Any, request_id: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        row = (await s.execute(text("select status, reason, ended_at, attempts, sends from run_requests where id = :i"),
                               {"i": request_id})).one()  # fmt: skip
        run = (await s.execute(text("select status, ended_at, error_code from runs where id = :i"),
                               {"i": request_id})).first()  # fmt: skip
        return (*row, *(run or ()))


async def requeued(dsm: Any, request: Any) -> None:
    """Back in the queue as the reconciler's trustworthy absence puts it (no send of its own answered)."""
    assert await dispatch.settle(dsm, dispatch.Ref(request.id, request.tenant_id), Outcome("absent"),
                                 audited=True) == "absent"  # fmt: skip


def _seal() -> Any:
    return dispatch.sealer(data_converter(KEYS), "default")


# --- the intent, and the answer ------------------------------------------------------------------------------------


async def test_the_intent_is_recorded_before_the_call_and_a_clean_start_removes_it(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """Ruling 1: an intent open while its call is in flight, then answered `started` and settled `started` in the same
    transaction: removed. Being briefly open isn't uncertainty."""
    _, _, request = queued
    during: list[Any] = []

    async def start(client: Any, starting: Any, *, reasons: bool = False) -> dispatch.Outcome:
        during.append((starting.attempt, await store(owner_sessionmaker, starting.request_id)))
        return Outcome("started", answer="started", run_id="run-1")

    monkeypatch.setattr(dispatch, "start", start)
    happened = await dispatch._dispatch(dispatch_sessionmaker, object(), _seal(), KEYS, api_settings, BUILD,  # type: ignore[arg-type]
                                        request.tenant_id, request.id)  # fmt: skip
    assert happened == "started"
    assert during == [(1, (("pending", False, None), [(1, None, None, False)]))]
    assert await store(owner_sessionmaker, request.id) == (None, [])


async def test_a_calls_answer_closes_only_its_own_row_and_only_once(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None)) == (
        "uncertain")  # fmt: skip
    await requeued(dispatch_sessionmaker, request)
    second = await begin(dispatch_sessionmaker, request, api_settings)
    assert second.attempt == 2  # never a number reused
    assert await dispatch.settle(dispatch_sessionmaker, second, Outcome("refused", answer="refused"),
                                 sent=Sent(2, "refused", None)) == "refused"  # fmt: skip
    expected = [(1, None, None, False), (2, "refused", None, True)]
    assert (await store(owner_sessionmaker, request.id))[1] == expected
    with structlog.testing.capture_logs() as logs:
        again = await dispatch.settle(dispatch_sessionmaker, second, Outcome("started", answer="started", run_id="r"),
                                      sent=Sent(2, "started", "r"))  # fmt: skip
    assert again == "moved"
    assert (await store(owner_sessionmaker, request.id))[1] == expected  # answered once: never again
    assert [e["event"] for e in logs if e["event"] == "start_send_unmatched"] == ["start_send_unmatched"]


async def test_started_records_the_calls_first_run_and_an_earlier_uncertainty_keeps_the_blocker(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None))
    await requeued(dispatch_sessionmaker, request)
    second = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, second, Outcome("started", answer="started", run_id="run-2"),
                                 sent=Sent(2, "started", "run-2")) == "started"  # fmt: skip
    assert await store(owner_sessionmaker, request.id) == (
        ("unresolved", False, None), [(1, None, None, False), (2, "started", "run-2", True)])  # fmt: skip


@pytest.mark.parametrize(("found", "settled"), [("started", "started"), ("uncertain", "uncertain"),
                                                 ("collision", "dead")])  # fmt: skip
async def test_already_started_is_the_calls_own_answer_whatever_verify_found(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, found: str, settled: str
) -> None:
    """Ruling 3: the call's answer is `already_started`, recorded as such; what `verify()` found is apart, in the
    request's settlement. With no own `started`, the blocker is kept, `unresolved`."""
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    outcome = Outcome(found, answer="already_started")
    assert await dispatch.settle(dispatch_sessionmaker, first, outcome, sent=Sent(1, "already_started", None)) == (
        settled)  # fmt: skip
    assert await store(owner_sessionmaker, request.id) == (
        ("unresolved", False, None), [(1, "already_started", None, True)])  # fmt: skip


async def test_an_uncertain_call_leaves_its_row_open_and_the_blocker_unresolved(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None)) == (
        "uncertain")  # fmt: skip
    assert await store(owner_sessionmaker, request.id) == (("unresolved", False, None), [(1, None, None, False)])


async def test_a_crash_before_settling_leaves_the_intent_open_and_the_next_send_is_numbered_on(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """Ruling 1: an attempt left unanswered by a crash keeps the blocker, whatever its later sends answer."""
    _, _, request = queued

    async def crash(request_id: uuid.UUID) -> None:
        raise RuntimeError("crashed between the commit and the send")

    monkeypatch.setattr(dispatch, "_after_starting_commit", crash)
    with pytest.raises(RuntimeError, match="crashed"):
        await dispatch._dispatch(dispatch_sessionmaker, object(), _seal(), KEYS, api_settings, BUILD,  # type: ignore[arg-type]
                                 request.tenant_id, request.id)  # fmt: skip
    blocker, sends = await store(owner_sessionmaker, request.id)
    assert sends == [(1, None, None, False)] and blocker is not None
    await requeued(dispatch_sessionmaker, request)  # restarted: the reconciler's absence puts it back
    second = await begin(dispatch_sessionmaker, request, api_settings)
    assert second.attempt == 2
    assert await dispatch.settle(dispatch_sessionmaker, second, Outcome("started", answer="started", run_id="run-2"),
                                 sent=Sent(2, "started", "run-2")) == "started"  # fmt: skip
    blocker, sends = await store(owner_sessionmaker, request.id)
    assert blocker is not None and sends == [(1, None, None, False), (2, "started", "run-2", True)]


NOTHING = [(dispatch.MAX_ATTEMPTS - 1, "refused", "dead"), (0, "throttled", "throttled"), (0, "refused", "refused")]


@pytest.mark.parametrize(("attempts", "kind", "settled"), NOTHING)
async def test_a_request_whose_every_answer_created_nothing_settles_without_its_blocker(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, attempts: int, kind: str, settled: str
) -> None:
    """Ruling 1: refused for good, or back in the queue, every answer certain that nothing was created: removed."""
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set attempts = :n where id = :i"), {"n": attempts, "i": request.id})
    first = await begin(dispatch_sessionmaker, request, api_settings)
    outcome = Outcome(kind, answer=kind)
    assert await dispatch.settle(dispatch_sessionmaker, first, outcome, sent=Sent(1, kind, None)) == settled
    assert await store(owner_sessionmaker, request.id) == (None, [])


# --- ruling 9: only a direct send result ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["started", "refused", "collision"])
async def test_a_reconcilers_settlement_never_answers_a_send_nor_removes_a_blocker(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch, kind: str
) -> None:
    """Its `Outcome("absent")` through a `Ref` (reconcile.py's NOT_FOUND), and its describe-based settlement, whatever
    the outcome: no `start_sends` row written, no blocker removed."""
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)  # a crash left it unanswered
    await requeued(dispatch_sessionmaker, request)
    blocker, sends = await store(owner_sessionmaker, request.id)
    assert blocker is not None and sends == [(1, None, None, False)]
    second = await begin(dispatch_sessionmaker, request, api_settings)
    described = dispatch.Starting(second.request_id, second.tenant_id, second.start, second.start_request_id)
    await dispatch.settle(dispatch_sessionmaker, described, Outcome(kind, answer=kind), audited=True)
    blocker, sends = await store(owner_sessionmaker, request.id)
    assert blocker is not None and sends == [(1, None, None, False), (2, None, None, False)]
    assert first.attempt == 1


def test_a_send_result_is_built_only_by_the_dispatchers_own_send_path() -> None:
    built: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                called = node.func if isinstance(node, ast.Call) else None
                name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
                if name == "Sent":
                    built.append((str(path.relative_to(SRC)), function.name))
    assert built == [("dewpoint/apps/dispatcher/dispatch.py", "_dispatch")]


def test_nothing_sends_a_start_outside_the_store() -> None:
    """`apps.runs.start_run` sends outside the store (2a's admission): nothing under src calls or imports it."""
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "dewpoint.apps.runs":
                found += [f"{path.name}: imports {a.name}" for a in node.names if a.name == "start_run"]
            if isinstance(node, ast.Attribute) and node.attr == "start_run" and isinstance(node.value, ast.Name) and (
                    node.value.id == "runs"):  # fmt: skip
                found.append(f"{path.name}: runs.start_run")
    assert found == []


# --- ruling 8: a late answer ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("moved", ["cancelled", "dead"])
async def test_a_late_answer_closes_only_its_own_row(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, moved: str
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    async with owner_sessionmaker() as s, s.begin():  # it moved on while its call was in flight
        await s.execute(text("update run_requests set status = :st, reason = 'test', ended_at = now() where id = :i"),
                        {"st": moved, "i": request.id})  # fmt: skip
    before = await request_row(owner_sessionmaker, request.id)
    assert await dispatch.settle(dispatch_sessionmaker, first, Outcome("refused", answer="refused"),
                                 sent=Sent(1, "refused", None)) == "moved"  # fmt: skip
    assert await request_row(owner_sessionmaker, request.id) == before
    assert await store(owner_sessionmaker, request.id) == (("pending", False, None), [(1, "refused", None, True)])


async def test_a_late_started_reply_records_its_run_and_leaves_the_blocker_unresolved(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Ruling 8: a late `started` isn't yet an identified execution. Its run id is kept on its own row; a `pending`
    blocker becomes `unresolved`, neither `identified` nor removed (`core.blockers.identified`, task 4, alone does)."""
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set status = 'cancelled', reason = 'test', ended_at = now() "
                             "where id = :i"), {"i": request.id})  # fmt: skip
    before = await request_row(owner_sessionmaker, request.id)
    assert await dispatch.settle(dispatch_sessionmaker, first, Outcome("started", answer="started", run_id="late"),
                                 sent=Sent(1, "started", "late")) == "moved"  # fmt: skip
    assert await request_row(owner_sessionmaker, request.id) == before
    assert await store(owner_sessionmaker, request.id) == (("unresolved", False, None), [(1, "started", "late", True)])


# --- ruling 2: a legacy-unknown blocker ----------------------------------------------------------------------------


async def test_a_legacy_unknown_blocker_is_never_removed(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """The backfill's (`tests/migrations/test_0054.py`): attempts from before 0054, none recorded. A later recorded send
    adds its own row beside the flag, and even a clean `started` removes nothing."""
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text("insert into unresolved_sends (request_id, tenant_id, workflow_id, legacy_unknown, state) "
                 "values (:r, :t, :w, true, 'unresolved')"),
            {"r": request.id, "t": request.tenant_id, "w": f"t:{request.tenant_id}:run:{request.id}"},
        )  # fmt: skip
    first = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, first, Outcome("started", answer="started", run_id="run-1"),
                                 sent=Sent(1, "started", "run-1")) == "started"  # fmt: skip
    assert await store(owner_sessionmaker, request.id) == (("unresolved", True, None), [(1, "started", "run-1", True)])
