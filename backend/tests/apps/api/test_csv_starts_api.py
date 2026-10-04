# SPDX-License-Identifier: Apache-2.0
"""A CSV start through the API (engine 2b spec §7.7, §8.1): `POST …/runs` with `csv: {upload_id, mapping,
skip_invalid}`, and a re-run with a new upload. Its refusals answer with their codes: 404 `upload_not_found`, 410
`upload_expired`, 409 `upload_consumed`, 422 `csv_mapping_invalid`. A run's details show its CSV record to `run.view`:
the mapping, the file's headers, the row count and the skipped rows' numbers and codes."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import member_client
from tests.apps.api.test_csv_uploads_api import CSV_TYPE, uploads_url
from tests.apps.api.test_run_requests_api import as_role, runs_url
from tests.apps.test_admission import KEYS, TOKEN, current, published
from tests.apps.test_admission_csv import GRAPH, MAPPING

pytestmark = pytest.mark.usefixtures("development_deployment")
FILE = b"Site,VLAN,PSK\nparis,10,s3cret-psk-1\nlyon,x,\n"
INPUT = {"token": TOKEN, "site": "a"}


@pytest.fixture
def keyed_app(app: Any) -> Any:
    app.state.keys = KEYS
    return app


@pytest.fixture
async def csv_ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def uploaded(client: Any, ctx: Any, wf: uuid.UUID, data: bytes = FILE) -> str:
    answer = await client.post(uploads_url(ctx, wf), content=data, headers=CSV_TYPE)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["upload_id"])


def csv_body(upload: str, mapping: dict[str, str] = MAPPING, skip: bool = True) -> dict[str, Any]:
    return {"input": INPUT, "mode": "live", "csv": {"upload_id": upload, "mapping": mapping, "skip_invalid": skip}}


async def test_a_csv_start_is_admitted_and_its_run_shows_its_record(
    keyed_app, csv_ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    upload = await uploaded(client, ctx, wf)
    answer = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
    assert answer.status_code == 202, answer.text
    request_id = answer.json()["id"]
    again = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
    assert (again.status_code, again.json()["id"]) == (202, request_id)
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    details = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}")).json()
    assert details["csv"] == {
        "mapping": MAPPING,
        "headers": ["Site", "VLAN", "PSK"],
        "row_count": 1,
        "skipped": [{"row": 2, "code": "not_integer"}],
        "errors": [{"row": 2, "column": "vlan", "code": "not_integer"}],
        "error_count": 1,
    }
    assert "s3cret" not in str(details)


async def test_another_user_replaying_the_start_gets_a_conflict(
    keyed_app, csv_ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    upload = await uploaded(client, ctx, wf)
    assert (await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
            ).status_code == 202  # fmt: skip
    other, _ = await member_client(keyed_app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    answer = await other.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
    assert (answer.status_code, answer.json()) == (409, {"error": "idempotency_conflict"})


async def test_each_refusal_answers_with_its_code(keyed_app, csv_ready, owner_sessionmaker, api_settings) -> None:
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)

    async def started(body: dict[str, Any], key: str) -> tuple[int, str]:
        answer = await client.post(runs_url(ctx, wf), json=body, headers={"Idempotency-Key": key})
        return answer.status_code, answer.json().get("error")

    assert await started(csv_body(str(uuid.uuid4())), "u") == (404, "upload_not_found")
    upload = await uploaded(client, ctx, wf)
    assert await started(csv_body(upload, {"vlan": "VLAN"}), "m") == (422, "csv_mapping_invalid")
    assert await started(csv_body(upload, skip=False), "r") == (422, "input_invalid")
    assert await started(csv_body(upload), "c1") == (202, None)
    assert await started(csv_body(upload), "c2") == (409, "upload_consumed")
    late = await uploaded(client, ctx, wf)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update csv_uploads set created_at = now() - interval '2 hours', "
                             "expires_at = now() - interval '1 hour' where id = :i"), {"i": late})  # fmt: skip
    assert await started(csv_body(late), "e") == (410, "upload_expired")


async def test_a_rerun_takes_a_new_upload(keyed_app, csv_ready, owner_sessionmaker, api_settings) -> None:
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    first = await client.post(runs_url(ctx, wf), json=csv_body(await uploaded(client, ctx, wf)),
                              headers={"Idempotency-Key": "c1"})  # fmt: skip
    upload = await uploaded(client, ctx, wf, b"Site\nnice\n")
    body = {"input": INPUT, "csv": {"upload_id": upload, "mapping": {"site": "Site"}}}
    rerun_url = f"/api/v1/t/{ctx.tenant_id}/runs/{first.json()['id']}/rerun"
    answer = await client.post(rerun_url, json=body, headers={"Idempotency-Key": "r1"})
    assert (answer.status_code, answer.json()["source"]) == (202, "rerun"), answer.text
    details = (await client.get(f"/api/v1/t/{ctx.tenant_id}/runs/{answer.json()['id']}")).json()
    assert details["csv"]["row_count"] == 1
    again = await client.post(rerun_url, json=body, headers={"Idempotency-Key": "r1"})
    assert (again.status_code, again.json()["id"]) == (202, answer.json()["id"])  # found by its key, upload consumed
