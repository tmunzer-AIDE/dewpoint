# SPDX-License-Identifier: Apache-2.0
"""`record_inbound_events`, ingress's privileged boundary (engine 2b spec §8.3; the owner's rulings and second review on
the 2b-3b outline). Under the tenant's lifecycle lock (shared), the endpoint's row and then the tenant's counter row,
it spends the rate budget first and commits it whatever it decides; it checks the batch itself (its count, its actual
sealed bytes, its shape), never trusting the caller's sizes; it acknowledges a duplicate and refuses an id reused for
other content; it applies the pending quotas and the retained caps; and it inserts events all or nothing. It never
raises for a refusal: it returns the outcome."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from dewpoint.core.crypto import events
from dewpoint.core.ingress import identity
from tests.core.ingress.support import digest, endpoint, events_of, key, record, sealed_layout, state, tenant_state

pytestmark = pytest.mark.usefixtures("development_deployment")


async def test_events_are_recorded_pending_and_counted(owner_sessionmaker, ingress_sessionmaker) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    before = await state(owner_sessionmaker, endpoint_id)
    outcome = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"a" * 70), (None, None, b"b" * 80)],
                           read=200)  # fmt: skip
    assert outcome == {"outcome": "recorded", "accepted": 2, "duplicates": 0}
    rows = await events_of(owner_sessionmaker, endpoint_id)
    assert sorted((r["status"], r["size_bytes"], r["tenant_id"]) for r in rows) == [
        ("pending", 70, tenant), ("pending", 80, tenant)
    ]  # fmt: skip
    after, counters = await state(owner_sessionmaker, endpoint_id), await tenant_state(owner_sessionmaker, tenant)
    assert (after["pending_events"], after["pending_bytes"], after["retained_events"], after["retained_bytes"]) == (
        2, 150, 2, 150
    )  # fmt: skip
    assert (counters["pending_events"], counters["retained_bytes"]) == (2, 150)
    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
    assert before["event_tokens"] - after["event_tokens"] == pytest.approx(2, abs=1)
    assert before["byte_tokens"] - after["byte_tokens"] == pytest.approx(200, abs=50)


async def test_a_duplicate_is_acknowledged_and_an_id_reused_for_other_content_refuses_the_batch(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker, request_per_s=0.001, event_per_s=0.001)  # no refill to speak of
    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
    again = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one"), (key(2), digest(2), b"two")])
    assert again == {"outcome": "recorded", "accepted": 1, "duplicates": 1}
    before = await state(owner_sessionmaker, endpoint_id)
    reused = await record(ingress_sessionmaker, endpoint_id, [(key(3), digest(3), b"three"), (key(1), digest(9), b"x")])
    assert reused == {"outcome": "event_id_reused"}
    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 2  # the batch recorded nothing, key 3 included
    after = await state(owner_sessionmaker, endpoint_id)
    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)  # it paid its budget
    assert before["event_tokens"] - after["event_tokens"] == pytest.approx(2, abs=1)


async def test_within_one_batch_a_repeated_id_is_a_duplicate_or_a_reuse(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker)
    same = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one"), (key(1), digest(1), b"one")])
    assert same == {"outcome": "recorded", "accepted": 1, "duplicates": 1}
    other = await record(ingress_sessionmaker, endpoint_id, [(key(2), digest(2), b"two"), (key(2), digest(3), b"t")])
    assert other == {"outcome": "event_id_reused"}


async def test_events_without_ids_are_each_their_own(owner_sessionmaker, ingress_sessionmaker) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker)
    twice = await record(ingress_sessionmaker, endpoint_id, [(None, None, b"same"), (None, None, b"same")])
    assert twice == {"outcome": "recorded", "accepted": 2, "duplicates": 0}


@pytest.mark.parametrize("refusal", ["too_large", "malformed"])
async def test_a_refusal_made_after_authentication_pays_its_request_and_its_bytes(
    owner_sessionmaker, ingress_sessionmaker, refusal: str
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker)
    before = await state(owner_sessionmaker, endpoint_id)
    assert await record(ingress_sessionmaker, endpoint_id, refusal=refusal, read=5000) == {"outcome": refusal}
    after = await state(owner_sessionmaker, endpoint_id)
    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
    assert before["byte_tokens"] - after["byte_tokens"] == pytest.approx(5000, abs=100)
    assert after["event_tokens"] == pytest.approx(before["event_tokens"], abs=1)


async def test_short_of_tokens_an_attempt_spends_nothing_and_says_how_long_to_wait(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker, request_tokens=0, request_per_s=0.5)
    outcome = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
    assert outcome["outcome"] == "rate_limited" and 1 <= outcome["retry_after"] <= 2
    assert await events_of(owner_sessionmaker, endpoint_id) == []


async def test_repeated_refusals_exhaust_the_bucket_as_accepted_requests_do(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker, request_tokens=3, request_burst=3, request_per_s=0.01)
    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
    outcomes = [
        (await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(2), b"x")]))["outcome"] for _ in range(3)
    ]
    assert outcomes == ["event_id_reused", "event_id_reused", "rate_limited"]


async def test_a_pending_quota_refuses_new_events_but_not_a_duplicate(owner_sessionmaker, ingress_sessionmaker) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker, pending_events_max=1)
    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
    full = await record(ingress_sessionmaker, endpoint_id, [(key(2), digest(2), b"two")])
    assert full == {"outcome": "quota_exceeded", "retry_after": 30}
    duplicate = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
    assert duplicate == {"outcome": "recorded", "accepted": 0, "duplicates": 1}


@pytest.mark.parametrize("column", ["retained_events_max", "retained_bytes_max"])
async def test_a_full_retained_cap_fails_closed_without_a_retry_time(
    owner_sessionmaker, ingress_sessionmaker, column: str
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker, **{column: 4})
    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
    if column == "retained_events_max":
        async with owner_sessionmaker() as s, s.begin():  # matched since: no longer pending, still retained
            await s.execute(text("update webhook_endpoints set pending_events = 0, retained_events = 4 where id = :e"),
                            {"e": endpoint_id})  # fmt: skip
    outcome = await record(ingress_sessionmaker, endpoint_id, [(key(2), digest(2), b"two")])
    assert outcome == {"outcome": "retained_full"}


async def test_the_tenants_counters_and_quotas_apply_across_its_endpoints(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    tenant, first = await endpoint(owner_sessionmaker)
    await record(ingress_sessionmaker, first, [(key(1), digest(1), b"one")])
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenant_event_counters set pending_events_max = 1 where tenant_id = :t"),
                        {"t": tenant})  # fmt: skip
        second = uuid.uuid4()
        copy = text(
            "insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, bearer_digest, dedupe_key) "
            "select :n, tenant_id, 'other', created_by, auth_kind, bearer_digest, dedupe_key "
            "from webhook_endpoints where id = :e"
        )
        await s.execute(copy, {"n": second, "e": first})
    assert await record(ingress_sessionmaker, second, [(key(2), digest(2), b"two")]) == {
        "outcome": "quota_exceeded", "retry_after": 30
    }  # fmt: skip


async def test_the_function_checks_the_batch_itself_whatever_its_caller_says(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    """The owner's M1 check: called directly as the ingress login, an oversized or misshapen batch records nothing,
    and sizes are the sealed bytes' own, never the caller's."""
    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1000)
    one = [(key(1), digest(1), b"x")]
    for given, kwargs, expected in (
        ([(None, None, b"x")] * 501, {}, "malformed"),  # past 500 events
        ([(None, None, b"x" * 5200)], {}, "too_large"),  # past five times the body limit, plus 128 bytes an event
        (one, {"versions": [2]}, "key_retired"),  # a keypair version the tenant doesn't have (retryable)
        (one, {"versions": [1, 1]}, "malformed"),  # arrays that don't line up
        ([(key(1), None, b"x")], {}, "malformed"),  # a dedupe key without its digest
        ([(b"short", digest(1), b"x")], {}, "malformed"),  # a digest that isn't 32 bytes
        ([(None, None, b"x"), (None, None, b"y")], {"ids": [uuid.UUID(int=7)] * 2}, "malformed"),  # one id twice
        ([], {}, "malformed"),  # no events and no refusal
    ):
        assert await record(ingress_sessionmaker, endpoint_id, given, **kwargs) == {"outcome": expected}
    assert await events_of(owner_sessionmaker, endpoint_id) == []
    before = await state(owner_sessionmaker, endpoint_id)
    await record(ingress_sessionmaker, endpoint_id, [(None, None, b"z" * 900)], read=1)  # understating what it read
    after = await state(owner_sessionmaker, endpoint_id)
    assert before["byte_tokens"] - after["byte_tokens"] == pytest.approx(900, abs=100)  # the sealed bytes' own size
    assert (await events_of(owner_sessionmaker, endpoint_id))[0]["size_bytes"] == 900


@pytest.mark.parametrize("change", ["update webhook_endpoints set enabled = false where id = :e",
                                    "update tenants set status = 'erasing' where id = :t",
                                    "update tenants set status = 'erased' where id = :t"])  # fmt: skip
async def test_a_disabled_endpoint_or_an_erasing_tenant_records_and_spends_nothing(
    owner_sessionmaker, ingress_sessionmaker, change: str
) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(change), {"e": endpoint_id, "t": tenant})
    before = await state(owner_sessionmaker, endpoint_id)
    assert await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]) == {"outcome": "unknown"}
    assert (await state(owner_sessionmaker, endpoint_id))["request_tokens"] == before["request_tokens"]
    assert await record(ingress_sessionmaker, uuid.uuid4(), [(key(1), digest(1), b"one")]) == {"outcome": "unknown"}


async def lock_waiters(owner) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
                    ).scalar_one())  # fmt: skip


async def test_a_tenant_marked_erasing_first_is_refused_by_a_recording_that_waited(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    """The owner's second review: ingress holds the tenant's lifecycle lock shared while it records, so marking a tenant
    `erasing` (2b-4's transition takes that lock exclusively) can't commit between ingress's check and its insert."""
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:tenant:{tenant}"}
        )
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": tenant})
        pending = asyncio.create_task(record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]))
        for _ in range(300):
            if await lock_waiters(owner_sessionmaker):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the recording didn't wait for the tenant's lock")
    assert await pending == {"outcome": "unknown"}
    assert await events_of(owner_sessionmaker, endpoint_id) == []


