# SPDX-License-Identifier: Apache-2.0
"""Step 1 and the writers it fences (the 2b-4 outline's "Fencing in-flight work"): every writer of tenant data takes
the tenant's lifecycle lock shared and checks `active` in the same transaction as its write, so step 1, which takes it
exclusively, waits for a writer that read `active` to commit, and every writer after it reads `erasing`. Each writer in
both orders: one holding its check while step 1 waits commits first (the erasure then removes what it wrote); one
started after step 1 is refused."""

import asyncio
import base64
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps import admission, cancels
from dewpoint.apps.api.main import create_app
from dewpoint.apps.cli.main import app as cli
from dewpoint.apps.dispatcher import tick
from dewpoint.core import http
from dewpoint.core.config import get_settings
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
from dewpoint.core.erasure import service
from dewpoint.core.plugins import asking, calls
from dewpoint.core.tenancy import lifecycle
from dewpoint.core.tenancy.service import ensure_tenant_event_keys, ensure_tenant_keys
from tests.apps.api.helpers import session_client
from tests.apps.dispatcher.test_schedule_tick import key
from tests.apps.test_admission import KEYS, TOKEN, count
from tests.apps.worker.test_plugin_calls import KIT_HASH, NAMES, outcome, server_for, setup
from tests.apps.worker.test_plugin_calls import ask as ask_call
from tests.apps.worker.test_plugin_calls import service as provider
from tests.conftest import _url_for
from tests.support.netfakes import Request, serve
from tests.support.workflows import seed_workflow

pytestmark = pytest.mark.usefixtures("development_deployment")
KEYRING = Keyring(KekSet(Kek("k1", bytes(32))))  # an ask refused before it waits never opens an answer


async def lock_waiters(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
                    ).scalar_one())  # fmt: skip


async def waiting(owner: Any) -> None:
    for _ in range(300):
        if await lock_waiters(owner) >= 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("nothing waited for a lock")


async def status(owner: Any, tenant_id: uuid.UUID) -> str:
    async with owner() as s:
        return str((await s.execute(text("select status from tenants where id = :t"), {"t": tenant_id})).scalar_one())


async def erase(api: Any, tenant_id: uuid.UUID, *, hold: asyncio.Event | None = None) -> None:
    async with api() as s, s.begin():
        await service.start(s, tenant_id=tenant_id, requested_by=uuid.uuid4())
        if hold is not None:
            await hold.wait()


async def erasing_first(api: Any, tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, asyncio.Event]:
    """Step 1 holding the lock, uncommitted, until the returned event is set."""
    locked, hold = asyncio.Event(), asyncio.Event()

    async def after_lock() -> None:
        locked.set()

    monkeypatch.setattr(service, "_after_lock", after_lock)
    task = asyncio.create_task(erase(api, tenant_id, hold=hold))
    await locked.wait()
    return task, hold


# Step 1 itself


async def test_step_1_marks_the_tenant_raises_its_schedules_and_records_and_audits_the_start(
    scheduled,
    owner_sessionmaker,
    api_sessionmaker,
) -> None:
    ctx, _, schedule_id = scheduled
    async with owner_sessionmaker() as s:
        before = (await s.execute(text("select generation from schedules where id = :i"), {"i": schedule_id})).scalar()
    actor = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        record = await service.start(s, tenant_id=ctx.tenant_id, requested_by=actor)
    assert (record.step, record.requested_by, await status(owner_sessionmaker, ctx.tenant_id)) == (20, actor, "erasing")
    async with owner_sessionmaker() as s:
        after = (await s.execute(text("select generation from schedules where id = :i"), {"i": schedule_id})).scalar()
        entry = (await s.execute(text("select actor_id, details from audit_log where action = 'tenant.erasure.start'"))
                 ).one()  # fmt: skip
    assert after == before + 1 and (entry.actor_id, entry.details) == (actor, {"schedules": 1})
    with pytest.raises(service.NotErasableError):  # irreversible, and never started twice
        async with api_sessionmaker() as s, s.begin():
            await service.start(s, tenant_id=ctx.tenant_id, requested_by=actor)
    with pytest.raises(service.TenantNotFoundError):
        async with api_sessionmaker() as s, s.begin():
            await service.start(s, tenant_id=uuid.uuid4(), requested_by=actor)


