# SPDX-License-Identifier: Apache-2.0
"""The pre-versioning visibility query's proof (2b-4b M4), as the owner asked (2026-10-09), before R3-A: on a
disposable D12 server, an open unversioned run on the engine's queue is found, and an open versioned run and a closed
run aren't, with visibility waited for (tests/proofs/preversioning.py). Opt-in (`DEWPOINT_PROOF=pv`), and run only
when the owner authorizes it:

    DEWPOINT_PROOF=pv DEWPOINT_PROOF_OUT=<file> .venv/bin/pytest -p no:cacheprovider -n 0 -x \\
        tests/proofs/d12/test_preversioning.py

Configuration B only, the harness R3-B proved locally: visibility doesn't depend on how a caller authenticates. It
doesn't qualify configuration A, a persistent target or the owner's deployment."""

import asyncio
import dataclasses
import subprocess

import pytest

from tests.proofs import environment, preversioning
from tests.proofs.conftest import gate, record
from tests.proofs.d12.test_d12 import SERVER_IMAGE, Server, connect, server  # noqa: F401

pytestmark = [gate("pv")]


@pytest.mark.parametrize("server", [environment.JWT], indirect=True)
def test_pv_1_the_query_finds_an_open_unversioned_run_and_neither_an_open_versioned_nor_a_closed_one(
    server: Server,  # noqa: F811
) -> None:
    image = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", SERVER_IMAGE], capture_output=True,
                           text=True, check=True).stdout.strip()  # fmt: skip
    evidence = asyncio.run(_observe(server))
    record({"environment": f"pv-{server.config}", "server_image": image, **dataclasses.asdict(evidence)})
    preversioning.check(evidence)


async def _observe(on: Server) -> preversioning.Evidence:
    return await preversioning.observe(await connect(on, "dewpoint-proof"))