async def test_a_recording_holds_the_tenants_lock_until_it_commits(owner_sessionmaker, ingress_sessionmaker) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    lock = text("select pg_advisory_xact_lock(hashtextextended(:k, 0))")
    async with ingress_sessionmaker() as s, s.begin():
        from tests.core.ingress.support import RECORD

        params = {"e": endpoint_id, "refusal": None, "read": 0, "ids": [uuid.uuid4()],
                  "sealed": [sealed_layout(b"one", 1)], "versions": [1], "dedupe": [key(1)],
                  "digests": [digest(1)]}  # fmt: skip
        assert dict((await s.execute(RECORD, params)).scalar_one())["outcome"] == "recorded"
        with pytest.raises(Exception, match="lock timeout|canceling statement"):
            async with owner_sessionmaker() as other, other.begin():
                await other.execute(text("set local lock_timeout = '200ms'"))
                await other.execute(lock, {"k": f"dewpoint:tenant:{tenant}"})
    async with owner_sessionmaker() as other, other.begin():  # committed: erasure may proceed, after the insert
        await other.execute(lock, {"k": f"dewpoint:tenant:{tenant}"})
    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 1


MIB = 1024 * 1024


async def test_a_body_whose_canonical_json_grows_is_still_accepted(owner_sessionmaker, ingress_sessionmaker) -> None:
    """The owner's M1 review: canonical floats grow (`1e15` is `1000000000000000.0`), so a permitted body's sealed
    bytes may pass twice its size; the backstop is five times the body limit, plus 128 bytes an event."""
    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1000)
    raw = '{"a":[' + ",".join(["1e15"] * 198) + "]}"
    assert len(raw) <= 1000
    sealed = identity.canonical(json.loads(raw)) + bytes(events.OVERHEAD)  # a sealed event's size
    assert len(sealed) > 2 * 1000 + 128  # what the first backstop refused
    outcome = await record(ingress_sessionmaker, endpoint_id, [(None, None, sealed)], read=len(raw))
    assert outcome == {"outcome": "recorded", "accepted": 1, "duplicates": 0}


