# SPDX-License-Identifier: Apache-2.0
"""What becomes of an event that can't be matched (engine 2b spec §8.3, §10.5): `dead` only for a confirmed
event-specific, unrecoverable failure (its ciphertext doesn't authenticate while its key version is present and opens
other events; its payload isn't a JSON object) or after 5 event-specific attempts, backing off. A platform-wide
failure (a key version missing, the tenant's data key unreadable) keeps it pending, backing off with an alert, its
attempts untouched. A dead event's pending counters are released, and its death audited."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.dispatcher import matching
from dewpoint.core.crypto import events
from tests.apps.dispatcher.inbound import bind, counters, event_state, inbound, send
from tests.apps.test_admission import KEYS
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")
ALARM = {"type": "ap_down"}


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    found = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    await bind(owner_sessionmaker, found)
    return found


async def matched(dispatch: Any, inbound: Any, event_id: uuid.UUID, verified: Any, keys: Any = KEYS) -> str:
    return await matching.match_event(
        dispatch, keys, verified, tenant_id=inbound.tenant_id, event_id=event_id, endpoint_id=inbound.endpoint_id
    )


async def tampered(owner: Any, event_id: uuid.UUID) -> None:
    """The event's ciphertext with its last byte flipped (its tag): the same size, no longer authentic."""
    async with owner() as s, s.begin():
        await s.execute(text("update inbound_events set sealed = overlay(sealed placing set_byte('\\x00', 0, "
                             "get_byte(sealed, length(sealed) - 1) # 1) from length(sealed)) where id = :e"),
                        {"e": event_id})  # fmt: skip


async def resealed(owner: Any, inbound: Any, event_id: uuid.UUID, plaintext: bytes, version: int = 1) -> None:
    """The event's payload replaced by `plaintext`, authentically sealed (what a bug before sealing could store)."""
    blob = events.seal(inbound.public_key, version, tenant_id=inbound.tenant_id, endpoint_id=inbound.endpoint_id,
                       event_id=event_id, plaintext=plaintext)  # fmt: skip
    async with owner() as s, s.begin():
        await s.execute(text("update inbound_events set sealed = :b, size_bytes = :n, key_version = :v where id = :e"),
                        {"b": blob, "n": len(blob), "v": version, "e": event_id})  # fmt: skip


async def due(owner: Any, event_id: uuid.UUID) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update inbound_events set next_attempt_at = null where id = :e"), {"e": event_id})


async def deaths(owner: Any) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(text("select target_id, details from audit_log where action = 'inbound_event.dead'"))
        return [dict(r) for r in found.mappings()]


async def test_a_ciphertext_that_fails_under_a_key_that_opened_others_is_dead_at_once(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    good, bad = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
    await tampered(owner_sessionmaker, bad)
    verified = matching.Verified()
    assert await matched(dispatch_sessionmaker, ready, good, verified) == "matched"
    with structlog.testing.capture_logs() as logs:
        assert await matched(dispatch_sessionmaker, ready, bad, verified) == "dead"
    state = await event_state(owner_sessionmaker, bad)
    assert (state["status"], state["reason"], state["request_count"]) == ("dead", "event_unreadable", None)
    assert state["ended_at"] is not None
    assert await counters(owner_sessionmaker, ready) == ((0, 0), (0, 0))
    assert [d["target_id"] for d in await deaths(owner_sessionmaker)] == [str(bad)]
    assert any(e["event"] == "inbound_event_dead" and e["log_level"] == "error" for e in logs)


async def test_an_unconfirmed_failure_backs_off_and_is_dead_after_five_attempts(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    await tampered(owner_sessionmaker, event_id)
    waits = []
    for attempt in range(1, matching.EVENT_ATTEMPTS):
        assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "retrying"
        state = await event_state(owner_sessionmaker, event_id)
        assert (state["status"], state["attempts"]) == ("pending", attempt)
        waits.append(state["next_attempt_at"] - datetime.now(UTC))
        assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "skipped"  # not due
        await due(owner_sessionmaker, event_id)
    assert [round(w / timedelta(seconds=30)) for w in waits] == [1, 2, 4, 8]  # doubling from 30 s
    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "dead"
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["reason"], state["attempts"]) == (
        "dead",
        "event_unreadable",
        matching.EVENT_ATTEMPTS,
    )


@pytest.mark.parametrize(("plaintext", "reason"), [(b"not json", "event_not_json"), (b"[1, 2]", "event_not_object")])
async def test_a_payload_that_isnt_a_json_object_is_dead(ready, owner_sessionmaker, ingress_sessionmaker,
                                                         dispatch_sessionmaker, plaintext, reason) -> None:  # fmt: skip
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    await resealed(owner_sessionmaker, ready, event_id, plaintext)
    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "dead"
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["reason"]) == ("dead", reason)
    async with owner_sessionmaker() as s:  # the endpoint's counter only: resealing changed the size the tenant's saw
        assert (await s.execute(text("select pending_events from webhook_endpoints where id = :e"),
                                {"e": ready.endpoint_id})).scalar_one() == 0  # fmt: skip


