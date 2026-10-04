# SPDX-License-Identifier: Apache-2.0
"""Uploading a CSV for a start (engine 2b spec §8.1): `POST /t/{tid}/workflows/{wid}/csv-uploads` (`run.start`) takes a
raw `text/csv` body, read as it arrives up to the smaller of the declaration's `max_bytes` and the platform's 5 MiB, and
stages the file encrypted for one hour, owned by its uploader. It answers with the headers, the exact matches mapped, a
preview of the first rows with sensitive columns left out, and each row's errors as its number, column and code."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.engine.graph.csv import MAX_BYTES
from tests.apps.api.helpers import member_client
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.test_admission import KEYS, published
from tests.support.graphs import G

pytestmark = pytest.mark.usefixtures("development_deployment")
CSV = {
    "columns": [
        {"header": "Site", "name": "site", "type": "string", "required": True},
        {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
        {"header": "PSK", "name": "psk", "type": "string", "sensitive": True},
    ],
    "max_bytes": 100_000,
}
GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": CSV}}
FILE = b"Site,VLAN,PSK,Extra\nparis,10,s3cret-psk,x\nlyon,,,y\n,20,k3y-two,z\n"
CSV_TYPE = {"Content-Type": "text/csv; charset=utf-8"}


@pytest.fixture
def keyed_app(app: Any) -> Any:
    """The API with fixture keys, which its tenants here have."""
    app.state.keys = KEYS
    return app


def uploads_url(ctx: Any, wf: uuid.UUID) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/csv-uploads"


@pytest.fixture
async def csv_workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)


async def stored(owner: Any, upload_id: str) -> Any:
    async with owner() as s:
        found = await s.execute(text("select * from csv_uploads where id = :i"), {"i": upload_id})
        return found.mappings().one()


async def test_an_operator_uploads_a_csv_and_gets_its_mapping_preview_and_errors(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["headers"] == ["Site", "VLAN", "PSK", "Extra"]
    assert body["mapping"] == {"site": "Site", "vlan": "VLAN", "psk": "PSK"}
    assert (body["row_count"], body["problems"], body["masked_columns"]) == (3, [], ["psk"])
    assert body["preview"] == [
        {"row": 1, "cells": {"site": "paris", "vlan": "10"}},
        {"row": 2, "cells": {"site": "lyon", "vlan": ""}},
        {"row": 3, "cells": {"site": "", "vlan": "20"}},
    ]  # the sensitive column and the undeclared one are never shown
    assert (body["errors"], body["error_count"]) == ([{"row": 3, "column": "site", "code": "required"}], 1)
    row = await stored(owner_sessionmaker, body["upload_id"])
    assert (row["workflow_id"], row["size_bytes"], row["row_count"]) == (wf, len(FILE), 3)
    assert b"s3cret-psk" not in row["staged"] and b"paris" not in row["staged"]  # encrypted
    assert len(row["file_digest"]) == 32 and row["consumed_by"] is None
    assert (row["expires_at"] - row["created_at"]).total_seconds() == 3600


async def test_the_upload_belongs_to_its_uploader(keyed_app, csv_workflow, owner_sessionmaker, api_settings) -> None:
    ctx, wf = csv_workflow
    client, me = await member_client(keyed_app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    upload = (await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()["upload_id"]
    assert (await stored(owner_sessionmaker, upload))["owner_id"] == me


async def chunks(total: int, size: int, read: list[int]) -> AsyncIterator[bytes]:
    yield b"Site\n"
    for _ in range(total // size):
        read.append(size)
        yield b"x" * (size - 1) + b"\n"


async def test_the_declarations_cap_stops_the_read_as_bytes_arrive(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    """A chunked body with no length: the route stops one chunk past the declaration's 100,000 bytes, not after the
    6 MiB the client would send, and nothing is staged."""
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    read: list[int] = []
    answer = await client.post(uploads_url(ctx, wf), content=chunks(6 * 1024 * 1024, 16_384, read), headers=CSV_TYPE)
    assert (answer.status_code, answer.json()) == (413, {"error": "too_large"})
    assert sum(read) <= 100_000 + 16_384
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from csv_uploads"))).scalar_one() == 0


async def test_a_declared_length_past_the_cap_is_refused_before_reading(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    read: list[int] = []
    headers = CSV_TYPE | {"Content-Length": str(100_001)}
    answer = await client.post(uploads_url(ctx, wf), content=chunks(100_001, 16_384, read), headers=headers)
    assert (answer.status_code, read) == (413, [])


async def test_other_routes_keep_the_api_body_limit(keyed_app, csv_workflow, owner_sessionmaker, api_settings) -> None:
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    big = b'{"input": {"x": "' + b"y" * (api_settings.max_request_body_bytes + 1) + b'"}}'
    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/runs", content=big,
                               headers={"Content-Type": "application/json", "Idempotency-Key": "k"})  # fmt: skip
    assert answer.status_code == 413
    assert MAX_BYTES > api_settings.max_request_body_bytes


@pytest.mark.parametrize(
    ("body", "code"),
    [(b"Site,Site\nx,y\n", "csv_duplicate_header"), (b"\xff\xfe", "csv_encoding"), (b"", "csv_empty")],
)
async def test_a_file_that_cant_be_read_is_refused_with_its_code(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings, body: bytes, code: str
) -> None:
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(uploads_url(ctx, wf), content=body, headers=CSV_TYPE)
    assert (answer.status_code, answer.json()) == (422, {"error": code})


async def test_a_required_column_the_file_lacks_is_a_mapping_problem(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    body = (await client.post(uploads_url(ctx, wf), content=b"Where,VLAN\nparis,1\n", headers=CSV_TYPE)).json()
    assert body["mapping"] == {"vlan": "VLAN"}
    assert (body["problems"], body["errors"]) == ([{"column": "site", "code": "required_unmapped"}], [])


async def test_what_the_route_refuses(
    keyed_app, csv_workflow, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    assert (await client.post(uploads_url(ctx, wf), content=FILE, headers={"Content-Type": "application/json"})
            ).status_code == 415  # fmt: skip
    plain = G().node("a", "testkit.echo@1", {"value": 1}).data()
    _, other = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, plain)
    assert (await client.post(uploads_url(ctx, other), content=FILE, headers=CSV_TYPE)).status_code == 404  # not ours
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    assert (await viewer.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).status_code == 403


async def test_a_workflow_without_a_csv_takes_no_upload(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    plain = G().node("a", "testkit.echo@1", {"value": 1}).data()
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, plain)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)
    assert (answer.status_code, answer.json()) == (409, {"error": "csv_not_declared"})


WIDE = {"columns": [{"header": f"h{i}", "name": f"c{i}", "type": "string", "required": True} for i in range(200)]}
WIDE_FILE = (",".join(f"h{i}" for i in range(200)) + "\n" + ("," * 199 + "\n") * 10_000).encode()


async def test_an_upload_at_the_permitted_limits_lists_100_errors_and_counts_them_all(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The owner's M2 review: 200 required columns and 10,000 records of empty cells, 2 MB, break 2 million rules. The
    answer lists the first 100 and counts every one, and the file is staged as its own bytes, sealed."""
    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": WIDE}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(uploads_url(ctx, wf), content=WIDE_FILE, headers=CSV_TYPE)
    assert answer.status_code == 201, answer.text[:200]
    body = answer.json()
    assert (len(body["errors"]), body["error_count"], body["row_count"]) == (100, 2_000_000, 10_000)
    row = await stored(owner_sessionmaker, body["upload_id"])
    assert len(row["staged"]) <= len(WIDE_FILE) + 64  # the file's bytes, never a parsed form several times larger