async def test_every_permitted_request_fits_its_bursts(owner_sessionmaker) -> None:
    """A burst smaller than the largest charge an endpoint permits would refuse such a request for ever: the database
    refuses that endpoint, and the tenant's bursts cover the largest any endpoint permits. The largest byte charge is
    the larger of its largest sealed batch (five times its body limit plus 128 bytes for each of 500 events) and the
    largest body ingress reads before authenticating, the global 5 MiB cap: a body past a small limit is refused, and
    pays, for every byte read (the owner's M2 review). The largest event charge is 500."""
    for columns in (
        {"body_limit": 5 * MIB},
        {"body_limit": 5 * MIB, "byte_burst": 5 * 5 * MIB + 64_000 - 1},
        {"body_limit": 1, "byte_burst": 5 * 1 + 64_000},  # its sealed batch fits; a 5 MiB body read doesn't
        {"body_limit": 1000, "byte_burst": 5 * MIB - 1},
        {"event_burst": 499},
    ):
        with pytest.raises(IntegrityError):
            await endpoint(owner_sessionmaker, **columns)
    await endpoint(owner_sessionmaker, body_limit=5 * MIB, byte_burst=5 * 5 * MIB + 64_000)
    await endpoint(owner_sessionmaker, body_limit=1, byte_burst=5 * MIB)
    tenant, _ = await endpoint(owner_sessionmaker)
    for change in ("byte_burst = 25 * 1048576", "event_burst = 499"):
        with pytest.raises(IntegrityError):
            async with owner_sessionmaker() as s, s.begin():
                counters = text("insert into tenant_event_counters (tenant_id) values (:t) on conflict do nothing")
                await s.execute(counters, {"t": tenant})
                await s.execute(text(f"update tenant_event_counters set {change} where tenant_id = :t"), {"t": tenant})


