# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
from pathlib import Path

import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User

app = typer.Typer(no_args_is_help=True)
admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")
audit = typer.Typer(no_args_is_help=True)
app.add_typer(audit, name="audit")


async def _init(email: str, password: str) -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            if (await s.execute(select(User.id).where(User.is_platform_admin.is_(True)).limit(1))).first():
                typer.echo("already initialized: a platform admin exists")
                raise typer.Exit(1)
            await create_user(s, email=email, password=password, platform_admin=True)
    finally:
        await engine.dispose()


@admin.command("init")
def admin_init(email: str = typer.Option(...)) -> None:
    """Create the first platform admin. Refuses if one already exists."""
    password = os.environ.get("DEWPOINT_INIT_PASSWORD") or typer.prompt(
        "Password", hide_input=True, confirmation_prompt=True
    )
    try:
        asyncio.run(_init(email, password))
    except PasswordPolicyError as e:
        typer.echo(f"password rejected: {', '.join(e.violations)}")
        raise typer.Exit(2) from None
    typer.echo(f"platform admin {email} created. Sign in to enroll MFA.")


def _signing_key() -> Ed25519PrivateKey:
    raw = get_settings().audit_signing_key_b64
    if not raw:
        typer.echo("DEWPOINT_AUDIT_SIGNING_KEY_B64 is not set")
        raise typer.Exit(2)
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))


def _anchor_path() -> Path:
    path = get_settings().audit_anchor_path
    if not path:
        typer.echo("DEWPOINT_AUDIT_ANCHOR_PATH is not set")
        raise typer.Exit(2)
    return Path(path)


@audit.command("anchor")
def audit_anchor() -> None:
    """Write current chain heads to the external anchor sink. Run as a dewpoint_auditor login, e.g. every 15 min."""
    sink = FileAnchorSink(_anchor_path(), _signing_key())

    async def _run() -> int:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                return await anchor_all(s, sink)
        finally:
            await engine.dispose()

    typer.echo(f"anchored {asyncio.run(_run())} scope head(s)")


@audit.command("verify")
def audit_verify() -> None:
    """Recompute every chain and check it against the signed external anchors. Exit 1 on any problem,
    including when no anchors exist, so a broken anchor job can't look healthy."""
    key = _signing_key()
    sink = FileAnchorSink(_anchor_path(), key)

    async def _run() -> list[str]:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await verify_anchors(s, sink.entries(), key.public_key())
        finally:
            await engine.dispose()

    problems = asyncio.run(_run())
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)
    typer.echo("audit chain verified against external anchors")
