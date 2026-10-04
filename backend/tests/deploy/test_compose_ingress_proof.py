# SPDX-License-Identifier: Apache-2.0
"""CI's ingress proof (engine 2b spec §8.3, §12; 2b-3b task 10): `deploy/compose/ci/ingress-proof.py` makes an HMAC
endpoint and its binding to the seeded workflow, as the API's login, and prints the endpoint's id and its secret; CI
posts a signed event through nginx to ingress, twice (the second a retry, acknowledged once); then the script waits for
the event's run to succeed through the Compose dispatcher's matcher, the dispatcher and the worker. Here the posting
goes through ingress's own app against the test database; CI does the same through the Compose stack."""

import base64
import hashlib
import hmac
import importlib.util
import time
from typing import Any

import pytest

from dewpoint.apps.dispatcher import matching
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.ingress.main import create_app as create_ingress
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.ingress.support import KEY_BYTES
from tests.apps.ingress.support import client as ingress_client
from tests.apps.ingress.support import settings as ingress_settings
from tests.apps.test_admission import current
from tests.apps.worker.harness import workers as engine_workers
from tests.deploy.test_compose_seed import ROOT, seeding
from tests.support.registry import sync_test_plugins

PROOF = ROOT / "deploy" / "compose" / "ci" / "ingress-proof.py"


def proving() -> Any:
    spec = importlib.util.spec_from_file_location("ingress_proof", PROOF)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.usefixtures("development_deployment")
async def test_the_ingress_proof_waits_for_the_webhooks_run_to_succeed(
    env, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, pg_url
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    tenant_id, workflow_id = await seeding().seed(api_settings)
    settings = api_settings.model_copy(update={"ingress_key_b64": base64.b64encode(KEY_BYTES).decode()})
    proof = proving()
    endpoint_id, secret = await proof.create(settings, tenant_id, workflow_id)
    assert await proof.state(settings, tenant_id, endpoint_id) == (None, None)
    body, stamp = b'{"id":"ci-proof-1","type":"ci_proof"}', str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"x-dewpoint-timestamp": stamp, "x-dewpoint-signature": signature, "content-type": "application/json"}
    ingress = create_ingress(ingress_settings(pg_url))
    async with ingress_client(ingress) as hooks:
        assert (await hooks.post(f"/hooks/{endpoint_id}", content=body, headers=headers)).json()["accepted"] == 1
        assert (await hooks.post(f"/hooks/{endpoint_id}", content=body, headers=headers)).json()["duplicates"] == 1
    await ingress.state.engine.dispose()
    assert await proof.state(settings, tenant_id, endpoint_id) == ("pending", None)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    keyring = Keyring(KekSet.from_settings(api_settings))
    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
    assert await matching.match_once(dispatch_sessionmaker, dispatch_keys, matching.Verified()) == {"matched": 1}
    async with engine_workers(env.client, DbRunStore(worker_sessionmaker, worker_keys)):
        assert await dispatch_once(dispatch_sessionmaker, env.client, dispatch_keys, api_settings, BUILD) == {
            "started": 1
        }
        assert await proof.wait(settings, tenant_id, endpoint_id, 30)
