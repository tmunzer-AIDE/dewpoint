# SPDX-License-Identifier: Apache-2.0
"""Rows for retention's tests, written as the table owner: run trees with their claims and requests, requests that
never started, uploads and schedules, aged by when they ended."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from tests.support.workflows import seed_workflow

OLD, RECENT = timedelta(days=2), timedelta(hours=1)  # against a retention of 1 day
CIPHER = b"\x01" * 16


async def sql(owner: Any, statement: str, **params: Any) -> None:
    async with owner() as s, s.begin():
        await s.execute(text(statement), params)


async def count(owner: Any, statement: str, **params: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text(statement), params)).scalar_one())


async def tenant(owner: Any, days: int | None = 1, tenant_id: uuid.UUID | None = None) -> dict[str, Any]:
    """A tenant (or `tenant_id`'s) with a published workflow, its retention `days` (or the default)."""
    t, w, v = await seed_workflow(owner, tenant_id=tenant_id)
    if days is not None:
        await sql(owner, "insert into tenant_retention (tenant_id, runs_days) values (:t, :d)", t=t, d=days)
    async with owner() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    return {"t": t, "w": w, "v": v, "u": user}


async def _claim(owner: Any, table: str, ctx: dict[str, Any], owner_run: uuid.UUID, root: uuid.UUID,
                 role: str = "claim") -> uuid.UUID:  # fmt: skip
    claim = uuid.uuid4()
    pointer = "'/x'" if role == "claim" else "null"  # an envelope is no claim: it has none
    extra = ("role, pointer", f":role, {pointer}") if table == "run_inputs" else ("kind", "'output'")
    await sql(owner, f"insert into {table} (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, "  # noqa: S608
              f"{extra[0]}) values (:i, :t, :o, :r, '[]', :c, {extra[1]})",
              i=claim, t=ctx["t"], o=owner_run, r=root, c=CIPHER, role=role)  # fmt: skip
    return claim


async def request(owner: Any, ctx: dict[str, Any], status: str, ago: timedelta | None,
                  request_id: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
    """A request in `status`, ended `ago` when terminal, with its envelope and one claim unless refused."""
    rid = request_id or uuid.uuid4()
    envelope = None
    if status != "refused":
        envelope = await _claim(owner, "run_inputs", ctx, rid, rid, role="envelope")
        await _claim(owner, "run_inputs", ctx, rid, rid)
    terminal = status in ("cancelled", "refused", "dead")
    await sql(owner, "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, "
              "idempotency_key, digest, digest_key_version, status, reason, envelope_id, queued_at, starting_at, "
              "ended_at) values (:i, :t, :w, :v, 'manual', 'live', :k, :d, 1, :s, :reason, :e, "
              "now() - interval '3 days', case when cast(:s as varchar) = 'starting' then now() end, "
              "case when :terminal then now() - cast(:ago as interval) end)",
              i=rid, t=ctx["t"], w=ctx["w"], v=ctx["v"], k=uuid.uuid4().hex, d=b"\x00" * 32, s=status,
              reason="r" if terminal else None, e=envelope, terminal=terminal, ago=ago or timedelta())  # fmt: skip
    return rid


async def run(owner: Any, ctx: dict[str, Any], ago: timedelta | None, parent: uuid.UUID | None = None,
              run_id: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
    """A run that ended `ago`, or is still running; a sub-run of `parent` when given."""
    rid = run_id or uuid.uuid4()
    await sql(owner, "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, "
              "parent_run_id, queued_at, ended_at) values (:i, :t, :w, :v, 'live', :s, :k, :p, "
              "now() - interval '3 days', now() - cast(:ago as interval))",
              i=rid, t=ctx["t"], w=ctx["w"], v=ctx["v"], s="running" if ago is None else "succeeded",
              k="run" if parent is None else "subflow", p=parent, ago=ago)  # fmt: skip
    return rid


async def tree(owner: Any, ctx: dict[str, Any], ago: timedelta | None, *, request_status: str | None = "started",
               sub_ago: timedelta | None | str = "same",
               root: uuid.UUID | None = None) -> dict[str, uuid.UUID]:  # fmt: skip
    """A run tree rooted in a run (`root`, or a new one) that ended `ago`: its request (`request_status`, or none, as a
    run from before 2b-2), a sub-run that ended with it (or `sub_ago`), a step of each, and claims of every kind on the
    tree."""
    root = root or uuid.uuid4()
    if request_status is not None:
        await request(owner, ctx, request_status, None, request_id=root)
    await run(owner, ctx, ago, run_id=root)
    sub = await run(owner, ctx, ago if sub_ago == "same" else sub_ago, parent=root)  # type: ignore[arg-type]
    for r in (root, sub):
        step = uuid.uuid4()
        await sql(owner, "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status) "
                  "values (:t, :r, :s, '', 1, 'n', 'succeeded')", t=ctx["t"], r=r, s=step)  # fmt: skip
        await sql(owner, "insert into run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, "
                  "connection_id, type, name, revision) values (:t, :r, :s, '', 1, :c, 'http', 'c', 1)",
                  t=ctx["t"], r=r, s=step, c=uuid.uuid4())  # fmt: skip
    output = await _claim(owner, "step_outputs", ctx, sub, root)
    await sql(owner, "insert into claim_grants (claim_id, run_id, tenant_id, granted_by, root_run_id) "
              "values (:c, :s, :t, :r, :r)", c=output, s=sub, t=ctx["t"], r=root)  # fmt: skip
    await sql(owner, "insert into run_secret_index (root_run_id, tenant_id, version, string_count, byte_count, "
              "ciphertext) values (:r, :t, 1, 0, 0, :c)", r=root, t=ctx["t"], c=CIPHER)  # fmt: skip
    return {"root": root, "sub": sub}


TREE_ROWS = (
    "select (select count(*) from runs where root_run_id = :r) + (select count(*) from run_steps s join runs r on "
    "r.id = s.run_id where r.root_run_id = :r) + (select count(*) from step_outputs where root_run_id = :r) + "
    "(select count(*) from run_inputs where root_run_id = :r) + (select count(*) from claim_grants where root_run_id "
    "= :r) + (select count(*) from run_secret_index where root_run_id = :r) + "
    "(select count(*) from run_step_connections c join runs r on r.id = c.run_id where r.root_run_id = :r) + "
    "(select count(*) from run_requests where id = :r)"
)