async def test_a_cell_longer_than_pythons_default_field_limit_uploads(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The owner's M2 review: the byte cap governs a field's length, not Python's 131,072-character default."""
    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": {"columns": CSV["columns"]}}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    long = b"Site\n" + b"x" * 140_000 + b"\n"
    answer = await client.post(uploads_url(ctx, wf), content=long, headers=CSV_TYPE)
    assert answer.status_code == 201, answer.text[:200]
    assert len(answer.json()["preview"][0]["cells"]["site"]) == 140_000


async def test_an_integer_cell_too_long_for_python_to_read_is_a_rows_error(
    keyed_app, csv_workflow, owner_sessionmaker, api_settings
) -> None:
    """The whole-branch review: a 5,000-digit integer cell was an unhandled `ValueError` (a 500); it's the row's
    `out_of_range`, so the upload answers and a start can skip the row."""
    ctx, wf = csv_workflow
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    long = b"Site,VLAN\nparis," + b"1" * 5000 + b"\n"
    answer = await client.post(uploads_url(ctx, wf), content=long, headers=CSV_TYPE)
    assert answer.status_code == 201, answer.text[:200]
    body = answer.json()
    assert (body["errors"], body["error_count"]) == ([{"row": 1, "column": "vlan", "code": "out_of_range"}], 1)
