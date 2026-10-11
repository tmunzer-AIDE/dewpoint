# SPDX-License-Identifier: Apache-2.0
"""The blocker store's transitions (2b-4b M4 recovery, migration 0054; the owner's rulings 1, 2, 8 and 9), shared by
the dispatcher and the erasure.

A request's blocker (`unresolved_sends`) is written with its first counted send, `pending`, and each send's intent
(`start_sends`) in the transaction that counts it, before the call. Only that call's own direct result answers its row,
once. A blocker never moves back: `pending` becomes `unresolved` once any attempt became uncertain, and stays. It's
removed only on a clean start (`removable`, ruling 1); a legacy-unknown one (the backfill's) never is."""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit

# Answers that certainly created nothing: a request settled without starting on these alone has nothing to block
CREATED_NOTHING = ("refused", "throttled", "not_permitted", "check_unavailable")


async def intend(s: AsyncSession, request_id: uuid.UUID, tenant_id: uuid.UUID, workflow_id: str,
                 start_request_id: uuid.UUID, attempt: int) -> None:  # fmt: skip
    """A send's intent, in the transaction that counts it (`attempt`, the request's `sends`): its blocker `pending` on
    the first, as it is on any later one (a legacy-unknown one keeps its flag; its recorded id is kept, or set)."""
    await s.execute(
        text("insert into unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, state) "
             "values (:r, :t, :w, :s, 'pending') on conflict (request_id) do update "
             "set start_request_id = coalesce(unresolved_sends.start_request_id, excluded.start_request_id)"),
        {"r": request_id, "t": tenant_id, "w": workflow_id, "s": start_request_id},
    )  # fmt: skip
    await s.execute(
        text("insert into start_sends (request_id, attempt) values (:r, :n)"), {"r": request_id, "n": attempt}
    )


async def answered(
    s: AsyncSession, request_id: uuid.UUID, attempt: int, answer: str | None, run_id: str | None
) -> bool:
    """A send's own call's direct answer, on its own row, once: whether its row was open. An uncertain call
    (`answer` None) leaves it open."""
    if answer is None:
        found = await s.execute(text("select 1 from start_sends where request_id = :r and attempt = :n "
                                     "and answer is null"), {"r": request_id, "n": attempt})  # fmt: skip
        return found.first() is not None
    done = await s.execute(
        text("update start_sends set answer = :a, run_id = :run, answered_at = statement_timestamp() "
             "where request_id = :r and attempt = :n and answer is null returning attempt"),
        {"a": answer, "run": run_id, "r": request_id, "n": attempt},
    )  # fmt: skip
    return done.first() is not None


async def unresolved(s: AsyncSession, request_id: uuid.UUID) -> None:
    """An attempt became uncertain (an uncertain result, a collision, `already_started` with no own `started`, an
    absence then requeue, a late `started`): a `pending` blocker becomes `unresolved`, for good."""
    await s.execute(text("update unresolved_sends set state = 'unresolved', changed_at = statement_timestamp() "
                         "where request_id = :r and state = 'pending'"), {"r": request_id})  # fmt: skip


async def removable(s: AsyncSession, request_id: uuid.UUID, settling_started: bool) -> bool:
    """Ruling 1, exactly. Removed only when: its blocker never left `pending` (no attempt ever became uncertain) and
    isn't legacy-unknown; every intent was answered by its own call; and either the request is being settled `started`
    in this transaction on a send whose own answer is `started` (every other answer having created nothing), or it
    settles without starting on answers that all created nothing."""
    row = (
        await s.execute(
            text(
                "select b.state, b.legacy_unknown, count(x.attempt) filter (where x.answer is null) as open, "
                "count(x.attempt) filter (where x.answer = 'started') as started, "
                "count(x.attempt) filter (where x.answer is not null and not x.answer = any(:nothing)) as other "
                "from unresolved_sends b left join start_sends x on x.request_id = b.request_id "
                "where b.request_id = :r group by b.state, b.legacy_unknown"
            ),
            {"r": request_id, "nothing": list(CREATED_NOTHING)},
        )  # fmt: skip
    ).first()
    if row is None or row.state != "pending" or row.legacy_unknown or row.open:
        return False
    if settling_started:
        return bool(row.started == 1 and row.other == 1)  # its one `started` is the only answer that created anything
    return bool(row.other == 0)


async def remove(s: AsyncSession, request_id: uuid.UUID) -> None:
    """The blocker and its sends, gone: only where `removable` said so, in the same transaction."""
    await s.execute(text("delete from unresolved_sends where request_id = :r"), {"r": request_id})


async def identified(s: AsyncSession, request_id: uuid.UUID, run_id: str) -> None:
    """The execution its sends created, identified: the recorded start request id is on the chain's first run's started
    event (`dispatch.started_by`; called only behind that check). Never touches a send's row."""
    await s.execute(
        text("update unresolved_sends set state = 'identified', identified_run_id = :run, "
             "changed_at = statement_timestamp() where request_id = :r and state in ('pending', 'unresolved')"),
        {"r": request_id, "run": run_id},
    )  # fmt: skip


