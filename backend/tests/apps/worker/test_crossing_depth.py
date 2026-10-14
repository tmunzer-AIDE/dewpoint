# SPDX-License-Identifier: Apache-2.0
"""A sub-flow's input past the input limit (issue #88): the crossing checks the envelope first, discovers its claims
without recursing, resolves them bounded to 64 levels of the value it builds, then validates. A value too deep, by
itself, through a chain of shallow claims or in one deep claim, is the child's refused input with the fixed reason:
never a `RecursionError`, never `claim_unavailable`, and nothing is granted to the child."""

import uuid
from typing import Any

from dewpoint.apps.inputs import TOO_DEEP
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.claims import service
from dewpoint.engine.handles import ClaimRef
from tests.apps.test_admission import OPEN_GRAPH, published
from tests.apps.worker.test_store_claims import crossed, granted_to
from tests.support.keys import FixtureKeys


def nest(levels: int, leaf: Any = None) -> Any:
    """`levels` objects deep, `leaf` inside the deepest."""
    value: Any = {} if leaf is None else {"leaf": leaf}
    for _ in range(levels - 1):
        value = {"n": value}
    return value


def chain(count: int, levels: int) -> Any:
    """`count` claims of `levels` levels each, claim `i` holding claim `i + 1` at its deepest."""
    return lambda ids: [nest(levels, ClaimRef(ids[i + 1]).to_json() if i < count - 1 else None) for i in range(count)]


async def crossing(
    stack: Any, count: int, values: Any, envelope_of: Any, seen: list[str] | None = None
) -> tuple[Any, uuid.UUID, uuid.UUID]:
    """A child version taking any object; `count` claims of a root run, `values(ids)` theirs, each granted to the
    crossing run; then the crossing of `envelope_of(ids)`, its statements appended to `seen`."""
    from sqlalchemy import text

    from tests.core.claims.test_service import statements

    owner, api, admin, worker, settings = stack
    ctx, wf = await published(owner, api, admin, settings, OPEN_GRAPH)
    async with owner() as s:
        version = (await s.execute(text("select id from workflow_versions where workflow_id = :w"), {"w": wf})).scalar()
    root, run, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ids = [str(uuid.uuid4()) for _ in range(count)]
    store = DbRunStore(worker, FixtureKeys())
    claims = [service.NewClaim(uuid.UUID(i), v, (), root, root) for i, v in zip(ids, values(ids), strict=True)]
    await store.write(str(ctx.tenant_id), claims, kind="output", step_id=None, iteration_key=None)
    await store.grant(str(ctx.tenant_id), granted_by=str(root), to=str(run), claim_ids=ids, root_run_id=str(root))
    with statements(worker) as executed:
        result = await crossed(ctx.tenant_id, str(version), root, run, child, envelope_of(ids), store)
    if seen is not None:
        seen.extend(executed)
    return result, ctx.tenant_id, child


async def test_a_raw_child_input_past_the_limit_is_refused_before_any_claim_is_read(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings
) -> None:  # fmt: skip
    """The envelope's own depth first: 65 levels under a permissive schema, a handle at its deepest, refused without
    reading the claim the handle names."""
    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    seen: list[str] = []
    result, tenant, child = await crossing(stack, 1, lambda ids: [1],
                                           lambda ids: {"a": nest(64, ClaimRef(ids[0]).to_json())}, seen)  # fmt: skip
    assert result.reasons == [TOO_DEEP]
    assert [s for s in seen if "step_outputs" in s] == []
    assert await granted_to(worker_sessionmaker, tenant, child) == 0


async def test_a_chain_of_shallow_claims_expanding_past_the_limit_is_refused(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings
) -> None:  # fmt: skip
    """The owner's first review of the plan: a two-level envelope naming 24 claims of 41 levels each."""
    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    result, tenant, child = await crossing(
        stack, 24, chain(24, 41), lambda ids: {"a": {"b": ClaimRef(ids[0]).to_json()}}
    )
    assert result.reasons == [TOO_DEEP]
    assert await granted_to(worker_sessionmaker, tenant, child) == 0


async def test_one_deep_stored_claim_is_refused(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings
) -> None:  # fmt: skip
    """The owner's second review of the plan: a two-level envelope naming one claim of 2,000 levels."""
    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    result, tenant, child = await crossing(
        stack, 1, lambda ids: [nest(2_000)], lambda ids: {"a": {"b": ClaimRef(ids[0]).to_json()}}
    )
    assert result.reasons == [TOO_DEEP]
    assert await granted_to(worker_sessionmaker, tenant, child) == 0


async def test_a_value_at_the_limit_through_claims_crosses(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings
) -> None:  # fmt: skip
    """1 (the envelope) + 31 (the first claim) + 32 (the second) = 64 levels: within it."""
    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    values = lambda ids: [nest(31, ClaimRef(ids[1]).to_json()), nest(32)]  # noqa: E731
    result, tenant, child = await crossing(stack, 2, values, lambda ids: {"x": ClaimRef(ids[0]).to_json()})
    assert result.reasons == []
    assert await granted_to(worker_sessionmaker, tenant, child) == 2


async def test_a_value_at_the_limit_whose_deepest_leaf_is_a_handle_crosses(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings
) -> None:  # fmt: skip
    """The review's L1: 64 levels whose deepest leaf the parent claimed (a spilled string, a sensitive value) put the
    handle object at level 65 of the envelope; resolved, the value is 64 levels: it crosses."""
    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    result, tenant, child = await crossing(stack, 1, lambda ids: ["a claimed leaf"],
                                           lambda ids: nest(64, ClaimRef(ids[0]).to_json()))  # fmt: skip
    assert result.reasons == []
    assert await granted_to(worker_sessionmaker, tenant, child) == 1
