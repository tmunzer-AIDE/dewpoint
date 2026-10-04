# SPDX-License-Identifier: Apache-2.0
"""After authentication, every attempt goes through `record_inbound_events` (engine 2b spec §8.3; "Work limits" in the
2b-3b outline): over the endpoint's body limit 413, malformed 400 (both paying their rate budget), short of tokens 429
with `Retry-After`, an id reused for other content 409, over a pending quota 429 (`Retry-After` 30), over a retained cap
429 without one, recorded 200 with its counts, answered only once committed. A tenant without an inbound key fails
closed."""

import json
import os
import uuid

import pytest
from sqlalchemy import text

from dewpoint.apps.ingress import main
from dewpoint.apps.ingress.main import create_app
from dewpoint.core.crypto import events
from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET, IngressKey
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress import keys as event_keys
from tests.apps.ingress.support import (
    SECRET,
    Clock,
    bearer,
    bearer_endpoint,
    client,
    hmac_endpoint,
    sealed_dedupe_key,
    settings,
    signed,
)
from tests.core.ingress.support import KEYRING, endpoint, events_of, state

pytestmark = pytest.mark.usefixtures("development_deployment")
MIB = 1024 * 1024
ALARMS = json.dumps({"topic": "alarms", "events": [{"id": "a-1", "type": "ap_down"}, {"id": "a-2", "type": "ap_up"}]})


@pytest.fixture
async def app(pg_url, _test_users):  # type: ignore[no-untyped-def]
    application = create_app(settings(pg_url), clock=Clock())
    yield application
    await application.state.engine.dispose()


async def _post(app, endpoint_id: uuid.UUID, body: bytes | str, **headers: str):  # type: ignore[no-untyped-def]
    raw = body.encode() if isinstance(body, str) else body
    async with client(app) as c:
        return await c.post(f"/hooks/{endpoint_id}", content=raw, headers=bearer() | headers)


async def test_a_batch_is_recorded_sealed_to_its_tenant_and_counted(
    app, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant, endpoint_id = await bearer_endpoint(
        owner_sessionmaker, id_source="pointer", id_pointer="/id", events_pointer="/events"
    )
    response = await _post(app, endpoint_id, ALARMS)
    assert (response.status_code, response.json()) == (200, {"accepted": 2, "duplicates": 0})
    rows = await events_of(owner_sessionmaker, endpoint_id)
    assert [r["status"] for r in rows] == ["pending", "pending"]
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        private = await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, 1)
    opened = sorted(
        events.open_sealed(private, tenant_id=tenant, endpoint_id=endpoint_id, event_id=r["id"], blob=r["sealed"])
        for r in rows
    )
    assert opened == [b'{"id":"a-1","type":"ap_down"}', b'{"id":"a-2","type":"ap_up"}']
    assert (await state(owner_sessionmaker, endpoint_id))["pending_events"] == 2


async def test_a_retried_batch_is_acknowledged_and_an_id_reused_for_other_content_is_409(
    app, owner_sessionmaker
) -> None:
    _, endpoint_id = await hmac_endpoint(
        owner_sessionmaker, id_source="pointer", id_pointer="/id", events_pointer="/events"
    )
    body = ALARMS.encode()
    assert (await _post(app, endpoint_id, body, **signed(body))).json() == {"accepted": 2, "duplicates": 0}
    reformatted = json.dumps(json.loads(body), indent=2).encode()  # the same content, other bytes
    again = await _post(app, endpoint_id, reformatted, **signed(reformatted))
    assert (again.status_code, again.json()) == (200, {"accepted": 0, "duplicates": 2})
    reused = json.dumps({"events": [{"id": "a-3"}, {"id": "a-1", "type": "other"}]}).encode()
    refused = await _post(app, endpoint_id, reused, **signed(reused))
    assert (refused.status_code, refused.json()) == (409, {"error": "event_id_reused"})
    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 2  # a-3 wasn't recorded either


async def test_without_ids_each_attempt_is_new_events(app, owner_sessionmaker) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
    for _ in range(2):
        assert (await _post(app, endpoint_id, '{"ping": 1}')).json() == {"accepted": 1, "duplicates": 0}
    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 2  # at-least-once, as documented


async def test_a_header_id_names_the_batch(app, owner_sessionmaker) -> None:
    _, endpoint_id = await bearer_endpoint(
        owner_sessionmaker, id_source="header", id_header="x-delivery", events_pointer="/events"
    )
    body = '{"events": [{"v": 1}, {"v": 1}]}'
    assert (await _post(app, endpoint_id, body, **{"x-delivery": "d-9"})).json() == {"accepted": 2, "duplicates": 0}
    assert (await _post(app, endpoint_id, body, **{"x-delivery": "d-9"})).json() == {"accepted": 0, "duplicates": 2}
    missing = await _post(app, endpoint_id, body)
    assert (missing.status_code, missing.json()) == (400, {"error": "malformed"})


@pytest.mark.parametrize(
    "body",
    [
        b'{"a": 1, "a": 1}',
        b'{"a": 1e400}',  # overflow (the owner's M2 check)
        b'{"a": "\\ud800"}',  # an escaped unpaired surrogate (the owner's M2 check)
        b'{"a": NaN}',
        b"[1]",
        b"\xff",
    ],
)
async def test_a_malformed_body_is_400_and_pays_its_budget(app, owner_sessionmaker, body: bytes) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
    before = await state(owner_sessionmaker, endpoint_id)
    response = await _post(app, endpoint_id, body)
    assert (response.status_code, response.json()) == (400, {"error": "malformed"})
    after = await state(owner_sessionmaker, endpoint_id)
    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
    assert await events_of(owner_sessionmaker, endpoint_id) == []


