# SPDX-License-Identifier: Apache-2.0
"""The deployment's ingress capacity (the owner's rulings 2 on 2b-4b's M3 checkpoints 2 and 3): the sustained starts
measured on its own Temporal, the headroom's share of them its ingress may use, and the agreed wait a tenant's queued
webhook requests may stand for. Changed only through the platform admin's API (D11), audited with that admin's id;
each value checked; none set by default, and until set, ingress keeps its development-only rates and cap."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.platform import service

pytestmark = pytest.mark.usefixtures("development_deployment")
SAID = "Measured on this deployment's Temporal."


async def stored(owner) -> tuple:  # type: ignore[no-untyped-def]
    async with owner() as s:
        found = await s.execute(text("select ingress_starts_per_s, ingress_headroom, ingress_queue_wait_s "
                                     "from platform_settings"))  # fmt: skip
        return tuple(found.one())


async def an_admin(owner) -> uuid.UUID:  # type: ignore[no-untyped-def]
    from dewpoint.core.auth.users import create_user

    async with owner() as s, s.begin():
        return (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password="violet-otter-canyon-42")).id


async def test_a_change_keeps_what_it_leaves_out_and_is_audited_with_its_actor(api_sessionmaker, owner_sessionmaker):
    assert await stored(owner_sessionmaker) == (None, None, None)
    actor = await an_admin(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        all_three = {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 300}
        whole = await service.set_ingress_capacity(s, change=all_three, attestation=SAID, actor_id=actor)
    async with api_sessionmaker() as s, s.begin():
        kept = await service.set_ingress_capacity(s, change={"queue_wait_s": 600}, attestation=SAID, actor_id=actor)
    assert whole["problems"] == [] and kept == {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 600,
                                                "problems": []}  # fmt: skip
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select actor_id, details from audit_log "
                                     "where action = 'platform.ingress_capacity.set' order by seq"))  # fmt: skip
        assert [(a, d["before"]["queue_wait_s"], d["after"]["queue_wait_s"], d["attestation"]) for a, d in found] == [
            (actor, None, 300, SAID), (actor, 300, 600, SAID),
        ]  # fmt: skip


OUT_OF_RANGE = [{"starts_per_s": 0.0}, {"headroom": 0.0}, {"headroom": 1.5}, {"queue_wait_s": 0},
                {"starts_per_s": float("inf")}, {"starts_per_s": float("nan")}, {"headroom": float("nan")},
                {"tenants": 3}]  # fmt: skip


@pytest.mark.parametrize("change", OUT_OF_RANGE)
async def test_a_value_out_of_range_is_refused(api_sessionmaker, owner_sessionmaker, change) -> None:
    actor = await an_admin(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        with pytest.raises(ValueError, match="ingress capacity"):
            await service.set_ingress_capacity(s, change=change, attestation=SAID, actor_id=actor)


async def test_only_the_apis_role_changes_it_never_the_admins_login_directly(
    admin_sessionmaker, owner_sessionmaker
) -> None:  # fmt: skip
    """D11: the CLI asks the API, which records the admin's id; the admin's database login has no way around it."""
    async with admin_sessionmaker() as s, s.begin():
        with pytest.raises(DBAPIError):
            await s.execute(text("select set_ingress_capacity(cast('{\"queue_wait_s\": 1}' as jsonb))"))
    assert await stored(owner_sessionmaker) == (None, None, None)


@pytest.mark.parametrize("starts", ["NaN", "Infinity"])
async def test_its_row_refuses_a_starts_rate_that_isnt_a_finite_number(owner_sessionmaker, starts: str) -> None:
    """The fresh M3 review 3: PostgreSQL holds NaN above every number, so `> 0` alone took it, and every match would
    then fail computing the cap."""
    async with owner_sessionmaker() as s, s.begin():
        with pytest.raises(DBAPIError):
            await s.execute(text(f"update platform_settings set ingress_starts_per_s = '{starts}'"))  # noqa: S608
    async with owner_sessionmaker() as s, s.begin():  # and its other values, whoever writes them
        with pytest.raises(DBAPIError):
            await s.execute(text("update platform_settings set ingress_headroom = 2"))
