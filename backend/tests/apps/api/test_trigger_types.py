# SPDX-License-Identifier: Apache-2.0
"""The trigger types the synced plugins declare (plugins-3 D17): what a webhook endpoint for one is set up with, where
an event names its topic, and each topic's schema, for the editor to type a workflow's trigger."""

from typing import Any

from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.sdk import Plugin, Trigger
from tests.apps.api.helpers import session_client
from tests.support.plugins.testkit import TESTKIT

EVENT = {"type": "object", "properties": {"topic": {"type": "string", "const": "a"}}, "required": ["topic"]}
DEMO = Plugin(
    name="demo",
    version="1.0.0",
    nodes=(),
    connection_types=(),
    triggers=(Trigger("demo.webhook", "Demo webhook", "bearer", "/topic", {"a": EVENT}),),
)


async def test_trigger_types_come_from_synced_manifests(app: Any, owner_sessionmaker: Any, api_settings: Any) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, DEMO])
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        r = await c.get("/api/v1/trigger-types")
    assert r.status_code == 200
    assert r.json() == [
        {
            "plugin": "demo",
            "key": "demo.webhook",
            "label": "Demo webhook",
            "endpoint": {"auth": "bearer", "events_pointer": None, "id_source": "none"},
            "topic_pointer": "/topic",
            "topics": {"a": EVENT},
        }
    ]


async def test_trigger_types_need_a_session(app: Any) -> None:
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://dewpoint.test") as c:
        assert (await c.get("/api/v1/trigger-types")).status_code == 401