async def test_a_body_over_the_endpoints_limit_is_413_and_pays_for_its_bytes(app, owner_sessionmaker) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, body_limit=100)
    before = await state(owner_sessionmaker, endpoint_id)
    response = await _post(app, endpoint_id, json.dumps({"pad": "x" * 200}))
    assert (response.status_code, response.json()) == (413, {"error": "too_large"})
    after = await state(owner_sessionmaker, endpoint_id)
    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
    assert before["byte_tokens"] - after["byte_tokens"] >= 211
    assert (await _post(app, endpoint_id, '{"pad": "fits"}')).status_code == 200


async def test_short_of_tokens_is_429_with_the_wait(app, owner_sessionmaker) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, request_burst=1, request_per_s=0.01, request_tokens=1)
    assert (await _post(app, endpoint_id, '{"n": 1}')).status_code == 200
    limited = await _post(app, endpoint_id, '{"n": 2}')
    assert (limited.status_code, limited.json()) == (429, {"error": "rate_limited"})
    assert 90 <= int(limited.headers["retry-after"]) <= 100


async def test_over_a_pending_quota_is_429_retry_in_30(app, owner_sessionmaker) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, pending_events_max=1)
    assert (await _post(app, endpoint_id, '{"n": 1}')).status_code == 200
    over = await _post(app, endpoint_id, '{"n": 2}')
    assert (over.status_code, over.json(), over.headers["retry-after"]) == (429, {"error": "quota_exceeded"}, "30")


async def test_over_a_retained_cap_is_429_without_a_retry_after(app, owner_sessionmaker) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, retained_events_max=1)
    assert (await _post(app, endpoint_id, '{"n": 1}')).status_code == 200
    full = await _post(app, endpoint_id, '{"n": 2}')
    assert (full.status_code, full.json()) == (429, {"error": "retained_full"})
    assert "retry-after" not in full.headers


async def test_a_tenant_without_an_inbound_key_fails_closed(app, owner_sessionmaker) -> None:
    tenant, endpoint_id = await bearer_endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("delete from tenant_event_keys where tenant_id = :t"), {"t": tenant})
    response = await _post(app, endpoint_id, '{"n": 1}')
    assert (response.status_code, response.json()) == (503, {"error": "unavailable"})
    assert await events_of(owner_sessionmaker, endpoint_id) == []


async def test_an_endpoint_disabled_after_it_was_resolved_is_the_same_401(app, owner_sessionmaker, monkeypatch) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
    resolved = main.resolve

    async def then_disabled(s, found_id):  # type: ignore[no-untyped-def]
        endpoint = await resolved(s, found_id)
        async with owner_sessionmaker() as o, o.begin():
            await o.execute(text("update webhook_endpoints set enabled = false where id = :e"), {"e": found_id})
        return endpoint

    monkeypatch.setattr(main, "resolve", then_disabled)
    response = await _post(app, endpoint_id, '{"n": 1}')
    assert (response.status_code, response.content) == (401, b"")
    assert await events_of(owner_sessionmaker, endpoint_id) == []


@pytest.mark.parametrize("sealed", ["malformed", "another key's"])
async def test_an_unopenable_hmac_secret_is_the_401_and_an_unopenable_dedupe_key_503(
    app, owner_sessionmaker, sealed
) -> None:
    other = IngressKey("ingress-2", os.urandom(32))
    endpoint_id = uuid.uuid4()
    secret = b"\x01" if sealed == "malformed" else other.seal(HMAC_SECRET, str(endpoint_id), SECRET)
    _, signed_endpoint = await endpoint(
        owner_sessionmaker, endpoint_id, auth_kind="hmac", bearer_digest=None, hmac_secret=secret,
        signature_header="x-signature", timestamp_header="x-timestamp", dedupe_key=sealed_dedupe_key(endpoint_id),
    )  # fmt: skip
    body = b'{"n": 1}'
    refused = await _post(app, signed_endpoint, body, **signed(body))
    assert (refused.status_code, refused.content) == (401, b"")
    dedupe_id = uuid.uuid4()
    dedupe = b"\x01" if sealed == "malformed" else other.seal(DEDUPE_KEY, str(dedupe_id), os.urandom(32))
    _, pointer_endpoint = await bearer_endpoint(
        owner_sessionmaker, id_source="pointer", id_pointer="/id", dedupe_key=dedupe
    )
    unavailable = await _post(app, pointer_endpoint, '{"id": 1}')
    assert (unavailable.status_code, unavailable.json()) == (503, {"error": "unavailable"})
    assert await events_of(owner_sessionmaker, pointer_endpoint) == []


@pytest.mark.parametrize("size", [70_000, 5 * MIB])
async def test_at_the_smallest_burst_a_body_up_to_the_global_cap_past_a_tiny_limit_is_413(
    app, owner_sessionmaker, size: int
) -> None:
    """The owner's M2 review: with `body_limit=1` the schema used to allow a 64,005-byte burst, and a 70,000-byte body
    (under the global cap) was a 429 for ever, never its 413. Now the smallest burst the schema allows covers the
    global cap: from a full bucket, any body ingress reads before authenticating gets its 413, paid for."""
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, body_limit=1, byte_burst=5 * MIB, byte_tokens=5 * MIB)
    response = await _post(app, endpoint_id, b"x" * size)
    assert (response.status_code, response.json()) == (413, {"error": "too_large"})
    after = await state(owner_sessionmaker, endpoint_id)
    assert after["request_tokens"] == pytest.approx(99, abs=0.1)
    assert 5 * MIB - after["byte_tokens"] == pytest.approx(size, abs=1)