async def test_a_stop_and_a_retry_are_audited_and_never_return_the_tenant_to_active(
    owner_sessionmaker, api_sessionmaker
) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erase(api_sessionmaker, tenant)
    operator = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        stopped = await service.stop(s, tenant_id=tenant, stopped_by=operator)
        assert (stopped.stopped_by, stopped.stopped_at is not None) == (operator, True)
    async with api_sessionmaker() as s, s.begin():
        retried = await service.retry(s, tenant_id=tenant, actor_id=operator)
        assert (retried.stopped_at, retried.stopped_by) == (None, None)
    assert await status(owner_sessionmaker, tenant) == "erasing"
    async with owner_sessionmaker() as s:
        actions = list((await s.execute(text("select action from audit_log where action like 'tenant.erasure.%' "
                                             "order by seq"))).scalars())  # fmt: skip
    assert actions == ["tenant.erasure.start", "tenant.erasure.stop", "tenant.erasure.retry"]
    with pytest.raises(service.NoErasureError):
        async with api_sessionmaker() as s, s.begin():
            await service.stop(s, tenant_id=uuid.uuid4(), stopped_by=operator)


# Admission


async def test_an_admission_holding_its_check_commits_before_step_1(
    ready,
    owner_sessionmaker,
    api_sessionmaker,
) -> None:
    ctx, wf = ready
    async with api_sessionmaker() as s, s.begin():
        await admission.admit_request(s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id,
                                      idempotency_key="k1", source="manual", mode="live",
                                      input={"token": TOKEN, "site": "a"})  # fmt: skip
        erasing = asyncio.create_task(erase(api_sessionmaker, ctx.tenant_id))
        await waiting(owner_sessionmaker)
        assert not erasing.done()
    await erasing
    assert (await count(owner_sessionmaker, "run_requests"), await status(owner_sessionmaker, ctx.tenant_id)) == (
        1, "erasing",
    )  # fmt: skip


async def test_an_admission_after_step_1_waits_and_is_refused(
    ready,
    owner_sessionmaker,
    api_sessionmaker,
    monkeypatch,
) -> None:
    ctx, wf = ready
    erasing, hold = await erasing_first(api_sessionmaker, ctx.tenant_id, monkeypatch)

    async def admit() -> None:
        async with api_sessionmaker() as s, s.begin():
            await admission.admit_request(s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id,
                                          idempotency_key="k1", source="manual", mode="live",
                                          input={"token": TOKEN, "site": "a"})  # fmt: skip

    admitting = asyncio.create_task(admit())
    try:
        await waiting(owner_sessionmaker)
    finally:
        hold.set()
        await erasing
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admitting
    assert refused.value.reason == "tenant_erasing" and await count(owner_sessionmaker, "run_requests") == 0


# The schedule tick: already ordered with step 1 by its schedule's row lock (step 1 raises its generation); it takes
# the lifecycle lock first all the same, the order every writer keeps.


async def test_a_tick_holding_its_check_commits_before_step_1(
    scheduled,
    owner_sessionmaker,
    api_sessionmaker,
    dispatch_sessionmaker,
) -> None:
    ctx, _, schedule_id = scheduled
    async with dispatch_sessionmaker() as s, s.begin():
        outcome = await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id, key=key(schedule_id))
        erasing = asyncio.create_task(erase(api_sessionmaker, ctx.tenant_id))
        await waiting(owner_sessionmaker)
        assert not erasing.done()
    await erasing
    assert outcome == "queued" and await count(owner_sessionmaker, "run_requests") == 1


async def test_a_tick_after_step_1_waits_and_is_skipped(
    scheduled,
    owner_sessionmaker,
    api_sessionmaker,
    dispatch_sessionmaker,
    monkeypatch,
) -> None:
    ctx, _, schedule_id = scheduled
    erasing, hold = await erasing_first(api_sessionmaker, ctx.tenant_id, monkeypatch)

    async def ticked() -> str:
        async with dispatch_sessionmaker() as s, s.begin():
            return await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
                                         key=key(schedule_id))  # fmt: skip

    ticking = asyncio.create_task(ticked())
    try:
        await waiting(owner_sessionmaker)
    finally:
        hold.set()
        await erasing
    assert await ticking == "skipped:tenant_erasing"
    assert await count(owner_sessionmaker, "run_requests") == 0


# A run's cancel


