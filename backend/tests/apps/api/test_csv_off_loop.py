# SPDX-License-Identifier: Apache-2.0
"""The CSV work's CPU off the API's event loop (the owner's ruling 2 on the M3 checkpoint): at the platform's caps an
upload's parse and preview take a few hundred milliseconds, and a CSV start's rows, their check against the trigger's
schema and their split several seconds (`probes/csv_memory.py`'s shapes). That pure work runs in a thread, inside the
request's CSV slot; the request's database session stays on the loop. Each test holds one step, in whatever thread runs
it, until another request has been answered meanwhile: run on the loop, the step would hold that request too."""

import asyncio
import threading
from types import ModuleType
from typing import Any

import pytest

from dewpoint.apps import admission, csv_uploads, inputs
from tests.apps.api.test_csv_starts_api import FILE, csv_body, csv_ready, keyed_app, uploaded  # noqa: F401
from tests.apps.api.test_csv_uploads_api import CSV_TYPE, uploads_url
from tests.apps.api.test_run_requests_api import as_role, runs_url

pytestmark = pytest.mark.usefixtures("development_deployment")
WAIT_S = 3.0  # how long a held step waits for the other request: on the loop, all of it


class Held:
    """`module.name`'s first call held until another request is answered (at most WAIT_S); `served`, whether it was."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str) -> None:
        self.entered, self.answered, self.served = threading.Event(), threading.Event(), list[bool]()
        step = getattr(module, name)

        def held(*args: Any, **kwargs: Any) -> Any:
            if not self.entered.is_set():
                self.entered.set()
                self.served.append(self.answered.wait(WAIT_S))
            return step(*args, **kwargs)

        monkeypatch.setattr(module, name, held)

    async def meanwhile(self, client: Any, job: Any) -> Any:
        """`job`'s answer, another request asked while the step is held."""
        task = asyncio.ensure_future(job)
        while not self.entered.is_set() and not task.done():  # noqa: ASYNC110  # a thread sets it, or the loop
            await asyncio.sleep(0.01)
        if not self.served:  # the step still waiting: off the loop
            assert (await client.get("/health/ready")).status_code == 200
            self.answered.set()
        return await task


@pytest.mark.parametrize(("module", "name"), [(csv_uploads, "read_table"), (csv_uploads, "described")])
async def test_an_uploads_parse_and_preview_leave_the_loop_serving(
    keyed_app, csv_ready, owner_sessionmaker, api_settings, monkeypatch, module: ModuleType, name: str  # noqa: F811
) -> None:  # fmt: skip
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    held = Held(monkeypatch, module, name)
    answer = await held.meanwhile(client, client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE))
    assert answer.status_code == 201, answer.text
    assert held.served == [True]


@pytest.mark.parametrize(
    ("module", "name"), [(admission, "read_table"), (admission, "build_rows"), (inputs, "reasons"), (inputs, "split")]
)
async def test_a_csv_starts_rows_and_their_checks_leave_the_loop_serving(
    keyed_app, csv_ready, owner_sessionmaker, api_settings, monkeypatch, module: ModuleType, name: str  # noqa: F811
) -> None:  # fmt: skip
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    upload = await uploaded(client, ctx, wf)
    held = Held(monkeypatch, module, name)
    answer = await held.meanwhile(
        client, client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "held"})
    )
    assert answer.status_code == 202, answer.text
    assert held.served == [True]


async def test_a_rerun_keeping_its_inputs_rows_checks_them_off_the_loop(
    keyed_app, csv_ready, owner_sessionmaker, api_settings, monkeypatch  # noqa: F811
) -> None:  # fmt: skip
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    upload = await uploaded(client, ctx, wf)
    started = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "first"})
    assert started.status_code == 202, started.text
    held = Held(monkeypatch, inputs, "split")
    rerun_url = f"/api/v1/t/{ctx.tenant_id}/runs/{started.json()['id']}/rerun"
    answer = await held.meanwhile(
        client, client.post(rerun_url, json={"mode": "live"}, headers={"Idempotency-Key": "again"})
    )
    assert answer.status_code == 202, answer.text
    assert held.served == [True]
