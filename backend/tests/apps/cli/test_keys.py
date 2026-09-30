# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
import uuid

from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine

OLD, NEW = base64.b64encode(os.urandom(32)).decode(), base64.b64encode(os.urandom(32)).decode()


def _env(monkeypatch, pg_url: str, **kek: str) -> None:
    for k, v in {"DEWPOINT_DATABASE_URL": pg_url, "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test", **kek}.items():
        monkeypatch.setenv(k, v)
    for k in ("DEWPOINT_KEK_PREVIOUS_B64", "DEWPOINT_KEK_PREVIOUS_ID"):
        if k not in kek:
            monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()


def test_status_rewrap_and_rotate(pg_url, monkeypatch) -> None:
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    t = str(uuid.uuid4())
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
    t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
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


def test_ensure_tenants_gives_every_tenant_without_a_key_one(pg_url, monkeypatch) -> None:
    """Engine 2b spec §6.3: tenants created before 2b-1a. Compose's migrate step runs it as the database owner."""

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
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    first = r.invoke(app, ["keys", "ensure-tenants"])
    assert (first.exit_code, first.output) == (0, "created a data key for 2 tenant(s)\n")
    again = r.invoke(app, ["keys", "ensure-tenants"])
    assert (again.exit_code, again.output) == (0, "created a data key for 0 tenant(s)\n")
    assert "old=2" in r.invoke(app, ["keys", "status"]).output
