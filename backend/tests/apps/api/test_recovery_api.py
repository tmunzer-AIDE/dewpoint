# SPDX-License-Identifier: Apache-2.0
"""The operator's recovery through the API (the owner's rulings on the 2b-4b M3 design, rev 1 and 2), a platform
admin's: on an active MFA session, and for every change a second factor proven within the reauthentication window.

The API records a command, pending, for the dispatcher's leader to carry out (it has no Temporal client), only on an
item whose reason is recorded, with the operator's evidence where the item's history is gone; an operator's key
returns the same command again, and an item has one pending command of a kind. It releases a held item for the kind it
names, at once. Each change is audited with the operator, in its own transaction. It lists held items and recovery
reasons across tenants: ids, kinds, reasons and times."""

import uuid
from typing import Any

from sqlalchemy import text

from tests.apps.api.helpers import session_client
from tests.apps.api.test_erasure_api import admin_of, tenant_of

EVIDENCE = "Past the namespace's retention: checked in the Temporal UI."


def url(tenant: uuid.UUID, tail: str) -> str:
    return f"/api/v1/admin/tenants/{tenant}/{tail}"


async def reason(owner: Any, tenant: uuid.UUID, item: uuid.UUID, why: str = "run_history_missing") -> str:
    async with owner() as s, s.begin():
        since = await s.execute(text("insert into recovery_items (tenant_id, reason, item_id) values (:t, :r, :i) "
                                     "returning since"), {"t": tenant, "r": why, "i": item})  # fmt: skip
        return str(since.scalar_one().isoformat())


async def held(owner: Any, tenant: uuid.UUID, kind: str, item: uuid.UUID, *, hold: bool = True) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, "
                             "held_at) values (:t, :k, :i, 7, 'RuntimeError', now(), case when :h then now() end)"),
                        {"t": tenant, "k": kind, "i": item, "h": hold})  # fmt: skip


async def audited(owner: Any, action: str) -> list[tuple[Any, ...]]:
    async with owner() as s:
        found = await s.execute(text("select actor_id, target_id, details from audit_log where action = :a "
                                     "order by seq"), {"a": action})  # fmt: skip
        return [tuple(r) for r in found]


def asked(kind: str, item: uuid.UUID, key: str = "first", evidence: str = EVIDENCE) -> dict[str, str]:
    return {"kind": kind, "item_id": str(item), "evidence": evidence, "idempotency_key": key}


async def test_a_command_is_recorded_pending_for_the_leader_and_its_key_returns_it_again(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item = uuid.uuid4()
    since = await reason(owner_sessionmaker, tenant, item)
    async with admin:
        made = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item))
        assert made.status_code == 202, made.text
        shown = made.json()
        assert {k: shown[k] for k in ("kind", "item_id", "reason", "status", "outcome", "actor_id")} == {
            "kind": "record_lost_run", "item_id": str(item), "reason": "run_history_missing", "status": "pending",
            "outcome": None, "actor_id": str(admin_id),
        }  # fmt: skip
        assert shown["incident_since"] == since and "evidence" not in shown
        again = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item))
        assert (again.status_code, again.json()["id"]) == (200, shown["id"])  # the same command, not another
        other = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item, key="second"))
        assert (other.status_code, other.json()) == (409, {"error": "command_pending", "command_id": shown["id"]})
        reused = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", uuid.uuid4()))
        assert (reused.status_code, reused.json()) == (409, {"error": "idempotency_key_reused"})
        read = await admin.get(url(tenant, f"commands/{shown['id']}"))
        assert (read.status_code, read.json()) == (200, shown)
        assert (await admin.get(url(tenant, f"commands/{uuid.uuid4()}"))).status_code == 404
    assert await audited(owner_sessionmaker, "operator.command.request") == [
        (admin_id, shown["id"], {"kind": "record_lost_run", "item_id": str(item), "reason": "run_history_missing",
                                 "evidence": EVIDENCE}),
    ]  # fmt: skip


async def test_a_command_needs_its_items_reason_recorded_and_where_history_is_gone_evidence(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item, start = uuid.uuid4(), uuid.uuid4()
    await reason(owner_sessionmaker, tenant, item, "subrun_history_missing")
    await reason(owner_sessionmaker, tenant, start, "start_after_end")
    async with admin:
        unrecorded = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item))
        assert (unrecorded.status_code, unrecorded.json()) == (409, {"error": "not_recoverable"})  # not that reason
        blank = await admin.post(url(tenant, "commands"), json=asked("record_lost_subrun", item, evidence="  "))
        assert (blank.status_code, blank.json()) == (422, {"error": "evidence_required"})
        long = await admin.post(url(tenant, "commands"), json=asked("record_lost_subrun", item, evidence="x" * 501))
        assert long.status_code == 422
        unknown = await admin.post(url(tenant, "commands"), json=asked("drop_everything", item))
        assert unknown.status_code == 422
        # settle_ended may verify a terminal execution: no evidence needed to ask
        settled = await admin.post(url(tenant, "commands"), json=asked("settle_ended", start, evidence=""))
        assert (settled.status_code, settled.json()["reason"]) == (202, "start_after_end")
        dirty = asked("record_lost_subrun", item, key="b", evidence="seen\x00 gone\x1b")
        cleaned = await admin.post(url(tenant, "commands"), json=dirty)
        assert cleaned.status_code == 202, cleaned.text
    async with owner_sessionmaker() as s:
        stored = await s.execute(text("select evidence from operator_commands where id = :c"),
                                 {"c": cleaned.json()["id"]})  # fmt: skip
        assert "\x00" not in stored.scalar_one()


