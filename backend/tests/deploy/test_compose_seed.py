# SPDX-License-Identifier: Apache-2.0
"""CI's Compose proof (engine 2b spec §12; the owner's M5 condition): `deploy/compose/ci/seed-workflow.py` makes a
synthetic tenant, with its data key, and a published workflow of the shipped `flow` plugin's nodes only, as the API's
login; then `dewpoint dev run --wait`, as the dispatcher's login, must end with the run succeeded. Here the seed runs
against the test database and its workflow through admission, the dispatcher and a worker; CI runs the same against
the Compose stack."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

from dewpoint.apps import dev_run
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import current
from tests.apps.worker.harness import workers as engine_workers
from tests.support.registry import sync_test_plugins

ROOT = Path(__file__).parents[3]
SEED = ROOT / "deploy" / "compose" / "ci" / "seed-workflow.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def seeding() -> Any:
    spec = importlib.util.spec_from_file_location("seed_workflow", SEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.usefixtures("development_deployment")
async def test_the_seeded_workflow_runs_to_success_through_the_dispatcher(
    env, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)  # Compose: `dewpoint plugins sync`, as the admin login
    tenant_id, workflow_id = await seeding().seed(api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    keyring = Keyring(KekSet.from_settings(api_settings))
    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
    request = await dev_run.admit(dispatch_sessionmaker, dispatch_keys, tenant_id=tenant_id, workflow_id=workflow_id,
                                  input={}, simulate=False, idempotency_key="ci-proof")  # fmt: skip
    async with engine_workers(env.client, DbRunStore(worker_sessionmaker, worker_keys)):
        assert await dispatch_once(dispatch_sessionmaker, env.client, dispatch_keys, api_settings, BUILD) == {
            "started": 1
        }
        ended = await dev_run.wait_for_end(dispatch_sessionmaker, tenant_id, request.id, within=30, poll=0.1)
    assert ended == dev_run.Ended("run", "succeeded", None, None)


def test_ci_proves_a_run_through_the_compose_dispatcher_with_the_dispatch_login() -> None:
    steps = yaml.safe_load(CI.read_text())["jobs"]["e2e"]["steps"]
    [proof] = [s for s in steps if s.get("name", "").startswith("A run through the Compose dispatcher")]
    assert proof["timeout-minutes"] <= 5  # bounded
    script = proof["run"]
    assert "dewpoint_admin_login" in script and "dewpoint plugins sync" in script
    assert "python - < ci/seed-workflow.py" in script
    assert "docker compose exec -T dispatcher dewpoint dev run" in script and "--wait" in script
    names = [s.get("name", "") for s in steps]
    assert names.index(proof["name"]) > names.index("The worker's build is current")
