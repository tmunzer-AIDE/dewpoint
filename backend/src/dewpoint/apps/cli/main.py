# SPDX-License-Identifier: Apache-2.0
import asyncio
import os

import typer
from sqlalchemy import select

from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User

app = typer.Typer(no_args_is_help=True)
admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")


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