async def gone(s: AsyncSession, request_id: uuid.UUID) -> bool:
    """The blocker and its sends deleted, only when `identified`, no send open and not legacy-unknown (the erasure's,
    once its execution is shown gone): whether it was. Its record is audited first, in this transaction: the identified
    run, the recorded start request id and the late start's record (0055), which nothing else keeps (the owner's
    gate-B condition on task 13)."""
    found = await s.execute(
        text("select b.tenant_id, b.start_request_id, b.identified_run_id, b.late_start, b.late_start_at "
             "from unresolved_sends b where b.request_id = :r and b.state = 'identified' and not b.legacy_unknown "
             "and not exists (select 1 from start_sends x where x.request_id = b.request_id and x.answer is null) "
             "for update of b"),
        {"r": request_id},
    )  # fmt: skip
    row = found.first()
    if row is None:
        return False
    await _removed(s, request_id, row, "run.request.start_gone")
    return True


async def _removed(s: AsyncSession, request_id: uuid.UUID, row: Any, action: str) -> None:
    """The blocker and its sends deleted, its record audited first in this transaction (`row`: its tenant, recorded
    start request id, identified run and late start)."""
    late_at = row.late_start_at.isoformat() if row.late_start_at is not None else None
    start_request_id = str(row.start_request_id) if row.start_request_id is not None else None
    await audit.record(s, tenant_id=row.tenant_id, actor_id=None, action=action, target_type="run_request",
                       target_id=str(request_id),
                       details={"run_id": row.identified_run_id, "start_request_id": start_request_id,
                                "late_start": row.late_start, "late_start_at": late_at})  # fmt: skip
    await s.execute(text("delete from unresolved_sends where request_id = :r"), {"r": request_id})


async def late_settled(s: AsyncSession, request_id: uuid.UUID) -> str | None:
    """A blocker's transition on answers that came in late, each its own send's (design revision 7 §3), applied by the
    erasure's recheck inside a resolution (its erasure row locked first). Once no send is open:
    - `deleted_open` (its identified run already deleted and read back): `gone` when no answer names another run;
      `identified` again, with the one other run an answer names (that run is the erasure's to handle);
    - `pending` or `unresolved`: `removed` when every answer certainly created nothing (`CREATED_NOTHING`).
    Each removal audited first, as `gone` is. None: nothing to apply (a send still open, a legacy-unknown blocker,
    ruling 1, more than one other run named, or anything else)."""
    found = await s.execute(
        text("select tenant_id, state, legacy_unknown, identified_run_id, start_request_id, late_start, "
             "late_start_at from unresolved_sends where request_id = :r for update"),
        {"r": request_id},
    )  # fmt: skip
    row = found.first()
    if row is None or row.legacy_unknown:
        return None
    answers = (await s.execute(text("select answer, run_id from start_sends where request_id = :r"),
                               {"r": request_id})).all()  # fmt: skip
    if not answers or any(a.answer is None for a in answers):
        return None
    if row.state == "deleted_open":
        others = {a.run_id for a in answers if a.answer == "started" and a.run_id != row.identified_run_id}
        if len(others) > 1:
            return None
        if others:
            await s.execute(text("update unresolved_sends set state = 'identified', identified_run_id = :run, "
                                 "changed_at = statement_timestamp() where request_id = :r"),
                            {"r": request_id, "run": others.pop()})  # fmt: skip
            return "identified"
        await _removed(s, request_id, row, "run.request.start_gone")
        return "gone"
    if row.state in ("pending", "unresolved") and all(a.answer in CREATED_NOTHING for a in answers):
        await _removed(s, request_id, row, "run.request.start_removed")
        return "removed"
    return None


async def deleted_open(s: AsyncSession, request_id: uuid.UUID) -> None:
    """An identified execution the erasure deleted while a send is still open: kept, `deleted_open`. Only with a send
    open: a legacy-unknown one with none open stays `identified` (never removed; an operator's abandonment)."""
    await s.execute(text("update unresolved_sends b set state = 'deleted_open', changed_at = statement_timestamp() "
                         "where b.request_id = :r and b.state = 'identified' and exists (select 1 from start_sends x "
                         "where x.request_id = b.request_id and x.answer is null)"), {"r": request_id})  # fmt: skip


async def of_root(s: AsyncSession, workflow_id: str) -> tuple[uuid.UUID, uuid.UUID | None, str] | None:
    """A root's blocker, by its workflow id: (request, recorded start request id, state); None: it has none."""
    found = await s.execute(
        text("select request_id, start_request_id, state from unresolved_sends where workflow_id = :w"),
        {"w": workflow_id},
    )
    row = found.first()
    return (row.request_id, row.start_request_id, row.state) if row is not None else None


async def late_started(s: AsyncSession, request_id: uuid.UUID, *, matched: bool) -> str | None:
    """A live execution of an ended request, recorded on its blocker (0055: unfenced, it outlives the erasure, which
    refuses the recovery item from stage 60): `matched`, or `unmatched` (its first run carries another id). Written
    once; an `unmatched` one becomes `matched` should a match be shown later, its first time kept (the owner's third
    gate-B review). What changed: `recorded`, `promoted` (that later match), or None. The caller audits and alerts
    only on a change and, on a promotion, clears the obsolete `late_start_unmatched` item, in this transaction."""
    before = (await s.execute(text("select late_start from unresolved_sends where request_id = :r for update"),
                              {"r": request_id})).first()  # fmt: skip
    if before is None or before.late_start == "matched" or (before.late_start == "unmatched" and not matched):
        return None
    await s.execute(text("update unresolved_sends set late_start = :m, "
                         "late_start_at = coalesce(late_start_at, statement_timestamp()) where request_id = :r"),
                    {"r": request_id, "m": "matched" if matched else "unmatched"})  # fmt: skip
    return "recorded" if before.late_start is None else "promoted"
