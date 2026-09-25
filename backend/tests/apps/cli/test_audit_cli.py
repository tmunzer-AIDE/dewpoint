# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
import uuid

from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.audit.service import record
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
from tests.conftest import _url_for


async def _seed(url: str) -> None:
    engine = make_engine(url)  # own engine: this runs on its own event loop via asyncio.run
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            t = uuid.uuid4()
            await tenant_scope(s, t)
            await record(s, tenant_id=t, actor_id=None, action="member.add")
    finally:
        await engine.dispose()


def _env(monkeypatch, url: str, **extra: str) -> None:  # type: ignore[no-untyped-def]
    base = {
        "DEWPOINT_DATABASE_URL": url,
        "DEWPOINT_KEK_B64": base64.b64encode(os.urandom(32)).decode(),
        "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test",
    }
    for k, v in {**base, **extra}.items():
        monkeypatch.setenv(k, v)
    for k in ("DEWPOINT_AUDIT_SIGNING_KEY_B64", "DEWPOINT_AUDIT_ANCHOR_PATH"):
        if k not in extra:
            monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()


def test_anchor_then_verify_as_auditor(pg_url, _test_users, tmp_path, monkeypatch) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    runner = CliRunner()
    auditor = _url_for(pg_url, "dewpoint_auditor")
    signing = {
        "DEWPOINT_AUDIT_SIGNING_KEY_B64": base64.b64encode(os.urandom(32)).decode(),
        "DEWPOINT_AUDIT_ANCHOR_PATH": str(tmp_path / "anchors.jsonl"),
    }
    _env(monkeypatch, auditor, **signing)
    empty = runner.invoke(app, ["audit", "verify"])
    assert empty.exit_code == 1 and "no external anchors found" in empty.output

    anchored = runner.invoke(app, ["audit", "anchor"])
    assert anchored.exit_code == 0 and "anchored 1 scope head(s)" in anchored.output
    verified = runner.invoke(app, ["audit", "verify"])
    assert verified.exit_code == 0, verified.output

    _env(monkeypatch, auditor)  # misconfigured: no key / path
    assert runner.invoke(app, ["audit", "anchor"]).exit_code == 2
