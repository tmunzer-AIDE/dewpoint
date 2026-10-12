# SPDX-License-Identifier: Apache-2.0
"""A tenant with a row in every table that holds tenant data, written as the table owner, and what's left of it."""

import uuid
from typing import Any

from sqlalchemy import text
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from dewpoint.core.auth.users import create_user
from dewpoint.core.erasure import service
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.core.erasure.test_fence import FENCED_TABLES
from tests.core.ingress.support import KEYRING, digest, endpoint, key, record
from tests.core.retention.support import CIPHER, OLD, request, sql, tree
from tests.support.workflows import seed_workflow


async def populated(owner: Any, ingress: Any) -> dict[str, Any]:
    """A tenant holding a row in each of its tables: its keys and keypair, a webhook endpoint with a pending event and
    a binding, a workflow and version, a run tree that ended (its steps, claims, grants, secret index, request and
    envelope, its evidence), a queued request, a schedule and a tick's record of a firing, a connection, a member, an
    upload and a saved mapping, its retention, limits and a slot, and a plugin call's answer."""
    tenant, endpoint_id = await endpoint(owner)
    _, workflow_id, version_id = await seed_workflow(owner, tenant_id=tenant)
    async with owner() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
        await KEYRING.ensure_key(s, tenant)
    ctx = {"t": tenant, "w": workflow_id, "v": version_id, "u": user}
    await record(ingress, endpoint_id, [(key(1), digest(1), b"one")])
    run_tree = await tree(owner, ctx, OLD)
    queued = await request(owner, ctx, "queued", None)
    schedule_id, release = uuid.uuid4(), uuid.uuid4()  # a release command (0057) and its snapshot
    for statement, params in (
        ("insert into memberships (tenant_id, user_id, role) values (:t, :u, 'owner')", {}),
        ("insert into connections (id, tenant_id, type, name, config) values (:i, :t, 'http', 'c', '{}')",
         {"i": uuid.uuid4()}),
        ("insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by) "
         "values (:i, :t, :w, 60, 'live', :c, :u)", {"i": schedule_id, "c": CIPHER}),
        ("insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, backfilled) "
         "values (:f, :t, :i, 0, true)",
         {"f": f"t:{tenant}:sched:{schedule_id}", "i": schedule_id}),  # as a schedule from before 2b-4a
        ("insert into schedule_intervals (tenant_id, schedule_id, temporal_id, kind, starts_at, ends_at, class, "
         "reason) values (:t, :i, :f, 'lost', now() - interval '1 hour', now(), 'unknown', "
         "'lost_from_before_migration')", {"f": f"t:{tenant}:sched:{schedule_id}", "i": schedule_id}),
        ("insert into schedule_firings (workflow_id, run_id, tenant_id, schedule_id) values (:f, :r, :t, :i)",
         {"f": f"t:{tenant}:sched:{schedule_id}-2026-10-05T09:00:00Z", "r": str(uuid.uuid4()), "i": schedule_id}),
        ("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
         "values (:i, :t, :e, :w, :u)", {"i": uuid.uuid4(), "e": endpoint_id}),
        ("insert into csv_uploads (id, tenant_id, owner_id, workflow_id, staged, file_digest, digest_key_version, "
         "size_bytes, row_count, expires_at) values (:i, :t, :u, :w, 'x', :d, 1, 1, 1, now() + interval '1 hour')",
         {"i": uuid.uuid4(), "d": b"\x00" * 32}),
        ("insert into csv_mappings (workflow_id, tenant_id, mapping, saved_by, saved_against) "
         "values (:w, :t, :c, :u, :v)", {"c": CIPHER}),
        ("insert into tenant_retention (tenant_id, runs_days) values (:t, 30)", {}),
        ("insert into egress_allowlist (network, tenant_id) values ('203.0.113.0/24', :t)", {}),  # 0041's tables
        ("insert into rate_buckets (tenant_id, scope, capacity, refill_per_s, tokens, refilled_at) "
         "values (:t, 'mist:org', 5, 1, 5, now())", {}),
        ("insert into rate_scope_keys (tenant_id, sealed) values (:t, :c)", {"c": CIPHER}),
        ("insert into plugin_calls (tenant_id, kind, node_ref, field, state, expires_at, result_ct) values "  # 0042's:
         "(:t, 'options', 'flow.x@1', 'f', 'done', now() + interval '1 hour', :c)", {"c": CIPHER}),  # no connection
        ("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 3)", {}),
        ("insert into run_slots (run_id, tenant_id) values (:i, :t)", {"i": uuid.uuid4()}),
        ("insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at) values "  # 2b-4b M3's
         "(:t, 'dispatch', :i, 1, 'RuntimeError', now())", {"i": queued}),
        ("insert into recovery_items (tenant_id, reason, item_id) values (:t, 'run_history_missing', :i)",
         {"i": uuid.uuid4()}),
        ("insert into operator_commands (id, tenant_id, kind, item_id, reason, incident_since, actor_id, "
         "idempotency_key, status) values (:i, :t, 'record_lost_run', :r, 'run_history_missing', now(), :u, 'k', "
         "'pending')", {"i": uuid.uuid4(), "r": uuid.uuid4()}),
        ("insert into operator_commands (id, tenant_id, kind, item_id, work_kind, actor_id, idempotency_key) "  # 0057's
         "values (:i, :t, 'release_held', :r, 'dispatch', :u, 'release')", {"i": release, "r": uuid.uuid4()}),
        ("insert into operator_command_holds (command_id, tenant_id, kind, item_id, hold_id) "
         "values (:c, :t, 'dispatch', :r, 1)", {"c": release, "r": uuid.uuid4()}),
    ):  # fmt: skip
        await sql(owner, statement, t=tenant, w=workflow_id, v=version_id, u=user, **params)
    return {**ctx, "endpoint": endpoint_id, "tree": run_tree, "queued": queued, "schedule": schedule_id}


