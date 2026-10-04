# SPDX-License-Identifier: Apache-2.0
"""Admission (engine 2b spec §7.2, revision 7): a request frozen in its caller's transaction. An exact retry under the
same idempotency key is the frozen request as it is now, whatever changed since; another request under the key is a
conflict; a new key passes the mutable checks, is digested with the tenant's key, has its trigger claimed and its
envelope stored, and is inserted, all in one savepoint that a lost race discards whole. A durable source's refusal is
kept as a `refused` request; an interactive one's is raised."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission
from dewpoint.apps.inputs import RESERVED_INPUT
from dewpoint.core.claims import secret_index
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import lifecycle
from dewpoint.engine import ENGINE_ABI
from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, update
from tests.support.graphs import G
from tests.support.keys import FixtureKeys
from tests.support.registry import sync_test_plugins

pytestmark = pytest.mark.usefixtures("development_deployment")

KEYS = FixtureKeys()
TOKEN = "t0ken-value-1"
SCHEMA = {
    "type": "object",
    "properties": {"token": {"type": "string", "x-sensitive": True}, "site": {"type": "string"}},
    "required": ["token"],
    "additionalProperties": False,
}
TOKEN_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": SCHEMA}}
OPEN_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": {"type": "object"}}}
CSV_GRAPH = TOKEN_GRAPH | {
    "settings": {"input_schema": SCHEMA, "csv": {"columns": [{"header": "Site", "name": "site", "type": "string"}]}}
}


async def published(owner: Any, api: Any, admin: Any, settings: Any, graph: Any = TOKEN_GRAPH) -> tuple[Any, uuid.UUID]:
    await sync_test_plugins(admin)
    ctx = await actor(owner)
    wf = await create(api, ctx, graph)
    assert (await publish(api, ctx, wf, settings)).version is not None
    return ctx, wf


async def current(dispatch: Any, *, abi: int = ENGINE_ABI, age: timedelta = timedelta()) -> None:
    """The current build as the dispatcher last recorded it, which admission checks the ABI against."""
    async with dispatch() as s, s.begin():
        await s.execute(
            text("insert into current_build (id, build_id, engine_abi, observed_at) "
                 "values (1, 'b', :a, now() - cast(:age as interval)) "
                 "on conflict (id) do update set engine_abi = excluded.engine_abi, observed_at = excluded.observed_at"),
            {"a": abi, "age": age},
        )  # fmt: skip


async def admit(api: Any, ctx: Any, wf: uuid.UUID, *, key: str = "k1", keys: Any = KEYS, **request: Any) -> Any:
    fields = {"source": "manual", "mode": "live", "input": {"token": TOKEN, "site": "a"}, **request}
    async with api() as s, s.begin():
        return await admission.admit_request(
            s, keys, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key=key, **fields
        )


async def count(owner: Any, table: str) -> int:
    async with owner() as s:
        return int((await s.execute(text(f"select count(*) from {table}"))).scalar_one())


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def test_a_new_request_is_frozen_on_the_active_version_with_its_envelope_and_claims(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, wf = ready
    admitted = await admit(api_sessionmaker, ctx, wf)
    r = admitted.request
    assert admitted.new and (r.status, r.source, r.mode, r.actor_id, r.digest_key_version) == (
        "queued", "manual", "live", ctx.user.id, 1,
    )  # fmt: skip
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        active = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
        envelope = await claims.read_envelope(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=r.id)
        handle = envelope["token"]["$claim"]
        token = await claims.fetch(s, ClaimCipher(KEYS), ctx.tenant_id, run_id=r.id, claim_id=uuid.UUID(handle))
    assert r.workflow_version_id == active and envelope["site"] == "a" and token.value == TOKEN
    async with owner_sessionmaker() as s:
        audit = (await s.execute(text("select action, target_id, details from audit_log"))).all()
        index = (await s.execute(text("select root_run_id from run_secret_index"))).scalars().all()
    assert [(a.action, a.target_id) for a in audit if a.action.startswith("run.")] == [("run.request", str(r.id))]
    assert index == [r.id]  # the run tree's secret index is seeded under the request's id, the run's
    assert await count(owner_sessionmaker, "runs") == 0  # the dispatcher writes the run's row (§7.3)


async def test_an_exact_retry_is_the_frozen_request_whatever_changed_since(
    ready, owner_sessionmaker, api_sessionmaker
) -> None:
    """A key rotation and a disabled workflow don't change what an exact retry returns (§7.2, step 2)."""
    ctx, wf = ready
    first = (await admit(api_sessionmaker, ctx, wf)).request
    stored = await count(owner_sessionmaker, "run_inputs")
    await update(api_sessionmaker, ctx, wf, enabled=False)
    again = await admit(api_sessionmaker, ctx, wf, keys=FixtureKeys(version=2))
    assert (again.new, again.request.id, again.request.status) == (False, first.id, "queued")
    assert await count(owner_sessionmaker, "run_inputs") == stored


