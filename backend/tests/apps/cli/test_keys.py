# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
import uuid

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.platform.service import DEVELOPMENT, record_environment
from tests.conftest import _url_for

OLD, NEW = base64.b64encode(os.urandom(32)).decode(), base64.b64encode(os.urandom(32)).decode()


def _env(monkeypatch, pg_url: str, **kek: str) -> None:
    for k, v in {"DEWPOINT_DATABASE_URL": pg_url, "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test", **kek}.items():
        monkeypatch.setenv(k, v)
    for k in ("DEWPOINT_KEK_PREVIOUS_B64", "DEWPOINT_KEK_PREVIOUS_ID"):
        if k not in kek:
            monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()


def _tenants(pg_url: str, n: int) -> list[str]:
    """Tenants to rotate keys for: a tenant's key rotates only while it's active (2b-4a M4's fencing)."""
    made = [uuid.uuid4() for _ in range(n)]

    async def _make() -> None:
        engine = make_engine(pg_url)
        async with make_sessionmaker(engine)() as s, s.begin():
            for t in made:
                await s.execute(text("insert into tenants (id, name, slug) values (:t, 'T', :s)"),
                                {"t": t, "s": t.hex[:12]})  # fmt: skip
        await engine.dispose()

    asyncio.run(_make())
    return [str(t) for t in made]


def _recorded(pg_url: str, namespace: str = "default") -> None:
    """The deployment's record: its environment and Temporal namespace (engine 2b spec §2.1)."""

    async def _record() -> None:
        engine = make_engine(pg_url)
        async with make_sessionmaker(engine)() as s, s.begin():
            await record_environment(s, environment=DEVELOPMENT, namespace=namespace)
        await engine.dispose()

    asyncio.run(_record())


def test_status_rewrap_and_rotate(pg_url, monkeypatch) -> None:
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    [t] = _tenants(pg_url, 1)
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", t]).exit_code == 0  # creates v1 then v2 under "old"
    assert "old=2" in r.invoke(app, ["keys", "status"]).output
    assert r.invoke(app, ["keys", "rewrap"]).exit_code == 2  # no previous key configured: refuse

    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=NEW, DEWPOINT_KEK_ID="new")  # misconfigured: old key dropped too early
    assert r.invoke(app, ["keys", "status"]).exit_code == 3

    _env(
        monkeypatch,
        pg_url,
        DEWPOINT_KEK_B64=NEW,
        DEWPOINT_KEK_ID="new",
        DEWPOINT_KEK_PREVIOUS_B64=OLD,
        DEWPOINT_KEK_PREVIOUS_ID="old",
    )
    out = r.invoke(app, ["keys", "rewrap", "--batch-size", "1"])
    assert out.exit_code == 0 and "rewrapped 2" in out.output
    status = r.invoke(app, ["keys", "status"])
    assert status.exit_code == 0 and "new=2" in status.output and "old=" not in status.output


