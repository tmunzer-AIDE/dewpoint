# SPDX-License-Identifier: Apache-2.0
"""`dewpoint schedules inventory-cutover` (the owner's D15 ruling on the 2b-4b M1 checkpoint): the schedule inventory
becomes the new dispatcher's and the erasure's to rely on only once every writer from before migration 0040 is gone,
on the operator's attestation, and an idempotent catch-up has accounted for any schedule its capture missed."""

import asyncio
import uuid

from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.cli.test_keys import OLD, _env, _recorded
from tests.conftest import _url_for
from tests.support.workflows import seed_workflow


def test_the_inventory_cutover_is_recorded_once_after_its_catch_up_and_never_while_an_old_dispatcher_polls(
    pg_url, _test_users, monkeypatch
) -> None:  # fmt: skip
    """The operator attests (`--attest`) that every writer from before 0040 is gone: no poller snapshot can prove an
    old API stopped; it only refuses while Temporal shows an old dispatcher still polling (its identity lacks the tick
    contract's mark). With --confirm, as the key admin, it records the cutover once, audited with the attestation,
    after giving any schedule without an incarnation (one its capture missed) its incarnation 0 and its life until then
    unknown, in the same transaction. Without, it's a dry run."""
    from dewpoint.apps import tick_contract
    from dewpoint.apps.cli import main as cli

    pollers: list[str] = ["4242@an-old-dispatcher"]

    async def admission_pollers(settings: object) -> list[str]:
        return pollers

    monkeypatch.setattr(cli, "_admission_pollers", admission_pollers)
    _recorded(pg_url)
    _env(monkeypatch, _url_for(pg_url, "dewpoint_admin"), DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    r = CliRunner()

    async def run(statement: str, **params: object) -> list[object]:
        engine = make_engine(pg_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                found = await s.execute(text(statement), params)
                return list(found.scalars()) if found.returns_rows else []
        finally:
            await engine.dispose()

    def sql(statement: str, **params: object) -> list[object]:
        return asyncio.run(run(statement, **params))

    async def missed() -> object:
        """A schedule the capture missed (its trigger off while it was added, as only an owner could)."""
        engine = make_engine(pg_url)
        try:
            tenant, workflow, _ = await seed_workflow(make_sessionmaker(engine))
        finally:
            await engine.dispose()
        [user] = await run("insert into users (id, email, password_hash) values (gen_random_uuid(), :e, 'x') "
                           "returning id", e=f"{uuid.uuid4().hex[:10]}@corp.test")  # fmt: skip
        await run("alter table schedules disable trigger schedules_inventoried")
        try:
            [found] = await run("insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
                                "generation, synced_generation) values (gen_random_uuid(), :t, :w, 60, 'live', "
                                "'\\x01', :u, 2, 2) returning id", t=tenant, w=workflow, u=user)  # fmt: skip
        finally:
            await run("alter table schedules enable trigger schedules_inventoried")
        return found

    [kept] = sql("select at from schedule_inventory_cutover")
    sql("delete from schedule_inventory_cutover")  # as a database upgraded while the old application ran
    try:
        schedule = asyncio.run(missed())
        unattested = r.invoke(app, ["schedules", "inventory-cutover", "--confirm"])
        assert unattested.exit_code == 2 and "--attest" in unattested.output, unattested.output
        refused = r.invoke(app, ["schedules", "inventory-cutover", "--attest", "--confirm"])
        assert refused.exit_code == 1 and "1 poller" in refused.output, refused.output
        pollers[:] = [f"4243@a-new-dispatcher {tick_contract.IDENTITY}"]
        dry = r.invoke(app, ["schedules", "inventory-cutover", "--attest"])
        assert dry.exit_code == 0 and "a dry run" in dry.output, dry.output
        assert sql("select count(*) from schedule_inventory_cutover") == [0]
        done = r.invoke(app, ["schedules", "inventory-cutover", "--attest", "--confirm"])
        assert done.exit_code == 0 and "1 schedule(s) caught up" in done.output, done.output
        [at] = sql("select at from schedule_inventory_cutover")
        assert sql("select count(*) from schedule_incarnations i join schedule_intervals v using (temporal_id) "
                   "where i.schedule_id = :s and i.number = 0 and i.backfilled and v.reason = 'before_migration'",
                   s=schedule) == [1]  # fmt: skip
        audited = sql("select details from audit_log where action = 'schedules.inventory_cutover'")
        assert audited == [{"caught_up": 1, "attested": cli.INVENTORY_ATTESTED}]
        again = r.invoke(app, ["schedules", "inventory-cutover", "--attest", "--confirm"])
        assert again.exit_code == 0 and "already recorded" in again.output, again.output
        assert sql("select at from schedule_inventory_cutover") == [at]
    finally:
        sql("delete from schedule_inventory_cutover")
        sql("insert into schedule_inventory_cutover (at) values (:a)", a=kept)
