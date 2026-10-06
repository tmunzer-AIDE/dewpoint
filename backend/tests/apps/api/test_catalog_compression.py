# SPDX-License-Identifier: Apache-2.0
"""The catalog compressed (the owner's ruling on the 3b-1 checkpoint): `GET /node-types` answers every node type's
schemas (8 MB with Mist's), so it and `GET /trigger-types` are gzipped for a client that accepts it. Only they are:
their answers are the plugins' public metadata, holding no secret and reflecting no input, while compressing an answer
that does (a session's token beside what a client sent) would let its length reveal the secret (BREACH)."""

from typing import Any

import pytest

from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.plugins.flow import PLUGIN as FLOW
from tests.apps.api.helpers import session_client
from tests.apps.api.test_trigger_types import DEMO
from tests.support.plugins.testkit import TESTKIT


@pytest.fixture(autouse=True)
async def synced(owner_sessionmaker: Any) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, DEMO])


@pytest.mark.parametrize("route", ["/api/v1/node-types", "/api/v1/trigger-types"])
async def test_the_catalog_is_gzipped_for_a_client_that_accepts_it(
    app: Any, owner_sessionmaker: Any, api_settings: Any, route: str
) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        zipped = await c.get(route, headers={"Accept-Encoding": "gzip, deflate"})
        plain = await c.get(route, headers={"Accept-Encoding": "identity"})
        refused = await c.get(route, headers={"Accept-Encoding": "gzip;q=0"})
    assert zipped.status_code == plain.status_code == 200
    assert zipped.headers["content-encoding"] == "gzip" and "accept-encoding" in zipped.headers["vary"].lower()
    assert "content-encoding" not in plain.headers and "content-encoding" not in refused.headers
    assert zipped.json() == plain.json() == refused.json() and plain.json()
    assert plain.headers["content-type"] == "application/json"


async def test_an_answer_that_could_hold_a_secret_is_never_compressed(
    app: Any, owner_sessionmaker: Any, api_settings: Any
) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        for route in ("/api/v1/auth/session", "/api/v1/connection-types"):
            answer = await c.get(route, headers={"Accept-Encoding": "gzip"})
            assert answer.status_code == 200 and "content-encoding" not in answer.headers, route
