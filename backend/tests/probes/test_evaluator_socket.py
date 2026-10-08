# SPDX-License-Identifier: Apache-2.0
"""#26 through the real evaluator (the owner's review of the 2b-4b M2 checkpoint: the frame fix was proved only against
the in-process evaluator). The evaluator's own server runs as a process of its own, on a Unix socket, forking a child
for each evaluation; the worker's CEL activity reaches it through the real client (`remote_evaluator`,
`evaluate_remote`), which refuses a call past the 4 MiB frame, as the server's frame reader does. The evaluator refuses
to start off Linux (its rlimits and cgroup v2): on another system its child limits are replaced by a no-op, as its own
tests do, and nothing else differs. On the dev server; a run by hand, never in CI (skipped unless `DEWPOINT_PROBE` is
set). From `backend/`:

    DEWPOINT_PROBE=1 .venv/bin/pytest tests/probes/test_evaluator_socket.py -p no:randomly -s"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker import claims
from dewpoint.apps.worker.activities import cel_activity, remote_evaluator
from dewpoint.apps.worker.deployment import set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import cel_queue
from tests.apps.worker.harness import MemoryStore, start
from tests.apps.worker.test_deployment import build
from tests.apps.worker.test_main import settings
from tests.apps.worker.test_real_server import task_failures
from tests.apps.worker.test_run_graph_binding import issue_26, request_bytes
from tests.support.keys import FIXTURE_CONVERTER
from tests.support.plugins.testkit import TESTKIT

pytestmark = pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)")
# A Unix socket's path has at most 103 bytes: the scratchpad's shortest spelling, under /tmp, and a one-letter name
SOCKET = os.environ.get("DEWPOINT_PROBE_SOCKET", "/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/"  # noqa: S108
                        "1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/s")  # fmt: skip
SERVE = """
import asyncio, sys
from dewpoint.apps.cel_evaluator import child, server
from dewpoint.apps.cel_evaluator.__main__ import identity
from dewpoint.engine.cel import runtime
limit = (lambda: None) if sys.platform != "linux" else child.apply_limits
runtime.compile_checked("1 + 1", {})
asyncio.run(server.serve(sys.argv[1], server.Evaluator(identity(), 2, limit=limit)))
"""


@pytest.fixture(scope="module")
async def dev() -> AsyncIterator[WorkflowEnvironment]:
    """The dev server, as the suite's `dev_env` starts it."""
    drainage = ["matching.wv.VersionDrainageStatusVisibilityGracePeriod",
                "matching.wv.VersionDrainageStatusRefreshInterval"]  # fmt: skip
    args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER,
                                                     dev_server_extra_args=args) as environment:  # fmt: skip
        yield environment


@pytest.fixture(scope="module")
def evaluator() -> Iterator[str]:
    """The evaluator's server, a process of its own on `SOCKET`."""
    process = subprocess.Popen([sys.executable, "-c", SERVE, SOCKET], cwd=Path(__file__).parents[2])  # noqa: S603
    try:
        for _ in range(100):
            if os.path.exists(SOCKET):
                break
            if process.poll() is not None:
                raise AssertionError(f"the evaluator exited ({process.returncode})")
            asyncio.run(asyncio.sleep(0.1))
        yield SOCKET
    finally:
        process.terminate()
        process.wait(10)
        if os.path.exists(SOCKET):
            os.unlink(SOCKET)


@asynccontextmanager
async def serving(client: Client, store: MemoryStore, socket: str, calls: list[int]) -> AsyncIterator[None]:
    """A build of the probe's own, current, its CEL activity reaching the evaluator through its socket. Each call the
    activity makes to it is recorded: its binding sets."""
    real = remote_evaluator(socket, CURRENT_CEL_PROFILE)

    async def counted(request: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(len(request["bindings"]))
        return await real(request)

    this = build("socket")
    evaluator = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(counted, store)])
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(), build=this, identity=this):
        await set_current(client, this)
        yield


@pytest.mark.parametrize("cut", [True, False], ids=["within the frame", "control: one call"])
async def test_issue_26s_thousand_items_through_the_real_evaluator(
    dev: WorkflowEnvironment, evaluator: str, monkeypatch: pytest.MonkeyPatch, cut: bool
) -> None:  # fmt: skip
    """#26's reproduction (1,000 items over a 65,500-character string): claimed once, its sets resolved in the activity
    (about 65 MB) go to the evaluator in calls within its frame, and every item is evaluated. The control sends them in
    one call: the real client refuses it (`input_too_large` for every item), which the in-process evaluator once
    didn't."""
    if not cut:
        monkeypatch.setattr(claims, "FRAME_BYTES", 1 << 40)
    client, store, calls = dev.client, MemoryStore(), []
    async with serving(client, store, evaluator, calls):
        handle = await start(client, store, issue_26(1_000), {"s": "x" * 65_500})
        result = await asyncio.wait_for(handle.result(), 300)
    sent = await request_bytes(handle)
    print(f"#26 through the socket ({'cut' if cut else 'one call'}): {result.status} {result.outputs}; "
          f"{len(sent)} request(s), {sum(sent):,} bytes; {len(calls)} evaluator call(s) of {calls} sets")  # fmt: skip
    assert await task_failures(handle) == []
    if cut:
        assert (result.status, result.outputs) == ("succeeded", {"kept": 1_000, "code": "none"}), result
        assert len(calls) > 1
    else:
        assert (result.status, result.outputs) == ("succeeded", {"kept": -1, "code": "input_too_large"}), result