def test_key_commands_work_as_the_admin_role(pg_url, _test_users, monkeypatch) -> None:
    """Production runs these as dewpoint_admin: RLS key-admin policy on data_keys + grants on platform_keys."""
    from tests.conftest import _url_for

    admin = _url_for(pg_url, "dewpoint_admin")
    r = CliRunner()
    _env(monkeypatch, admin, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    t1, t2 = _tenants(pg_url, 2)
    for args in (["--tenant", t1], ["--tenant", t2], ["--platform"]):
        out = r.invoke(app, ["keys", "rotate-dek", *args])
        assert out.exit_code == 0 and "version: 2" in out.output, out.output
    assert "old=6" in r.invoke(app, ["keys", "status"]).output  # tenant keys from two tenants + platform

    _env(
        monkeypatch,
        admin,
        DEWPOINT_KEK_B64=NEW,
        DEWPOINT_KEK_ID="new",
        DEWPOINT_KEK_PREVIOUS_B64=OLD,
        DEWPOINT_KEK_PREVIOUS_ID="old",
    )
    assert "rewrapped 6" in r.invoke(app, ["keys", "rewrap", "--batch-size", "4"]).output
    assert r.invoke(app, ["keys", "status"]).output.strip() == "new=6"
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", "not-a-uuid"]).exit_code == 2


def test_ensure_tenants_gives_every_tenant_without_a_key_one(pg_url, _test_users, monkeypatch) -> None:
    """Engine 2b spec §6.3: tenants created before 2b-1a. It runs as the key admin, under row-level security, as
    Compose's migrate step runs it; another role is refused (review, 2b-1a)."""

    async def add() -> None:
        engine = make_engine(pg_url)
        async with engine.begin() as c:
            for n in range(2):
                await c.execute(
                    text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": uuid.uuid4(), "s": f"t{n}"}
                )
        await engine.dispose()

    asyncio.run(add())
    r = CliRunner()
    _env(monkeypatch, _url_for(pg_url, "dewpoint_api"), DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    refused = r.invoke(app, ["keys", "ensure-tenants"])
    assert (refused.exit_code, refused.output) == (
        2,
        "ERROR: run it as a dewpoint_admin login: it lists every tenant under row-level security.\n",
    )
    _env(monkeypatch, _url_for(pg_url, "dewpoint_admin"), DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    first = r.invoke(app, ["keys", "ensure-tenants"])
    assert (first.exit_code, first.output) == (
        0,
        "created a data key for 2 tenant(s)\ncreated an inbound keypair for 2 tenant(s)\n",
    )  # and an inbound keypair (2b-3b)
    again = r.invoke(app, ["keys", "ensure-tenants"])
    assert (again.exit_code, again.output) == (
        0,
        "created a data key for 0 tenant(s)\ncreated an inbound keypair for 0 tenant(s)\n",
    )
    assert "old=2" in r.invoke(app, ["keys", "status"]).output


def test_reencrypt_takes_one_scope_and_reports_what_it_sealed_again(pg_url, monkeypatch) -> None:
    """Engine 2b spec §6.4: `keys reencrypt` seals every record under an older version again, for a tenant, every
    tenant, or the platform's key; a second run finds nothing."""
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    t = str(uuid.uuid4())

    async def seed() -> None:
        engine = make_engine(pg_url)
        async with engine.begin() as c:
            await c.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": t, "s": t[:12]})
        await engine.dispose()

    asyncio.run(seed())
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", t]).exit_code == 0
    for wrong in ([], ["--all", "--platform"], ["--tenant", "not-a-uuid"]):
        assert r.invoke(app, ["keys", "reencrypt", *wrong]).exit_code == 2, wrong
    answer = r.invoke(app, ["keys", "reencrypt", "--all"])
    assert answer.exit_code == 0, answer.output
    assert f"tenant {t}: " in answer.output and "run_inputs=0" in answer.output
    platform = r.invoke(app, ["keys", "reencrypt", "--platform"])
    assert platform.exit_code == 0 and "platform: user_mfa=0" in platform.output, platform.output


def test_event_keypairs_rotate_and_retire(pg_url, monkeypatch) -> None:
    """Engine 2b spec §8.3: `keys rotate-event-key` makes a tenant's next inbound keypair; `keys retire-event-keys`
    removes the older ones no stored event names, once the newest has settled (none has, right after)."""
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    t = str(uuid.uuid4())

    async def seed() -> None:
        engine = make_engine(pg_url)
        async with engine.begin() as c:
            await c.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": t, "s": t[:12]})
        await engine.dispose()

    asyncio.run(seed())
    assert r.invoke(app, ["keys", "ensure-tenants"]).exit_code == 0  # its data key and keypair 1
    rotated = r.invoke(app, ["keys", "rotate-event-key", "--tenant", t])
    assert rotated.exit_code == 0 and "inbound keypair version: 2" in rotated.output, rotated.output
    retired = r.invoke(app, ["keys", "retire-event-keys", "--all"])
    assert retired.exit_code == 0 and "retired 0 inbound keypair(s)" in retired.output, retired.output
    assert r.invoke(app, ["keys", "rotate-event-key"]).exit_code == 2  # a tenant is required


def test_the_ingress_keys_rollout_reseals_every_secret_and_status_says_when_the_old_one_can_go(
    pg_url, monkeypatch
) -> None:
    """Engine 2b spec §8.3: like the KEK's, the ingress key's rollout is distribute, switch, reseal, retire;
    `keys ingress-status` exits 3 while a secret is sealed under a key the configuration lacks."""
    from dewpoint.core.crypto.ingress import DEDUPE_KEY, IngressKey
    from tests.core.ingress.support import endpoint

    old_raw, new_raw = os.urandom(32), os.urandom(32)
    endpoint_id = uuid.uuid4()

    async def seed() -> None:
        engine = make_engine(pg_url)
        try:
            sealed = IngressKey("in-old", old_raw).seal(DEDUPE_KEY, str(endpoint_id), b"d" * 32)
            await endpoint(make_sessionmaker(engine), endpoint_id, dedupe_key=sealed)
        finally:
            await engine.dispose()

    asyncio.run(seed())
    r = CliRunner()
    b64 = base64.b64encode
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old",
         DEWPOINT_INGRESS_KEY_B64=b64(new_raw).decode(), DEWPOINT_INGRESS_KEY_ID="in-new")  # fmt: skip
    assert r.invoke(app, ["keys", "reseal-ingress"]).exit_code == 2  # no previous key: nothing could open the old
    status = r.invoke(app, ["keys", "ingress-status"])
    assert status.exit_code == 3 and "in-old=1" in status.output, status.output
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_PREVIOUS_B64", b64(old_raw).decode())
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_PREVIOUS_ID", "in-old")
    get_settings.cache_clear()
    resealed = r.invoke(app, ["keys", "reseal-ingress"])
    assert resealed.exit_code == 0 and "dedupe_key=1" in resealed.output, resealed.output
    status = r.invoke(app, ["keys", "ingress-status"])
    assert status.exit_code == 0 and "in-new=1" in status.output and "in-old" not in status.output, status.output


def test_retire_lists_its_checks_and_retires_only_with_confirm(pg_url, monkeypatch) -> None:
    """Engine 2b spec §6.4: `keys retire` prints every check (a dry run) and, with --confirm, deletes the version only
    when all pass (exit 4 otherwise). The namespace's retention comes from Temporal (here, a stand-in)."""
    from datetime import timedelta

    from dewpoint.apps.cli import main as cli

    async def one_day(settings: object) -> timedelta:
        return timedelta(days=1)

    async def proven(settings: object, s: object, tenant: object, version: int, **_: object) -> object:
        from dewpoint.core.crypto.retire import RunProof

        return RunProof()  # Temporal shows none of its run executions (here, a stand-in)

    monkeypatch.setattr(cli, "_namespace_retention", one_day)
    monkeypatch.setattr(cli, "_run_histories", proven)
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    _recorded(pg_url)
    t = str(uuid.uuid4())

    async def seed(sql: str) -> None:
        engine = make_engine(pg_url)
        async with engine.begin() as c:
            await c.execute(text(sql), {"t": t, "s": t[:12]})
        await engine.dispose()

    asyncio.run(seed("insert into tenants(id,name,slug) values (:t,'T',:s)"))
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", t]).exit_code == 0  # 1, then 2
    dry = r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "1"])
    assert dry.exit_code == 1 and "payload_floor: no" in dry.output, dry.output
    asyncio.run(seed("update data_keys set created_at = now() - interval '9 days' where tenant_id = cast(:t as uuid) "
                     "and version = 2"))  # fmt: skip
    asyncio.run(seed("insert into run_duration_limits (days) values (1) on conflict do nothing"))
    assert r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "2", "--confirm"]).exit_code == 4  # active
    dry = r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "1"])
    assert dry.exit_code == 0 and "payload_floor: yes" in dry.output and "not retired" in dry.output, dry.output

    async def unknown(settings: object, s: object, tenant: object, version: int, **_: object) -> None:
        return None

    monkeypatch.setattr(cli, "_run_histories", unknown)  # Temporal can't be asked: never assumed gone
    dry = r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "1"])
    assert dry.exit_code == 1 and "run_histories: no (Temporal couldn't be asked)" in dry.output, dry.output
    monkeypatch.setattr(cli, "_run_histories", proven)

    done = r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "1", "--confirm"])
    assert done.exit_code == 0 and "retired version 1" in done.output, done.output


