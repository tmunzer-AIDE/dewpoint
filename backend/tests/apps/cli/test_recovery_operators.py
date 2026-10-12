# SPDX-License-Identifier: Apache-2.0
"""Personal recovery logins (2b-4b M4 recovery, task 7; design revisions 7 to 9, the owner's rulings on them). The
operator computes their SCRAM-SHA-256 verifier offline (`dewpoint recovery verifier`): the password never leaves them.
The database administrator provisions it (`recovery operator add`), rotates it, or revokes it, each one transaction
with its audit entry, its intent and outcome recorded off the host first and last; a failed intent stops it. Names are
checked before any SQL, and quoted by the server (`%I`) in the DDL. Revoked: NOLOGIN, no membership, its sessions
ended, its name never reused. `dewpoint_recovery`'s members are always exactly the unrevoked mapped logins.

What no test here can see: the server's logs. The provisioning transaction turns statement and parameter logging off
(`SET LOCAL`), and whether a target's logging leaks a verifier anyway is its qualification's (revision 9)."""

import asyncio
import base64
import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import recovery
from dewpoint.apps.cli.main import app
from dewpoint.core.audit.administration import AdministrationSink
from dewpoint.core.auth.users import create_user
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.cli.test_audit_cli import _env
from tests.core.audit.fake_s3 import FakeS3
from tests.support.recovery import PREFIX

PASSWORD = "a long recovery passphrase 42"  # printable ASCII: SASLprep leaves it as it is


def _login() -> str:
    return f"{PREFIX}{uuid.uuid4().hex[:12]}"  # dropped after the test (`clean_db`)


def _dsn(pg_url: str) -> str:
    return pg_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def _owner(pg_url: str) -> AsyncIterator[asyncpg.Connection]:
    c = await asyncpg.connect(_dsn(pg_url))
    try:
        yield c
    finally:
        await c.close()