async def test_a_request_at_the_largest_permitted_size_is_recorded_from_a_full_bucket(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1000, byte_burst=5 * MIB, byte_tokens=5 * MIB)
    largest = [(None, None, b"x" * (5 * 1000 + 128))]  # the backstop's largest for one event
    assert (await record(ingress_sessionmaker, endpoint_id, largest, read=1000))["outcome"] == "recorded"


async def test_a_refusal_of_the_largest_body_read_is_charged_from_a_full_smallest_bucket(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    """The owner's M2 review: a body as large as the global cap, past a 1-byte limit, is `too_large`, never short of
    tokens, from the smallest burst the schema allows."""
    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1, byte_burst=5 * MIB, byte_tokens=5 * MIB)
    outcome = await record(ingress_sessionmaker, endpoint_id, refusal="too_large", read=5 * MIB)
    assert outcome == {"outcome": "too_large"}


async def test_the_refill_is_reckoned_from_after_the_locks(owner_sessionmaker, ingress_sessionmaker) -> None:
    """The owner's M1 review: a recording that waited for its endpoint's row is credited with the time it waited, so
    contention never throttles it by a stale clock. Empty at half a token a second, it waits 2.5 s and has one."""
    _, endpoint_id = await endpoint(owner_sessionmaker, request_tokens=0, request_per_s=0.5)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("select 1 from webhook_endpoints where id = :e for update"), {"e": endpoint_id})
        await s.execute(text("update webhook_endpoints set refilled_at = clock_timestamp() where id = :e"),
                        {"e": endpoint_id})  # fmt: skip
        pending = asyncio.create_task(record(ingress_sessionmaker, endpoint_id, [(None, None, b"one")]))
        for _ in range(300):
            if await lock_waiters(owner_sessionmaker):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the recording didn't wait for the endpoint's row")
        await asyncio.sleep(2.5)
    assert (await pending)["outcome"] == "recorded"


V1 = b"\x01" + (1).to_bytes(4, "big")


@pytest.mark.parametrize(("sealed", "outcome"), [
    (V1 + b"x" * 60, "recorded"),  # the sealed layout at its smallest: an empty payload's
    (b"\x01" + (2).to_bytes(4, "big") + b"x" * 60, "malformed"),  # naming another version than the one given
    (b"\x02" + (1).to_bytes(4, "big") + b"x" * 60, "malformed"),  # another format
    (V1 + b"x" * 59, "malformed"),  # shorter than any sealed event
    (V1, "malformed"),
    (b"one", "malformed"),  # no layout at all
])  # fmt: skip
async def test_a_sealed_event_must_be_in_the_sealed_layout_naming_the_keypair_version_given_with_it(
    owner_sessionmaker, ingress_sessionmaker, sealed: bytes, outcome: str
) -> None:
    """2b-4 ruling D10 and the owner's M3 review: a sealed event is in the one documented layout (its format byte, the
    version of its keypair, at least the sealing's overhead), naming the version recorded beside it; otherwise the
    batch is refused whole, nothing recorded, as from a direct caller of the ingress role. No other layout is stored."""
    _, endpoint_id = await endpoint(owner_sessionmaker)  # keypair 1 only
    answer = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), sealed)], versions=[1], layout=False)
    assert answer["outcome"] == outcome
    assert len(await events_of(owner_sessionmaker, endpoint_id)) == (1 if outcome == "recorded" else 0)
