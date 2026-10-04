# SPDX-License-Identifier: Apache-2.0
"""A CSV's saved default mapping (engine 2b spec §8.1; the owner's ruling 6): one per workflow, encrypted, saved with
`trigger.manage` against the active version's declaration. An upload proposes it; one a later version no longer fits
(a column it maps is gone, a required column unmapped) is marked stale and returned as stale with each column's code,
never applied, until a new one is saved."""

from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.test_csv_uploads_api import CSV, CSV_TYPE, GRAPH, uploads_url
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.test_admission import KEYS, published
from tests.apps.test_workflow_ops import publish, save
from tests.support.graphs import G

pytestmark = pytest.mark.usefixtures("development_deployment")
MAPPING = {"site": "Where", "vlan": "Vlan id"}
FILE = b"Where,Vlan id,PSK\nparis,10,s3cret\n"


@pytest.fixture
def keyed_app(app: Any) -> Any:
    app.state.keys = KEYS
    return app


def mapping_url(ctx: Any, wf: Any) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/csv-mapping"


@pytest.fixture
async def csv_workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)


async def saved(owner: Any) -> Any:
    async with owner() as s:
        return (await s.execute(text("select * from csv_mappings"))).mappings().one()


async def test_an_editor_saves_a_default_mapping_the_next_upload_proposes(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.put(mapping_url(ctx, wf), json={"mapping": MAPPING})
    assert answer.status_code == 200, answer.text
    assert answer.json()["mapping"] == MAPPING
    row = await saved(owner_sessionmaker)
    assert b"Where" not in row["mapping"] and row["stale_at"] is None  # encrypted
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    body = (await operator.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()
    assert (body["default_mapping"], body["mapping"], body["problems"]) == ({"status": "applied"}, MAPPING, [])
    assert body["preview"] == [{"row": 1, "cells": {"site": "paris", "vlan": "10"}}]


async def test_without_a_saved_mapping_the_exact_matches_are_proposed(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    body = (await operator.post(uploads_url(ctx, wf), content=b"Site,PSK\nx,y\n", headers=CSV_TYPE)).json()
    assert (body["default_mapping"], body["mapping"]) == ({"status": "none"}, {"site": "Site", "psk": "PSK"})


async def test_a_header_the_file_lacks_is_the_uploads_problem_not_the_mappings(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await editor.put(mapping_url(ctx, wf), json={"mapping": MAPPING})
    body = (await editor.post(uploads_url(ctx, wf), content=b"Where\nparis\n", headers=CSV_TYPE)).json()
    assert body["default_mapping"] == {"status": "applied"}
    assert body["problems"] == [{"column": "vlan", "code": "unknown_header"}]
    assert (await saved(owner_sessionmaker))["stale_at"] is None


async def test_a_mapping_a_later_version_no_longer_fits_is_stale_and_never_applied(
    keyed_app, csv_workflow, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await editor.put(mapping_url(ctx, wf), json={"mapping": MAPPING})
    columns = [CSV["columns"][0], {"header": "Region", "name": "region", "type": "string", "required": True}]
    v2 = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": {"columns": columns}}}
    await save(api_sessionmaker, ctx, wf, v2)
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
    body = (await editor.post(uploads_url(ctx, wf), content=b"Site,Region\nparis,eu\n", headers=CSV_TYPE)).json()
    assert body["default_mapping"] == {
        "status": "stale",
        "problems": [{"column": "vlan", "code": "unknown_column"}, {"column": "region", "code": "required_unmapped"}],
    }
    assert body["mapping"] == {"site": "Site", "region": "Region"}  # the exact matches, never the stale mapping
    assert (await saved(owner_sessionmaker))["stale_at"] is not None
    assert (await editor.put(mapping_url(ctx, wf), json={"mapping": {"site": "Site", "region": "Region"}})
            ).status_code == 200  # fmt: skip
    assert (await saved(owner_sessionmaker))["stale_at"] is None


@pytest.mark.parametrize(
    ("mapping", "problems"),
    [
        ({"site": "Where", "nope": "X"}, [{"column": "nope", "code": "unknown_column"}]),
        ({"vlan": "VLAN"}, [{"column": "site", "code": "required_unmapped"}]),
    ],
)
async def test_a_mapping_that_doesnt_fit_the_declaration_isnt_saved(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings, mapping: dict[str, str], problems: list[Any]
) -> None:
    ctx, wf = csv_workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.put(mapping_url(ctx, wf), json={"mapping": mapping})
    assert (answer.status_code, answer.json()) == (422, {"error": "csv_mapping_invalid", "problems": problems})
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from csv_mappings"))).scalar_one() == 0


async def test_saving_a_default_needs_trigger_manage(keyed_app, csv_workflow, owner_sessionmaker, api_settings) -> None:
    ctx, wf = csv_workflow
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    assert (await operator.put(mapping_url(ctx, wf), json={"mapping": MAPPING})).status_code == 403
