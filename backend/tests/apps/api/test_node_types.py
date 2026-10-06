# SPDX-License-Identifier: Apache-2.0
"""The editor's palette of node types (sub-project 4, B5): each also says how a step of it runs."""

import pytest

from tests.apps.api.helpers import session_client
from tests.support.registry import sync_test_plugins


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def test_each_type_says_how_a_step_of_it_runs(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        r = await c.get("/api/v1/node-types")
    assert r.status_code == 200, r.text
    by_ref = {t["ref"]: t for t in r.json()}
    loop = by_ref["flow.loop@1"]
    assert (loop["kind"], loop["ports"], loop["side_effect"]) == ("control", ["body", "done"], "none")
    assert (loop["credentials"], loop["capabilities"], loop["timeout_s"]) == ([], [], 60.0)
    assert loop["retry"] == {
        "max_attempts": 3,
        "initial_interval_s": 1.0,
        "backoff": 2.0,
        "max_interval_s": 60.0,
        "non_retryable": [],
    }
    assert (loop["icon"], loop["options"]) == ("repeat", [])
    assert by_ref["flow.switch@1"]["dynamic_ports"] == "cases"
    call = by_ref["testkit.http_call@1"]
    assert (call["kind"], call["credentials"], call["side_effect"]) == ("action", ["testkit"], "idempotent")
    assert by_ref["testkit.pick@1"]["options"] == ["site_id"]  # plugins-3 D3: a field its options() lists


async def test_the_palette_needs_a_session(client) -> None:
    assert (await client.get("/api/v1/node-types")).status_code == 401
