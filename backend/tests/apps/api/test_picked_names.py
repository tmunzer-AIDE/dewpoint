# SPDX-License-Identifier: Apache-2.0
"""The names a start form picked, kept with the run (editor 4f-3; the start-form pickers design §4.1): sent beside the
input, kept only where they fit the frozen version and the value they were picked for, never refused, never in the
input, its envelope or its key's digest; a re-run's copied or sent again; read back beside the value they name."""

import uuid
from typing import Any

import pytest

from tests.apps.api.test_run_requests_api import as_role, keyed_app, published_with_a_picker, runs_url
from tests.apps.test_admission import TOKEN, count, current

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
INPUT = {"token": TOKEN, "site": "a", "count": 1}
LYON = {"site": {"value": "a", "label": "Lyon DC"}}


@pytest.fixture
async def picker(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    """A published version whose `site` is a picker (and `token` sensitive, `count` a plain integer)."""
    ctx, wf, _ = await published_with_a_picker(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def started(client: Any, ctx: Any, wf: uuid.UUID, key: str = "k1", **body: Any) -> dict[str, Any]:
    answer = await client.post(runs_url(ctx, wf), json={"input": INPUT, "mode": "live", **body},
                               headers={"Idempotency-Key": key})  # fmt: skip
    assert answer.status_code == 202, answer.text
    return answer.json()  # type: ignore[no-any-return]


async def read(client: Any, ctx: Any, request_id: str) -> dict[str, Any]:
    answer = await client.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}/input")
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


async def test_a_picked_name_is_read_back_beside_the_value_it_names(
    keyed_app, picker, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = picker
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    request = await started(client, ctx, wf, names=LYON)
    assert await read(client, ctx, request["id"]) == {
        "read_back": "kept", "input": {"token": "[redacted]", "site": "a", "count": 1}, "seeds": None,
        "names": {"site": "Lyon DC"},
    }  # fmt: skip


async def test_a_name_that_doesnt_fit_is_dropped_never_refused(
    keyed_app, picker, owner_sessionmaker, api_settings
) -> None:
    """Not the value it was picked for, not a picker, a sensitive field, a field that isn't there: the start goes on."""
    ctx, wf = picker
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    names = {"site": {"value": "b", "label": "Paris"}, "count": {"value": "1", "label": "One"},
             "token": {"value": TOKEN, "label": "Token"}, "gone": {"value": "x", "label": "X"}}  # fmt: skip
    request = await started(client, ctx, wf, names=names)
    assert (await read(client, ctx, request["id"]))["names"] == {}
    assert await count(owner_sessionmaker, "run_inputs where role = 'names'") == 0


async def test_names_stay_out_of_the_keys_digest(keyed_app, picker, owner_sessionmaker, api_settings) -> None:
    """Display only: an exact retry with other names is the first request, its names the first's."""
    ctx, wf = picker
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    first = await started(client, ctx, wf, names=LYON)
    again = await started(client, ctx, wf, names={"site": {"value": "a", "label": "Renamed"}})
    assert again["id"] == first["id"]
    assert (await read(client, ctx, first["id"]))["names"] == {"site": "Lyon DC"}


@pytest.mark.parametrize(
    "names",
    [
        {"site": {"value": "a"}},
        {"site": {"value": "a", "label": ""}},
        {"site": {"value": "a", "label": "x" * 201}},
        {"site": {"value": "a" * 1001, "label": "x"}},
        {"site": {"value": "a", "label": "x", "other": 1}},
        {f"f{i}": {"value": "a", "label": "x"} for i in range(201)},
    ],
)
async def test_malformed_names_are_refused_as_a_malformed_body(
    keyed_app, picker, owner_sessionmaker, api_settings, names: Any
) -> None:
    ctx, wf = picker
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json={"input": INPUT, "names": names},
                               headers={"Idempotency-Key": "k1"})  # fmt: skip
    assert answer.status_code == 422, answer.text


async def test_a_rerun_keeps_its_originals_names_or_the_ones_it_sends(
    keyed_app, picker, owner_sessionmaker, api_settings
) -> None:
    """An untouched re-run copies them, as it copies a CSV record; one with new input keeps what it sends; names
    without new input are refused: they follow the input they were picked for."""
    ctx, wf = picker
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    first = await started(client, ctx, wf, names=LYON)
    url = f"/api/v1/t/{ctx.tenant_id}/runs/{first['id']}/rerun"
    untouched = await client.post(url, headers={"Idempotency-Key": "r1"})
    assert untouched.status_code == 202, untouched.text
    assert (await read(client, ctx, untouched.json()["id"]))["names"] == {"site": "Lyon DC"}
    changed = await client.post(url, json={"input": INPUT | {"site": "b"}, "names": {"site": {"value": "b",
                                "label": "Paris"}}}, headers={"Idempotency-Key": "r2"})  # fmt: skip
    assert changed.status_code == 202, changed.text
    assert (await read(client, ctx, changed.json()["id"]))["names"] == {"site": "Paris"}
    alone = await client.post(url, json={"names": LYON}, headers={"Idempotency-Key": "r3"})
    assert alone.status_code == 422, alone.text