async def test_another_request_under_the_same_key_is_a_conflict(ready, api_sessionmaker) -> None:
    ctx, wf = ready
    await admit(api_sessionmaker, ctx, wf)
    for other in ({"input": {"token": "another-token", "site": "a"}}, {"mode": "simulate"}):
        with pytest.raises(admission.IdempotencyConflictError):
            await admit(api_sessionmaker, ctx, wf, **other)


@pytest.mark.parametrize("same", [True, False])
async def test_a_concurrent_admission_under_the_key_returns_the_winner_and_leaves_nothing_of_its_own(
    ready, owner_sessionmaker, api_sessionmaker, monkeypatch, same
) -> None:
    """Another transaction freezes a request under the key between this one's lookup and its insert: the insert
    conflicts, the savepoint is rolled back with this call's claims and envelope, and the winner is compared with its
    own stored key version (§7.2, step 6)."""
    ctx, wf = ready
    winner: list[Any] = []

    async def race() -> None:
        if not winner:
            winner.append(None)
            winner[0] = (await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN if same else "x" * 9})).request

    monkeypatch.setattr(admission, "_before_insert", race)
    if same:
        admitted = await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN})
        assert (admitted.new, admitted.request.id) == (False, winner[0].id)
    else:
        with pytest.raises(admission.IdempotencyConflictError):
            await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN})
    async with owner_sessionmaker() as s:
        owners = (await s.execute(text("select distinct owner_run_id from run_inputs"))).scalars().all()
    assert owners == [winner[0].id]


@pytest.mark.parametrize(
    ("breaks", "reason"),
    [
        ("erasing", "tenant_erasing"),
        ("disabled", "workflow_disabled"),
        ("retired", "node_type_retired"),
        ("no_build", "no_current_build"),
        ("stale_build", "no_current_build"),
        ("other_abi", "version_unusable"),
        ("input", "input_invalid"),
    ],  # fmt: skip
)
async def test_a_refused_interactive_request_is_raised_and_leaves_nothing(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, breaks, reason
) -> None:
    ctx, wf = ready
    request: dict[str, Any] = {}
    async with owner_sessionmaker() as s, s.begin():
        if breaks == "erasing":
            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
        elif breaks == "retired":
            await s.execute(
                text("update node_type_versions set state = 'retired' where type = 'testkit.echo' and version = 1")
            )
        elif breaks == "no_build":
            await s.execute(text("delete from current_build"))
    if breaks == "disabled":
        await update(api_sessionmaker, ctx, wf, enabled=False)
    elif breaks == "stale_build":
        await current(dispatch_sessionmaker, age=timedelta(minutes=10))
    elif breaks == "other_abi":
        await current(dispatch_sessionmaker, abi=ENGINE_ABI + 1)
    elif breaks == "input":
        request["input"] = {"token": 7, "secret-key-name": "v"}
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, **request)
    assert refused.value.reason == reason and refused.value.messages
    if breaks == "input":  # locations and rules only, never a value nor a key the data supplied (§3.5)
        assert not any("secret-key-name" in m or "7" in m.split("at ")[-1] for m in refused.value.messages)
    assert (await count(owner_sessionmaker, "run_requests"), await count(owner_sessionmaker, "run_inputs")) == (0, 0)


async def test_a_workflow_with_no_active_version_admits_nothing(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)  # never published
    await current(dispatch_sessionmaker)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, input={})
    assert refused.value.reason == "not_active"


