# SPDX-License-Identifier: Apache-2.0
"""A schedule's picked names (editor 4f-3; the start-form pickers design §4.1): kept where they fit the active version,
sealed under `schedule.names` with the schedule's id as context, never shown; replaced with its input, kept without it,
cleared with its tombstone; each tick's request carries those that still fit the version active then."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import tick
from dewpoint.core.claims.cipher import ClaimCipher
from tests.apps.api.test_run_requests_api import as_role, keyed_app, published_with_a_picker
from tests.apps.test_admission import KEYS, TOKEN, current, published_again

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
INPUT = {"token": TOKEN, "site": "a"}  # what a version without the picker takes too
LYON = {"site": {"value": "a", "label": "Lyon DC"}}
BODY = {"cron": "0 9 * * *", "input": INPUT, "names": LYON | {"count": {"value": "1", "label": "One"}}}


@pytest.fixture
async def picker(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf, _ = await published_with_a_picker(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def sealed(owner: Any, schedule_id: str) -> bytes | None:
    async with owner() as s:
        found = await s.execute(text("select names from schedules where id = :i"), {"i": schedule_id})
        blob = found.scalar_one()
        return bytes(blob) if blob is not None else None


async def opened(owner: Any, ctx: Any, schedule_id: str) -> Any:
    blob = await sealed(owner, schedule_id)
    if blob is None:
        return None
    plain = await ClaimCipher(KEYS, purpose="schedule.names").open(str(ctx.tenant_id), schedule_id, blob)
    return json.loads(plain)


async def scheduled(client: Any, ctx: Any, wf: uuid.UUID, body: Any = BODY) -> str:
    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/schedules", json=body)
    assert answer.status_code == 201, answer.text
    assert "names" not in answer.json() and "Lyon DC" not in answer.text
    return str(answer.json()["id"])


async def test_a_schedules_names_are_sealed_with_it_and_never_shown(
    keyed_app, picker, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = picker
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    schedule_id = await scheduled(editor, ctx, wf)
    assert b"Lyon DC" not in (await sealed(owner_sessionmaker, schedule_id) or b"")
    assert await opened(owner_sessionmaker, ctx, schedule_id) == LYON  # `count` isn't a picker: dropped
    shown = await editor.get(f"/api/v1/t/{ctx.tenant_id}/schedules/{schedule_id}")
    assert "names" not in shown.json() and "Lyon DC" not in shown.text


async def test_names_follow_the_input_they_were_picked_for(keyed_app, picker, owner_sessionmaker, api_settings) -> None:
    """Replaced with a new input (none given: none kept), kept without one, refused alone; gone with the tombstone."""
    ctx, wf = picker
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    schedule_id = await scheduled(editor, ctx, wf)
    url = f"/api/v1/t/{ctx.tenant_id}/schedules/{schedule_id}"
    assert (await editor.patch(url, json={"enabled": False})).status_code == 200
    assert await opened(owner_sessionmaker, ctx, schedule_id) == LYON
    paris = {"site": {"value": "b", "label": "Paris"}}
    assert (await editor.patch(url, json={"input": INPUT | {"site": "b"}, "names": paris})).status_code == 200
    assert await opened(owner_sessionmaker, ctx, schedule_id) == paris
    assert (await editor.patch(url, json={"names": LYON})).status_code == 422
    assert (await editor.patch(url, json={"input": INPUT})).status_code == 200
    assert await sealed(owner_sessionmaker, schedule_id) is None
    assert (await editor.patch(url, json={"input": INPUT, "names": LYON})).status_code == 200
    assert (await editor.delete(url)).status_code == 204
    assert await sealed(owner_sessionmaker, schedule_id) is None


async def test_each_ticks_request_carries_the_names_that_still_fit(
    keyed_app, picker, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = picker
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    schedule_id = await scheduled(editor, ctx, wf)

    async def fired(ago: int) -> dict[str, Any]:
        key = tick.tick_key(schedule_id, datetime.now(UTC) - timedelta(seconds=ago))[0]
        async with dispatch_sessionmaker() as s, s.begin():
            await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=uuid.UUID(schedule_id), key=key)
        async with owner_sessionmaker() as s:
            request_id = (await s.execute(text("select id from run_requests where idempotency_key = :k"),
                                          {"k": key})).scalar_one()  # fmt: skip
        answer = await editor.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}/input")
        assert answer.status_code == 200, answer.text
        return answer.json()  # type: ignore[no-any-return]

    assert (await fired(60))["names"] == {"site": "Lyon DC"}
    await published_again(api_sessionmaker, ctx, wf, api_settings)  # `site` no longer a picker
    assert (await fired(30))["names"] == {}
