# SPDX-License-Identifier: Apache-2.0
"""The deployment's ingress capacity through the platform admin's API (D11, as the owner's ruling on 2b-4b's M3
checkpoint 3 applies it): a platform admin on an active MFA session, a second factor proven within the reauthentication
window, the change audited in its transaction with that admin's id, the attestation and the readiness it leaves. A
value left out keeps what it was, `null` unsets it, `unset` unsets all three; a production deployment whose runs are
on keeps a whole capacity (409 `ingress_capacity_required`)."""

from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.test_erasure_api import admin_of
from tests.apps.api.test_recovery_api import audited

URL = "/api/v1/admin/platform/ingress-capacity"
WHOLE = {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 300}
SAID = "Measured with tests/probes/test_ingress_starts.py on this deployment's Temporal."


async def stored(owner: Any) -> tuple[Any, ...]:
    async with owner() as s:
        found = await s.execute(text("select ingress_starts_per_s, ingress_headroom, ingress_queue_wait_s "
                                     "from platform_settings"))  # fmt: skip
        return tuple(found.one())


@pytest.mark.usefixtures("development_deployment")
async def test_a_platform_admin_sets_it_audited_with_their_id_the_attestation_and_its_readiness(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    async with owner_sessionmaker() as s, s.begin():  # what the deployment's budget counts now, shown with it
        await s.execute(text("update ingress_budget set outstanding = 7, active = 2"))
    held = {"outstanding": 7, "active_tenants": 2}
    async with admin:
        before = await admin.get(URL)
        assert before.json() == {"starts_per_s": None, "headroom": None, "queue_wait_s": None, "limit": 50_000, **held,
                                 "problems": ["starts_per_s", "headroom", "queue_wait_s"]}  # fmt: skip
        answer = await admin.patch(URL, json=WHOLE | {"attestation": SAID})
        assert (answer.status_code, answer.json()) == (200, WHOLE | {"limit": 1_200, **held, "problems": []})
        wait = await admin.patch(URL, json={"queue_wait_s": 600, "attestation": SAID})  # the others kept
        assert wait.json() == WHOLE | {"queue_wait_s": 600, "limit": 2_400, **held, "problems": []}
        unset_one = await admin.patch(URL, json={"headroom": None, "attestation": SAID})
        assert unset_one.json()["problems"] == ["headroom"]
        unset = await admin.patch(URL, json={"unset": True, "attestation": SAID})
        assert unset.json()["problems"] == ["starts_per_s", "headroom", "queue_wait_s"]
    assert await stored(owner_sessionmaker) == (None, None, None)
    entries = await audited(owner_sessionmaker, "platform.ingress_capacity.set")
    assert [(actor, details["attestation"], details["after"], details["problems"])
            for actor, _, details in entries][:2] == [
        (admin_id, SAID, WHOLE, []),
        (admin_id, SAID, WHOLE | {"queue_wait_s": 600}, []),
    ]  # fmt: skip
    assert entries[0][2]["before"] == {"starts_per_s": None, "headroom": None, "queue_wait_s": None}


@pytest.mark.usefixtures("development_deployment")
async def test_it_needs_a_platform_admin_a_fresh_second_factor_an_attestation_and_values_in_range(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    from tests.apps.api.helpers import session_client

    stale, _ = await admin_of(app, owner_sessionmaker, api_settings, fresh=False)
    member, _ = await session_client(app, owner_sessionmaker, api_settings, "owner")
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    body = WHOLE | {"attestation": SAID}
    async with stale, member, admin:
        assert (await stale.patch(URL, json=body)).json() == {"error": "reauth_required"}
        assert (await member.patch(URL, json=body)).status_code == 403
        assert (await member.get(URL)).status_code == 403
        assert (await admin.patch(URL, json=WHOLE)).status_code == 422  # no attestation
        for bad in ({"starts_per_s": 0}, {"headroom": 1.5}, {"queue_wait_s": 0}, {"starts_per_s": "Infinity"},
                    {"unset": True, "headroom": 0.5}):  # fmt: skip
            assert (await admin.patch(URL, json=bad | {"attestation": SAID})).status_code == 422, bad
    assert await stored(owner_sessionmaker) == (None, None, None)


async def test_a_production_deployment_whose_runs_are_on_keeps_a_whole_capacity(
    app, owner_sessionmaker, api_settings
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint 3: `--unset` never silently restores development rates while production
    ingress is enabled (until D14's own switch: a production deployment with its runs on)."""
    from dewpoint.core.platform.service import PRODUCTION, record_environment

    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    async with admin:
        assert (await admin.patch(URL, json=WHOLE | {"attestation": SAID})).status_code == 200
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update platform_settings set production_runs = true"))
        for incomplete in ({"unset": True}, {"queue_wait_s": None}):
            refused = await admin.patch(URL, json=incomplete | {"attestation": SAID})
            assert (refused.status_code, refused.json()) == (409, {"error": "ingress_capacity_required"})
        assert (await admin.patch(URL, json={"headroom": 0.4, "attestation": SAID})).status_code == 200
    assert await stored(owner_sessionmaker) == (8.0, 0.4, 300)