@pytest.mark.parametrize("breaks", ["disabled", "input"])
async def test_a_durable_sources_refusal_is_kept_as_a_refused_request(
    ready, owner_sessionmaker, api_sessionmaker, breaks
) -> None:
    """A schedule tick's or a webhook event's refusal is never lost (§7.2): a `refused` request with its reason, no
    envelope and no claims, audited. It's frozen like any request: retried under its key, it's the same refusal."""
    ctx, wf = ready
    request: dict[str, Any] = {"source": "schedule"}
    if breaks == "disabled":
        await update(api_sessionmaker, ctx, wf, enabled=False)
    else:
        request["input"] = {"token": 7}
    admitted = await admit(api_sessionmaker, ctx, wf, **request)
    r = admitted.request
    assert admitted.new and (r.status, r.reason, r.envelope_id) == (
        "refused", "workflow_disabled" if breaks == "disabled" else "input_invalid", None,
    )  # fmt: skip
    assert await count(owner_sessionmaker, "run_inputs") == 0
    again = await admit(api_sessionmaker, ctx, wf, **request)
    assert (again.new, again.request.id) == (False, r.id)


async def test_an_input_past_the_secret_index_bound_is_refused_and_its_claims_discarded(
    ready, owner_sessionmaker, api_sessionmaker, monkeypatch
) -> None:
    ctx, wf = ready
    monkeypatch.setattr(secret_index, "MAX_STRINGS", 0)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf)
    assert refused.value.reason == "secret_index_limit"
    assert await count(owner_sessionmaker, "run_inputs") == 0


async def test_admission_refuses_a_repeatable_read_transaction(ready, api_sessionmaker) -> None:
    """Its locks serialize with retirement and workflow changes only at READ COMMITTED (engine-core §4.5)."""
    ctx, wf = ready
    with pytest.raises(lifecycle.IsolationError):
        async with api_sessionmaker() as s, s.begin():
            await s.execute(text("set transaction isolation level repeatable read"))
            await admission.admit_request(
                s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="k",
                source="manual", mode="live", input={"token": TOKEN},
            )  # fmt: skip


async def test_the_build_record_ages_with_the_clock_not_the_callers_transaction(
    ready, api_sessionmaker, monkeypatch
) -> None:
    """A caller admitting several requests in one transaction (2b-3's matcher) sees the record go stale while it holds
    the transaction: the check reads the statement's time, not the transaction's start (the owner's M1 checkpoint)."""
    ctx, wf = ready
    monkeypatch.setattr(admission, "BUILD_STALE", timedelta(seconds=1))
    async with api_sessionmaker() as s, s.begin():
        first = await admission.admit_request(
            s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="a",
            source="manual", mode="live", input={"token": TOKEN},
        )  # fmt: skip
        assert first.new
        await s.execute(text("select pg_sleep(1.2)"))
        with pytest.raises(admission.AdmissionRefusedError) as stale:
            await admission.admit_request(
                s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="b",
                source="manual", mode="live", input={"token": TOKEN},
            )  # fmt: skip
    assert stale.value.reason == "no_current_build"


@pytest.mark.parametrize("name", ["rows", "row_count"])
@pytest.mark.parametrize("source", ["manual", "schedule"])
async def test_no_caller_supplies_rows_or_row_count(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, name, source
) -> None:
    """Only admission writes `rows` and `row_count`, from a CSV upload (engine 2b spec §8.1): a caller's input holding
    either is refused, even where the workflow's input schema would take it."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, OPEN_GRAPH)
    await current(dispatch_sessionmaker)
    request = {"source": source, "input": {name: 1}}
    if source == "manual":
        with pytest.raises(admission.AdmissionRefusedError) as refused:
            await admit(api_sessionmaker, ctx, wf, **request)
        assert (refused.value.reason, refused.value.messages) == ("input_invalid", [RESERVED_INPUT])
    else:
        r = (await admit(api_sessionmaker, ctx, wf, **request)).request
        assert (r.status, r.reason) == ("refused", "input_invalid")
    assert await count(owner_sessionmaker, "run_inputs") == 0


async def test_a_workflow_declaring_a_csv_isnt_started_without_one(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Its trigger schema requires `rows` and `row_count` (engine 2b spec §8.1), which only a CSV upload supplies."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, CSV_GRAPH)
    await current(dispatch_sessionmaker)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf)
    assert refused.value.reason == "input_invalid"
    assert any("its root: it breaks `required`" in m for m in refused.value.messages)