async def _admin(pg_url: str, *, platform_admin: bool = True) -> uuid.UUID:
    engine = make_engine(pg_url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            email = f"{uuid.uuid4().hex[:10]}@corp.test"
            return (await create_user(s, email=email, password="violet-otter-42", platform_admin=platform_admin)).id
    finally:
        await engine.dispose()


def _sink() -> tuple[AdministrationSink, FakeS3]:
    bucket = FakeS3()
    return AdministrationSink(bucket, "audit-anchors", "dewpoint/database-administration/"), bucket


def _phases(bucket: FakeS3) -> list[str]:
    return [put["Key"].rsplit("/", 1)[1] for put in bucket.puts]


async def _signs_in(pg_url: str, login: str, password: str) -> bool:
    address = pg_url.split("@", 1)[1]
    try:
        c = await asyncpg.connect(f"postgresql://{login}:{password}@{address}")
    except (asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError):
        return False
    await c.close()
    return True


async def _state(pg_url: str, login: str) -> dict[str, Any]:
    async with _owner(pg_url) as c:
        role = await c.fetchrow("select rolcanlogin from pg_roles where rolname = $1", login)
        member = await c.fetchval("select exists (select 1 from pg_auth_members a join pg_roles g on g.oid = a.roleid "
                                  "join pg_roles m on m.oid = a.member where g.rolname = 'dewpoint_recovery' "
                                  "and m.rolname = $1)", login)  # fmt: skip
        mapping = await c.fetchrow("select user_id, revoked_at is not null as revoked from recovery_operators "
                                   "where login = $1", login)  # fmt: skip
        audited = await c.fetch("select action from audit_log where target_id = $1 order by seq", login)
    return {"role": None if role is None else role["rolcanlogin"], "member": member,
            "mapping": None if mapping is None else tuple(mapping),
            "audited": [r["action"] for r in audited]}  # fmt: skip


# --- the verifier ----------------------------------------------------------------------------------------------------


def test_the_verifier_is_postgresqls_own_a_login_provisioned_with_it_signs_in(pg_url: str) -> None:
    async def run() -> tuple[bool, bool]:
        login, user = _login(), await _admin(pg_url)
        verifier = recovery.scram_verifier(PASSWORD)
        async with _owner(pg_url) as c:
            await recovery.provision(c, None, login, user, verifier, by="tests")
        return await _signs_in(pg_url, login, PASSWORD), await _signs_in(pg_url, login, PASSWORD + "!")

    assert asyncio.run(run()) == (True, False)


def test_a_verifier_is_rfc_5802s_shape_salted_and_fingerprinted() -> None:
    verifier = recovery.scram_verifier(PASSWORD, salt=bytes(16))
    method, rest = verifier.split("$", 1)
    iterations_salt, keys = rest.split("$")
    assert method == "SCRAM-SHA-256" and iterations_salt == f"4096:{base64.b64encode(bytes(16)).decode()}"
    assert all(len(base64.b64decode(k)) == 32 for k in keys.split(":"))
    assert recovery.scram_verifier(PASSWORD) != recovery.scram_verifier(PASSWORD)  # a random salt each time
    assert recovery.fingerprint(verifier) == hashlib.sha256(verifier.encode()).hexdigest()


@pytest.mark.parametrize("password", ["short one 1", "a long recovery passphrase é", "a long recovery\tpassphrase"],
                         ids=["under 16", "not ASCII", "a control character"])  # fmt: skip
def test_a_password_the_verifier_wont_take(password: str) -> None:
    with pytest.raises(ValueError, match="password"):
        recovery.checked_password(password)


def test_the_verifier_command_asks_twice_and_prints_the_verifier_and_its_fingerprint() -> None:
    result = CliRunner().invoke(app, ["recovery", "verifier"], input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 0, result.output
    [verifier] = [line for line in result.output.splitlines() if line.startswith("SCRAM-SHA-256$")]
    assert f"fingerprint: sha256:{recovery.fingerprint(verifier)}" in result.output
    assert PASSWORD not in result.output


# --- what's refused before any SQL -----------------------------------------------------------------------------------


class NoSql:
    """A connection that fails the test on any statement."""

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        raise AssertionError(f"SQL run: {name}")


@pytest.mark.parametrize("login", ['rcv_a"b', "RCV_X", "rcv_" + "x" * 60, "admin", "rcv_"],
                         ids=["a quote", "upper case", "64 bytes", "not rcv_", "nothing after rcv_"])  # fmt: skip
def test_a_login_name_is_refused_before_any_sql(login: str) -> None:
    sink, bucket = _sink()
    with pytest.raises(ValueError, match="login"):
        asyncio.run(recovery.provision(NoSql(), sink, login, uuid.uuid4(), recovery.scram_verifier(PASSWORD),
                                       by="tests"))  # fmt: skip
    assert bucket.puts == []


@pytest.mark.parametrize("verifier", [PASSWORD, "md5" + "0" * 32, "SCRAM-SHA-256$4096:c2FsdA==$a2V5:a2V5",
                                      "SCRAM-SHA-256$1000:" + recovery.scram_verifier(PASSWORD).split(":", 1)[1]],
                         ids=["plaintext", "md5", "short keys", "too few iterations"])  # fmt: skip
def test_a_verifier_other_than_scram_sha_256_is_refused_before_any_sql(verifier: str) -> None:
    sink, bucket = _sink()
    with pytest.raises(ValueError, match="verifier"):
        asyncio.run(recovery.provision(NoSql(), sink, _login(), uuid.uuid4(), verifier, by="tests"))
    assert bucket.puts == []


def test_the_server_quotes_a_name_in_the_ddl_whatever_it_holds(pg_url: str) -> None:
    """Review focus 5, past the name check: the DDL's names are quoted by the server (`%I`), never formatted here."""
    hostile = f'{PREFIX}{uuid.uuid4().hex[:6]}"X; drop table users; --'

    async def run() -> list[str]:
        async with _owner(pg_url) as c:
            await recovery._ddl(c, "CREATE ROLE %I NOLOGIN", hostile)
            return [r["rolname"] for r in await c.fetch("select rolname from pg_roles where rolname = $1", hostile)]

    assert asyncio.run(run()) == [hostile]


# --- provisioning ----------------------------------------------------------------------------------------------------


def test_provisioning_records_its_intent_then_its_outcome_off_the_host(pg_url: str) -> None:
    sink, bucket = _sink()
    login = _login()

    async def run() -> dict[str, Any]:
        user = await _admin(pg_url)
        async with _owner(pg_url) as c:
            await recovery.provision(c, sink, login, user, recovery.scram_verifier(PASSWORD), by="tests")
        return {"user": user, **await _state(pg_url, login)}

    state = asyncio.run(run())
    assert (state["role"], state["member"], state["mapping"]) == (True, True, (state["user"], False))
    assert state["audited"] == ["recovery.operator.added"]
    assert _phases(bucket) == ["intent.json", "outcome.json"]
    assert all(b"SCRAM-SHA-256$" not in v.body for v in bucket.versions if v.body)  # no verifier off the host


def test_a_failed_intent_stops_provisioning_before_any_change(pg_url: str) -> None:
    sink, _ = _sink()
    login = _login()

    def refused(record: dict[str, Any]) -> str:
        raise OSError("the bucket refused it")

    sink.write = refused  # type: ignore[method-assign]

    async def run() -> dict[str, Any]:
        user = await _admin(pg_url)
        async with _owner(pg_url) as c:
            with pytest.raises(OSError):
                await recovery.provision(c, sink, login, user, recovery.scram_verifier(PASSWORD), by="tests")
        return await _state(pg_url, login)

    assert asyncio.run(run()) == {"role": None, "member": False, "mapping": None, "audited": []}


def test_provisioning_is_atomic_a_failure_after_create_role_leaves_nothing(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink, bucket = _sink()
    login = _login()

    async def failed(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("the audit entry failed")

    monkeypatch.setattr(recovery, "_audited", failed)

    async def run() -> dict[str, Any]:
        user = await _admin(pg_url)
        async with _owner(pg_url) as c:
            with pytest.raises(RuntimeError):
                await recovery.provision(c, sink, login, user, recovery.scram_verifier(PASSWORD), by="tests")
        return await _state(pg_url, login)

    assert asyncio.run(run()) == {"role": None, "member": False, "mapping": None, "audited": []}
    outcome = [v.body for v in bucket.versions if v.key.endswith("outcome.json")]
    assert len(outcome) == 1 and b'"failed"' in outcome[0]  # the outcome off the host says so


def test_only_an_active_platform_admin_is_mapped(pg_url: str) -> None:
    async def run() -> dict[str, Any]:
        login, member = _login(), await _admin(pg_url, platform_admin=False)
        async with _owner(pg_url) as c:
            with pytest.raises(ValueError, match="platform admin"):
                await recovery.provision(c, None, login, member, recovery.scram_verifier(PASSWORD), by="tests")
        return await _state(pg_url, login)

    assert asyncio.run(run())["role"] is None


# --- rotation and revocation -----------------------------------------------------------------------------------------


def test_rotation_replaces_the_password_audited(pg_url: str) -> None:
    async def run() -> tuple[bool, bool, list[str]]:
        login, user = _login(), await _admin(pg_url)
        async with _owner(pg_url) as c:
            await recovery.provision(c, None, login, user, recovery.scram_verifier(PASSWORD), by="tests")
            await recovery.rotate(c, None, login, recovery.scram_verifier(PASSWORD + " rotated"), by="tests")
        return (await _signs_in(pg_url, login, PASSWORD), await _signs_in(pg_url, login, PASSWORD + " rotated"),
                (await _state(pg_url, login))["audited"])  # fmt: skip

    assert asyncio.run(run()) == (False, True, ["recovery.operator.added", "recovery.operator.rotated"])


def test_revocation_ends_the_login_its_membership_and_its_sessions_and_its_name_is_never_reused(pg_url: str) -> None:
    async def run() -> tuple[dict[str, Any], int, bool]:
        login, user = _login(), await _admin(pg_url)
        async with _owner(pg_url) as c:
            await recovery.provision(c, None, login, user, recovery.scram_verifier(PASSWORD), by="tests")
        address = pg_url.split("@", 1)[1]
        session = await asyncpg.connect(f"postgresql://{login}:{PASSWORD}@{address}")
        async with _owner(pg_url) as c:
            ended = await recovery.revoke(c, None, login, by="tests")
            with pytest.raises(ValueError, match="never reused"):
                await recovery.provision(c, None, login, user, recovery.scram_verifier(PASSWORD), by="tests")
        try:
            await session.fetchval("select 1")
            alive = True
        except (asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError):
            alive = False
        finally:
            await session.close()
        return await _state(pg_url, login), ended, alive

    state, ended, alive = asyncio.run(run())
    assert (state["role"], state["member"], state["mapping"][1]) == (False, False, True)
    assert state["audited"] == ["recovery.operator.added", "recovery.operator.revoked"]
    assert ended == 1 and not alive


def test_the_recovery_groups_members_are_exactly_the_unrevoked_mapped_logins(pg_url: str) -> None:
    async def run() -> tuple[set[str], set[str]]:
        user = await _admin(pg_url)
        logins = [_login() for _ in range(4)]
        async with _owner(pg_url) as c:
            for login in logins:
                await recovery.provision(c, None, login, user, recovery.scram_verifier(PASSWORD), by="tests")
            for login in logins[1:3]:
                await recovery.revoke(c, None, login, by="tests")
            members = {r["rolname"] for r in await c.fetch(
                "select m.rolname from pg_auth_members a join pg_roles g on g.oid = a.roleid "
                "join pg_roles m on m.oid = a.member where g.rolname = 'dewpoint_recovery'")}  # fmt: skip
            mapped = {
                r["login"] for r in await c.fetch("select login from recovery_operators where revoked_at is null")
            }
        return members & set(logins), mapped & set(logins)

    members, mapped = asyncio.run(run())
    assert members == mapped and len(members) == 2


# --- the commands ----------------------------------------------------------------------------------------------------


def test_the_sink_takes_an_empty_endpoint_or_region_as_unset() -> None:
    """Compose passes a variable `.env` doesn't set as an empty string, which boto3 refuses as an endpoint ("Invalid
    endpoint"): the owner's review of gate C, finding 2."""
    from types import SimpleNamespace

    settings = SimpleNamespace(audit_s3_bucket="audit-anchors", audit_s3_prefix="dewpoint/", audit_s3_endpoint_url="",
                               audit_s3_region="")  # fmt: skip
    sink = recovery.administration_sink(settings)  # type: ignore[arg-type]
    assert sink is not None and (sink.bucket, sink.prefix) == ("audit-anchors", "dewpoint/database-administration/")


def test_the_administrators_commands_refuse_in_production_without_the_administration_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEWPOINT_AUDIT_S3_BUCKET", raising=False)
    _env(monkeypatch, "postgresql+asyncpg://unused@db.example/dewpoint", DEWPOINT_ENVIRONMENT="production")
    ca = tmp_path / "ca.pem"
    ca.write_text("unused: refused before")
    verifier = tmp_path / "verifier"
    verifier.write_text(recovery.scram_verifier(PASSWORD))
    dsn = f"postgresql://postgres@db.example/dewpoint?sslmode=verify-full&sslrootcert={ca}"
    for args in (["add", "rcv_alice", "--user", str(uuid.uuid4()), "--verifier-file", str(verifier)],
                 ["rotate", "rcv_alice", "--verifier-file", str(verifier)], ["revoke", "rcv_alice"]):  # fmt: skip
        result = CliRunner().invoke(app, ["recovery", "operator", *args, "--dsn", dsn], input="pw\n")
        assert result.exit_code == 2 and "administration" in result.output, (args, result.output)