async def test_a_cancel_after_step_1_waits_and_is_refused(
    ready,
    owner_sessionmaker,
    api_sessionmaker,
    monkeypatch,
) -> None:
    ctx, wf = ready
    async with api_sessionmaker() as s, s.begin():
        request = (await admission.admit_request(
            s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="k1",
            source="manual", mode="live", input={"token": TOKEN, "site": "a"},
        )).request  # fmt: skip
    erasing, hold = await erasing_first(api_sessionmaker, ctx.tenant_id, monkeypatch)

    async def cancel() -> str:
        async with api_sessionmaker() as s, s.begin():
            return await cancels.cancel_request(s, tenant_id=ctx.tenant_id, request_id=request.id, actor_id=ctx.user.id)

    cancelling = asyncio.create_task(cancel())
    try:
        await waiting(owner_sessionmaker)
    finally:
        hold.set()
        await erasing
    with pytest.raises(lifecycle.TenantNotActiveError):
        await cancelling
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select status from run_requests"))).scalar_one() == "queued"  # erasure's own


async def test_a_cancel_holding_its_check_commits_before_step_1(
    ready,
    owner_sessionmaker,
    api_sessionmaker,
) -> None:
    ctx, wf = ready
    async with api_sessionmaker() as s, s.begin():
        request = (await admission.admit_request(
            s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="k1",
            source="manual", mode="live", input={"token": TOKEN, "site": "a"},
        )).request  # fmt: skip
    async with api_sessionmaker() as s, s.begin():
        assert await cancels.cancel_request(s, tenant_id=ctx.tenant_id, request_id=request.id,
                                            actor_id=ctx.user.id) == "cancelled"  # fmt: skip
        erasing = asyncio.create_task(erase(api_sessionmaker, ctx.tenant_id))
        await waiting(owner_sessionmaker)
        assert not erasing.done()
    await erasing
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select status from run_requests"))).scalar_one() == "cancelled"


# The API's tenant-scoped writes, through require()


def _requires(route: APIRoute) -> bool:
    pending, seen = [route.dependant], set()
    while pending:
        dependant = pending.pop()
        call = dependant.call
        if call is not None and getattr(call, "__qualname__", "").startswith("require.<locals>"):
            return True
        for sub in dependant.dependencies:
            if id(sub) not in seen:
                seen.add(id(sub))
                pending.append(sub)
    return False


def _routes(routes: Any) -> list[APIRoute]:
    """Every API route, through the routers FastAPI includes (0.141 keeps each as an included router)."""
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_routes(route.original_router.routes))
    return found


def _admins(route: APIRoute) -> bool:
    return any(d.call is http.require_platform_admin for d in route.dependant.dependencies)


def test_every_tenant_scoped_write_goes_through_require(api_settings) -> None:
    """require() takes the lock and refuses a tenant that isn't active for every non-safe method, so every route
    naming a tenant that writes must go through it; but the platform admin's, which erase a tenant (2b-4a M4)."""
    writes = [route for route in _routes(create_app(api_settings).routes)
              if "{tenant_id}" in route.path and route.methods - http.SAFE_METHODS]  # fmt: skip
    admins = [route for route in writes if route.path.startswith("/api/v1/admin/")]
    assert len(writes) > 20 and len(admins) == 3  # the inventory isn't empty; start, stop and retry
    assert [route.path for route in admins if not _admins(route)] == []
    assert [
        (route.path, sorted(route.methods)) for route in writes if route not in admins and not _requires(route)
    ] == []


async def test_an_api_write_holding_its_check_commits_before_step_1(
    app, owner_sessionmaker, api_sessionmaker, api_settings, monkeypatch
) -> None:
    c, tenant = await session_client(app, owner_sessionmaker, api_settings, "owner")
    reached, release = asyncio.Event(), asyncio.Event()

    async def after_require() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(http, "_after_require", after_require)
    async with c:
        patching = asyncio.create_task(c.patch(f"/api/v1/t/{tenant}", json={"name": "Renamed"}))
        await reached.wait()
        erasing = asyncio.create_task(erase(api_sessionmaker, tenant))
        try:
            await waiting(owner_sessionmaker)
            assert not erasing.done()
        finally:
            release.set()
        assert (await patching).status_code == 200
        await erasing
    async with owner_sessionmaker() as s:
        row = (await s.execute(text("select name, status from tenants where id = :t"), {"t": tenant})).one()
    assert tuple(row) == ("Renamed", "erasing")


