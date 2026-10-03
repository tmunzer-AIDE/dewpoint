# SPDX-License-Identifier: Apache-2.0
"""A request's trigger envelope (engine 2b spec revision 7, §7.1): stored encrypted beside its claims, never served as
one. A handle that names it is refused, a grant that reaches it grants nothing, and it's read only through its own
reader, scoped to its tenant and its request."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.claims import service
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from tests.support.keys import FixtureKeys
from tests.support.workflows import seed_workflow

CIPHER = ClaimCipher(FixtureKeys())
ENVELOPE = {"site": "a", "token": {"$claim": str(uuid.UUID(int=9))}}


async def admitted(owner: Any, dispatch: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A queued request with its envelope, written as admission writes them: the tenant, the request, the envelope."""
    tenant, wf, version = await seed_workflow(owner)
    request = uuid.uuid4()
    async with dispatch() as s, s.begin():
        await tenant_scope(s, tenant)
        envelope = await service.write_envelope(s, CIPHER, tenant, request_id=request, envelope=ENVELOPE)
        await s.execute(
            text(
                "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, "
                "idempotency_key, digest, digest_key_version, status, envelope_id) "
                "values (:r, :t, :w, :v, 'manual', 'live', 'k', :d, 1, 'queued', :e)"
            ),
            {"r": request, "t": tenant, "w": wf, "v": version, "d": b"\x00" * 32, "e": envelope},
        )
    return tenant, request, envelope


async def test_a_handle_that_names_an_envelope_is_refused_even_to_its_owner(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, request, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
    with pytest.raises(service.ClaimUnavailableError):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await service.fetch(s, CIPHER, tenant, run_id=request, claim_id=envelope)


async def test_a_grant_that_reaches_an_envelope_grants_nothing(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, request, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
    child = uuid.uuid4()
    with pytest.raises(service.ClaimUnavailableError):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await service.grant(s, tenant, granted_by=request, to=child, claim_ids=[envelope], root_run_id=request)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from claim_grants"))).scalar_one() == 0


async def test_the_envelope_is_read_through_its_request_and_tenant_only(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant, request, _ = await admitted(owner_sessionmaker, dispatch_sessionmaker)
    other, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert await service.read_envelope(s, CIPHER, tenant, request_id=request) == ENVELOPE
        with pytest.raises(service.EnvelopeUnavailableError):  # no such request in this tenant
            await service.read_envelope(s, CIPHER, tenant, request_id=uuid.uuid4())
    with pytest.raises(service.EnvelopeUnavailableError):
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, other)
            await service.read_envelope(s, CIPHER, other, request_id=request)


async def test_the_database_holds_no_envelope_in_plain_text(owner_sessionmaker, dispatch_sessionmaker) -> None:
    _, _, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
    async with owner_sessionmaker() as s:
        row = (
            await s.execute(text("select ciphertext, pointer, role from run_inputs where id = :e"), {"e": envelope})
        ).one()
    assert b"site" not in row.ciphertext and (row.pointer, row.role) == (None, "envelope")
