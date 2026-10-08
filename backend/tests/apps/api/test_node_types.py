# SPDX-License-Identifier: Apache-2.0
"""The editor's palette of node types (sub-project 4, B5): each also says how a step of it runs."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from dewpoint.core.plugins import registry
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


async def test_the_gzipped_palette_still_says_how_each_step_runs(app, owner_sessionmaker, api_settings) -> None:
    # Plugins 3b-1 compresses the catalog; B5's metadata travels in it, through the same model (the owner's review
    # of #60).
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        zipped = await c.get("/api/v1/node-types", headers={"Accept-Encoding": "gzip"})
        plain = await c.get("/api/v1/node-types", headers={"Accept-Encoding": "identity"})
    assert zipped.headers["content-encoding"] == "gzip" and zipped.json() == plain.json()
    loop = {t["ref"]: t for t in zipped.json()}["flow.loop@1"]
    assert (loop["side_effect"], loop["timeout_s"], loop["retry"]["max_attempts"]) == ("none", 60.0, 3)


async def test_a_row_the_answers_model_refuses_is_never_sent(
    app, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    # The catalog is a raw Response, which FastAPI's response model doesn't check: the route checks NodeTypeOut itself.
    real = registry.list_node_types

    async def with_a_stray(db: Any) -> list[Any]:
        rows = await real(db)
        stray = SimpleNamespace(**{k: getattr(rows[0], k) for k in ("ref", "type", "version", "state", "manifest")})
        stray.kind = "plugin"  # neither action nor control
        return [*rows, stray]

    monkeypatch.setattr(registry, "list_node_types", with_a_stray)
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    with pytest.raises(ValidationError):
        async with c:
            await c.get("/api/v1/node-types")
