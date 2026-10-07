# SPDX-License-Identifier: Apache-2.0
"""`dewpoint schedules inventory-cutover` (the owner's D15 ruling on the 2b-4b M1 checkpoint): the schedule inventory
becomes the new dispatcher's and the erasure's to rely on only once every writer from before migration 0040 is gone,
on the operator's attestation, and an idempotent catch-up has accounted for any schedule its capture missed."""

import asyncio
import contextlib
import threading
import time
import uuid
from collections.abc import Iterator

import asyncpg
from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.cli.test_keys import OLD, _env, _recorded
from tests.conftest import _url_for
from tests.support.workflows import seed_workflow


def _sql(pg_url: str, statement: str, **params: object) -> list[object]:
    async def run() -> list[object]:
        engine = make_engine(pg_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                found = await s.execute(text(statement), params)
                return list(found.scalars()) if found.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


@contextlib.contextmanager
def _restoring(pg_url: str) -> Iterator[list[object]]:
    """The suite's cutover taken away for the block, as a database upgraded while the old application ran, and put
    back after. The catch-up reaches every schedule: what it gives those without an incarnation (other tests', the new
    sync's alone) is taken back after. Yields their ids."""
    [kept] = _sql(pg_url, "select at from schedule_inventory_cutover")
    _sql(pg_url, "delete from schedule_inventory_cutover")
    others = _sql(pg_url, "select id from schedules s where not exists (select 1 from schedule_incarnations i "
                          "where i.schedule_id = s.id)")  # fmt: skip
    try:
        yield others
    finally:
        _sql(pg_url, "delete from schedule_inventory_cutover")
        _sql(pg_url, "insert into schedule_inventory_cutover (at) values (:a)", a=kept)
        for table in ("schedule_intervals", "schedule_incarnations"):
            _sql(pg_url, f"delete from {table} where schedule_id = any(:s)", s=others)


def _seeded(pg_url: str, n: int, *, captured: bool, misses: int = 0) -> object:
    """`n` schedules of a tenant of their own, added as the old application did, synced; `captured`: with the capture
    on (each gets its incarnation 0), else off (as only the table's owner could turn it). Their tenant."""

    async def run() -> object:
        engine = make_engine(pg_url)
        try:
            tenant, workflow, _ = await seed_workflow(make_sessionmaker(engine))
            async with make_sessionmaker(engine)() as s, s.begin():
                [user] = (await s.execute(text("insert into users (id, email, password_hash) values "
                                               "(gen_random_uuid(), :e, 'x') returning id"),
                                          {"e": f"{uuid.uuid4().hex[:10]}@corp.test"})).scalars()  # fmt: skip
                if not captured:
                    await s.execute(text("alter table schedules disable trigger schedules_inventoried"))
                await s.execute(text("insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, "
                                     "created_by, generation, synced_generation, misses) select gen_random_uuid(), "
                                     ":t, :w, 60, 'live', '\\x01', :u, 2, 2, :m from generate_series(1, :n)"),
                                {"t": tenant, "w": workflow, "u": user, "m": misses, "n": n})  # fmt: skip
                if not captured:
                    await s.execute(text("alter table schedules enable trigger schedules_inventoried"))
        finally:
            await engine.dispose()
        return tenant

    return asyncio.run(run())


def _unseeded(pg_url: str, tenant: object) -> None:
    for table in ("schedule_intervals", "schedule_incarnations", "schedules"):
        _sql(pg_url, f"delete from {table} where tenant_id = :t", t=tenant)


LATEST = "select details from audit_log where action = 'schedules.inventory_cutover' order by seq desc limit 1"


def _cutover_env(pg_url: str, monkeypatch) -> list[str]:
    from dewpoint.apps import tick_contract
    from dewpoint.apps.cli import main as cli

    async def admission_pollers(settings: object) -> list[str]:
        return [f"4243@a-new-dispatcher {tick_contract.IDENTITY}"]

    monkeypatch.setattr(cli, "_admission_pollers", admission_pollers)
    _recorded(pg_url)
    _env(monkeypatch, _url_for(pg_url, "dewpoint_admin"), DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    return ["schedules", "inventory-cutover", "--attest", "--confirm"]


def test_the_inventory_cutover_is_recorded_once_after_its_catch_up_and_never_while_an_old_dispatcher_polls(
    pg_url, _test_users, monkeypatch
) -> None:  # fmt: skip
    """The operator attests (`--attest`) that every writer from before 0040 is gone: no poller snapshot can prove an
    old API stopped; it only refuses while Temporal shows an old dispatcher still polling (its identity lacks the tick
    contract's mark). With --confirm, as the key admin, it first catches up, giving any schedule without an incarnation
    (one its capture missed) its incarnation 0 and its life until then unknown, then records the cutover once, audited
    with the attestation. Without, it's a dry run."""
    from dewpoint.apps import tick_contract
    from dewpoint.apps.cli import main as cli

    pollers: list[str] = ["4242@an-old-dispatcher"]

    async def admission_pollers(settings: object) -> list[str]:
        return pollers

    monkeypatch.setattr(cli, "_admission_pollers", admission_pollers)
    _recorded(pg_url)
    _env(monkeypatch, _url_for(pg_url, "dewpoint_admin"), DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    r = CliRunner()
    with _restoring(pg_url) as others:
        tenant = _seeded(pg_url, 1, captured=False)
        [schedule] = _sql(pg_url, "select id from schedules where tenant_id = :t", t=tenant)
        try:
            unattested = r.invoke(app, ["schedules", "inventory-cutover", "--confirm"])
            assert unattested.exit_code == 2 and "--attest" in unattested.output, unattested.output
            refused = r.invoke(app, ["schedules", "inventory-cutover", "--attest", "--confirm"])
            assert refused.exit_code == 1 and "1 poller" in refused.output, refused.output
            pollers[:] = [f"4243@a-new-dispatcher {tick_contract.IDENTITY}"]
            dry = r.invoke(app, ["schedules", "inventory-cutover", "--attest"])
            assert dry.exit_code == 0 and "a dry run" in dry.output, dry.output
            assert _sql(pg_url, "select count(*) from schedule_inventory_cutover") == [0]
            done = r.invoke(app, ["schedules", "inventory-cutover", "--attest", "--confirm"])
            caught = len(others) + 1
            assert done.exit_code == 0 and f"{caught} schedule(s) caught up" in done.output, done.output
            [at] = _sql(pg_url, "select at from schedule_inventory_cutover")
            assert _sql(pg_url, "select count(*) from schedule_incarnations i join schedule_intervals v using "
                                "(temporal_id) where i.schedule_id = :s and i.number = 0 and i.backfilled and "
                                "v.reason = 'before_migration'", s=schedule) == [1]  # fmt: skip
            assert _sql(pg_url, LATEST) == [{"caught_up": caught, "refreshed": 0, "attested": cli.INVENTORY_ATTESTED}]
            again = r.invoke(app, ["schedules", "inventory-cutover", "--attest", "--confirm"])
            assert again.exit_code == 0 and "already recorded" in again.output, again.output
            assert _sql(pg_url, "select at from schedule_inventory_cutover") == [at]
        finally:
            _unseeded(pg_url, tenant)


class _Writer:
    """A schedule writer's open transaction (`ROW EXCLUSIVE` on schedules, as any insert holds until it commits), on a
    thread of its own until the block ends."""

    def __init__(self, pg_url: str) -> None:
        self.url = pg_url.replace("postgresql+asyncpg://", "postgresql://")
        self.held, self.done = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=lambda: asyncio.run(self._hold()))

    async def _hold(self) -> None:
        c = await asyncpg.connect(self.url)
        try:
            async with c.transaction():
                await c.execute("LOCK TABLE schedules IN ROW EXCLUSIVE MODE")
                self.held.set()
                await asyncio.to_thread(self.done.wait)
        finally:
            await c.close()

    def __enter__(self) -> "_Writer":
        self.thread.start()
        assert self.held.wait(10)
        return self

    def __exit__(self, *_: object) -> None:
        self.done.set()
        self.thread.join()


def test_the_cutover_waits_for_schedules_writers_only_briefly_and_gives_way_to_them(
    pg_url, _test_users, monkeypatch
) -> None:  # fmt: skip
    """Its final step's lock on schedules (their inserts held off while it records) is waited for at most `LOCK_WAIT`
    an attempt, so a writer arriving meanwhile, queued behind it, waits no longer; then it gives way and tries again.
    Still busy after `ATTEMPTS`, it records nothing and says so (exit 1). Unbounded, one writer left open would have
    queued every schedule write behind it (the review's M2, held to D15's bar: no writer waits long)."""
    from dewpoint.core.platform import inventory

    command = _cutover_env(pg_url, monkeypatch)
    monkeypatch.setattr(inventory, "ATTEMPTS", 3)
    monkeypatch.setattr(inventory, "PAUSE_S", 0.1)
    with _restoring(pg_url):
        answers: list[object] = []
        with _Writer(pg_url):
            attempt = threading.Thread(target=lambda: answers.append(CliRunner().invoke(app, command)))
            started = time.monotonic()
            attempt.start()
            attempt.join(20)
            took = time.monotonic() - started
        attempt.join()
        [busy] = answers
        assert busy.exit_code == 1 and "busy" in busy.output, busy.output  # type: ignore[attr-defined]
        assert took < 10 and _sql(pg_url, "select count(*) from schedule_inventory_cutover") == [0]
        done = CliRunner().invoke(app, command)
        assert done.exit_code == 0 and "recorded the inventory's cutover" in done.output, done.output


TABLES = "('schedules'::regclass, 'schedule_incarnations'::regclass, 'schedule_intervals'::regclass)"
SCHEDULES_READ = f"""SELECT coalesce(sum(pg_stat_get_xact_tuples_returned(c.oid)
  + pg_stat_get_xact_tuples_fetched(c.oid)), 0) FROM pg_class c
WHERE c.oid IN {TABLES} OR c.oid IN (SELECT indexrelid FROM pg_index WHERE indrelid IN {TABLES})"""


def test_the_cutovers_final_step_reads_no_schedule_however_many_there_are(pg_url, _test_users) -> None:
    """The owner's review of checkpoint 3: the cutover held a lock schedules' writers wait for while it scanned every
    schedule, caught up and refreshed, so its hold grew with them. The catch-up now runs before it, in batches; the
    final step, holding schedules' inserts off only while it records, reads no schedule, incarnation or span, however
    many there are."""

    async def record() -> int:
        engine = make_engine(pg_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                await s.execute(text("SELECT schedule_inventory_cutover_record()"))
                return int((await s.execute(text(SCHEDULES_READ))).scalar_one())
        finally:
            await engine.dispose()

    with _restoring(pg_url):
        tenant = _seeded(pg_url, 3_000, captured=True)
        try:
            assert asyncio.run(record()) == 0
            assert _sql(pg_url, "select count(*) from schedule_inventory_cutover") == [1]
        finally:
            _unseeded(pg_url, tenant)


def test_the_catch_up_runs_in_committed_batches_and_an_interrupted_one_goes_on_from_them(
    pg_url, _test_users, monkeypatch
) -> None:  # fmt: skip
    """2,500 schedules the capture missed, and 500 whose counts the old dispatcher recorded after the capture copied
    them: caught up and refreshed a batch of `CATCH_UP_BATCH` at a time, each committed on its own, holding no lock a
    schedule's writer waits for. Interrupted after its first batch, that batch stays done and nothing is recorded; run
    again, the catch-up goes on, and the cutover is recorded."""
    from dewpoint.core.platform import inventory

    command = _cutover_env(pg_url, monkeypatch)
    monkeypatch.setattr(inventory, "CATCH_UP_BATCH", 1_000)
    batch, calls = inventory._batch, []

    async def interrupted(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) > 1:
            raise KeyboardInterrupt
        return await batch(*args, **kwargs)  # type: ignore[arg-type]

    with _restoring(pg_url):
        missed, copied = _seeded(pg_url, 2_500, captured=False), _seeded(pg_url, 500, captured=True)
        try:
            _sql(pg_url, "update schedules set misses = 5 where tenant_id = :t", t=copied)  # the old dispatcher's
            monkeypatch.setattr(inventory, "_batch", interrupted)
            stopped = CliRunner().invoke(app, command)
            assert stopped.exit_code != 0 and _sql(pg_url, "select count(*) from schedule_inventory_cutover") == [0]
            [first] = _sql(pg_url, "select count(*) from schedule_incarnations where tenant_id = :t", t=missed)
            assert 0 < first <= 1_000  # type: ignore[operator]  # the first batch's, committed
            monkeypatch.setattr(inventory, "_batch", batch)
            done = CliRunner().invoke(app, command)
            assert done.exit_code == 0 and "recorded the inventory's cutover" in done.output, done.output
            assert _sql(pg_url, "select count(*) from schedule_incarnations where tenant_id = :t and number = 0 and "
                                "backfilled", t=missed) == [2_500]  # fmt: skip
            assert _sql(pg_url, "select count(*) from schedule_incarnations where tenant_id = :t and misses = 5",
                        t=copied) == [500]  # fmt: skip
        finally:
            _unseeded(pg_url, missed)
            _unseeded(pg_url, copied)


def test_the_cutover_refuses_while_the_capture_is_off(pg_url, _test_users, monkeypatch) -> None:
    """The catch-up covers every schedule committed before its batches passed; one added afterwards with the capture
    off would be missed, so the final step, holding schedules' inserts and the trigger's state still, refuses while the
    capture is off (only the table's owner can turn it off): nothing is recorded."""
    command = _cutover_env(pg_url, monkeypatch)
    with _restoring(pg_url):
        _sql(pg_url, "alter table schedules disable trigger schedules_inventoried")
        try:
            refused = CliRunner().invoke(app, command)
            assert refused.exit_code != 0 and _sql(pg_url, "select count(*) from schedule_inventory_cutover") == [0]
        finally:
            _sql(pg_url, "alter table schedules enable trigger schedules_inventoried")


class _Writers:
    """Schedules' writers and readers through a cutover, each on a connection of its own, one operation at a time:
    an insert (as the API adds a schedule), an update, a read of an incarnation; each operation's time kept."""

    def __init__(self, pg_url: str, tenant: object) -> None:
        self.url, self.tenant = pg_url.replace("postgresql+asyncpg://", "postgresql://"), tenant
        self.times: list[float] = []
        self.started, self.done = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=lambda: asyncio.run(self._run()))

    async def _loop(self, statement: str) -> None:
        c = await asyncpg.connect(self.url)
        try:
            row = await c.fetchrow("select workflow_id, created_by from schedules where tenant_id = $1 limit 1",
                                   self.tenant)  # fmt: skip
            while not self.done.is_set():
                t0 = time.monotonic()
                await c.execute(statement.format(t=self.tenant, w=row["workflow_id"], u=row["created_by"]))
                self.times.append(time.monotonic() - t0)
                await asyncio.sleep(0.01)
        finally:
            await c.close()

    async def _run(self) -> None:
        loops = [asyncio.create_task(self._loop(statement)) for statement in (
            "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by) values "
            "(gen_random_uuid(), '{t}', '{w}', 60, 'live', '\\x01', '{u}')",
            "update schedules set updated_at = now() where id = (select id from schedules where tenant_id = '{t}' "
            "order by random() limit 1)",
            "select count(*) from schedule_incarnations where tenant_id = '{t}' and number = 0",
        )]  # fmt: skip
        await asyncio.sleep(0.3)
        self.started.set()
        await asyncio.gather(*loops)

    def __enter__(self) -> "_Writers":
        self.thread.start()
        assert self.started.wait(10)
        return self

    def __exit__(self, *_: object) -> None:
        self.done.set()
        self.thread.join()


def test_schedules_writers_wait_briefly_through_a_whole_cutover(pg_url, _test_users, monkeypatch) -> None:
    """The owner's review of checkpoint 3, measured: writers and readers of schedules run through a whole cutover (a
    catch-up of 5,000 schedules and the final step): none waits more than a fraction of a second, and the cutover is
    recorded. The lock probe measures it at scale (`tests/probes/cutover_locks.py`)."""
    command = _cutover_env(pg_url, monkeypatch)
    with _restoring(pg_url):
        tenant = _seeded(pg_url, 5_000, captured=False, misses=2)
        try:
            with _Writers(pg_url, tenant) as writers:
                done = CliRunner().invoke(app, command)
                time.sleep(0.3)
            assert done.exit_code == 0 and "recorded the inventory's cutover" in done.output, done.output
            assert len(writers.times) > 30 and max(writers.times) < 1.0
        finally:
            _unseeded(pg_url, tenant)
