# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import get_settings
from dewpoint.core.crypto.kek import KekSet, UnknownKekError
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User

app = typer.Typer(no_args_is_help=True)
admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")
audit = typer.Typer(no_args_is_help=True)
app.add_typer(audit, name="audit")
keys = typer.Typer(no_args_is_help=True)
app.add_typer(keys, name="keys")


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


async def _in_session[T](fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            return await fn(s)
    finally:
        await engine.dispose()


@keys.command("status")
def keys_status() -> None:
    """Data keys per KEK id. Exit 3 if any are wrapped by a KEK this configuration lacks. Run as dewpoint_admin."""
    keks = KekSet.from_settings(get_settings())
    usage = asyncio.run(_in_session(Keyring(keks).kek_usage))
    missing = []
    for kek_id, n in sorted(usage.items()):
        typer.echo(f"{kek_id}={n}")
        try:
            keks.get(kek_id)
        except UnknownKekError:
            missing.append(kek_id)
    if missing:
        typer.echo(f"ERROR: no configured key for: {', '.join(missing)}. Do not remove a KEK before rewrap completes.")
        raise typer.Exit(3)


@keys.command("rewrap")
def keys_rewrap(batch_size: int = typer.Option(100, min=1, max=1000)) -> None:
    """Phase C of docs/operations/key-rotation.md: move every data key to the current KEK, in committed batches."""
    st = get_settings()
    if not st.kek_previous_b64 or st.kek_previous_id == st.kek_id:
        typer.echo("refusing: configure the new KEK as current and the old one as previous first (phase B)")
        raise typer.Exit(2)
    keyring = Keyring(KekSet.from_settings(st))

    async def _run(s: AsyncSession) -> int:
        total = 0
        while True:
            async with s.begin():
                n = await keyring.rewrap_batch(s, batch_size)
            total += n
            if n == 0:
                return total

    typer.echo(f"rewrapped {asyncio.run(_in_session(_run))} data key(s)")


@keys.command("rotate-dek")
def keys_rotate_dek(tenant: str | None = typer.Option(None), platform: bool = typer.Option(False)) -> None:
    """Rotate one scope's data key. Existing ciphertext stays readable; new writes use the new version."""
    if bool(tenant) == platform:
        typer.echo("pass exactly one of --tenant or --platform")
        raise typer.Exit(2)
    try:
        tenant_id = None if platform else uuid.UUID(tenant)
    except ValueError:
        typer.echo("--tenant must be a UUID")
        raise typer.Exit(2) from None
    keyring = Keyring(KekSet.from_settings(get_settings()))

    async def _run(s: AsyncSession) -> int:
        async with s.begin():
            return await keyring.rotate(s, tenant_id)

    typer.echo(f"active data key version: {asyncio.run(_in_session(_run))}")