def test_the_tick_cutover_is_recorded_once_and_never_while_an_old_dispatcher_polls(pg_url, monkeypatch) -> None:
    """The owner's M3 rulings: `keys tick-cutover` records the boundary after which no dispatcher seals a tick's
    payload under a tenant's key. The operator attests (`--attest`) that every dispatcher from before 0039 has stopped
    and can't restart: a poller snapshot can't prove that, it only refuses while Temporal shows one still polling the
    admission queue (its identity lacks the tick contract's mark). With --confirm it records the boundary once,
    audited with the attestation, and queues every live schedule, so its sync writes its action without the argument
    the old one sealed. Without, it's a dry run."""
    from dewpoint.apps import tick_contract
    from dewpoint.apps.cli import main as cli
    from tests.support.workflows import seed_workflow

    pollers: list[str] = ["4242@an-old-dispatcher"]

    async def admission_pollers(settings: object) -> list[str]:
        return pollers

    monkeypatch.setattr(cli, "_admission_pollers", admission_pollers)
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    _recorded(pg_url)

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

    async def scheduled() -> object:
        engine = make_engine(pg_url)
        try:
            tenant, workflow, _ = await seed_workflow(make_sessionmaker(engine))
        finally:
            await engine.dispose()
        [user] = await run("insert into users (id, email, password_hash) values (gen_random_uuid(), :e, 'x') "
                           "returning id", e=f"{uuid.uuid4().hex[:10]}@corp.test")  # fmt: skip
        [found] = await run("insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
                            "generation, synced_generation) values (gen_random_uuid(), :t, :w, 60, 'live', "
                            "'\\x01', :u, 2, 2) returning id", t=tenant, w=workflow, u=user)  # fmt: skip
        return found

    [kept] = sql("select at from tick_cutover")
    sql("delete from tick_cutover")  # as a database that had tenants when 0039 ran
    try:
        schedule = asyncio.run(scheduled())
        unattested = r.invoke(app, ["keys", "tick-cutover", "--confirm"])
        assert unattested.exit_code == 2 and "--attest" in unattested.output, unattested.output
        refused = r.invoke(app, ["keys", "tick-cutover", "--attest", "--confirm"])
        assert refused.exit_code == 1 and "1 poller" in refused.output, refused.output
        pollers[:] = [f"4243@a-new-dispatcher {tick_contract.IDENTITY}"]
        dry = r.invoke(app, ["keys", "tick-cutover", "--attest"])
        assert dry.exit_code == 0 and "a dry run" in dry.output, dry.output
        assert sql("select count(*) from tick_cutover") == [0]
        done = r.invoke(app, ["keys", "tick-cutover", "--attest", "--confirm"])
        assert done.exit_code == 0 and "recorded" in done.output, done.output
        [at] = sql("select at from tick_cutover")
        assert sql("select generation from schedules where id = :i", i=schedule) == [3]
        audited = sql("select details from audit_log where action = 'keys.tick_cutover'")
        assert audited == [{"schedules": 1, "attested": cli.ATTESTED}]
        again = r.invoke(app, ["keys", "tick-cutover", "--attest", "--confirm"])
        assert again.exit_code == 0 and "already recorded" in again.output, again.output
        assert sql("select at from tick_cutover") == [at]
    finally:
        sql("delete from tick_cutover")
        sql("insert into tick_cutover (at) values (:a)", a=kept)


