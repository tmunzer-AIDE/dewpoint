# SPDX-License-Identifier: Apache-2.0
"""`dewpoint platform egress add|list|remove` (plugins-3 D8), run as the admin role: an entry is for one tenant or,
explicitly, for every tenant; a network covering everything or a bad port range is refused; removing is audited."""

import asyncio
import base64
import uuid

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.conftest import _url_for


@pytest.fixture
def admin_env(monkeypatch: pytest.MonkeyPatch, pg_url: str, _test_users: None) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_admin"))
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()


def tenant(pg_url: str) -> uuid.UUID:
    """A tenant written outside the test's loop: the CLI runs its own (`asyncio.run`)."""
    tid = uuid.uuid4()

    async def _write() -> None:
        engine = make_engine(pg_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                await s.execute(
                    text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
                )
        finally:
            await engine.dispose()

    asyncio.run(_write())
    return tid


@pytest.mark.usefixtures("admin_env")
def test_add_list_and_remove(pg_url: str) -> None:
    tid = tenant(pg_url)
    added = CliRunner().invoke(
        cli.app, ["platform", "egress", "add", "10.20.0.0/16", "--tenant", str(tid), "--ports", "8000-8100",
                  "--note", "internal llm"],
    )  # fmt: skip
    assert added.exit_code == 0, added.output
    entry_id = added.output.strip().split()[-1]
    shared = CliRunner().invoke(cli.app, ["platform", "egress", "add", "fd00::/8", "--every-tenant"])
    assert shared.exit_code == 0, shared.output
    listed = CliRunner().invoke(cli.app, ["platform", "egress", "list"])
    assert listed.exit_code == 0
    assert f"{entry_id} 10.20.0.0/16 8000-8100 {tid} internal llm" in listed.output
    assert "fd00::/8 any * " in listed.output
    removed = CliRunner().invoke(cli.app, ["platform", "egress", "remove", entry_id])
    assert removed.exit_code == 0 and "removed" in removed.output
    again = CliRunner().invoke(cli.app, ["platform", "egress", "remove", entry_id])
    assert again.exit_code == 1


@pytest.mark.usefixtures("admin_env")
@pytest.mark.parametrize(
    "args",
    [
        ["0.0.0.0/0", "--every-tenant"],
        ["10.0.0.1/8", "--every-tenant"],
        ["10.0.0.0/8"],
        ["10.0.0.0/8", "--every-tenant", "--tenant", str(uuid.uuid4())],
        ["10.0.0.0/8", "--every-tenant", "--ports", "90-80"],
        ["10.0.0.0/8", "--every-tenant", "--ports", "http"],
    ],
)
def test_bad_entries_are_refused(args: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["platform", "egress", "add", *args])
    assert result.exit_code == 2 and result.output.startswith("ERROR: "), result.output
