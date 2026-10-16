# SPDX-License-Identifier: Apache-2.0
"""What a run was admitted with, read back (editor 4e-1; the runs design §4.3), `run.view`: from its request's own
envelope, redacted, never recomputed; a step test's seeds; a CSV start's input without its rows; `absent` when the
request kept none; `unreadable` when it doesn't open, its key gone included, never an error."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.test_run_requests_api import as_role, keyed_app
from tests.apps.test_admission import admit, current, published
from tests.apps.test_admission_csv import GRAPH, staged, start
from tests.apps.test_admission_drafts import STEPS_GRAPH, drafted, simulate
from tests.support.graphs import nid
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def read(app: Any, owner: Any, settings: Any, ctx: Any, run_id: uuid.UUID) -> Any:
    viewer = await as_role(app, owner, settings, ctx, "viewer")
    answer = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/input")
    assert answer.status_code == 200, answer.text
    return answer.json()


async def test_the_input_is_read_back_redacted(keyed_app, ready, owner_sessionmaker, api_sessionmaker,
                                               api_settings) -> None:  # fmt: skip
    ctx, wf = ready
    request = (await admit(api_sessionmaker, ctx, wf)).request
    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, request.id) == {
        "read_back": "kept", "input": {"token": "[redacted]", "site": "a"}, "seeds": None,
    }  # fmt: skip


async def test_a_step_tests_seeds_are_read_back(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                              values={"/steps/a/output/value": 3})).request  # fmt: skip
    found = await read(keyed_app, owner_sessionmaker, api_settings, ctx, request.id)
    assert (found["read_back"], found["input"]) == ("kept", None)
    assert found["seeds"]["values"] == {"/steps/a/output/value": "[redacted]"}  # an echo's output: tainted


async def test_a_csv_starts_input_leaves_its_rows_to_its_csv_record(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
    await current(dispatch_sessionmaker)
    upload = await staged(api_sessionmaker, ctx, wf)
    request = (await admit(api_sessionmaker, ctx, wf, csv=start(upload))).request
    found = await read(keyed_app, owner_sessionmaker, api_settings, ctx, request.id)
    assert found == {"read_back": "kept", "input": {"token": "[redacted]", "site": "a"}, "seeds": None}


async def test_a_refusal_that_froze_nothing_kept_no_input(keyed_app, ready, owner_sessionmaker, api_sessionmaker,
                                                          api_settings) -> None:  # fmt: skip
    ctx, wf = ready
    refused = (await admit(api_sessionmaker, ctx, wf, source="schedule", input={"token": 7})).request
    assert refused.status == "refused"
    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, refused.id) == {
        "read_back": "absent", "input": None, "seeds": None,
    }  # fmt: skip


async def test_an_input_that_doesnt_open_is_unreadable_its_key_gone_included(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    broken = (await admit(api_sessionmaker, ctx, wf, key="broken")).request
    kept = (await admit(api_sessionmaker, ctx, wf, key="kept")).request
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_inputs set ciphertext = :junk "
                             "where id = (select envelope_id from run_requests where id = :r)"),
                        {"junk": b"\x00" * 48, "r": broken.id})  # fmt: skip
    unreadable = {"read_back": "unreadable", "input": None, "seeds": None}
    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, broken.id) == unreadable
    keyed_app.state.keys = FixtureKeys(missing={str(ctx.tenant_id)})  # an erasure took the tenant's key
    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, kept.id) == unreadable


async def test_another_tenants_runs_input_isnt_found(keyed_app, ready, owner_sessionmaker, api_sessionmaker,
                                                     admin_sessionmaker, api_settings) -> None:  # fmt: skip
    ctx, wf = ready
    request = (await admit(api_sessionmaker, ctx, wf)).request
    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, other, "viewer")
    assert (await viewer.get(f"/api/v1/t/{other.tenant_id}/runs/{request.id}/input")).status_code == 404
