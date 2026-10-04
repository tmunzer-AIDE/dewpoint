# SPDX-License-Identifier: Apache-2.0
"""CI's schedule proof (engine 2b spec §8.2, §12; 2b-3a): a schedule of the synthetic workflow `seed-workflow.py` made,
every 60 s in a non-UTC time zone, so the API's image must hold the IANA time zone data to accept it; the Compose
dispatcher's sync creates its Temporal Schedule and its admission worker admits each firing. Run in the API's image,
as the API's database login:

    docker compose run --rm -T api python - create <tenant> <workflow> < ci/schedule-proof.py   # prints its id
    docker compose run --rm -T api python - wait <tenant> <schedule> <seconds> < ci/schedule-proof.py

`wait` exits 0 once the schedule's first run succeeded, and 1 when the time is up, printing only states and fixed
codes. Nothing here is real data."""

import asyncio
import sys
import uuid

from sqlalchemy import text

from dewpoint.apps import schedules
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope

ZONE = "Europe/Paris"  # not UTC: accepted only when the image holds the time zone data


async def create(settings: Settings, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> uuid.UUID:
    """The schedule's id: every 60 s, in `ZONE`, made by the tenant's owner."""
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            owner = (
                await s.execute(text("select user_id from memberships where tenant_id = :t and role = 'owner'"),
                                {"t": tenant_id})
            ).scalar_one()  # fmt: skip
            timing = {"cron": None, "every_s": 60, "offset_s": 0, "time_zone": ZONE, "catchup_window_s": 600}
            created = await schedules.create(s, keys, tenant_id=tenant_id, actor_id=owner, workflow_id=workflow_id,
                                             timing=timing, mode="live", input={}, enabled=True)  # fmt: skip
        return created.id
    finally:
        await engine.dispose()


async def state(settings: Settings, tenant_id: uuid.UUID, schedule_id: uuid.UUID) -> tuple[str | None, str | None]:
    """The first scheduled run's state (its run's status once it started, else its request's), and the schedule's
    sync code, if its last sync failed."""
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            await tenant_scope(s, tenant_id)
            found = (
                await s.execute(
                    text("select coalesce(r.status, q.status) from run_requests q left join runs r on r.id = q.id "
                         "and q.status = 'started' where q.idempotency_key like :key order by q.queued_at limit 1"),
                    {"key": f"sched:{schedule_id}:%"},
                )
            ).scalar_one_or_none()  # fmt: skip
            code = (
                await s.execute(text("select sync_error from schedules where id = :i"), {"i": schedule_id})
            ).scalar_one_or_none()
        return found, code
    finally:
        await engine.dispose()


async def wait(settings: Settings, tenant_id: uuid.UUID, schedule_id: uuid.UUID, seconds: int) -> bool:
    found, code = None, None
    for _ in range(seconds):
        found, code = await state(settings, tenant_id, schedule_id)
        if found in ("succeeded", "failed", "cancelled", "refused", "dead"):
            break
        await asyncio.sleep(1)
    print(f"first scheduled run: {found}; last sync: {code or 'ok'}")
    return found == "succeeded"


if __name__ == "__main__":
    command, tenant, *rest = sys.argv[1:]
    if command == "create":
        print(asyncio.run(create(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0]))))
    else:
        sys.exit(0 if asyncio.run(wait(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0]), int(rest[1]))) else 1)
