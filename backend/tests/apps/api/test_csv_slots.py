# SPDX-License-Identifier: Apache-2.0
"""The API process's CSV work, bounded (the 2b-4b plan's M3, item 5): an upload's parse holds about 90 MiB at the
platform's caps, and a CSV start's built rows about 235 MiB until its transaction commits (`probes/csv_memory.py`),
so a process takes at most `csv_concurrency` of them at once (2 by default). One past it is refused at once, 503
`csv_busy` with `Retry-After`, before an upload's body is read or a start opens its staged file: nothing is recorded,
and the client asks again. A re-run that keeps its original's input (which may hold a CSV's rows) takes a slot too."""

from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.csv_slots import CsvBusyError, CsvSlots
from dewpoint.core.config import Settings
from tests.apps.api.test_csv_starts_api import INPUT, csv_body, csv_ready, keyed_app, uploaded  # noqa: F401
from tests.apps.api.test_csv_uploads_api import CSV_TYPE, chunks, uploads_url
from tests.apps.api.test_run_requests_api import as_role, runs_url
from tests.apps.test_admission import current, published

pytestmark = pytest.mark.usefixtures("development_deployment")


def test_a_process_holds_at_most_its_slots_and_a_finished_one_frees_its_own() -> None:
    slots = CsvSlots(2)
    with slots.held(), slots.held():
        with pytest.raises(CsvBusyError), slots.held():
            pass
    with slots.held(), slots.held():  # each freed, even past a refusal
        pass
    with pytest.raises(RuntimeError), slots.held():
        raise RuntimeError("a failed upload frees its slot too")
    with slots.held(), slots.held():
        pass


def test_the_default_is_two_and_a_process_needs_one() -> None:
    assert Settings.model_fields["csv_concurrency"].default == 2
    with pytest.raises(ValueError, match="csv_concurrency"):
        Settings(csv_concurrency=0, public_origin="https://dewpoint.test")  # type: ignore[call-arg]


async def test_an_upload_past_the_processs_slots_is_refused_before_its_body_is_read(
    keyed_app, csv_ready, owner_sessionmaker, api_settings  # noqa: F811
) -> None:  # fmt: skip
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    keyed_app.state.csv_slots = CsvSlots(1)
    read: list[int] = []
    with keyed_app.state.csv_slots.held():  # another upload, still parsing
        answer = await client.post(uploads_url(ctx, wf), content=chunks(1_000_000, 16_384, read), headers=CSV_TYPE)
    assert (answer.status_code, answer.json(), answer.headers.get("retry-after")) == (503, {"error": "csv_busy"}, "1")
    assert read == []
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from csv_uploads"))).scalar_one() == 0
    assert (await client.post(uploads_url(ctx, wf), content=b"Site\nparis\n", headers=CSV_TYPE)).status_code == 201


async def test_a_csv_start_or_a_rerun_keeping_its_input_past_the_slots_is_refused_recording_nothing(
    keyed_app, csv_ready, owner_sessionmaker, api_settings  # noqa: F811
) -> None:  # fmt: skip
    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    upload = await uploaded(client, ctx, wf)
    started = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "first"})
    assert started.status_code == 202, started.text
    keyed_app.state.csv_slots = CsvSlots(1)
    again = await uploaded(client, ctx, wf)
    rerun_url = f"/api/v1/t/{ctx.tenant_id}/runs/{started.json()['id']}/rerun"
    with keyed_app.state.csv_slots.held():
        busy = await client.post(runs_url(ctx, wf), json=csv_body(again), headers={"Idempotency-Key": "second"})
        kept = await client.post(rerun_url, json={"mode": "live"}, headers={"Idempotency-Key": "third"})
    for answer in (busy, kept):
        assert (answer.status_code, answer.json(), answer.headers.get("retry-after")) == (
            503, {"error": "csv_busy"}, "1",
        )  # fmt: skip
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from run_requests"))).scalar_one() == 1
    done = await client.post(runs_url(ctx, wf), json=csv_body(again), headers={"Idempotency-Key": "second"})
    assert done.status_code == 202, done.text


async def test_a_start_without_a_csv_takes_no_slot(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings  # noqa: F811
) -> None:  # fmt: skip
    """Only the work that may hold a CSV's rows is bounded: a plain start goes on whatever the CSV work."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    keyed_app.state.csv_slots = CsvSlots(1)
    with keyed_app.state.csv_slots.held():
        answer = await client.post(runs_url(ctx, wf), json={"input": INPUT, "mode": "live"},
                                   headers={"Idempotency-Key": "plain"})  # fmt: skip
    assert answer.status_code == 202, answer.text


async def test_a_rerun_keeping_its_input_takes_its_slot_before_reading_that_input(
    keyed_app, csv_ready, owner_sessionmaker, api_settings, monkeypatch  # noqa: F811
) -> None:  # fmt: skip
    """The fresh M3 review's I5: the original's input (a CSV's rows, perhaps) is decoded only in a slot, so a refused
    re-run never holds it, and a client retrying every second never decodes it again and again."""
    from dewpoint.apps.api.routes import run_requests

    ctx, wf = csv_ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    upload = await uploaded(client, ctx, wf)
    started = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "first"})
    read: list[str] = []
    original = run_requests.original_input

    async def counted(*args: Any, **kwargs: Any) -> Any:
        read.append("input")
        return await original(*args, **kwargs)

    monkeypatch.setattr(run_requests, "original_input", counted)
    keyed_app.state.csv_slots = CsvSlots(1)
    rerun_url = f"/api/v1/t/{ctx.tenant_id}/runs/{started.json()['id']}/rerun"
    with keyed_app.state.csv_slots.held():
        busy = await client.post(rerun_url, json={"mode": "live"}, headers={"Idempotency-Key": "again"})
    assert (busy.status_code, read) == (503, [])
    done = await client.post(rerun_url, json={"mode": "live"}, headers={"Idempotency-Key": "again"})
    assert (done.status_code, read) == (202, ["input"]), done.text
    assert keyed_app.state.csv_slots.held_now == 0
