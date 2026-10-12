# SPDX-License-Identifier: Apache-2.0
"""Releases through the API (2b-4b M4 recovery, task 8; design revisions 7 and 8 §1). `held/release` and
`held/release-many` record a pending command, 202, with the holds it shows (its snapshot, each with its token), and
release nothing: the dispatcher's leader does, once their operator confirms it through their recovery login, and those
holds alone. A platform admin on a fresh second factor, as before; an item not held, or no hold eligible, records
nothing."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from tests.apps.api.test_erasure_api import admin_of, tenant_of
from tests.apps.api.test_recovery_api import aged, audited, held, url


async def _holds(owner: Any, tenant: uuid.UUID) -> dict[tuple[str, str], int]:
    async with owner() as s:
        found = await s.execute(text("select kind, item_id, hold_id from work_failures where tenant_id = :t "
                                     "and held_at is not null"), {"t": tenant})  # fmt: skip
        return {(k, str(i)): h for k, i, h in found}


async def _commands(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from operator_commands"))).scalar_one())


async def test_a_release_records_a_command_showing_its_hold_and_releases_nothing(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item = uuid.uuid4()
    await held(owner_sessionmaker, tenant, "dispatch", item)
    before = await _holds(owner_sessionmaker, tenant)
    asked = {"kind": "dispatch", "item_id": str(item), "idempotency_key": "release-1"}
    async with admin:
        made = await admin.post(url(tenant, "held/release"), json=asked)
        assert made.status_code == 202, made.json()
        body = made.json()
        assert (body["kind"], body["work_kind"], body["item_id"], body["status"]) == (
            "release_held", "dispatch", str(item), "pending")  # fmt: skip
        assert [(h["kind"], h["item_id"], h["hold_id"]) for h in body["holds"]] == [
            ("dispatch", str(item), before[("dispatch", str(item))])]  # fmt: skip
        again = await admin.post(url(tenant, "held/release"), json=asked)
        assert (again.status_code, again.json()["id"]) == (200, body["id"])
    assert await _holds(owner_sessionmaker, tenant) == before  # nothing released
    assert [(a, t) for a, t, _ in await audited(owner_sessionmaker, "operator.command.request")] == [
        (admin_id, body["id"])]  # fmt: skip


async def test_releasing_an_item_not_held_records_nothing(app, owner_sessionmaker, api_settings) -> None:
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    counting = uuid.uuid4()
    await held(owner_sessionmaker, tenant, "match", counting, hold=False)
    async with admin:
        for item, kind in ((uuid.uuid4(), "dispatch"), (counting, "match")):
            refused = await admin.post(url(tenant, "held/release"), json={"kind": kind, "item_id": str(item)})
            assert (refused.status_code, refused.json()) == (404, {"error": "not_held"})
    assert await _commands(owner_sessionmaker) == 0


async def test_a_bulk_release_records_the_oldest_holds_of_its_kind_held_before_bounded(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    (tenant, _), (other, _) = [await tenant_of(app, owner_sessionmaker, api_settings) for _ in range(2)]
    old = await aged(owner_sessionmaker, tenant, "cancel", 120, n=3)
    await aged(owner_sessionmaker, tenant, "cancel", 5)  # newer
    await aged(owner_sessionmaker, tenant, "dispatch", 120)  # another kind
    await aged(owner_sessionmaker, other, "cancel", 120)  # another tenant's
    before = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    query = {"kind": "cancel", "held_before": before}
    holds = await _holds(owner_sessionmaker, tenant)
    async with admin:
        made = await admin.post(url(tenant, "held/release-many"), json=query | {"max": 2})
        assert made.status_code == 202, made.json()
        body = made.json()
        assert (body["kind"], body["work_kind"], body["held_before"], body["max_holds"], body["item_id"]) == (
            "release_held_many", "cancel", before, 2, None)  # fmt: skip
        oldest = sorted(str(i) for i in old)[:2]  # held at the same time: by item
        assert [(h["item_id"], h["hold_id"]) for h in body["holds"]] == [(i, holds[("cancel", i)]) for i in oldest]
        too_many = await admin.post(url(tenant, "held/release-many"), json=query | {"max": 1001})
        no_kind = await admin.post(url(tenant, "held/release-many"), json={"held_before": before, "max": 10})
        assert (too_many.status_code, no_kind.status_code) == (422, 422)
        long_ago = {"kind": "cancel", "held_before": "2000-01-01T00:00:00+00:00", "max": 10}
        none = await admin.post(url(tenant, "held/release-many"), json=long_ago)
        assert (none.status_code, none.json()) == (404, {"error": "not_held"})
    assert await _holds(owner_sessionmaker, tenant) == holds  # nothing released
    assert await _commands(owner_sessionmaker) == 1