async def test_an_api_write_after_step_1_waits_and_is_refused_while_a_read_still_answers(
    app, owner_sessionmaker, api_sessionmaker, api_settings, monkeypatch
) -> None:
    c, tenant = await session_client(app, owner_sessionmaker, api_settings, "owner")
    erasing, hold = await erasing_first(api_sessionmaker, tenant, monkeypatch)
    async with c:
        patching = asyncio.create_task(c.patch(f"/api/v1/t/{tenant}", json={"name": "Renamed"}))
        try:
            await waiting(owner_sessionmaker)
        finally:
            hold.set()
            await erasing
        refused = await patching
        assert (refused.status_code, refused.json()) == (409, {"error": "tenant_erasing"})
        assert (await c.get(f"/api/v1/t/{tenant}")).status_code == 200
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select name from tenants where id = :t"), {"t": tenant})).scalar_one() == "T"


# The CLI's per-tenant key commands


async def test_ensuring_keys_skips_a_tenant_that_isnt_active(
    owner_sessionmaker, admin_sessionmaker, api_sessionmaker
) -> None:
    """`keys ensure-tenants` gives a key to every tenant without one: never to one being erased, whose keys go."""
    tenant, _, _ = await seed_workflow(owner_sessionmaker)  # no key: seeded directly
    await erase(api_sessionmaker, tenant)
    async with admin_sessionmaker() as s, s.begin():
        keyring = Keyring(KekSet(Kek("k1", bytes(32))))
        assert (await ensure_tenant_keys(s, keyring), await ensure_tenant_event_keys(s, keyring)) == ([], [])


