# SPDX-License-Identifier: Apache-2.0
"""CI's ingress proof (engine 2b spec §8.3, §12; 2b-3b): an HMAC endpoint of the synthetic tenant `seed-workflow.py`
made, its events' ids at `/id`, bound to the seeded workflow; CI posts a signed event through nginx to ingress; the
Compose dispatcher matches it, starts it and the worker runs it. Run in the API's image, as the API's database login
(which holds the ingress key and the KEK):

    docker compose run --rm -T api python - create <tenant> <workflow> < ci/ingress-proof.py   # prints id and secret
    docker compose run --rm -T api python - wait <tenant> <endpoint> <seconds> < ci/ingress-proof.py

`create` prints the endpoint's id and its secret on its last line, for the caller's shell only. `wait` exits 0 once the
endpoint's first event's run succeeded, and 1 when the time is up, printing only states. Nothing here is real data."""

import asyncio
import sys
import uuid

from sqlalchemy import text

from dewpoint.apps import webhooks
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto.ingress import IngressKey
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope

ENDPOINT = {
    "name": "CI proof", "enabled": True, "auth": "hmac", "tolerance_s": 300, "allowlist": [], "body_limit": 1024 * 1024,
    "id_source": "pointer", "id_pointer": "/id",
}  # fmt: skip


async def create(settings: Settings, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """The endpoint's id and its secret: made by the tenant's owner, bound to the workflow."""
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            owner = (
                await s.execute(text("select user_id from memberships where tenant_id = :t and role = 'owner'"),
                                {"t": tenant_id})
            ).scalar_one()  # fmt: skip
            endpoint, secret = await webhooks.create_endpoint(
                s, Keyring(KekSet.from_settings(settings)), IngressKey.from_settings(settings), tenant_id=tenant_id,
                actor_id=owner, given=ENDPOINT,
            )  # fmt: skip
            await webhooks.create_binding(s, endpoint_id=endpoint.id, actor_id=owner, workflow_id=workflow_id,
                                          filter=[], enabled=True)  # fmt: skip
        return endpoint.id, secret
    finally:
        await engine.dispose()


async def state(settings: Settings, tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> tuple[str | None, str | None]:
    """The endpoint's first event's status, and its request's state (its run's status once it started)."""
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            await tenant_scope(s, tenant_id)
            found = (
                await s.execute(
                    text("select e.status, coalesce(r.status, q.status) from inbound_events e "
                         "left join run_requests q on q.idempotency_key like 'evt:' || e.id || ':%' "
                         "left join runs r on r.id = q.id and q.status = 'started' "
                         "where e.endpoint_id = :e order by e.received_at limit 1"),
                    {"e": endpoint_id},
                )
            ).first()  # fmt: skip
        return (found[0], found[1]) if found else (None, None)
    finally:
        await engine.dispose()


async def wait(settings: Settings, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, seconds: int) -> bool:
    event, run = None, None
    for _ in range(seconds):
        event, run = await state(settings, tenant_id, endpoint_id)
        if run in ("succeeded", "failed", "cancelled", "refused", "dead") or event in ("unmatched", "dead"):
            break
        await asyncio.sleep(1)
    print(f"first event: {event}; its run: {run}")
    return run == "succeeded"


if __name__ == "__main__":
    command, tenant, *rest = sys.argv[1:]
    if command == "create":
        endpoint_id, secret = asyncio.run(create(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0])))
        print(endpoint_id, secret)
    else:
        sys.exit(0 if asyncio.run(wait(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0]), int(rest[1]))) else 1)
