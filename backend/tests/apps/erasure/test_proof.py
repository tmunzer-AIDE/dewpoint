# SPDX-License-Identifier: Apache-2.0
"""The 2b-4a M4 proof: once a tenant's erasure completes, nothing of the tenant stays decodable, and nothing stays
stored beyond the agreed exceptions (the owner's list): its audit records, under the platform's audit-retention policy;
backups, until they expire (not testable here); its tombstone (`tenants`, anonymized); the erasure's record and the
Temporal ids it keeps for reconciliation, identifiers only; identifier-only logs; and late Temporal items awaiting
reconciliation (none here). The erasure runs end to end: started through the API by a platform admin, carried on by
the retention process's passes against the CLI dev server, and completed, the firing bound taken as proven (the only
way any erasure completes until the owner rules on it)."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import text
from temporalio.client import ScheduleBackfill, ScheduleOverlapPolicy

from dewpoint.apps.dispatcher import schedule_sync
from dewpoint.apps.erasure import bound, process, temporal
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.erasure import Stage
from dewpoint.engine.runtime.ids import run_workflow_id, schedule_workflow_id
from tests.apps.api.test_erasure_api import admin_of, url
from tests.apps.dispatcher.test_schedule_sync import Leading
from tests.apps.erasure.support import populated
from tests.apps.erasure.test_stages import QUEUE, Root, serving, until
from tests.core.ingress.support import KEYRING
from tests.core.retention.support import sql

pytestmark = pytest.mark.usefixtures("development_deployment")
KEPT = {"audit_log", "tenant_erasures", "tenant_erasure_known"}  # what still names the tenant's id


async def test_after_completion_nothing_of_the_tenant_is_decodable_or_stored_beyond_the_exceptions(
    server, app, api_settings, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, retention_sessionmaker,
    monkeypatch,
) -> None:  # fmt: skip
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    tenant, client = data["t"], server.client
    mark = f"proof-{uuid.uuid4().hex}"  # what the tenant wrote: its names and labels
    for statement in ("update tenants set name = :m, slug = :m where id = :t",
                      "update workflows set name = :m where tenant_id = :t",
                      "update connections set name = :m where tenant_id = :t",
                      "update webhook_endpoints set name = :m where tenant_id = :t"):  # fmt: skip
        await sql(owner_sessionmaker, statement, m=mark, t=tenant)
    async with owner_sessionmaker() as s, s.begin():  # a secret under the tenant's data key, and the audit a create
        await tenant_scope(s, tenant)
        secret = await KEYRING.encrypt(s, tenant_id=tenant, purpose="connection.secret", context="c", plaintext=b"pw")
        await s.execute(text("update connections set secret_ct = :b where tenant_id = :t"), {"b": secret, "t": tenant})
        await audit.record(s, tenant_id=tenant, actor_id=None, action="workflow.create", target_type="workflow",
                           target_id=str(data["w"]), details={"name": mark})  # fmt: skip
    # Temporal: its schedule, ticks left open, and a run still executing with a child (its row ended long ago)
    assert await schedule_sync.sync_one(dispatch_sessionmaker, client, Leading(), tenant, data["schedule"]) == "synced"
    schedule_id = schedule_workflow_id(str(tenant), str(data["schedule"]))
    handle = client.get_schedule_handle(schedule_id)
    at = (await handle.describe()).info.created_at.replace(second=0, microsecond=0)
    await handle.backfill(ScheduleBackfill(start_at=at - timedelta(minutes=2), end_at=at,
                                           overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
    root = run_workflow_id(str(tenant), str(data["tree"]["root"]))
    async with serving(client):
        await client.start_workflow(Root.run, True, id=root, task_queue=QUEUE)
        for _ in range(100):  # it continued as new and started its child
            if len(await temporal.listed(client, f"t:{tenant}:run:")) >= 3:
                break
            await asyncio.sleep(0.1)
    temporal_before = await temporal.listed(client, f"t:{tenant}:")
    assert len(temporal_before) >= 4  # ticks, the run's chain, its child

    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    async with admin:
        assert (await admin.post(url(tenant), json={"confirm": mark})).status_code == 202
    assert await until(retention_sessionmaker, client, tenant, Stage.BOUND) == Stage.BOUND
    monkeypatch.setattr(bound, "FIRING_BOUND", "proven for the test")
    await sql(owner_sessionmaker, "insert into namespace_boundaries (name) values ('test boundary')")
    await process.advance(retention_sessionmaker, client, tenant)
    await sql(owner_sessionmaker, "update tenant_erasures set check_after = now() - interval '1 second' "
              "where tenant_id = :t", t=tenant)  # fmt: skip
    for _ in range(100):  # visibility lags behind the deletes: a finding reopens, each time with its own bound
        if await process.advance(retention_sessionmaker, client, tenant) == Stage.COMPLETE:
            break
        await asyncio.sleep(1)
        await sql(owner_sessionmaker, "update tenant_erasures set check_after = now() - interval '1 second' "
                  "where tenant_id = :t and step = 90", t=tenant)  # fmt: skip
    else:
        raise AssertionError("never completed")

    async with owner_sessionmaker() as s:
        # Nothing decodable: the tenant's data keys are gone (the keyring answers a missing key as a bad tag), whatever
        # still holds a ciphertext, a backup say, with the key-encryption key still configured
        with pytest.raises(InvalidTag):
            await KEYRING.decrypt(s, tenant_id=tenant, purpose="connection.secret", context="c", blob=secret)
        # Nothing stored that names the tenant's id, but the exceptions
        holding = list((await s.execute(text(
            "select c.relname from pg_class c join pg_attribute a on a.attrelid = c.oid where c.relnamespace = "
            "'public'::regnamespace and c.relkind = 'r' and a.attname = 'tenant_id' and not a.attisdropped"
        ))).scalars())  # fmt: skip
        left = {table: (await s.execute(text(f"select count(*) from {table} where tenant_id = :t"),  # noqa: S608
                                        {"t": tenant})).scalar_one() for table in holding}  # fmt: skip
        tombstone = tuple((await s.execute(text("select name, slug, status from tenants where id = :t"),
                                           {"t": tenant})).one())  # fmt: skip
        # Nothing the tenant wrote, in any column of any table, but its audit records (D3c)
        columns = (await s.execute(text(
            "select table_name, column_name, data_type from information_schema.columns where table_schema = 'public' "
            "and data_type in ('text', 'character varying', 'jsonb', 'bytea')"
        ))).all()  # fmt: skip
        named = set()
        for table, column, kind in columns:
            match = (f"position(convert_to(:m, 'UTF8') in {column}) > 0" if kind == "bytea"
                     else f"{column}::text like '%' || :m || '%'")  # fmt: skip
            if (await s.execute(text(f"select exists (select 1 from {table} where {match})"),  # noqa: S608
                                {"m": mark})).scalar_one():  # fmt: skip
                named.add(table)
    assert {table for table, n in left.items() if n} == KEPT
    assert tombstone == ("Erased tenant", f"erased-{tenant}", "erased")
    assert named == {"audit_log"}
    # Nothing of the tenant in Temporal: every execution found, and its schedule, are gone, and nothing is listed
    assert await temporal.listed(client, f"t:{tenant}:") == []
    assert await temporal.schedule(client, schedule_id) is None
    for workflow_id, run_id in temporal_before:
        assert await temporal.execution(client, workflow_id, run_id) is None
    erasure: Any = None
    async with owner_sessionmaker() as s:
        erasure = (await s.execute(text("select * from tenant_erasures where tenant_id = :t"), {"t": tenant})).one()
        kinds = set((await s.execute(text("select kind from tenant_erasure_known where tenant_id = :t"),
                                     {"t": tenant})).scalars())  # fmt: skip
    assert (
        erasure.completed_at is not None and erasure.boundary == "test boundary" and kinds == {"schedule", "execution"}
    )