def test_no_key_command_creates_a_key_for_a_tenant_that_isnt_active(pg_url, _test_users, monkeypatch) -> None:
    tenant = uuid.uuid4()

    async def erasing() -> None:
        engine = make_engine(pg_url)
        async with make_sessionmaker(engine)() as s, s.begin():
            await s.execute(text("insert into tenants (id, name, slug, status) values (:t, 'T', :s, 'erasing')"),
                            {"t": tenant, "s": tenant.hex[:12]})  # fmt: skip
        await engine.dispose()

    asyncio.run(erasing())
    for k, v in {"DEWPOINT_DATABASE_URL": _url_for(pg_url, "dewpoint_admin"), "DEWPOINT_PUBLIC_ORIGIN":
                 "https://dewpoint.test", "DEWPOINT_KEK_B64": base64.b64encode(bytes(32)).decode(),
                 "DEWPOINT_KEK_ID": "k1"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    for command in ("rotate-dek", "rotate-event-key"):
        out = CliRunner().invoke(cli, ["keys", command, "--tenant", str(tenant)])
        assert (out.exit_code, "being erased" in out.output) == (1, True), out.output
    out = CliRunner().invoke(cli, ["keys", "rotate-dek", "--tenant", str(uuid.uuid4())])  # no such tenant
    assert out.exit_code == 1, out.output
    get_settings.cache_clear()


# A plugin call (plugins-3a-2; the owner's review of 2b-4a v5): the API asks, then a worker claims the call, runs its
# hook, which reaches the tenant's connection outside PostgreSQL, and answers. A call queued before step 1 is never run;
# one in flight finishes, its answer included, before step 1 commits; an ask after step 1 records nothing.


async def _state(api: Any, tenant: uuid.UUID, call: uuid.UUID) -> tuple[str, bool]:
    async with api() as s, s.begin():
        await tenant_scope(s, tenant)
        found = (await s.execute(text("select state, claim_token is not null from plugin_calls where id = :i"),
                                 {"i": call})).one()  # fmt: skip
    return str(found[0]), bool(found[1])


async def test_a_plugin_call_queued_before_step_1_is_never_run(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(provider, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask_call(api_sessionmaker, tenant, cid)
        await erase(api_sessionmaker, tenant)
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert (await _state(api_sessionmaker, tenant, call), fake.requests) == (("pending", False), [])


async def test_queued_calls_of_erasing_tenants_never_hold_an_active_tenants_call_back(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    """The owner's review of 2b-4a v6: a worker takes at most its free slots' worth of candidates, oldest first. Calls
    an erasure left queued are never run, so if they stayed candidates, as many of them as a worker has slots would be
    taken and skipped every round, and a newer call of an active tenant would never reach a worker."""
    async with serve(provider, tls_names=NAMES) as fake:
        for _ in range(8):  # a worker's concurrency: every slot
            erased, erased_cid = await setup(owner_sessionmaker, fake.port)
            await ask_call(api_sessionmaker, erased, erased_cid)
            await erase(api_sessionmaker, erased)
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask_call(api_sessionmaker, tenant, cid)
        await server_for(worker_sessionmaker, tenant, concurrency=8).serve_once()
    assert (await outcome(api_sessionmaker, tenant, call))[0] == "done"
    assert len(fake.requests) == 1  # the active tenant's call only


async def test_a_plugin_call_in_flight_answers_before_step_1_commits(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    arrived, release = asyncio.Event(), asyncio.Event()

    async def held(request: Request, writer: asyncio.StreamWriter) -> None:
        arrived.set()
        await release.wait()
        await provider(request, writer)

    async with serve(held, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask_call(api_sessionmaker, tenant, cid)
        served = asyncio.create_task(server_for(worker_sessionmaker, tenant).serve_once())
        erasing: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(arrived.wait(), 10)  # the hook reached the provider: the call is in flight
            erasing = asyncio.create_task(erase(api_sessionmaker, tenant))
            await waiting(owner_sessionmaker)  # step 1 waits for the call
            assert await status(owner_sessionmaker, tenant) == "active"
            # A write a hook may make meanwhile, on its own connection (a tenant's first rate budget, or key, as its
            # answer is sealed), takes the lifecycle lock shared in the fence's trigger: it isn't queued behind step 1.
            async with owner_sessionmaker() as s, s.begin():
                await asyncio.wait_for(s.execute(text(
                    "insert into rate_buckets (tenant_id, scope, capacity, refill_per_s, tokens, refilled_at) "
                    "values (:t, 'mist:org', 5, 1, 5, now())"), {"t": tenant}), 5)  # fmt: skip
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(served, *([erasing] if erasing else []), return_exceptions=True), 30)
    assert (await outcome(api_sessionmaker, tenant, call))[0] == "done"
    assert await status(owner_sessionmaker, tenant) == "erasing"


async def test_an_ask_after_step_1_is_refused_and_records_nothing(owner_sessionmaker, api_sessionmaker) -> None:
    tenant, cid = await setup(owner_sessionmaker, 443)
    await erase(api_sessionmaker, tenant)

    async def asked(s: Any) -> uuid.UUID:
        return await calls.ask_options(s, tenant, node_ref="testkit.pick@1", field="site_id", connection_id=cid,
                                       revision=1, query="", type_hash=KIT_HASH)  # fmt: skip

    with pytest.raises(lifecycle.TenantNotActiveError):
        await asking.ask_and_wait(api_sessionmaker, KEYRING, tenant, asked)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from plugin_calls where tenant_id = :t"), {"t": tenant})
                ).scalar_one() == 0  # fmt: skip


async def test_an_ask_holding_its_check_commits_before_step_1(owner_sessionmaker, api_sessionmaker) -> None:
    tenant, cid = await setup(owner_sessionmaker, 443)
    held, release = asyncio.Event(), asyncio.Event()

    async def asked(s: Any) -> uuid.UUID:
        held.set()
        await release.wait()
        return await calls.ask_options(s, tenant, node_ref="testkit.pick@1", field="site_id", connection_id=cid,
                                       revision=1, query="", type_hash=KIT_HASH)  # fmt: skip

    asked_task = asyncio.create_task(asking._ask(api_sessionmaker, tenant, asked))
    erasing: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(held.wait(), 10)
        erasing = asyncio.create_task(erase(api_sessionmaker, tenant))
        await waiting(owner_sessionmaker)  # step 1 waits for the ask
        assert await status(owner_sessionmaker, tenant) == "active"
    finally:
        release.set()
        done = await asyncio.wait_for(asyncio.gather(asked_task, *([erasing] if erasing else []),
                                                     return_exceptions=True), 30)  # fmt: skip
    call = done[0]
    assert isinstance(call, uuid.UUID), call
    # recorded before step 1: the erasure removes it, and no worker runs it (above)
    assert await _state(api_sessionmaker, tenant, call) == ("pending", False)
    assert await status(owner_sessionmaker, tenant) == "erasing"
