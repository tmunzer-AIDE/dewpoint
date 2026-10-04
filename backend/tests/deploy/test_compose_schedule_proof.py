# SPDX-License-Identifier: Apache-2.0
"""CI's schedule proof (engine 2b spec §8.2, §12; 2b-3a task 19): `deploy/compose/ci/schedule-proof.py` makes a
schedule of the seeded workflow, every 60 s in a non-UTC time zone (the API's image must hold the time zone data), as
the API's login, then waits for its first run to succeed through the Compose dispatcher's sync, its admission worker,
the dispatcher and the worker. Here the script runs against the test database, a tick through admission, the dispatcher
and a worker; CI runs the same against the Compose stack."""

import importlib.util
from typing import Any

import pytest
import yaml

from dewpoint.apps.dispatcher import tick
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import current
from tests.apps.worker.harness import workers as engine_workers
from tests.deploy.test_compose_seed import CI, ROOT, seeding
from tests.support.registry import sync_test_plugins

PROOF = ROOT / "deploy" / "compose" / "ci" / "schedule-proof.py"


def proving() -> Any:
    spec = importlib.util.spec_from_file_location("schedule_proof", PROOF)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.usefixtures("development_deployment")
async def test_the_schedule_proof_waits_for_the_first_scheduled_run_to_succeed(
    env, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    tenant_id, workflow_id = await seeding().seed(api_settings)
    proof = proving()
    schedule_id = await proof.create(api_settings, tenant_id, workflow_id)
    assert await proof.state(api_settings, tenant_id, schedule_id) == (None, None)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    keyring = Keyring(KekSet.from_settings(api_settings))
    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
    async with dispatch_sessionmaker() as s, s.begin():  # the Compose dispatcher's admission worker, a firing's tick
        assert await tick.admit_tick(s, dispatch_keys, tenant_id=tenant_id, schedule_id=schedule_id,
                                     key=f"sched:{schedule_id}:2026-10-04T09:00:00Z") == "queued"  # fmt: skip
    assert (await proof.state(api_settings, tenant_id, schedule_id))[0] == "queued"
    async with engine_workers(env.client, DbRunStore(worker_sessionmaker, worker_keys)):
        assert await dispatch_once(dispatch_sessionmaker, env.client, dispatch_keys, api_settings, BUILD) == {
            "started": 1
        }
        assert await proof.wait(api_settings, tenant_id, schedule_id, 30)


async def test_a_zone_the_image_lacks_is_refused_before_anything_is_scheduled(
    owner_sessionmaker, admin_sessionmaker, api_settings, monkeypatch
) -> None:
    """An image without the IANA data would refuse `Europe/Paris` at once, so the CI step fails at its first line."""
    from dewpoint.apps import schedules

    await sync_test_plugins(admin_sessionmaker)
    tenant_id, workflow_id = await seeding().seed(api_settings)
    monkeypatch.setattr(schedules, "_zones", lambda: frozenset({"UTC"}))
    with pytest.raises(schedules.ScheduleRefusedError) as refused:
        await proving().create(api_settings, tenant_id, workflow_id)
    assert refused.value.detail["problems"] == [{"field": "time_zone", "code": "time_zone_unknown"}]


def test_ci_proves_a_schedule_through_the_compose_dispatcher() -> None:
    steps = yaml.safe_load(CI.read_text())["jobs"]["e2e"]["steps"]
    [proof] = [s for s in steps if s.get("name", "").startswith("A schedule through the Compose dispatcher")]
    assert proof["timeout-minutes"] <= 5  # bounded
    script = proof["run"]
    assert "python - < ci/seed-workflow.py" in script
    assert "python - create" in script and "< ci/schedule-proof.py" in script
    assert "python - wait" in script and " 150 " in script
    names = [s.get("name", "") for s in steps]
    assert names.index(proof["name"]) > names.index("A run through the Compose dispatcher (engine 2b spec §12)")
