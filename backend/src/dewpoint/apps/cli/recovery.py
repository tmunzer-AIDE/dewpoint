# SPDX-License-Identifier: Apache-2.0
"""`dewpoint recovery`: an operator's own tools (2b-4b M4 recovery), run under their personal recovery login, never a
service's credentials; and the database administrator's, for those logins (`recovery operator`).

The server is verified before any credential is sent (design revision 11 §1): `sslmode=verify-full`, against the
deployment's private authority that `sslrootcert` names, the only one trusted (never the system's store). Nothing
falls back: no CA file, a weaker mode, another issuer or another name is refused. asyncpg offers no channel binding,
which the owner accepted for this slice.

A recovery login's password never leaves its operator (task 7; design revisions 7 to 9): they compute its SCRAM-SHA-256
verifier offline (`recovery verifier`) and hand it over, its fingerprint checked apart. The administrator provisions,
rotates or revokes it, each in one transaction with its audit entry, its intent recorded off the database host before
(a failed write stops it) and its outcome after: the administrator and the migration run are trusted exceptions whose
audit must live outside the database they control (the owner's ruling on revision 8). In production, none of them runs
without that record."""

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import ssl
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, NamedTuple
from urllib.parse import parse_qs, unquote, urlsplit

import asyncpg  # type: ignore[import-untyped]  # it ships no type information
import structlog
import typer

from dewpoint.core.audit.administration import ADMINISTRATION, AdministrationSink, recorded
from dewpoint.core.config import Settings, get_settings

log = structlog.get_logger("dewpoint.cli")
recovery_cli = typer.Typer(help="An operator's recovery, under their own recovery login (2b-4b M4).",
                           no_args_is_help=True)  # fmt: skip
operator_cli = typer.Typer(help="Recovery logins, provisioned, rotated and revoked by the database administrator.",
                           no_args_is_help=True)  # fmt: skip
recovery_cli.add_typer(operator_cli, name="operator")
LOGIN = re.compile(r"rcv_[a-z0-9_]{1,59}")
ADMINISTRATOR = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,62}")  # any role's name: the administrator's own
DSN_SHAPE = "postgresql://<login>@<host>[:port]/<database>?sslmode=verify-full&sslrootcert=<the deployment's CA file>"


class Target(NamedTuple):
    """A server, and the only way it's reached: its pinned authority, its name checked."""

    host: str
    port: int
    database: str
    user: str
    ssl: ssl.SSLContext


def server(dsn: str, *, user: re.Pattern[str] = LOGIN) -> Target:
    """The server `dsn` names, reached through `verify-full` against the CA file it names alone; or ValueError, why,
    before any connection. Its user: a recovery login, or (`ADMINISTRATOR`) the administrator's role."""
    parts = urlsplit(dsn)
    if parts.scheme not in ("postgresql", "postgres") or not parts.hostname or not parts.path.strip("/"):
        raise ValueError(f"the DSN must be {DSN_SHAPE}")
    if parts.password is not None:
        raise ValueError("no password in the DSN: it's asked for")
    name = unquote(parts.username or "")
    if not user.fullmatch(name):
        raise ValueError("the DSN's user must be your recovery login (rcv_...)" if user is LOGIN
                         else "the DSN's user must be a role's name")  # fmt: skip
    query = parse_qs(parts.query, keep_blank_values=True)
    other = sorted(set(query) - {"sslmode", "sslrootcert"})
    if other:
        raise ValueError(f"the DSN takes sslmode and sslrootcert only, not {', '.join(other)}")
    if query.get("sslmode") != ["verify-full"]:
        raise ValueError("sslmode=verify-full is required, nothing weaker")
    roots = query.get("sslrootcert", [])
    if len(roots) != 1 or not roots[0]:
        raise ValueError("sslrootcert must name the deployment's CA file")
    ca = Path(roots[0])
    if not ca.is_file():
        raise ValueError(f"sslrootcert: no CA file at {ca}")
    try:  # that authority alone: given a CA file, the default context loads no system store
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    except ssl.SSLError as e:
        raise ValueError(f"sslrootcert: {ca} isn't a CA certificate ({type(e).__name__})") from None
    context.check_hostname, context.verify_mode = True, ssl.CERT_REQUIRED
    return Target(parts.hostname, parts.port or 5432, unquote(parts.path.lstrip("/")), name, context)


