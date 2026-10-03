# SPDX-License-Identifier: Apache-2.0
"""What stops a start before anything is written, told apart (the owner's M2 checkpoint): a tenant key that can't be
read waits, queued, with no attempt (§2.3); an envelope that doesn't open, or isn't JSON, is broken for good, so its
request is `dead`, audited; a bug is neither, and it stays queued. None of them stops a cycle for the other tenants."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import dispatch
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from tests.apps.dispatcher.support import BUILD, begin, state
from tests.apps.test_admission import KEYS, admit, published
from tests.apps.test_runs import FakeClient
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")


async def envelope_id(owner: Any, request_id: uuid.UUID) -> uuid.UUID:
    async with owner() as s:
        found = await s.execute(text("select envelope_id from run_requests where id = :r"), {"r": request_id})
        return found.scalar_one()


async def break_envelope(owner: Any, request: Any, how: str) -> None:
    """`tampered`: one bit of its ciphertext flipped. `not_json`: a sound ciphertext of bytes that aren't JSON."""
    eid = await envelope_id(owner, request.id)
    async with owner() as s, s.begin():
        if how == "tampered":
            await s.execute(
                text("update run_inputs set ciphertext = set_byte(ciphertext, length(ciphertext) - 1,"
                     " get_byte(ciphertext, length(ciphertext) - 1) # 1) where id = :i"),
                {"i": eid},
            )  # fmt: skip
        else:
            sealed = await ClaimCipher(KEYS).seal(str(request.tenant_id), str(eid), b"\xff not json")
            await s.execute(text("update run_inputs set ciphertext = :c where id = :i"), {"c": sealed, "i": eid})


async def second_tenant(owner: Any, api: Any, admin: Any, settings: Any) -> Any:
    ctx, wf = await published(owner, api, admin, settings)
    return (await admit(api, ctx, wf, key="other")).request


async def audited(owner: Any, action: str) -> list[Any]:
    async with owner() as s:
        rows = await s.execute(text("select target_id, details from audit_log where action = :a"), {"a": action})
        return [tuple(r) for r in rows]


@pytest.mark.parametrize("how", ["tampered", "not_json"])
async def test_a_broken_envelope_makes_its_request_dead_never_a_key_outage(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, how
) -> None:
    _, _, request = queued
    await break_envelope(owner_sessionmaker, request, how)
    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Dead("envelope_unreadable")
    after = await state(owner_sessionmaker, request.id)
    assert after == {"request": ("dead", "envelope_unreadable", 0), "run": None, "slot": 0}
    assert await audited(owner_sessionmaker, "run.request.dead") == [
        (str(request.id), {"reason": "envelope_unreadable"})
    ]


async def test_a_broken_envelope_never_stops_the_cycle_for_other_tenants(
    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, broken = queued  # the oldest due request: the cycle reaches it first
    other = await second_tenant(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await break_envelope(owner_sessionmaker, broken, "tampered")
    client = FakeClient()
    counts = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
    assert counts == {"envelope_unreadable": 1, "started": 1}
    assert [a.run_id for a, _, _ in client.started] == [str(other.id)]


class ActiveKeyGone(FixtureKeys):
    """The envelope's key opens it, but the tenant's active key, which seals the start, can't be read."""

    async def active(self, tenant_id: str) -> Any:
        raise LookupError(f"no active key for tenant {tenant_id}")


async def test_a_key_that_cant_seal_the_start_waits_queued(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    assert await begin(dispatch_sessionmaker, request, api_settings, keys=ActiveKeyGone()) == dispatch.Waiting(
        "key_unusable"
    )
    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}


async def test_a_bug_while_building_the_start_is_never_a_key_outage(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued

    async def broken(_: Any) -> None:
        raise TypeError("a bug")

    with pytest.raises(TypeError):
        await dispatch.begin(
            dispatch_sessionmaker, broken, api_settings, KEYS, tenant_id=request.tenant_id, request_id=request.id,
            build=BUILD,
        )  # fmt: skip
    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}


@pytest.mark.parametrize("error", [TypeError("a bug"), claims.EnvelopeUnavailableError("missing")])
async def test_a_failure_dispatch_cant_classify_is_isolated_and_its_request_stays_queued(
    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings,
    monkeypatch, error,
) -> None:  # fmt: skip
    """A bug, or an envelope its foreign key should have kept: logged as an error, the request left as it was, and
    the cycle goes on to the next tenant."""
    _, _, failing = queued
    other = await second_tenant(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    read = claims.read_envelope

    async def read_envelope(s: Any, cipher: Any, tenant_id: uuid.UUID, *, request_id: uuid.UUID) -> Any:
        if request_id == failing.id:
            raise error
        return await read(s, cipher, tenant_id, request_id=request_id)

    monkeypatch.setattr(claims, "read_envelope", read_envelope)
    client = FakeClient()
    counts = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
    assert counts == {"error": 1, "started": 1}
    assert [a.run_id for a, _, _ in client.started] == [str(other.id)]
    assert await state(owner_sessionmaker, failing.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
