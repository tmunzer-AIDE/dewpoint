# SPDX-License-Identifier: Apache-2.0
"""A namespace boundary (D3g) recorded through the platform admin's API (D11; the owner's ruling on the 2b-4b M4
design): on an active MFA session with a second factor proven within the reauthentication window, tied to the D12
proof it rests on (the proof record's SHA-256) and to the server and namespace it holds for (the server binary's
SHA-256, the namespace's name and Temporal's id for it), audited in the recording's transaction with the admin's id and
the attestation. Only the deployment's recorded namespace; only a development deployment's for now: production's
waits for real-target qualification (409). The API's role writes the table only through that function."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.apps.api.test_erasure_api import admin_of
from tests.apps.api.test_recovery_api import audited

URL = "/api/v1/admin/platform/namespace-boundaries"
BUILD, DIGEST = "sha256:" + "ab" * 32, "sha256:" + "cd" * 32
SAID = "D12 passed on the local proof environment (configurations A and B); record kept in the M4 ledger."
BODY = {"name": "d12-local", "namespace": "default", "namespace_id": "8f1d2c3b-0000-4000-8000-000000000001",
        "server_build": BUILD, "proof_digest": DIGEST, "attestation": SAID}  # fmt: skip


async def stored(owner: Any) -> list[tuple[Any, ...]]:
    async with owner() as s:
        found = await s.execute(text("select name, namespace, namespace_id, server_build, proof_digest, attestation, "
                                     "recorded_by, lost_at from namespace_boundaries order by id"))  # fmt: skip
        return [tuple(r) for r in found]


@pytest.mark.usefixtures("development_deployment")
async def test_a_platform_admin_records_the_local_boundary_tied_to_its_proof_and_audited(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    async with admin:
        recorded = await admin.post(URL, json=BODY)
        assert recorded.status_code == 201, recorded.text
        shown = recorded.json()
        unshown = {k: v for k, v in BODY.items() if k != "attestation"}  # kept in the row and the audit, not listed
        assert {k: shown[k] for k in unshown} == unshown
        assert shown["recorded_by"] == str(admin_id) and shown["lost_at"] is None
        listed = await admin.get(URL)
        assert [b["id"] for b in listed.json()["boundaries"]] == [shown["id"]]
    assert await stored(owner_sessionmaker) == [
        ("d12-local", "default", BODY["namespace_id"], BUILD, DIGEST, SAID, admin_id, None)
    ]
    [(actor, target, details)] = await audited(owner_sessionmaker, "platform.namespace_boundary.record")
    assert (actor, target) == (admin_id, str(shown["id"]))
    assert details == {k: v for k, v in BODY.items()}


@pytest.mark.usefixtures("development_deployment")
async def test_it_needs_a_platform_admin_a_fresh_second_factor_and_well_formed_evidence(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    from tests.apps.api.helpers import session_client

    stale, _ = await admin_of(app, owner_sessionmaker, api_settings, fresh=False)
    member, _ = await session_client(app, owner_sessionmaker, api_settings, "owner")
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    async with stale, member, admin:
        assert (await stale.post(URL, json=BODY)).json() == {"error": "reauth_required"}
        assert (await member.post(URL, json=BODY)).status_code == 403
        assert (await member.get(URL)).status_code == 403
        for bad in ({"attestation": ""}, {"server_build": "ab" * 32}, {"proof_digest": "sha256:xyz"},
                    {"namespace_id": ""}, {"name": ""}):  # fmt: skip
            assert (await admin.post(URL, json=BODY | bad)).status_code == 422, bad
    assert await stored(owner_sessionmaker) == []


@pytest.mark.usefixtures("development_deployment")
async def test_only_the_deployments_recorded_namespace(app, owner_sessionmaker, api_settings) -> None:
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    async with admin:
        refused = await admin.post(URL, json=BODY | {"namespace": "another"})
    assert (refused.status_code, refused.json()) == (409, {"error": "namespace_not_recorded"})
    assert await stored(owner_sessionmaker) == []


async def test_a_production_deployment_waits_for_real_target_qualification(app, owner_sessionmaker,
                                                                           api_settings) -> None:  # fmt: skip
    from dewpoint.core.platform.service import PRODUCTION, record_environment

    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    async with admin:
        refused = await admin.post(URL, json=BODY)
    assert (refused.status_code, refused.json()) == (409, {"error": "boundary_needs_qualification"})
    assert await stored(owner_sessionmaker) == []


async def test_the_api_role_writes_boundaries_only_through_the_function(api_sessionmaker) -> None:
    async with api_sessionmaker() as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            async with s.begin():
                await s.execute(text("insert into namespace_boundaries (name) values ('forged')"))


async def test_the_admin_role_can_mark_a_boundary_lost_but_no_longer_insert_one(
    admin_sessionmaker, owner_sessionmaker
) -> None:
    """The review's I4: a direct insert as the key admin would skip every refusal of the function (any environment,
    any namespace, no evidence) and the platform admin's second factor; finding one lost stays the admin's."""
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into namespace_boundaries (name) values ('seeded')"))
    async with admin_sessionmaker() as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            async with s.begin():
                await s.execute(text("insert into namespace_boundaries (name) values ('forged')"))
    async with admin_sessionmaker() as s, s.begin():
        await s.execute(text("update namespace_boundaries set lost_at = now()"))
    assert [row[0] for row in await stored(owner_sessionmaker)] == ["seeded"]