async def connect(target: Target, password: str) -> asyncpg.Connection:
    """`target` reached through its verified TLS, then signed in as the login. An SSL context of asyncpg's own never
    falls back: a server refusing TLS is refused."""
    return await asyncpg.connect(host=target.host, port=target.port, user=target.user, database=target.database,
                                 password=password, ssl=target.ssl, timeout=30,
                                 server_settings={"application_name": "dewpoint-recovery"})  # fmt: skip


def _target(dsn: str, user: re.Pattern[str] = LOGIN) -> Target:
    try:
        return server(dsn, user=user)
    except ValueError as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(2) from None


@recovery_cli.command("confirm")
def confirm(
    command_id: uuid.UUID,
    dsn: str = typer.Option(..., "--dsn", envvar="DEWPOINT_RECOVERY_DSN", help=f"Your recovery login's: {DSN_SHAPE}"),
) -> None:
    """A command you asked for (its id, as the API recorded it), confirmed: its text and digest as the database
    computes them, then your `yes`. The dispatcher carries it out only then, and only while it's still exactly what
    you were shown."""
    target = _target(dsn)
    password = typer.prompt(f"Password for {target.user}", hide_input=True)
    asyncio.run(_confirm(target, password, command_id))


async def _confirm(target: Target, password: str, command_id: uuid.UUID) -> None:
    try:
        c = await connect(target, password)
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(1) from None
    try:
        row = await c.fetchrow("select canonical, digest from recovery.operator_command_show($1)", command_id)
        if row is None or row["canonical"] is None:  # the function refuses a command not this login's: none shown
            typer.echo(f"refused: no command {command_id}", err=True)
            raise typer.Exit(1)
        canonical, digest = row["canonical"], bytes(row["digest"])
        typer.echo(canonical)  # the database's text, exactly: nothing built here
        typer.echo(f"digest: sha256:{digest.hex()}")
        if typer.prompt("Type yes to confirm this command, exactly as shown") != "yes":
            typer.echo("not confirmed", err=True)
            raise typer.Exit(1)
        await c.execute("select recovery.operator_command_confirm($1, $2)", command_id, digest)
        typer.echo(f"confirmed: {command_id}")
    except asyncpg.PostgresError as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(1) from None
    finally:
        await c.close()


@recovery_cli.command("reveal")
def reveal(
    command_id: uuid.UUID,
    dsn: str = typer.Option(..., "--dsn", envvar="DEWPOINT_RECOVERY_DSN", help=f"Your recovery login's: {DSN_SHAPE}"),
) -> None:
    """An unresolved send's identifiers (task 9): an `inspect_unresolved_send` command you asked for and confirmed
    (its id), revealed once, to the confirming login alone, audited before anything is shown."""
    target = _target(dsn)
    password = typer.prompt(f"Password for {target.user}", hide_input=True)
    asyncio.run(_reveal(target, password, command_id))


async def _reveal(target: Target, password: str, command_id: uuid.UUID) -> None:
    try:
        c = await connect(target, password)
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(1) from None
    try:
        rows = await c.fetch("select * from recovery.unresolved_send_reveal($1)", command_id)
    except asyncpg.PostgresError as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(1) from None
    finally:
        await c.close()
    first = rows[0]
    for label in ("tenant_id", "request_id", "workflow_id", "start_request_id", "state", "identified_run_id"):
        typer.echo(f"{label}: {first[label]}")
    for row in rows:
        if row["attempt"] is not None:  # a legacy blocker has no send recorded
            run = f" ({row['run_id']})" if row["run_id"] else ""
            typer.echo(f"attempt {row['attempt']}: {row['answer'] or 'unanswered'}{run}")


# --- a recovery login's verifier, computed offline ------------------------------------------------------------------

ITERATIONS = 4096  # PostgreSQL's own default
PASSWORD_MIN = 16
VERIFIER = re.compile(r"SCRAM-SHA-256\$(\d+):([A-Za-z0-9+/]+={0,2})\$([A-Za-z0-9+/]+={0,2}):([A-Za-z0-9+/]+={0,2})")


def checked_password(password: str) -> str:
    """At least `PASSWORD_MIN` printable ASCII characters: SASLprep leaves those as they are, so the verifier computed
    here and every client's proof agree byte for byte."""
    if len(password) < PASSWORD_MIN or not all(" " <= ch <= "~" for ch in password):
        raise ValueError(f"the password must be at least {PASSWORD_MIN} printable ASCII characters")
    return password


