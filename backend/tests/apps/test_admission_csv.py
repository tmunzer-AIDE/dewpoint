# SPDX-License-Identifier: Apache-2.0
"""A CSV start (engine 2b spec §8.1; the owner's rulings 5 and 7–8, and the M1 corrections): admission builds the
trigger's rows from a staged upload and consumes it in the same transaction.

- The key first: the digest covers what was asked (the input, the upload, the mapping, `skip_invalid`), so an exact
  retry is recognized without the rows, after the upload is gone, and returned only to the upload's owner.
- Then the upload, locked and checked (its tenant, its owner, its workflow, not expired, not consumed): concurrent
  starts yield one consumer, and a start that finds it consumed looks its own key up again.
- The rows are built against the frozen version's declaration, the sensitive cells claimed with taint, the upload's
  cells cleared, and the mapping, headers and skipped rows kept in a `run_inputs` row of the role `csv`."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission, csv_uploads
from dewpoint.apps.inputs import RESERVED_INPUT
from dewpoint.core.claims import secret_index
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from dewpoint.engine.graph.csv import MAX_BYTES
from dewpoint.engine.handles import StoredClaim, resolve_value
from tests.apps.api.helpers import member_client
from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, admit, count, current, published
from tests.apps.test_workflow_ops import publish, save

pytestmark = pytest.mark.usefixtures("development_deployment")
CSV = {
    "columns": [
        {"header": "Site", "name": "site", "type": "string", "required": True},
        {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
        {"header": "PSK", "name": "psk", "type": "string", "sensitive": True},
    ],
    "max_rows": 10_000,
    "max_bytes": MAX_BYTES,
}
GRAPH = {"graph_format": 1, "nodes": [{"id": str(uuid.uuid4()), "key": "a", "type": "testkit.echo@1",
         "config": {"value": 1}}], "edges": [], "settings": {"input_schema": SCHEMA, "csv": CSV}}  # fmt: skip
FILE = b"Site,VLAN,PSK\nparis,10,s3cret-psk-1\nlyon,,\n"
MAPPING = {"site": "Site", "vlan": "VLAN", "psk": "PSK"}
ROWS = [{"site": "paris", "vlan": 10, "psk": "s3cret-psk-1"}, {"site": "lyon", "vlan": 1}]


@pytest.fixture
async def csv_ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def staged(api: Any, ctx: Any, wf: uuid.UUID, data: bytes = FILE, owner: uuid.UUID | None = None) -> uuid.UUID:
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        body = await csv_uploads.stage(s, KEYS, tenant_id=ctx.tenant_id, owner_id=owner or ctx.user.id,
                                       workflow_id=wf, csv=CSV, data=data)  # fmt: skip
    return uuid.UUID(body["upload_id"])


def start(upload: uuid.UUID, mapping: dict[str, str] = MAPPING, skip_invalid: bool = False) -> admission.CsvStart:
    return admission.CsvStart(upload, mapping, skip_invalid)


async def full_input(dispatch: Any, ctx: Any, request_id: uuid.UUID) -> Any:
    async with dispatch() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        cipher = ClaimCipher(KEYS)

        async def fetch(claim_id: str) -> StoredClaim:
            got = await claims.read_request_claim(s, cipher, ctx.tenant_id, request_id=request_id,
                                                  claim_id=uuid.UUID(claim_id))  # fmt: skip
            return StoredClaim(got.value, got.sensitive_pointers)

        envelope = await claims.read_envelope(s, cipher, ctx.tenant_id, request_id=request_id)
        return (await resolve_value(envelope, fetch)).value


async def upload_row(owner: Any, upload: uuid.UUID) -> Any:
    async with owner() as s:
        return (await s.execute(text("select * from csv_uploads where id = :i"), {"i": upload})).mappings().one()


async def record(api: Any, ctx: Any, request_id: uuid.UUID) -> Any:
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        return await claims.read_csv_record(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=request_id)


async def test_a_csv_start_freezes_its_rows_and_consumes_its_upload(
    csv_ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    admitted = await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    r = admitted.request
    assert admitted.new and r.status == "queued"
    trigger = await full_input(dispatch_sessionmaker, ctx, r.id)
    assert trigger == {"token": TOKEN, "site": "a", "rows": ROWS, "row_count": 2}
    async with owner_sessionmaker() as s:
        tainted_claims = text("select count(*) from run_inputs where owner_run_id = :r and role = 'claim' "
                              "and sensitive_pointers::text = '[\"\"]'")  # fmt: skip
        tainted = (await s.execute(tainted_claims, {"r": r.id})).scalar_one()
        audit = (await s.execute(text("select details from audit_log where action = 'run.request'"))).scalar_one()
    assert tainted == 2  # the token and the one PSK cell, each claimed with taint
    row = await upload_row(owner_sessionmaker, upload)
    assert (row["staged"], row["consumed_by"]) == (None, r.id) and row["consumed_at"] is not None
    assert await record(api_sessionmaker, ctx, r.id) == {
        "mapping": MAPPING, "headers": ["Site", "VLAN", "PSK"], "row_count": 2, "skipped": [], "errors": [],
        "error_count": 0,
    }  # fmt: skip
    assert (audit["csv_digest"], audit["csv_rows"], audit["csv_skipped"]) == (row["file_digest"].hex(), 2, 0)


async def test_an_exact_retry_returns_its_request_after_the_upload_was_consumed(csv_ready, api_sessionmaker) -> None:
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    first = await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    again = await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    assert (again.new, again.request.id) == (False, first.request.id)
    with pytest.raises(admission.IdempotencyConflictError):
        await admit(api_sessionmaker, ctx, wf, csv=start(upload, skip_invalid=True))  # another request, same key


async def test_an_exact_retry_is_returned_only_to_the_uploads_owner(
    csv_ready, owner_sessionmaker, api_sessionmaker, api_settings, app
) -> None:
    """The owner's correction: another user of the tenant who knows the key and the upload's id gets a conflict."""
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    _, other = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    async with api_sessionmaker() as s, s.begin():
        with pytest.raises(admission.IdempotencyConflictError):
            await admission.admit_request(s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, source="manual",
                                          actor_id=other, mode="live", idempotency_key="k1",
                                          input={"token": TOKEN, "site": "a"}, csv=start(upload))  # fmt: skip


async def test_another_start_with_a_consumed_upload_is_refused(csv_ready, api_sessionmaker) -> None:
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload))
    assert refused.value.reason == "upload_consumed"


async def lock_waiters(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
                    ).scalar_one())  # fmt: skip


@pytest.mark.parametrize("same_key", [True, False])
async def test_concurrent_starts_with_one_upload_yield_one_consumer(
    csv_ready, owner_sessionmaker, api_sessionmaker, monkeypatch, same_key
) -> None:
    """The second start looks its key up before the first commits, then waits on the upload's row lock. Once the first
    commits, it finds the upload consumed and looks its key up again: under the same key, the first's request; under
    another, `upload_consumed`."""
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    second: list[asyncio.Task[Any]] = []

    async def race() -> None:
        if second:
            return
        second.append(asyncio.create_task(admit(api_sessionmaker, ctx, wf, key="k1" if same_key else "k2",
                                                csv=start(upload))))  # fmt: skip
        for _ in range(200):  # until it waits on this transaction's row lock
            if await lock_waiters(owner_sessionmaker):
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the second start never waited on the upload")

    monkeypatch.setattr(admission, "_after_upload_locked", race)
    first = (await admit(api_sessionmaker, ctx, wf, csv=start(upload))).request
    if same_key:
        again = await second[0]
        assert (again.new, again.request.id) == (False, first.id)
    else:
        with pytest.raises(admission.AdmissionRefusedError) as refused:
            await second[0]
        assert refused.value.reason == "upload_consumed"
    assert await count(owner_sessionmaker, "run_requests") == 1


async def test_an_upload_of_another_user_or_workflow_is_never_found(
    csv_ready, owner_sessionmaker, api_sessionmaker, api_settings, app
) -> None:
    ctx, wf = csv_ready
    _, other = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    theirs = await staged(api_sessionmaker, ctx, wf, owner=other)
    elsewhere = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, 'X', true, "
                             "'{}')"), {"w": elsewhere, "t": ctx.tenant_id})  # fmt: skip
    for_another = await staged(api_sessionmaker, ctx, elsewhere)
    for upload in (theirs, for_another, uuid.uuid4()):
        with pytest.raises(admission.AdmissionRefusedError) as refused:
            await admit(api_sessionmaker, ctx, wf, key=str(upload), csv=start(upload))
        assert refused.value.reason == "upload_not_found"
    assert (await upload_row(owner_sessionmaker, theirs))["consumed_by"] is None


async def test_an_expired_upload_is_refused(csv_ready, owner_sessionmaker, api_sessionmaker) -> None:
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update csv_uploads set created_at = now() - interval '2 hours', "
                             "expires_at = now() - interval '1 hour' where id = :i"), {"i": upload})  # fmt: skip
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    assert refused.value.reason == "upload_expired"


async def test_a_mapping_the_frozen_version_refuses_is_refused(csv_ready, api_sessionmaker) -> None:
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(upload, {"vlan": "VLAN"}))
    assert (refused.value.reason, refused.value.messages) == (
        "csv_mapping_invalid", ["The mapping's column `site`: required_unmapped."],
    )  # fmt: skip


async def test_a_row_that_breaks_a_rule_refuses_the_start_unless_invalid_rows_are_skipped(
    csv_ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, wf = csv_ready
    data = b"Site,VLAN,PSK\nparis,ten,k3y-value-1\nlyon,2,\n"
    upload = await staged(api_sessionmaker, ctx, wf, data)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    assert (refused.value.reason, refused.value.messages) == (
        "input_invalid", ["The CSV's row 1, column `vlan`: not_integer."],
    )  # fmt: skip
    assert not any("ten" in m or "k3y" in m for m in refused.value.messages)
    assert (await upload_row(owner_sessionmaker, upload))["consumed_by"] is None  # nothing commits
    r = (await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload, skip_invalid=True))).request
    assert (await full_input(dispatch_sessionmaker, ctx, r.id))["rows"] == [{"site": "lyon", "vlan": 2}]
    kept = await record(api_sessionmaker, ctx, r.id)
    assert (kept["skipped"], kept["error_count"]) == ([{"row": 1, "code": "not_integer"}], 1)
    assert kept["errors"] == [{"row": 1, "column": "vlan", "code": "not_integer"}]


async def test_sensitive_cells_past_the_secret_index_bound_refuse_the_start_and_keep_nothing(
    csv_ready, owner_sessionmaker, api_sessionmaker, monkeypatch
) -> None:
    """Each sensitive cell joins the run tree's index (2b-3a task 18): a file whose cells pass its bound is refused with
    `secret_index_limit`, its claims discarded and its upload left for another start."""
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf, b"Site,VLAN,PSK\nparis,10,psk-one-1\nlyon,2,psk-two-2\n")
    monkeypatch.setattr(secret_index, "MAX_STRINGS", 2)  # the input's token and one cell fit; the second cell doesn't
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    assert refused.value.reason == "secret_index_limit"
    assert await count(owner_sessionmaker, "run_inputs") == 0
    assert (await upload_row(owner_sessionmaker, upload))["consumed_by"] is None


async def test_a_csv_start_still_refuses_rows_in_its_input(csv_ready, api_sessionmaker) -> None:
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN, "rows": []}, csv=start(upload))
    assert refused.value.messages == [RESERVED_INPUT]


async def test_a_workflow_without_a_csv_takes_no_csv_start(ready_plain, api_sessionmaker) -> None:
    ctx, wf = ready_plain
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(uuid.uuid4()))
    assert refused.value.reason == "csv_not_declared"


@pytest.fixture
async def ready_plain(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def test_a_rerun_takes_the_original_rows_or_a_new_csv(csv_ready, api_sessionmaker, dispatch_sessionmaker) -> None:
    """The original input's rows come back from the retained claims, which admission accepts as only a re-run's own
    input; a re-run may take a new upload instead."""
    ctx, wf = csv_ready
    first = (await admit(api_sessionmaker, ctx, wf, csv=start(await staged(api_sessionmaker, ctx, wf)))).request
    original = await full_input(dispatch_sessionmaker, ctx, first.id)
    again = await admit(api_sessionmaker, ctx, wf, key="r1", source="rerun", input=original,
                        rerun=admission.Rerun(first.id))  # fmt: skip
    assert (await full_input(dispatch_sessionmaker, ctx, again.request.id))["rows"] == ROWS
    upload = await staged(api_sessionmaker, ctx, wf, b"Site\nnice\n")
    fresh = await admit(api_sessionmaker, ctx, wf, key="r2", source="rerun",
                        rerun=admission.Rerun(first.id, {"token": TOKEN}, start(upload, {"site": "Site"})),
                        input={"token": TOKEN}, csv=start(upload, {"site": "Site"}))  # fmt: skip
    assert (await full_input(dispatch_sessionmaker, ctx, fresh.request.id))["rows"] == [{"site": "nice", "vlan": 1}]


WIDE = {"columns": [{"header": f"h{i}", "name": f"c{i}", "type": "string", "required": True} for i in range(200)],
        "max_rows": 10_000, "max_bytes": MAX_BYTES}  # fmt: skip
WIDE_FILE = (",".join(f"h{i}" for i in range(200)) + "\n" + ("," * 199 + "\n") * 10_000).encode()


async def test_a_skip_invalid_start_at_the_permitted_limits_keeps_a_bounded_record(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """The owner's M2 review: 2 million broken rules in a 2 MB file. A refused start names the first five; a start that
    skips them keeps each skipped record's number and first code, the first 100 errors in detail and an exact count,
    in a record that grows with the records, never with records times columns."""
    graph = {**GRAPH, "settings": {"input_schema": SCHEMA, "csv": WIDE}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
    await current(dispatch_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        body = await csv_uploads.stage(s, KEYS, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=wf,
                                       csv=WIDE, data=WIDE_FILE)  # fmt: skip
    upload = uuid.UUID(body["upload_id"])
    mapping = {f"c{i}": f"h{i}" for i in range(200)}
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(upload, mapping))
    assert refused.value.messages == [f"The CSV's row 1, column `c{i}`: required." for i in range(5)]
    r = (await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload, mapping, skip_invalid=True))).request
    kept = await record(api_sessionmaker, ctx, r.id)
    assert (kept["row_count"], kept["error_count"], len(kept["errors"])) == (0, 2_000_000, 100)
    assert kept["skipped"] == [{"row": n, "code": "required"} for n in range(1, 10_001)]
    assert len(json.dumps(kept)) < 400_000
    async with owner_sessionmaker() as s:
        audit = (await s.execute(text("select details from audit_log where action = 'run.request'"))).scalar_one()
    assert (audit["csv_rows"], audit["csv_skipped"]) == (0, 10_000)


async def test_the_frozen_versions_caps_govern_the_start(
    csv_ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    """The upload is staged as its bytes, and read again at the start under the version it freezes: one published
    since with a lower cap refuses a file the earlier one took."""
    ctx, wf = csv_ready
    upload = await staged(api_sessionmaker, ctx, wf)
    lower = {**GRAPH, "settings": {"input_schema": SCHEMA, "csv": {**CSV, "max_rows": 1}}}
    await save(api_sessionmaker, ctx, wf, lower)
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
    assert (refused.value.reason, refused.value.messages) == ("input_invalid", ["The CSV file: csv_too_many_rows."])
