# SPDX-License-Identifier: Apache-2.0
"""The claim store (engine 2b spec §3.1, §3.3, §3.4): a claim is written once, idempotently, a rewrite checked against
the existing claim's decrypted value, never a digest of it (#28); only its owner, or a run it was granted to, reads it;
a run grants only what it owns or holds a grant on."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.claims import service
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from tests.support.keys import FixtureKeys

CIPHER = ClaimCipher(FixtureKeys())
VALUE = {"token": "s3cret-value", "public": [1, 2]}


async def a_tenant(owner: Any) -> uuid.UUID:
    tenant = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": str(tenant)}
        )
    return tenant


def claim(owner_run: uuid.UUID, value: Any = VALUE, sensitive: tuple[str, ...] = ("/token",)) -> service.NewClaim:
    return service.NewClaim(
        id=uuid.uuid4(), value=value, sensitive_pointers=sensitive, owner_run_id=owner_run, root_run_id=owner_run
    )


async def write(sm: Any, tenant: uuid.UUID, new: service.NewClaim, cipher: ClaimCipher = CIPHER) -> None:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.write_output(s, cipher, tenant, new, kind="output", step_id=uuid.UUID(int=1), iteration_key="",
                                   attempt=1)  # fmt: skip


async def fetch(sm: Any, tenant: uuid.UUID, run: uuid.UUID, claim_id: uuid.UUID) -> service.Stored:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await service.fetch(s, CIPHER, tenant, run_id=run, claim_id=claim_id)


async def test_the_owner_reads_what_it_wrote_and_the_database_holds_no_plaintext(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run = await a_tenant(owner_sessionmaker), uuid.uuid4()
    new = claim(run)
    await write(worker_sessionmaker, tenant, new)
    stored = await fetch(worker_sessionmaker, tenant, run, new.id)
    assert (stored.value, stored.sensitive_pointers) == (VALUE, ("/token",))
    async with owner_sessionmaker() as s:
        raw = (await s.execute(text("select ciphertext from step_outputs where id = :i"), {"i": new.id})).scalar_one()
    assert b"s3cret" not in raw


async def test_writing_a_claim_again_is_a_no_op_and_another_value_under_its_id_is_refused(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run = await a_tenant(owner_sessionmaker), uuid.uuid4()
    new = claim(run)
    await write(worker_sessionmaker, tenant, new)
    await write(worker_sessionmaker, tenant, new)  # a retried activity writes the same row
    with pytest.raises(service.ClaimConflictError):
        await write(worker_sessionmaker, tenant, service.NewClaim(**{**new.__dict__, "value": {"token": "other"}}))
    assert (await fetch(worker_sessionmaker, tenant, run, new.id)).value == VALUE


async def test_no_digest_of_a_claims_value_is_kept(owner_sessionmaker) -> None:
    """#28: an unkeyed SHA-256 of each claim's plaintext let anyone who reads the claim tables test guesses for a
    low-entropy secret offline. The tables keep the ciphertext and nothing derived from the value."""
    async with owner_sessionmaker() as s:
        columns = (
            await s.execute(
                text(
                    "select table_name, column_name from information_schema.columns "
                    "where table_name in ('run_inputs', 'step_outputs') and column_name not in "
                    "('id', 'tenant_id', 'owner_run_id', 'root_run_id', 'sensitive_pointers', 'ciphertext', "
                    "'created_at', 'pointer', 'role', 'kind', 'step_id', 'iteration_key', 'attempt')"
                )
            )
        ).all()
    assert columns == []


async def test_a_rewrite_is_checked_against_the_existing_claim_decrypted_across_a_key_rotation(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    """With no digest, a write that finds its id taken opens the existing claim, with the key version its ciphertext
    names, and compares the canonical plaintext: the same value, its keys in another order, is a retry; another value
    is refused, even after the tenant's key rotated."""
    tenant, run = await a_tenant(owner_sessionmaker), uuid.uuid4()
    new = claim(run)
    await write(worker_sessionmaker, tenant, new)  # under key version 1
    rotated = ClaimCipher(FixtureKeys(version=2))
    reordered = service.NewClaim(**{**new.__dict__, "value": {"public": [1, 2], "token": "s3cret-value"}})
    await write(worker_sessionmaker, tenant, reordered, rotated)
    with pytest.raises(service.ClaimConflictError):
        await write(worker_sessionmaker, tenant, service.NewClaim(**{**new.__dict__, "value": {"token": "x"}}), rotated)
    assert (await fetch(worker_sessionmaker, tenant, run, new.id)).value == VALUE


async def test_admission_writes_a_trigger_claim_the_run_then_reads(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run = await a_tenant(owner_sessionmaker), uuid.uuid4()
    new = claim(run)
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.write_input(s, CIPHER, tenant, new, pointer="/token")
    assert (await fetch(worker_sessionmaker, tenant, run, new.id)).value == VALUE


async def test_only_the_owner_and_runs_it_was_granted_to_read_a_claim(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = await a_tenant(owner_sessionmaker)
    parent, child, grandchild, sibling = (uuid.uuid4() for _ in range(4))
    new = claim(parent)
    await write(worker_sessionmaker, tenant, new)
    for run in (child, sibling):
        with pytest.raises(service.ClaimUnavailableError):
            await fetch(worker_sessionmaker, tenant, run, new.id)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.grant(s, tenant, granted_by=parent, to=child, claim_ids=[new.id], root_run_id=parent)
        await service.grant(s, tenant, granted_by=child, to=grandchild, claim_ids=[new.id], root_run_id=parent)
    for run in (child, grandchild):
        assert (await fetch(worker_sessionmaker, tenant, run, new.id)).value == VALUE
    with pytest.raises(service.ClaimUnavailableError):
        await fetch(worker_sessionmaker, tenant, sibling, new.id)


async def test_a_run_grants_only_what_it_owns_or_holds(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = await a_tenant(owner_sessionmaker)
    owner, other, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    new = claim(owner)
    await write(worker_sessionmaker, tenant, new)
    with pytest.raises(service.ClaimUnavailableError):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await service.grant(s, tenant, granted_by=other, to=child, claim_ids=[new.id], root_run_id=owner)
    with pytest.raises(service.ClaimUnavailableError):
        await fetch(worker_sessionmaker, tenant, child, new.id)


async def test_a_claim_of_another_tenant_or_none_at_all_is_unavailable(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant, other, run = await a_tenant(owner_sessionmaker), await a_tenant(owner_sessionmaker), uuid.uuid4()
    new = claim(run)
    await write(worker_sessionmaker, tenant, new)
    for t, claim_id in ((other, new.id), (tenant, uuid.uuid4())):
        with pytest.raises(service.ClaimUnavailableError) as raised:
            await fetch(worker_sessionmaker, t, run, claim_id)
        assert "s3cret" not in str(raised.value)