def scram_verifier(password: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    """The password's SCRAM-SHA-256 verifier as PostgreSQL stores one (RFC 5802 and 7677):
    `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>`, a random 16-byte salt unless given."""
    salt = secrets.token_bytes(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", checked_password(password).encode(), salt, iterations)
    stored = hashlib.sha256(hmac.new(salted, b"Client Key", "sha256").digest()).digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    encoded = [base64.b64encode(b).decode() for b in (salt, stored, server_key)]
    return f"SCRAM-SHA-256${iterations}:{encoded[0]}${encoded[1]}:{encoded[2]}"


def fingerprint(verifier: str) -> str:
    """What the operator and the administrator compare apart: the verifier's sha256."""
    return hashlib.sha256(verifier.encode()).hexdigest()


def checked_verifier(text: str) -> str:
    """A SCRAM-SHA-256 verifier, its keys 32 bytes, at least `ITERATIONS`: never a password, nor an md5 hash."""
    found = VERIFIER.fullmatch(text.strip())
    if found is None:
        raise ValueError("the verifier must be `dewpoint recovery verifier`'s SCRAM-SHA-256 one: never a password or "
                         "an md5 hash")  # fmt: skip
    if int(found[1]) < ITERATIONS:
        raise ValueError(f"the verifier's iterations must be at least {ITERATIONS}")
    try:
        salt, *keys = (base64.b64decode(part, validate=True) for part in found.groups()[1:])
    except binascii.Error:
        raise ValueError("the verifier isn't valid base64") from None
    if len(salt) < 16 or any(len(key) != 32 for key in keys):
        raise ValueError("the verifier's salt must be 16 bytes or more, its keys 32 bytes each")
    return text.strip()


def checked_login(name: str) -> str:
    """A recovery login's name, checked before any SQL: `rcv_`, then lower-case letters, digits or underscores, 63
    bytes at most (PostgreSQL's limit); the DDL quotes it besides (`%I`)."""
    if not LOGIN.fullmatch(name):
        raise ValueError(f"a recovery login must match ^{LOGIN.pattern}$")
    return name


@recovery_cli.command("verifier")
def verifier_command() -> None:
    """Your recovery login's verifier, computed here: your password, asked twice, never leaves you. Hand the verifier
    to the database administrator, and its fingerprint apart, by another channel: they check it matches."""
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        verifier = scram_verifier(password)
    except ValueError as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(2) from None
    typer.echo(verifier)
    typer.echo(f"fingerprint: sha256:{fingerprint(verifier)}")


# --- the administrator's: provisioning, rotation, revocation --------------------------------------------------------

# Nothing of the provisioning statement logged: statements, durations, an error's statement, parameters (the owner's
# ruling on revision 8: whether a target's logging leaks a verifier anyway is its qualification's)
QUIET = (
    "SET LOCAL log_statement = 'none'",
    "SET LOCAL log_min_duration_statement = -1",
    "SET LOCAL log_min_error_statement = 'panic'",
    "SET LOCAL log_parameter_max_length = 0",
    "SET LOCAL log_parameter_max_length_on_error = 0",
)


async def _quiet(c: asyncpg.Connection) -> None:
    for statement in QUIET:
        await c.execute(statement)
    if await c.fetchval("select current_setting('pgaudit.log', true)") is not None:  # the extension's, if loaded
        await c.execute("SET LOCAL pgaudit.log = 'none'")


async def _ddl(c: asyncpg.Connection, template: str, *values: str) -> None:
    """`template`'s statement, its names quoted by the server (`%I`, `%L`): no name is ever formatted here."""
    arguments = ", ".join(f"${i + 1}::text" for i in range(len(values)))
    await c.execute(await c.fetchval(f"select format('{template}', {arguments})", *values))


async def _audited(c: asyncpg.Connection, action: str, login: str, details: dict[str, Any]) -> None:
    """The database's own audit entry (the platform's scope), in the action's transaction."""
    await c.execute("select audit_append(NULL, NULL, $1, 'recovery_operator', $2, $3::jsonb)", action, login,
                    json.dumps(details))  # fmt: skip


async def _recorded[T](sink: AdministrationSink | None, action: str, fields: dict[str, Any],
                       act: Callable[[], Awaitable[T]]) -> T:  # fmt: skip
    """`act`, its intent recorded off the host before (a failure stops it) and its outcome after."""
    action_id = uuid.uuid4()
    if sink is not None:
        sink.write(recorded(action, "intent", action_id, **fields))
    try:
        result = await act()
    except Exception as e:
        if sink is not None:
            try:
                sink.write(recorded(action, "outcome", action_id, status="failed", error=type(e).__name__, **fields))
            except Exception as unrecorded:  # the action's own failure is the one raised
                log.error("administration_outcome_unrecorded", action=action, error=type(unrecorded).__name__)
        raise
    if sink is not None:
        sink.write(recorded(action, "outcome", action_id, status="succeeded", **fields))
    return result


async def provision(c: asyncpg.Connection, sink: AdministrationSink | None, login: str, user_id: uuid.UUID,
                    verifier: str, *, by: str) -> None:  # fmt: skip
    """`login` made, a member of `dewpoint_recovery` alone, its password `verifier`, mapped to `user_id` (an active
    platform admin), audited: one transaction. Its name and verifier are checked before any SQL; a name is never
    reused."""
    checked_login(login)
    checked_verifier(verifier)

    async def act() -> None:
        async with c.transaction():
            await _quiet(c)
            admin = await c.fetchval("select is_platform_admin and is_active from users where id = $1", user_id)
            if not admin:
                raise ValueError("a recovery login maps an active platform admin")
            if await c.fetchval("select exists (select 1 from recovery_operators where login = $1) "
                                "or exists (select 1 from pg_roles where rolname = $1)", login):  # fmt: skip
                raise ValueError(f"{login} was provisioned before: a name is never reused")
            await _ddl(c, "CREATE ROLE %I LOGIN PASSWORD %L IN ROLE dewpoint_recovery", login, verifier)
            await c.execute("insert into recovery_operators (login, user_id, provisioned_by, provisioned_at) "
                            "values ($1, $2, session_user, statement_timestamp())", login, user_id)  # fmt: skip
            await _audited(c, "recovery.operator.added", login,
                           {"user_id": str(user_id), "verifier_fingerprint": fingerprint(verifier)})  # fmt: skip

    fields = {"login": login, "user_id": str(user_id), "verifier_fingerprint": fingerprint(verifier), "by": by}
    await _recorded(sink, "recovery.operator.add", fields, act)


async def rotate(c: asyncpg.Connection, sink: AdministrationSink | None, login: str, verifier: str, *, by: str) -> None:
    """An unrevoked login's password replaced by `verifier`, audited: one transaction, as quiet as provisioning."""
    checked_login(login)
    checked_verifier(verifier)

    async def act() -> None:
        async with c.transaction():
            await _quiet(c)
            if not await c.fetchval("select exists (select 1 from recovery_operators where login = $1 "
                                    "and revoked_at is null)", login):  # fmt: skip
                raise ValueError(f"{login} isn't an unrevoked recovery login")
            await _ddl(c, "ALTER ROLE %I PASSWORD %L", login, verifier)
            await _audited(c, "recovery.operator.rotated", login, {"verifier_fingerprint": fingerprint(verifier)})

    fields = {"login": login, "verifier_fingerprint": fingerprint(verifier), "by": by}
    await _recorded(sink, "recovery.operator.rotate", fields, act)


async def revoke(c: asyncpg.Connection, sink: AdministrationSink | None, login: str, *, by: str) -> int:
    """`login` revoked: its mapping marked, its membership taken, NOLOGIN, audited, in one transaction; then its
    sessions ended. How many were."""
    checked_login(login)

    async def act() -> int:
        async with c.transaction():
            marked = await c.fetchval("update recovery_operators set revoked_at = statement_timestamp(), "
                                      "revoked_by = session_user where login = $1 and revoked_at is null "
                                      "returning login", login)  # fmt: skip
            if marked is None:
                raise ValueError(f"{login} isn't an unrevoked recovery login")
            await _ddl(c, "REVOKE dewpoint_recovery FROM %I", login)
            await _ddl(c, "ALTER ROLE %I NOLOGIN", login)
            await _audited(c, "recovery.operator.revoked", login, {})
        return int(await c.fetchval("select count(*) filter (where pg_terminate_backend(pid)) from pg_stat_activity "
                                    "where usename = $1", login))  # fmt: skip

    return await _recorded(sink, "recovery.operator.revoke", {"login": login, "by": by}, act)


def administration_sink(settings: Settings) -> AdministrationSink | None:
    """The administration writer, with this process's own credentials (put-only on its prefix, not the anchor
    writer's); None without D6's bucket."""
    if not settings.audit_s3_bucket:
        return None
    import boto3

    # Compose passes a variable `.env` leaves unset as an empty string: unset, not an endpoint boto3 refuses
    client = boto3.session.Session().client("s3", endpoint_url=settings.audit_s3_endpoint_url or None,
                                            region_name=settings.audit_s3_region or None)  # fmt: skip
    return AdministrationSink(client, settings.audit_s3_bucket, settings.audit_s3_prefix + ADMINISTRATION)


def required_sink(settings: Settings) -> AdministrationSink | None:
    """The administration sink; in production none is a refusal (the plan's ruling 7), elsewhere a warning."""
    sink = administration_sink(settings)
    if sink is None:
        if settings.environment == "production":
            why = (
                "refused: production records its administration off the database host first: set "
                "DEWPOINT_AUDIT_S3_BUCKET (D6's bucket) and this identity's put-only credentials"
            )
            typer.echo(why, err=True)
            raise typer.Exit(2)
        typer.echo(f"no off-host record: a {settings.environment} deployment without D6's bucket", err=True)
    return sink


Administered = Callable[[asyncpg.Connection, AdministrationSink | None, str], Awaitable[Any]]


def _administered(dsn: str, act: Administered) -> Any:
    """`act` on the administrator's connection: the sink first, then the server, verified, then their password."""
    sink = required_sink(get_settings())
    target = _target(dsn, ADMINISTRATOR)
    password = typer.prompt(f"Password for {target.user}", hide_input=True)

    async def run() -> Any:
        try:
            c = await connect(target, password)
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
            typer.echo(f"refused: {e}", err=True)
            raise typer.Exit(1) from None
        try:
            return await act(c, sink, target.user)
        except (ValueError, asyncpg.PostgresError) as e:
            typer.echo(f"refused: {e}", err=True)
            raise typer.Exit(1) from None
        finally:
            await c.close()

    return asyncio.run(run())


def _verifier_file(path: Path) -> str:
    try:
        return checked_verifier(path.read_text())
    except (OSError, ValueError) as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(2) from None


ADMIN_DSN = "The administrator's: postgresql://<role>@<host>[:port]/<database>?sslmode=verify-full&sslrootcert=<CA>"
VerifierFile = Annotated[Path, typer.Option("--verifier-file", help="The operator's `recovery verifier` output.")]


@operator_cli.command("add")
def operator_add(
    login: str,
    user: Annotated[uuid.UUID, typer.Option("--user", help="The platform admin this login is.")],
    verifier_file: VerifierFile,
    dsn: str = typer.Option(..., "--dsn", envvar="DEWPOINT_ADMINISTRATOR_DSN", help=ADMIN_DSN),
) -> None:
    """A recovery login provisioned from its operator's verifier. Check its fingerprint with them first."""
    verifier = _verifier_file(verifier_file)
    typer.echo(f"fingerprint: sha256:{fingerprint(verifier)}")
    _administered(dsn, lambda c, sink, by: provision(c, sink, login, user, verifier, by=by))
    typer.echo(f"provisioned: {login}")


@operator_cli.command("rotate")
def operator_rotate(
    login: str,
    verifier_file: VerifierFile,
    dsn: str = typer.Option(..., "--dsn", envvar="DEWPOINT_ADMINISTRATOR_DSN", help=ADMIN_DSN),
) -> None:
    """A recovery login's password replaced by its operator's new verifier."""
    verifier = _verifier_file(verifier_file)
    typer.echo(f"fingerprint: sha256:{fingerprint(verifier)}")
    _administered(dsn, lambda c, sink, by: rotate(c, sink, login, verifier, by=by))
    typer.echo(f"rotated: {login}")


@operator_cli.command("revoke")
def operator_revoke(
    login: str,
    dsn: str = typer.Option(..., "--dsn", envvar="DEWPOINT_ADMINISTRATOR_DSN", help=ADMIN_DSN),
) -> None:
    """A recovery login revoked for good: NOLOGIN, out of `dewpoint_recovery`, its sessions ended, its name never
    reused."""
    ended = _administered(dsn, lambda c, sink, by: revoke(c, sink, login, by=by))
    typer.echo(f"revoked: {login} ({ended} session(s) ended)")