async def test_every_change_needs_a_platform_admin_with_a_fresh_second_factor(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item = uuid.uuid4()
    await reason(owner_sessionmaker, tenant, item)
    await held(owner_sessionmaker, tenant, "cancel", item)
    member, _ = await session_client(app, owner_sessionmaker, api_settings, "owner")
    stale, _ = await admin_of(app, owner_sessionmaker, api_settings, fresh=False)
    release = {"kind": "cancel", "item_id": str(item)}
    async with member, stale:
        for client, error in ((member, "forbidden"), (stale, "reauth_required")):
            made = await client.post(url(tenant, "commands"), json=asked("record_lost_run", item))
            freed = await client.post(url(tenant, "held/release"), json=release)
            assert [(r.status_code, r.json()) for r in (made, freed)] == [(403, {"error": error})] * 2
        assert (await member.get("/api/v1/admin/held")).status_code == 403
        assert (await stale.get("/api/v1/admin/held")).status_code == 200  # reading needs no fresh factor
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from operator_commands"))).scalar_one() == 0
        assert (await s.execute(text("select count(*) from work_failures"))).scalar_one() == 1


async def test_a_release_clears_the_hold_of_the_kind_it_names_alone_audited(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item, counting = uuid.uuid4(), uuid.uuid4()
    await held(owner_sessionmaker, tenant, "dispatch", item)
    await held(owner_sessionmaker, tenant, "cancel", item)
    await held(owner_sessionmaker, tenant, "match", counting, hold=False)
    async with admin:
        freed = await admin.post(url(tenant, "held/release"), json={"kind": "dispatch", "item_id": str(item)})
        assert (freed.status_code, freed.json()) == (200, {"released": True, "kind": "dispatch", "item_id": str(item)})
        again = await admin.post(url(tenant, "held/release"), json={"kind": "dispatch", "item_id": str(item)})
        assert (again.status_code, again.json()) == (404, {"error": "not_held"})
        unheld = await admin.post(url(tenant, "held/release"), json={"kind": "match", "item_id": str(counting)})
        assert (unheld.status_code, unheld.json()) == (404, {"error": "not_held"})  # counting, not held
    async with owner_sessionmaker() as s:
        left = (await s.execute(text("select kind from work_failures where tenant_id = :t order by kind"),
                                {"t": tenant})).scalars().all()  # fmt: skip
    assert left == ["cancel", "match"]
    assert await audited(owner_sessionmaker, "work_failure.release") == [
        (admin_id, str(item), {"kind": "dispatch", "item_id": str(item)})
    ]


async def test_the_listings_show_held_items_and_recovery_reasons_across_tenants(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    (a, _), (b, _) = [await tenant_of(app, owner_sessionmaker, api_settings) for _ in range(2)]
    first, second, counting = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await held(owner_sessionmaker, a, "cancel", first)
    await held(owner_sessionmaker, b, "reconcile_open", second)
    await held(owner_sessionmaker, a, "dispatch", counting, hold=False)
    await reason(owner_sessionmaker, b, second)
    async with admin:
        listed = (await admin.get("/api/v1/admin/held")).json()["items"]
        reasons = (await admin.get("/api/v1/admin/recovery")).json()["items"]
        assert (await admin.get("/api/v1/admin/held", params={"limit": 0})).status_code == 422
    assert {(i["tenant_id"], i["kind"], i["item_id"]) for i in listed} == {
        (str(a), "cancel", str(first)), (str(b), "reconcile_open", str(second)),
    }  # fmt: skip
    assert set(listed[0]) == {"tenant_id", "kind", "item_id", "errors", "last_error", "held_at"}
    assert [(r["tenant_id"], r["reason"], r["item_id"]) for r in reasons] == [
        (str(b), "run_history_missing", str(second))
    ]
    assert set(reasons[0]) == {"tenant_id", "reason", "item_id", "since", "last_seen_at"}


async def test_a_tenant_being_erased_takes_no_command_and_no_release(app, owner_sessionmaker, api_settings) -> None:
    """As require() fences a member's writes: the tenant's lifecycle lock, shared, then its status, so an erasure
    never races an operator's change (its step 1 waits for the change to commit, or the change sees `erasing`)."""
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item = uuid.uuid4()
    await reason(owner_sessionmaker, tenant, item)
    await held(owner_sessionmaker, tenant, "cancel", item)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": tenant})
    async with admin:
        made = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item))
        freed = await admin.post(url(tenant, "held/release"), json={"kind": "cancel", "item_id": str(item)})
    assert [(r.status_code, r.json()) for r in (made, freed)] == [(409, {"error": "tenant_erasing"})] * 2


async def test_two_requests_with_one_key_at_once_get_the_same_command(
    app, owner_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint: a second request with the key whose first lookup ran before the first
    request committed (simulated: its lookup misses) conflicts on insert, and still answers the same command, 200; a
    key reused for another item is still `idempotency_key_reused`."""
    from dewpoint.apps.api.routes import recovery

    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    item, other = uuid.uuid4(), uuid.uuid4()
    await reason(owner_sessionmaker, tenant, item)
    await reason(owner_sessionmaker, tenant, other)
    original, missed = recovery._mine, []

    async def raced(*args: Any) -> Any:
        if not missed:  # the request's first lookup, before the other committed
            missed.append(True)
            return None
        return await original(*args)

    async with admin:
        first = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item))
        monkeypatch.setattr(recovery, "_mine", raced)
        again = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", item))
        missed.clear()
        reused = await admin.post(url(tenant, "commands"), json=asked("record_lost_run", other))
    assert (first.status_code, again.status_code, again.json()["id"]) == (202, 200, first.json()["id"])
    assert (reused.status_code, reused.json()) == (409, {"error": "idempotency_key_reused"})