async def test_a_missing_key_version_waits_with_an_alert_and_its_attempts_untouched(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update inbound_events set key_version = 7 where id = :e"), {"e": event_id})
    with structlog.testing.capture_logs() as logs:
        assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "key_unavailable"
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["attempts"]) == ("pending", 0)
    assert state["next_attempt_at"] - datetime.now(UTC) == pytest.approx(matching.WAIT, abs=timedelta(seconds=5))
    assert [e for e in logs if e["event"] == "event_key_unavailable"][0]["log_level"] == "error"


async def test_an_unreadable_data_key_waits_too(ready, owner_sessionmaker, ingress_sessionmaker,
                                                dispatch_sessionmaker) -> None:  # fmt: skip
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    keys = FixtureKeys(missing={str(ready.tenant_id)})
    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified(), keys) == "key_unavailable"
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["attempts"]) == ("pending", 0)
    await due(owner_sessionmaker, event_id)
    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "matched"  # the key back


async def test_a_verified_version_rewrapped_with_another_key_keeps_its_events_pending(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    """The owner's M3 review: a keypair whose private key no longer pairs with its public one is the keypair's failure.
    Its events wait, alerted on, attempts untouched; none is dead, though the version opened an event before."""
    from dewpoint.core.claims.cipher import ClaimCipher
    from dewpoint.core.ingress.keys import PURPOSE

    first, second = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
    verified = matching.Verified()
    assert await matched(dispatch_sessionmaker, ready, first, verified) == "matched"
    other, _ = events.generate_keypair()
    rewrapped = await ClaimCipher(KEYS, purpose=PURPOSE).seal(str(ready.tenant_id), "1", other)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenant_event_keys set private_sealed = :p where tenant_id = :t"),
                        {"p": rewrapped, "t": ready.tenant_id})  # fmt: skip
    with structlog.testing.capture_logs() as logs:
        assert await matched(dispatch_sessionmaker, ready, second, verified) == "key_unavailable"
    state = await event_state(owner_sessionmaker, second)
    assert (state["status"], state["attempts"], state["reason"]) == ("pending", 0, None)
    assert [e["error"] for e in logs if e["event"] == "event_key_unavailable"] == ["EventKeyMismatchError"]
    assert await deaths(owner_sessionmaker) == []


async def test_a_death_rolled_back_is_never_alerted_nor_audited(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's M3 review: an outcome's alert is logged once its transaction has committed, never before. A death
    whose transaction fails before its commit leaves no alert, no audit entry and the event pending."""
    good, bad = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
    await tampered(owner_sessionmaker, bad)
    verified = matching.Verified()
    assert await matched(dispatch_sessionmaker, ready, good, verified) == "matched"

    async def fail() -> None:
        raise RuntimeError("the commit never happens")

    monkeypatch.setattr(matching, "_before_commit", fail, raising=False)
    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
        await matched(dispatch_sessionmaker, ready, bad, verified)
    assert [e for e in logs if e["event"] == "inbound_event_dead"] == []
    assert (await event_state(owner_sessionmaker, bad))["status"] == "pending"
    assert await deaths(owner_sessionmaker) == []


async def test_a_wait_rolled_back_is_never_alerted(ready, owner_sessionmaker, ingress_sessionmaker,
                                                   dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update inbound_events set key_version = 7 where id = :e"), {"e": event_id})

    async def fail() -> None:
        raise RuntimeError("the commit never happens")

    monkeypatch.setattr(matching, "_before_commit", fail, raising=False)
    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
        await matched(dispatch_sessionmaker, ready, event_id, matching.Verified())
    assert [e for e in logs if e["event"] == "event_key_unavailable"] == []
    assert (await event_state(owner_sessionmaker, event_id))["next_attempt_at"] is None
