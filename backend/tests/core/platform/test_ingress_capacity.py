# SPDX-License-Identifier: Apache-2.0
"""The deployment's ingress capacity (the owner's ruling 2 on 2b-4b's M3 checkpoint 2): the sustained starts measured
on its own Temporal, the headroom's share of them its ingress may use, and the agreed wait a tenant's queued webhook
requests may stand for. Set by the platform's admin, audited with what it was, each value checked; unset (none of
them by default), ingress keeps its development-only rates and cap."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.platform import service

pytestmark = pytest.mark.usefixtures("development_deployment")


async def stored(owner) -> tuple:  # type: ignore[no-untyped-def]
    async with owner() as s:
        found = await s.execute(text("select ingress_starts_per_s, ingress_headroom, ingress_queue_wait_s "
                                     "from platform_settings"))  # fmt: skip
        return tuple(found.one())


async def test_the_admin_sets_it_audited_with_what_it_was_and_may_unset_it(admin_sessionmaker, owner_sessionmaker):
    assert await stored(owner_sessionmaker) == (None, None, None)
    async with admin_sessionmaker() as s, s.begin():
        await service.set_ingress_capacity(s, starts_per_s=8.0, headroom=0.5, queue_wait_s=300, actor_id=None)
    async with admin_sessionmaker() as s, s.begin():
        await service.set_ingress_capacity(s, starts_per_s=None, headroom=None, queue_wait_s=None, actor_id=None)
    assert await stored(owner_sessionmaker) == (None, None, None)
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select details from audit_log where action = 'platform.ingress_capacity.set' "
                                     "order by seq"))  # fmt: skip
        assert [d for (d,) in found] == [
            {"before": {"starts_per_s": None, "headroom": None, "queue_wait_s": None},
             "after": {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 300}},
            {"before": {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 300},
             "after": {"starts_per_s": None, "headroom": None, "queue_wait_s": None}},
        ]  # fmt: skip


OUT_OF_RANGE = [(0.0, 0.5, 300), (8.0, 0.0, 300), (8.0, 1.5, 300), (8.0, 0.5, 0), (float("inf"), 0.5, 300),
                (float("nan"), 0.5, 300), (8.0, float("nan"), 300)]  # fmt: skip


@pytest.mark.parametrize(("starts", "headroom", "wait"), OUT_OF_RANGE)
async def test_a_value_out_of_range_is_refused(admin_sessionmaker, starts: float, headroom: float, wait: int) -> None:
    async with admin_sessionmaker() as s, s.begin():
        with pytest.raises(ValueError, match="ingress capacity"):
            await service.set_ingress_capacity(s, starts_per_s=starts, headroom=headroom, queue_wait_s=wait,
                                               actor_id=None)  # fmt: skip


async def test_only_the_admin_sets_it(api_sessionmaker, owner_sessionmaker) -> None:
    async with api_sessionmaker() as s, s.begin():
        with pytest.raises(DBAPIError):
            await s.execute(text("select set_ingress_capacity(8, 0.5, 300)"))
    async with owner_sessionmaker() as s, s.begin():  # and its row checks each value whoever writes it
        with pytest.raises(DBAPIError):
            await s.execute(text("update platform_settings set ingress_headroom = 2"))


@pytest.mark.parametrize("starts", ["NaN", "Infinity"])
async def test_its_row_refuses_a_starts_rate_that_isnt_a_finite_number(owner_sessionmaker, starts: str) -> None:
    """The fresh M3 review 3: PostgreSQL holds NaN above every number, so `> 0` alone took it, and every match would
    then fail computing the cap."""
    async with owner_sessionmaker() as s, s.begin():
        with pytest.raises(DBAPIError):
            await s.execute(text(f"update platform_settings set ingress_starts_per_s = '{starts}'"))  # noqa: S608
