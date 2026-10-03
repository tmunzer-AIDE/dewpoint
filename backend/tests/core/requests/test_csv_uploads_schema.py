# SPDX-License-Identifier: Apache-2.0
"""Staged CSV uploads (engine 2b spec §8.1, §14): under forced row-level security, the API's only within its tenant;
staged until a start consumes it, which clears its cells; never deleted by the API, since only retention deletes
(§10.3)."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from tests.apps.api.helpers import PW
from tests.support.workflows import seed_workflow

INSERT = text(
    "insert into csv_uploads (id, tenant_id, owner_id, workflow_id, staged, file_digest, digest_key_version, "
    "size_bytes, row_count, expires_at) values (:id, :t, :o, :w, :staged, :d, 1, 10, 1, now() + interval '1 hour')"
)


async def upload(api: Any, owner: Any) -> tuple[uuid.UUID, uuid.UUID]:
    tenant, wf, _ = await seed_workflow(owner)
    async with owner() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)).id
    upload_id = uuid.uuid4()
    async with api() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(INSERT, {"id": upload_id, "t": tenant, "o": user, "w": wf, "staged": b"\x01", "d": b"\x02"})
    return tenant, upload_id


async def test_uploads_force_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        flags = (
            await s.execute(
                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'csv_uploads'")
            )
        ).one()
    assert tuple(flags) == (True, True)


async def test_an_upload_is_seen_only_within_its_tenant(api_sessionmaker, owner_sessionmaker) -> None:
    tenant, upload_id = await upload(api_sessionmaker, owner_sessionmaker)
    other, _ = await upload(api_sessionmaker, owner_sessionmaker)
    for scope, seen in ((tenant, 1), (other, 0)):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, scope)
            found = await s.execute(text("select count(*) from csv_uploads where id = :i"), {"i": upload_id})
            assert found.scalar_one() == seen


async def test_the_api_consumes_an_upload_but_never_deletes_one(api_sessionmaker, owner_sessionmaker) -> None:
    tenant, upload_id = await upload(api_sessionmaker, owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        consume = "update csv_uploads set staged = null, consumed_by = :r, consumed_at = now() where id = :i"
        await s.execute(text(consume), {"i": upload_id, "r": uuid.uuid4()})
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text("delete from csv_uploads where id = :i"), {"i": upload_id})


@pytest.mark.parametrize(
    "change",
    [
        "consumed_by = gen_random_uuid(), consumed_at = now()",  # consumed while its cells stay
        "staged = null",  # cleared without a consumer
        "consumed_by = gen_random_uuid(), staged = null",  # consumed without a time
    ],
)
async def test_an_upload_is_staged_until_a_start_consumes_it(api_sessionmaker, owner_sessionmaker, change) -> None:
    tenant, upload_id = await upload(api_sessionmaker, owner_sessionmaker)
    with pytest.raises(IntegrityError):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text(f"update csv_uploads set {change} where id = :i"), {"i": upload_id})


async def test_a_csv_record_is_never_a_claim(api_sessionmaker, owner_sessionmaker, worker_sessionmaker) -> None:
    """A CSV start's record (§8.1, §7.1) sits in `run_inputs` under the role `csv`: no pointer, one per request, and
    neither a claim read nor a grant serves it, as for an envelope."""
    from dewpoint.core.claims import service as claims
    from dewpoint.core.claims.cipher import ClaimCipher
    from tests.core.requests.test_schema import claim
    from tests.support.keys import FixtureKeys

    tenant, _ = await upload(api_sessionmaker, owner_sessionmaker)
    request = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        record = await claim(s, tenant, request, role="csv", pointer=None)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        with pytest.raises(claims.ClaimUnavailableError):
            await claims.fetch(s, ClaimCipher(FixtureKeys()), tenant, run_id=request, claim_id=record)
        with pytest.raises(claims.ClaimUnavailableError):
            await claims.grant(s, tenant, granted_by=request, to=uuid.uuid4(), claim_ids=[record], root_run_id=request)
    for pointer in (None, ""):  # a second record, then one with a pointer
        with pytest.raises(IntegrityError):
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant)
                await claim(s, tenant, request, role="csv", pointer=pointer)