async def rows_of(owner: Any, tenant: uuid.UUID) -> dict[str, int]:
    """Every fenced table's count of the tenant's rows (the tables holding tenant data), a run's steps included."""
    counts: dict[str, int] = {}
    async with owner() as s:
        for table in sorted(FENCED_TABLES):
            counted = text(f"select count(*) from {table} where tenant_id = :t")  # noqa: S608  # fixed names
            counts[table] = int((await s.execute(counted, {"t": tenant})).scalar_one())
    return counts


async def erasing(api: Any, tenant: uuid.UUID) -> None:
    async with api() as s, s.begin():
        await service.start(s, tenant_id=tenant, requested_by=uuid.uuid4())


async def executed(client: Client, owner: Any, tenant: uuid.UUID) -> None:
    """Every execution step 60 will enumerate for the tenant started on the dev server and closed at once (the runs
    `populated` writes ended long ago; no worker serves the queue), and the exact runs its evidence and firings name set
    to the started ones: each is then shown, deleted and read back, `gone`. `populated` writes those rows alone, as if
    Temporal had them: an id Temporal never shows holds an erasure for good (2b-4b M4 recovery, task 12;
    `test_erasure_bound.py`). Closed, not left open: the dev server takes minutes, more for each, to delete an execution
    terminated just before (measured, task 12), and one closed a while before in about 30 s."""
    runs_of = text("select id from runs where tenant_id = :t")
    started_of = text("select id from run_requests where tenant_id = :t and status = 'started'")
    async with owner() as s:
        runs = [str(r) for r in (await s.execute(runs_of, {"t": tenant})).scalars()]
        started = [str(r) for r in (await s.execute(started_of, {"t": tenant})).scalars()]
        evidence = (await s.execute(text("select id, workflow_id from execution_evidence where tenant_id = :t"),
                                    {"t": tenant})).all()  # fmt: skip
        firings = (await s.execute(text("select workflow_id, run_id from schedule_firings where tenant_id = :t"),
                                   {"t": tenant})).all()  # fmt: skip
    run_ids: dict[str, str] = {}

    async def start(workflow_id: str) -> str:
        if workflow_id not in run_ids:
            try:
                handle = await client.start_workflow("Unserved", id=workflow_id, task_queue="erasure-unserved")
                await handle.terminate()
                run_ids[workflow_id] = str(handle.first_execution_run_id or handle.result_run_id)
            except WorkflowAlreadyStartedError as err:  # the test started it itself: its open run, left as it is
                run_ids[workflow_id] = str(err.run_id)
        return run_ids[workflow_id]

    for run in dict.fromkeys([*runs, *started]):
        await start(run_workflow_id(str(tenant), run))
    async with owner() as s, s.begin():
        for evidence_id, workflow_id in evidence:
            await s.execute(text("update execution_evidence set run_id = :r where id = :i"),
                            {"r": await start(workflow_id), "i": evidence_id})  # fmt: skip
        for workflow_id, run_id in firings:
            await s.execute(text("update schedule_firings set run_id = :r where workflow_id = :w and run_id = :o "
                                 "and tenant_id = :t"),
                            {"r": await start(workflow_id), "w": workflow_id, "o": run_id, "t": tenant})  # fmt: skip