@pytest.mark.parametrize("recorded", ["another-namespace", None])
def test_key_commands_that_ask_temporal_refuse_a_namespace_not_the_recorded_one_before_connecting(
    pg_url, monkeypatch, recorded: str | None
) -> None:
    """The final review's I1 (engine 2b spec §2.1): `keys retire` and `keys tick-cutover` ask Temporal, so each checks
    first that this process's namespace is the deployment's recorded one. A mismatch, or none recorded, ends it (exit
    2) before any connection: never read as Temporal being unreachable, an unknown answer."""
    from dewpoint.apps.cli import main as cli

    attempts: list[object] = []

    class Unreached:
        @staticmethod
        async def connect(*args: object, **kwargs: object) -> object:
            attempts.append(args)
            raise AssertionError("connected to Temporal")

    monkeypatch.setattr(cli, "Client", Unreached)
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    if recorded is not None:
        _recorded(pg_url, recorded)
    [t] = _tenants(pg_url, 1)
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", t]).exit_code == 0
    retire = r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "1"])
    cutover = r.invoke(app, ["keys", "tick-cutover", "--attest"])
    assert (retire.exit_code, cutover.exit_code, attempts) == (2, 2, []), (retire.output, cutover.output)


def test_a_retire_dry_run_changes_nothing(pg_url, monkeypatch) -> None:
    """The final review's I1: proving a version's run executions deletes the evidence of those Temporal shows gone and
    marks what it reads (seen, lost); a dry run proves the same in a read-only transaction, so only --confirm acts on
    what Temporal showed."""
    from datetime import timedelta

    from dewpoint.apps.cli import main as cli
    from dewpoint.apps.dispatcher import evidence

    async def one_day(settings: object) -> timedelta:
        return timedelta(days=1)

    class Connected:
        @staticmethod
        async def connect(*args: object, **kwargs: object) -> object:
            return object()

    async def gone(client: object, workflow_id: str, run_id: str | None) -> None:
        return None  # Temporal shows none of them

    monkeypatch.setattr(cli, "_namespace_retention", one_day)
    monkeypatch.setattr(cli, "Client", Connected)
    monkeypatch.setattr(evidence, "_described", gone)
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    _recorded(pg_url)
    [t] = _tenants(pg_url, 1)
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", t]).exit_code == 0

    async def sql(statement: str) -> list[tuple[object, ...]]:
        engine = make_engine(pg_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                found = await s.execute(text(statement), {"t": t})
                return [tuple(row) for row in found.all()] if found.returns_rows else []
        finally:
            await engine.dispose()

    for read, seen in ((True, True), (False, True), (False, False)):  # proven gone, lost, pending
        run, at, read_at = ("gen_random_uuid()" if read else "null"), ("now()" if seen else "null"), (
            "now()" if read else "null")  # fmt: skip
        asyncio.run(sql(
            "insert into execution_evidence (tenant_id, workflow_id, run_id, started_at, seen_at, read_at) values "
            f"(cast(:t as uuid), 't:' || :t || ':run:' || gen_random_uuid(), {run}, now() - interval '30 days', {at}, "
            f"{read_at})"
        ))  # fmt: skip
    snapshot = ("select id, seen_at, checked_at, read_at, lost_at from execution_evidence where tenant_id = :t "
                "order by id")  # fmt: skip
    before = asyncio.run(sql(snapshot))
    dry = r.invoke(app, ["keys", "retire", "--tenant", t, "--version", "1"])
    assert dry.exit_code in (0, 1) and "Traceback" not in dry.output, dry.output
    assert asyncio.run(sql(snapshot)) == before
