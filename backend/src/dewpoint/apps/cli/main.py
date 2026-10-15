# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import json
import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.api.enums.v1 import ArchivalState
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client

from dewpoint.apps import admission, dev_run, stopping, tick_contract
from dewpoint.apps.cli import recovery as recovery_commands
from dewpoint.apps.cli.recovery import recovery_cli
from dewpoint.apps.codec import KeyringKeys, data_converter
from dewpoint.apps.dispatcher import evidence
from dewpoint.apps.dispatcher.dispatch import START_DEADLINE
from dewpoint.apps.dispatcher.gate import disable_and_wait
from dewpoint.apps.dispatcher.tick import admission_pollers
from dewpoint.apps.environment import verify_environment
from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
from dewpoint.apps.worker.deployment import Deployment, describe, set_current, this_build
from dewpoint.apps.worker.health import WorkerUnhealthyError
from dewpoint.apps.worker.main import run as run_worker
from dewpoint.core import logs
from dewpoint.core.audit import service as audit_log
from dewpoint.core.audit.administration import ADMINISTRATION, read_records, recorded
from dewpoint.core.audit.anchor import AnchorSink, FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
from dewpoint.core.audit.monitor import Catalog, Login, Roster, Scope, drift, watch
from dewpoint.core.audit.s3 import S3AnchorSink, bucket_problems, read_anchors
from dewpoint.core.auth.sessions import SESSION_COOKIE
from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto import reencrypt, retire
from dewpoint.core.crypto.ingress import IngressKey
from dewpoint.core.crypto.kek import KekSet, UnknownKekError
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
from dewpoint.core.egress import allowlist
from dewpoint.core.ingress import secrets_reseal
from dewpoint.core.ingress.keys import retire_event_keys, rotate_event_key
from dewpoint.core.models.identity import User
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.platform import inventory
from dewpoint.core.platform.boundary import ProofRefusedError, proof_evidence
from dewpoint.core.platform.service import (
    EnvironmentMismatchError,
    EnvironmentNotRecordedError,
    check_namespace,
    record_environment,
)
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.core.plugins.registry import (
    ContractChangedError,
    MissingNodeTypeError,
    ensure_cel_profile,
    list_node_types,
    sync_plugins,
)
from dewpoint.core.temporal_check import problems as temporal_problems
from dewpoint.core.temporal_connect import TemporalConfigError
from dewpoint.core.temporal_connect import connect as temporal_connect
from dewpoint.core.tenancy import lifecycle as tenant_lifecycle
from dewpoint.core.tenancy.service import NotKeyAdminError, ensure_tenant_event_keys, ensure_tenant_keys
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.sdk import ManifestError

log = structlog.get_logger("dewpoint.cli")
app = typer.Typer(no_args_is_help=True)


@app.callback()
def _process() -> None:
    # Each command runs as a process of its own (the worker, the dispatcher, ingress, an admin command): it logs as
    # every process does, an exception by its type and where it was raised, never a value.
    logs.configure()


admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")
audit = typer.Typer(no_args_is_help=True)
app.add_typer(audit, name="audit")
keys = typer.Typer(no_args_is_help=True)
app.add_typer(keys, name="keys")
plugins_cli = typer.Typer(no_args_is_help=True)
app.add_typer(plugins_cli, name="plugins")
lifecycle_cli = typer.Typer(no_args_is_help=True)
app.add_typer(lifecycle_cli, name="lifecycle")
dev_cli = typer.Typer(no_args_is_help=True)
app.add_typer(dev_cli, name="dev")
deployment_cli = typer.Typer(no_args_is_help=True)
app.add_typer(deployment_cli, name="deployment")
platform_cli = typer.Typer(no_args_is_help=True)
app.add_typer(platform_cli, name="platform")
egress_cli = typer.Typer(
    no_args_is_help=True, help="The outbound guard's allowlist (plugins-3 D8). Run as dewpoint_admin."
)
platform_cli.add_typer(egress_cli, name="egress")
api_cli = typer.Typer(no_args_is_help=True)
app.add_typer(api_cli, name="api")
temporal_cli = typer.Typer(help="Temporal, as this deployment reaches it (2b-4b M4).", no_args_is_help=True)
app.add_typer(temporal_cli, name="temporal")
schedules_cli = typer.Typer(no_args_is_help=True)
app.add_typer(schedules_cli, name="schedules")
app.add_typer(recovery_cli, name="recovery")  # an operator's, under their own recovery login


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


def _s3_client(settings: Settings) -> Any:
    """An S3 client with this process's own credentials (AWS's variables or profile): the anchor writer's put-only
    ones, the verifier's or the monitor's read-only ones (D6). A session of its own: boto3's default one keeps the
    first credentials it resolves, which a later command in the same process would otherwise reuse (R2's third
    attempt: the writer's, on a verify)."""
    import boto3

    session = boto3.session.Session()
    return session.client("s3", endpoint_url=settings.audit_s3_endpoint_url, region_name=settings.audit_s3_region)


def _kept(settings: Settings) -> timedelta:
    """How long the bucket must lock each anchor: the audit retention plus the backup period (D6.9)."""
    return timedelta(days=settings.audit_retention_days + settings.backup_retention_days)


def _sink() -> AnchorSink:
    settings = get_settings()
    if settings.audit_s3_bucket:
        return S3AnchorSink(_s3_client(settings), settings.audit_s3_bucket, settings.audit_s3_prefix, _signing_key(),
                            settings.audit_signing_key_id)  # fmt: skip
    return FileAnchorSink(_anchor_path(), _signing_key())


def _public_keys(settings: Settings) -> dict[str, Ed25519PublicKey]:
    """The keys anchors are verified with, by id: DEWPOINT_AUDIT_PUBLIC_KEYS, every id kept (rotation); else, in
    development, the signing key's own. A verifier needs no private key."""
    if not settings.audit_public_keys:
        return {settings.audit_signing_key_id: _signing_key().public_key()}
    try:
        given = json.loads(settings.audit_public_keys)
        return {str(kid): Ed25519PublicKey.from_public_bytes(base64.b64decode(raw)) for kid, raw in given.items()}
    except (ValueError, TypeError, AttributeError):
        typer.echo("ERROR: DEWPOINT_AUDIT_PUBLIC_KEYS isn't a JSON object of key ids to base64 Ed25519 public keys")
        raise typer.Exit(2) from None


def _anchor_path() -> Path:
    path = get_settings().audit_anchor_path
    if not path:
        typer.echo("DEWPOINT_AUDIT_ANCHOR_PATH is not set")
        raise typer.Exit(2)
    return Path(path)


@audit.command("anchor")
def audit_anchor() -> None:
    """Write current chain heads to the external anchor sink (DEWPOINT_AUDIT_S3_BUCKET's, else the file). Run as a
    dewpoint_auditor login, off the database host, e.g. every 15 min."""
    sink = _sink()

    async def _run() -> int:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                return await anchor_all(s, sink)
        finally:
            await engine.dispose()

    typer.echo(f"anchored {asyncio.run(_run())} scope head(s)")


@audit.command("prune")
def audit_prune() -> None:
    """Delete audit entries older than DEWPOINT_AUDIT_RETENTION_DAYS (400 unless set, never under 30) through a
    checkpoint, the last entry pruned, anchored to the external sink first (engine 2b spec §10.2). Run as a
    dewpoint_auditor login. Refused outside a development deployment until an off-host anchor sink exists (#3)."""
    from dewpoint.core.audit.prune import PruningDisabledError, prune

    sink = _sink()

    async def _run() -> dict[str, int]:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                return await prune(s, sink, older_than_days=get_settings().audit_retention_days)
        finally:
            await engine.dispose()

    try:
        pruned = asyncio.run(_run())
    except PruningDisabledError:
        typer.echo("ERROR: audit pruning is disabled outside a development deployment until an off-host anchor sink is "
                   "configured (#3)")  # fmt: skip
        raise typer.Exit(2) from None
    typer.echo(f"pruned {sum(pruned.values())} entries in {len(pruned)} scope(s)")


@audit.command("verify")
def audit_verify() -> None:
    """Recompute every chain and check it against the signed external anchors. Exit 1 on any problem,
    including when no anchors exist, so a broken anchor job can't look healthy. With DEWPOINT_AUDIT_S3_BUCKET: every
    version and delete marker in the bucket, each one's lock, and the bucket's default retention (D6), verified with
    the public keys alone."""
    settings = get_settings()

    async def _run() -> list[str]:
        if settings.audit_s3_bucket:
            client, kept = _s3_client(settings), _kept(settings)
            listing = read_anchors(client, settings.audit_s3_bucket, settings.audit_s3_prefix, kept=kept)
            found = bucket_problems(client, settings.audit_s3_bucket, kept=kept) + listing.problems
            keys = _public_keys(settings)
            async with _auditing() as s:
                return found + await verify_anchors(s, listing.entries, keys)
        key = _signing_key()
        sink = FileAnchorSink(_anchor_path(), key)
        async with _auditing() as s:
            return await verify_anchors(s, sink.entries(), key.public_key())

    problems = asyncio.run(_run())
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)
    typer.echo("audit chain verified against external anchors")


@asynccontextmanager
async def _auditing() -> AsyncIterator[AsyncSession]:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            yield s
    finally:
        await engine.dispose()


_SCOPES = text(
    "select scope, max(seq) from (select scope, seq from audit_log union all select scope, seq from audit_checkpoints)"
    " kept group by scope"
)
_UNANCHORED = text("select min(created_at) from audit_log where scope = :s and seq > :after")
# The database's administration, as the auditor reads it (task 7): the recovery group's members, the mappings, every
# recovery login's attributes, the schema's revision
_MEMBERS = text("select m.rolname from pg_auth_members a join pg_roles g on g.oid = a.roleid "
                "join pg_roles m on m.oid = a.member where g.rolname = 'dewpoint_recovery'")  # fmt: skip
_MAPPINGS = text("select login, revoked_at is not null from recovery_operators")
_LOGINS = text(r"select rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
               r"from pg_roles where rolname like 'rcv\_%' or rolname = any(:names)")  # fmt: skip
_REVISION = text("select version_num from alembic_version")


async def _catalog(s: AsyncSession) -> Catalog:
    members = frozenset(str(row[0]) for row in (await s.execute(_MEMBERS)).all())
    mappings = {str(login): bool(gone) for login, gone in (await s.execute(_MAPPINGS)).all()}
    found = await s.execute(_LOGINS, {"names": sorted(members | mappings.keys())})
    logins = {str(row[0]): Login(*(bool(v) for v in row[1:])) for row in found.all()}
    return Catalog(members, mappings, logins, (await s.execute(_REVISION)).scalar())


@audit.command("monitor")
def audit_monitor(
    roster_file: str = typer.Option(..., "--roster", help="the expected scopes and cadences, off the database host"),
    state_file: str = typer.Option(..., "--state", help="this monitor's high-water marks, off the database host"),
    init: bool = typer.Option(False, "--init", help="set the marks up: no state yet is no alert, this once"),
) -> None:
    """D6's independent monitor (#3), run on a schedule off the database host with read-only credentials: `audit
    verify` against the bucket, then a scope gone from the database, an anchor overdue past its cadence, or a
    high-water mark lost or rolled back. Each alert is logged and printed; exit 1 on any, so a monitor that can't see
    can't look healthy. Its alert destination is the operator's (the owner's ruling: chosen and tested before
    readiness)."""
    settings, roster, state = get_settings(), Path(roster_file), Path(state_file)
    if not settings.audit_s3_bucket:
        typer.echo("ERROR: the monitor reads the anchors' bucket: set DEWPOINT_AUDIT_S3_BUCKET")
        raise typer.Exit(2)
    try:
        given = json.loads(roster.read_text())
        cadences = {str(k): timedelta(minutes=int(v)) for k, v in given.get("scopes", {}).items()}
        rostered = Roster(default=timedelta(minutes=int(given["default_cadence_minutes"])), scopes=cadences)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        typer.echo("ERROR: the roster isn't readable JSON with default_cadence_minutes and scopes")
        raise typer.Exit(2) from None
    try:
        marks: dict[str, int] | None = {str(k): int(v) for k, v in json.loads(state.read_text()).items()}
    except (OSError, ValueError, TypeError, AttributeError):
        marks = None  # lost: alerted on, unless --init
    client, kept = _s3_client(settings), _kept(settings)
    listing = read_anchors(client, settings.audit_s3_bucket, settings.audit_s3_prefix, kept=kept)
    found = bucket_problems(client, settings.audit_s3_bucket, kept=kept) + listing.problems
    newest: dict[str, int] = {}
    for entry in listing.entries:
        newest[str(entry["scope"])] = max(newest.get(str(entry["scope"]), 0), int(entry["seq"]))
    keys = _public_keys(settings)

    records = read_records(client, settings.audit_s3_bucket, settings.audit_s3_prefix + ADMINISTRATION)

    async def _run() -> tuple[list[str], dict[str, Scope], datetime, Catalog]:
        async with _auditing() as s:
            problems = await verify_anchors(s, listing.entries, keys)
            catalog = await _catalog(s)
            now: datetime = (await s.execute(text("select statement_timestamp()"))).scalar_one()  # the entries' clock
            database: dict[str, Scope] = {}
            for scope, top in (await s.execute(_SCOPES)).all():
                oldest = (await s.execute(_UNANCHORED, {"s": scope, "after": newest.get(scope, 0)})).scalar()
                database[str(scope)] = Scope(newest=int(top), oldest_unanchored=oldest)
            return problems, database, now, catalog

    problems, database, now, catalog = asyncio.run(_run())
    alerts, updated = watch(rostered, marks, database, newest, now, init=init)
    alerts = [("audit_verify_failed", "", problem) for problem in found + problems] + alerts
    alerts += [("admin_record_problem", "", problem) for problem in records.problems]
    alerts += drift(records.entries, catalog)  # the administration no record off the host explains
    if marks is not None or init:  # a lost state isn't made afresh: it stays alerted on until set up knowingly (--init)
        written = state.with_name(state.name + ".new")
        written.write_text(json.dumps(updated, sort_keys=True))
        os.replace(written, state)
    for event, scope, what in alerts:
        log.error(event, scope=scope, what=what)
        typer.echo(f"ALERT {event}{' ' + scope if scope else ''}: {what}")
    if alerts:
        raise typer.Exit(1)
    typer.echo(f"audit monitor: healthy, {len(updated)} scope(s)")


@audit.command("freshness")
def audit_freshness(max_age_minutes: int = typer.Option(30, min=0)) -> None:
    """Exit 1 if any audit rows older than --max-age-minutes have no anchor. Use as the anchor job's
    healthcheck and in monitoring: a failing or stuck anchor job must not look healthy."""
    problems = asyncio.run(_in_session(lambda s: anchor_freshness(s, timedelta(minutes=max_age_minutes))))
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)
    typer.echo("anchors are fresh")


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
            if tenant_id is not None:  # in the transaction that writes the key (the 2b-4 outline's fencing)
                await tenant_lifecycle.require_active(s, tenant_id)
            return await keyring.rotate(s, tenant_id)

    try:
        typer.echo(f"active data key version: {asyncio.run(_in_session(_run))}")
    except tenant_lifecycle.TenantNotActiveError as e:
        typer.echo(f"ERROR: {e} (or no such tenant)")
        raise typer.Exit(1) from None


@keys.command("reencrypt")
def keys_reencrypt(
    tenant: str | None = typer.Option(None, help="one tenant's records"),
    all_tenants: bool = typer.Option(False, "--all", help="every tenant's records"),
    platform: bool = typer.Option(False, "--platform", help="the platform key's records (users' TOTP secrets)"),
    batch_size: int = typer.Option(100, min=1, max=1000),
) -> None:
    """Seal every record stored under an older data-key version again under the active one, and queue each schedule
    whose Temporal action was written under another for its sync (engine 2b spec §6.4): what retiring a version waits
    on. Idempotent: re-run until it reports nothing. Run as dewpoint_admin."""
    if sum((tenant is not None, all_tenants, platform)) != 1:
        typer.echo("pass exactly one of --tenant, --all or --platform")
        raise typer.Exit(2)
    try:
        chosen = uuid.UUID(tenant) if tenant is not None else None
    except ValueError:
        typer.echo("--tenant must be a UUID")
        raise typer.Exit(2) from None
    keyring = Keyring(KekSet.from_settings(get_settings()))

    async def _run() -> list[tuple[str, dict[str, int]]]:
        engine = make_engine(get_settings().database_url)
        try:
            sessionmaker = make_sessionmaker(engine)
            if platform:
                return [("platform", await reencrypt.platform(sessionmaker, keyring, batch=batch_size))]
            if chosen is not None:
                tenants = [chosen]
            else:
                async with sessionmaker() as s:
                    tenants = list((await s.execute(select(Tenant.id).order_by(Tenant.id))).scalars())
            return [(f"tenant {t}", await reencrypt.tenant(sessionmaker, keyring, t, batch=batch_size))
                    for t in tenants]  # fmt: skip
        finally:
            await engine.dispose()

    for scope, counts in asyncio.run(_run()):
        typer.echo(f"{scope}: " + " ".join(f"{k}={v}" for k, v in counts.items()))


@keys.command("rotate-event-key")
def keys_rotate_event_key(tenant: str = typer.Option(..., help="the tenant whose inbound keypair rotates")) -> None:
    """Make a tenant's next inbound keypair (engine 2b spec §8.3): ingress seals each delivery after it to it; events
    sealed to older ones still open. Run as dewpoint_admin."""
    try:
        tenant_id = uuid.UUID(tenant)
    except ValueError:
        typer.echo("--tenant must be a UUID")
        raise typer.Exit(2) from None
    keyring = Keyring(KekSet.from_settings(get_settings()))

    async def _run(s: AsyncSession) -> int:
        async with s.begin():
            await tenant_scope(s, tenant_id)
            await tenant_lifecycle.require_active(s, tenant_id)
            return await rotate_event_key(s, keyring, tenant_id)

    try:
        typer.echo(f"inbound keypair version: {asyncio.run(_in_session(_run))}")
    except tenant_lifecycle.TenantNotActiveError as e:
        typer.echo(f"ERROR: {e} (or no such tenant)")
        raise typer.Exit(1) from None


@keys.command("retire-event-keys")
def keys_retire_event_keys(
    tenant: str | None = typer.Option(None, help="one tenant's keypairs"),
    all_tenants: bool = typer.Option(False, "--all", help="every tenant's"),
) -> None:
    """Delete the inbound keypairs no stored event names, older than one that has existed for 10 minutes (engine 2b
    spec §8.3). Run as dewpoint_admin."""
    if (tenant is None) == (not all_tenants):
        typer.echo("pass exactly one of --tenant or --all")
        raise typer.Exit(2)
    try:
        chosen = uuid.UUID(tenant) if tenant is not None else None
    except ValueError:
        typer.echo("--tenant must be a UUID")
        raise typer.Exit(2) from None

    async def _run(s: AsyncSession) -> int:
        async with s.begin():
            tenants = [chosen] if chosen else list((await s.execute(select(Tenant.id).order_by(Tenant.id))).scalars())
        retired = 0
        for t in tenants:
            async with s.begin():
                await tenant_scope(s, t)
                retired += len(await retire_event_keys(s, t))
        return retired

    typer.echo(f"retired {asyncio.run(_in_session(_run))} inbound keypair(s)")


@keys.command("ingress-status")
def keys_ingress_status() -> None:
    """Endpoint secrets per ingress key id. Exit 3 if any are sealed under a key this configuration lacks: the previous
    key retires only once none names it (engine 2b spec §8.3). Run as dewpoint_admin, with the ingress key."""
    key = IngressKey.from_settings(get_settings())
    usage = asyncio.run(_in_session(secrets_reseal.usage))
    for kid, n in sorted(usage.items()):
        typer.echo(f"{kid}={n}")
    missing = sorted(set(usage) - key.key_ids)
    if missing:
        typer.echo(f"ERROR: no configured ingress key for: {', '.join(missing)}. Do not remove a key before "
                   "reseal-ingress completes.")  # fmt: skip
        raise typer.Exit(3)


@keys.command("reseal-ingress")
def keys_reseal_ingress(batch_size: int = typer.Option(100, min=1, max=1000)) -> None:
    """Seal every endpoint's secrets again under the current ingress key, their plaintext unchanged (engine 2b spec
    §8.3): the rollout's third phase, with the new key current and the old one previous. Re-run until it reports 0.
    Run as dewpoint_admin, with the ingress key."""
    st = get_settings()
    if not st.ingress_key_previous_b64 or st.ingress_key_previous_id == st.ingress_key_id:
        typer.echo("refusing: configure the new ingress key as current and the old one as previous first")
        raise typer.Exit(2)
    key = IngressKey.from_settings(st)

    async def _run() -> dict[str, int]:
        engine = make_engine(st.database_url)
        try:
            return await secrets_reseal.reseal(make_sessionmaker(engine), key, batch=batch_size)
        finally:
            await engine.dispose()

    typer.echo("resealed " + " ".join(f"{k}={v}" for k, v in asyncio.run(_run()).items()))


async def _verified_namespace(s: AsyncSession, settings: Settings) -> str:
    """Engine 2b spec §2.1, before a key command asks Temporal anything: this process's namespace is the deployment's
    recorded one. A mismatch, or none recorded, ends the command (exit 2) before any connection: never read as Temporal
    being unreachable, an unknown answer (the final review's I1). The recorded environment, which §10.4's settings are
    checked against."""
    async with s.begin():
        try:
            return (await check_namespace(s, settings.temporal_namespace)).environment
        except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
            typer.echo(f"ERROR: {e}")
            raise typer.Exit(2) from None


def _refused(e: TemporalConfigError) -> typer.Exit:
    """§10.4's settings refused: the command ends (exit 2), never read as Temporal being unreachable."""
    typer.echo(f"ERROR: {e}")
    return typer.Exit(2)


@temporal_cli.command("check")
def temporal_check() -> None:
    """Read-only: Temporal's namespace as it reports itself, reached with this deployment's §10.4 settings: TLS
    verified, a retention of at most 30 days (D3g), archival disabled. Exit 1 on a problem or when Temporal can't be
    asked; 2 when the settings are refused or the namespace isn't the deployment's recorded one."""
    settings = get_settings()

    async def _run(s: AsyncSession) -> list[str]:
        environment = await _verified_namespace(s, settings)
        try:
            client = await temporal_connect(settings, environment)
            answer = await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=settings.temporal_namespace)
            )
        except TemporalConfigError as e:
            raise _refused(e) from None
        except Exception as e:  # unreachable, refused: a problem, never a pass
            return [f"Temporal couldn't be asked ({type(e).__name__})"]
        ttl = answer.config.workflow_execution_retention_ttl
        typer.echo(f"temporal: {settings.temporal_address}, namespace {settings.temporal_namespace} ({environment})")
        typer.echo(f"retention: {ttl.seconds // 86400} days")
        archived = [n for n, a in (("history", answer.config.history_archival_state),
                                   ("visibility", answer.config.visibility_archival_state))
                    if a == ArchivalState.ARCHIVAL_STATE_ENABLED]  # fmt: skip
        typer.echo("archival: " + (", ".join(f"{n} enabled" for n in archived) if archived else "disabled"))
        return temporal_problems(answer, plaintext=settings.temporal_insecure_dev)

    found = asyncio.run(_in_session(_run))
    for problem in found:
        typer.echo(f"PROBLEM: {problem}")
    if found:
        raise typer.Exit(1)
    typer.echo("tls: verified; the namespace is within D3g's rules")


async def _namespace_retention(settings: Settings, environment: str) -> timedelta | None:
    """The Temporal namespace's retention, as it reports it (engine 2b spec §6.4's payload floor); None when it can't
    be read: the floor then can't be reckoned, and nothing retires."""
    try:
        client = await temporal_connect(settings, environment)
        answer = await client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=settings.temporal_namespace)
        )
    except TemporalConfigError as e:
        raise _refused(e) from None
    except Exception as e:  # unreachable, refused: unknown, never assumed
        typer.echo(f"WARNING: the namespace's retention couldn't be read ({type(e).__name__})")
        return None
    ttl = answer.config.workflow_execution_retention_ttl
    return timedelta(seconds=ttl.seconds, microseconds=ttl.nanos // 1000)


async def _run_histories(settings: Settings, environment: str, s: AsyncSession, tenant_id: uuid.UUID, version: int,
                         *, record: bool) -> retire.RunProof | None:  # fmt: skip
    """What Temporal shows of the tenant's run executions that could hold `version` (the owner's M3 rulings), in the
    caller's transaction (`record`: whether to record what it shows); None when Temporal can't be asked."""
    try:
        client = await temporal_connect(settings, environment)
        before = await retire.candidates_before(s, tenant_id, version)
        return await evidence.prove(s, client, tenant_id, before=before, record=record)
    except TemporalConfigError as e:
        raise _refused(e) from None
    except Exception as e:  # unreachable, refused: unknown, never assumed
        typer.echo(f"WARNING: the run executions couldn't be asked about ({type(e).__name__})")
        return None


@keys.command("retire")
def keys_retire(
    version: int = typer.Option(..., min=1, help="the data-key version to retire"),
    tenant: str | None = typer.Option(None, help="a tenant's data key"),
    platform: bool = typer.Option(False, "--platform", help="the platform's key"),
    confirm: bool = typer.Option(False, "--confirm", help="delete it if every check passes (else a dry run)"),
) -> None:
    """Retire a data-key version nothing needs (engine 2b spec §6.4): print every check, and with --confirm delete the
    version, audited, if all pass. Exit 1 when a dry run finds a check failing, 4 when --confirm does. A tenant's
    version reads the Temporal namespace's retention, and asks Temporal about each run execution that could hold it.
    Exit 2 when no Temporal namespace is recorded or the configured one isn't it, before any connection. Run as
    dewpoint_admin."""
    if (tenant is None) != platform:
        typer.echo("pass exactly one of --tenant or --platform")
        raise typer.Exit(2)
    try:
        tenant_id = uuid.UUID(tenant) if tenant is not None else None
    except ValueError:
        typer.echo("--tenant must be a UUID")
        raise typer.Exit(2) from None
    settings = get_settings()

    async def _run(s: AsyncSession) -> tuple[list[retire.Check], bool]:
        environment = await _verified_namespace(s, settings) if tenant_id else ""
        retention = await _namespace_retention(settings, environment) if tenant_id else None
        async with s.begin():
            if not confirm:  # a dry run changes nothing, what it reads of Temporal included (the final review's I1)
                await s.execute(text("SET TRANSACTION READ ONLY"))
            await tenant_scope(s, tenant_id)
            histories = (await _run_histories(settings, environment, s, tenant_id, version, record=confirm)
                         if tenant_id else None)  # fmt: skip
            if not confirm:
                found = await retire.checks(s, tenant_id, version, namespace_retention=retention,
                                            run_histories=histories)  # fmt: skip
                return found, False
            try:
                return await retire.retire(s, tenant_id, version, namespace_retention=retention,
                                           run_histories=histories), True  # fmt: skip
            except retire.NotRetiredError as e:
                return e.checks, False

    found, retired = asyncio.run(_in_session(_run))
    for c in found:
        typer.echo(f"{c.name}: {'yes' if c.ok else 'no'}" + (f" ({c.found})" if c.found else ""))
    if retired:
        typer.echo(f"retired version {version}")
        return
    if not all(c.ok for c in found):
        raise typer.Exit(4 if confirm else 1)
    typer.echo("not retired (a dry run: pass --confirm)")


ATTESTED = "every dispatcher from before 0039 stopped and unable to restart; no image from before 0039 deployable"


async def _admission_pollers(settings: Settings, environment: str) -> list[str] | None:
    """The identities polling the admission queue, as Temporal shows them; None when it can't be asked."""
    try:
        client = await temporal_connect(settings, environment)
        return await admission_pollers(client)
    except TemporalConfigError as e:
        raise _refused(e) from None
    except Exception as e:  # unreachable, refused: unknown, never assumed
        typer.echo(f"WARNING: the admission queue's pollers couldn't be read ({type(e).__name__})")
        return None


@keys.command("tick-cutover")
def keys_tick_cutover(
    attest: bool = typer.Option(False, "--attest", help="no dispatcher from before 0039 runs or can run again"),
    confirm: bool = typer.Option(False, "--confirm", help="record it (else a dry run)"),
) -> None:
    """Record the tick cutover (the owner's M3 rulings): from it, no dispatcher seals a schedule tick's payload under a
    tenant's key, so a key made after it can retire. No migration records it, not even a fresh deployment's: it needs
    the operator's attestation (`--attest`, required) that every dispatcher from before migration 0039 has stopped and
    can't restart, and that no dispatcher image from before 0039 can be deployed against this database. Nothing here
    can prove that. It also refuses (exit 1) while Temporal shows one still polling the admission queue, and when
    Temporal can't be asked (exit 3). It records once, audited with the attestation, and queues every live schedule,
    so its sync writes the action without the argument the old one sealed. A key made before it never retires. Exit 2
    without --attest. Exit 2 when no Temporal namespace is recorded or the configured one isn't it, before any
    connection. Run as dewpoint_admin."""
    if not attest:
        typer.echo("pass --attest: no dispatcher from before migration 0039 runs, or can be deployed again")
        raise typer.Exit(2)
    settings = get_settings()

    async def _run(s: AsyncSession) -> str:
        environment = await _verified_namespace(s, settings)
        async with s.begin():
            existing = (await s.execute(text("SELECT at FROM tick_cutover"))).scalar_one_or_none()
        if existing is not None:
            return f"already recorded at {existing.isoformat()}"
        pollers = await _admission_pollers(settings, environment)
        if pollers is None:
            raise typer.Exit(3)
        old = [p for p in pollers if tick_contract.IDENTITY not in p]
        if old:
            typer.echo(f"{len(old)} poller(s) of the admission queue without the tick contract's mark: stop every "
                       "dispatcher from before migration 0039 first")  # fmt: skip
            raise typer.Exit(1)
        if not confirm:
            return "not recorded (a dry run: pass --confirm)"
        async with s.begin():
            recorded = (await s.execute(text("INSERT INTO tick_cutover (at) VALUES (now()) ON CONFLICT DO NOTHING "
                                             "RETURNING at"))).scalar_one_or_none()  # fmt: skip
            if recorded is None:
                return "already recorded"
            queued = 0
            for t in list((await s.execute(select(Tenant.id).order_by(Tenant.id))).scalars()):
                await tenant_scope(s, t)
                done = await s.execute(
                    text(
                        "UPDATE schedules SET generation = generation + 1 WHERE tenant_id = :t "
                        "AND deleted_at IS NULL AND synced_generation = generation"
                    ),
                    {"t": t},
                )
                queued += int(done.rowcount)
            await tenant_scope(s, None)
            details: dict[str, object] = {"schedules": queued, "attested": ATTESTED}
            await audit_log.record(s, tenant_id=None, actor_id=None, action="keys.tick_cutover", target_type="platform",
                               target_id="tick_cutover", details=details)  # fmt: skip
        return f"recorded the tick cutover at {recorded.isoformat()}; {queued} schedule(s) queued"

    typer.echo(asyncio.run(_in_session(_run)))


INVENTORY_ATTESTED = (
    "every writer from before 0040 (its API, its dispatcher) stopped and unable to restart; no image from before 0040 "
    "deployable"
)


@schedules_cli.command("inventory-cutover")
def schedules_inventory_cutover(
    attest: bool = typer.Option(False, "--attest", help="no writer from before 0040 runs or can run again"),
    confirm: bool = typer.Option(False, "--confirm", help="record it (else a dry run)"),
) -> None:
    """Record the schedule inventory's cutover (the owner's D15 ruling on the 2b-4b M1 checkpoint): from it, the
    dispatcher's schedule passes and an erasure's schedule stages rely on every Temporal id a schedule may have. An
    online upgrade runs while the application from before migration 0040 still writes, and its dispatcher syncs any
    schedule under the schedule's own id: until this cutover, 0040 records each schedule added as it backfilled those
    already there. It needs the operator's attestation (`--attest`, required) that every writer from before 0040 (its
    API and its dispatcher) has stopped and can't restart, and that no image from before 0040 can be deployed against
    this database: nothing here can prove that. It also refuses (exit 1) while Temporal shows a dispatcher from before
    0040 polling the admission queue (its identity lacks the tick contract's mark, from the same release), and when
    Temporal can't be asked (exit 3). With --confirm it catches up first, in batches each committed on its own (any
    schedule without an incarnation, one the capture missed; each incarnation 0's missed count, as the old dispatcher
    last recorded it), then records once, audited with the attestation, in a short transaction holding schedules'
    writes off (`dewpoint.core.platform.inventory`). Interrupted, it's run again: the batches done stay done. Its lock
    waited for in vain through every attempt, nothing is recorded (exit 1; run it again); the capture off, it refuses.
    Exit 2 without --attest. Exit 2 when no Temporal namespace is recorded or the configured one isn't it, before any
    connection. Run as dewpoint_admin."""
    if not attest:
        typer.echo("pass --attest: no writer from before migration 0040 runs, or can be deployed again")
        raise typer.Exit(2)
    settings = get_settings()

    async def _run(s: AsyncSession) -> str:
        environment = await _verified_namespace(s, settings)
        async with s.begin():
            existing = (await s.execute(text("SELECT at FROM schedule_inventory_cutover"))).scalar_one_or_none()
        if existing is not None:
            return f"already recorded at {existing.isoformat()}"
        pollers = await _admission_pollers(settings, environment)
        if pollers is None:
            raise typer.Exit(3)
        old = [p for p in pollers if tick_contract.IDENTITY not in p]
        if old:
            typer.echo(f"{len(old)} poller(s) of the admission queue without the tick contract's mark: stop every "
                       "dispatcher from before migration 0040 first")  # fmt: skip
            raise typer.Exit(1)
        if not confirm:
            return "not recorded (a dry run: pass --confirm)"
        try:
            done = await inventory.cut_over(s, INVENTORY_ATTESTED)
        except inventory.CutoverRefusedError as e:
            typer.echo(f"not recorded: {e}")
            raise typer.Exit(1) from None
        said = "already recorded" if done.at is None else (
            f"recorded the inventory's cutover at {done.at.isoformat()}; {done.caught.caught} schedule(s) caught up, "
            f"{done.caught.refreshed} count(s) refreshed, in {done.caught.batches} batch(es)")  # fmt: skip
        if done.lock_lost:
            said += ("; its lock wasn't held to its end (its connection lost, or its unlock unanswered), so another "
                     "cutover may have run beside it (the database records one only)")  # fmt: skip
        return said

    typer.echo(asyncio.run(_in_session(_run)))


@keys.command("ensure-tenants")
def keys_ensure_tenants() -> None:
    """A data key for every tenant that has none (tenants created before 2b-1a): the payload codec only reads keys.
    Idempotent. Run as dewpoint_admin, as Compose's migrate step does: it lists tenants under row-level security."""
    keyring = Keyring(KekSet.from_settings(get_settings()))

    async def _run(s: AsyncSession) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        async with s.begin():
            return await ensure_tenant_keys(s, keyring), await ensure_tenant_event_keys(s, keyring)

    try:
        created, paired = asyncio.run(_in_session(_run))
    except NotKeyAdminError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(2) from None
    typer.echo(f"created a data key for {len(created)} tenant(s)")
    typer.echo(f"created an inbound keypair for {len(paired)} tenant(s)")


@plugins_cli.command("sync")
def plugins_sync() -> None:
    """Register installed plugins and this build's CEL profile. Run as dewpoint_admin on every deploy."""
    try:
        prepared = prepare(installed_plugins())
    except (PluginLoadError, ManifestError) as e:
        for problem in e.problems:
            typer.echo(f"ERROR: {problem}")
        raise typer.Exit(2) from None

    async def _run(s: AsyncSession) -> tuple[int, int]:
        async with s.begin():
            report = await sync_plugins(s, prepared)
            await ensure_cel_profile(s, CURRENT_CEL_PROFILE)
            return len(report.added), len(report.unchanged)

    try:
        added, unchanged = asyncio.run(_in_session(_run))
    except ContractChangedError as e:
        typer.echo(f"ERROR: the contract of {', '.join(e.refs)} changed; publish a new node type version instead")
        raise typer.Exit(2) from None
    except MissingNodeTypeError as e:
        typer.echo(f"ERROR: this build lacks {', '.join(e.refs)}, which are not retired; retire them first")
        raise typer.Exit(2) from None
    typer.echo(f"added {added}, unchanged {unchanged}")


@plugins_cli.command("list")
def plugins_list() -> None:
    """Node type versions that can still be used (active or deprecated)."""

    async def _run(s: AsyncSession) -> list[str]:
        return [f"{row.ref} {row.state}" for row in await list_node_types(s)]

    for line in asyncio.run(_in_session(_run)):
        typer.echo(line)


def _entry(node_type: str | None, cel_profile: str | None) -> Entry:
    if bool(node_type) == bool(cel_profile):
        typer.echo("pass exactly one of --node-type or --cel-profile")
        raise typer.Exit(2)
    return Entry("node", node_type) if node_type else Entry("cel", str(cel_profile))


def _print_preview(preview: lifecycle.RetirePreview) -> None:
    typer.echo(f"active references (enabled workflows): {len(preview.active_refs)}")
    for ref in preview.active_refs:
        typer.echo(f"  tenant {ref.tenant_id}  workflow {ref.workflow_name} ({ref.workflow_id})  v{ref.version_number}")
    typer.echo(f"versions that can no longer run, be activated or be enabled: {len(preview.affected)}")
    for v in preview.affected:
        flags = ", ".join(flag for flag, on in (("active", v.active), ("enabled", v.enabled)) if on) or "superseded"
        typer.echo(
            f"  tenant {v.tenant_id}  workflow {v.workflow_name} ({v.workflow_id})  v{v.version_number}  [{flags}]"
        )


@lifecycle_cli.command("deprecate")
def lifecycle_deprecate(
    node_type: str | None = typer.Option(None, help="type@version"),
    cel_profile: str | None = typer.Option(None),
) -> None:
    """Stop new versions from using a node type or CEL profile. Existing ones keep running."""
    entry = _entry(node_type, cel_profile)

    async def _run(s: AsyncSession) -> str:
        async with s.begin():
            return await lifecycle.deprecate(s, entry, actor_id=None)

    try:
        state = asyncio.run(_in_session(_run))
    except lifecycle.UnknownEntryError:
        typer.echo(f"unknown {entry}")
        raise typer.Exit(2) from None
    typer.echo(f"{entry}: {state}")


@lifecycle_cli.command("retire")
def lifecycle_retire(
    node_type: str | None = typer.Option(None, help="type@version"),
    cel_profile: str | None = typer.Option(None),
    force: bool = typer.Option(False, help="Retire even though active workflows use it (they stop being startable)."),
    confirm: bool = typer.Option(False, help="Apply a forced retirement after reviewing its preview."),
) -> None:
    """Retire a node type or CEL profile (spec §4.5). New builds may drop it afterwards."""
    entry = _entry(node_type, cel_profile)

    async def _run(s: AsyncSession) -> lifecycle.RetirePreview:
        async with s.begin():
            return await lifecycle.retire(s, entry, force=force, confirm=confirm)

    try:
        preview = asyncio.run(_in_session(_run))
    except lifecycle.UnknownEntryError:
        typer.echo(f"unknown {entry}")
        raise typer.Exit(2) from None
    except lifecycle.ReferencedError as e:
        _print_preview(e.preview)
        typer.echo("refusing: still used by active workflows. Migrate them, or use --force.")
        raise typer.Exit(4) from None
    _print_preview(preview)
    if not preview.applied:
        typer.echo("forced retirement NOT applied: review the list above, then re-run with --confirm")
        raise typer.Exit(3)
    typer.echo(f"{entry}: retired")


@app.command("dispatcher")
def dispatcher() -> None:
    """Run the dispatcher: it starts every admitted run within its tenant's slots (engine 2b spec §7.3). SIGTERM or
    SIGINT stops it once the cycle in hand ends: exit 0 (apps/stopping.py)."""
    from dewpoint.apps.dispatcher.main import run as run_dispatcher

    settings, code = get_settings(), 0
    try:
        asyncio.run(stopping.stoppable(lambda requested: run_dispatcher(settings, stop_requested=requested)))
    except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
        typer.echo(f"ERROR: {e}")
        code = 2
    stopping.leave(code)  # past interpreter finalization, where temporalio's bridge can crash


@app.command("worker")
def worker() -> None:
    """Run the Temporal worker: RunGraph and its activities, and cel.evaluate when DEWPOINT_CEL_SOCKET is set. SIGTERM
    or SIGINT stops it once running attempts end, within DEWPOINT_WORKER_SHUTDOWN_GRACE_S: exit 0 (apps/stopping.py)."""
    settings, code = get_settings(), 0
    try:
        asyncio.run(stopping.stoppable(lambda requested: run_worker(settings, stop_requested=requested)))
    except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
        typer.echo(f"ERROR: {e}")
        code = 2
    except WorkerUnhealthyError as e:  # its orchestrator restarts it (engine 2b spec §2.7)
        typer.echo(f"ERROR: {e}")
        code = 3
    stopping.leave(code)  # past interpreter finalization, where temporalio's bridge can crash


@app.command("retention")
def retention(once: bool = typer.Option(False, "--once", help="One sweep, then exit 0 if it succeeded")) -> None:
    """Run the retention job (engine 2b spec §10.3): every tenant's data past its retention deleted, every interval
    (DEWPOINT_RETENTION_INTERVAL_S), as the retention login. It holds no key. SIGTERM or SIGINT stops the job once the
    step in hand ends: exit 0 (apps/stopping.py)."""
    from dewpoint.apps.retention import RetentionSettings
    from dewpoint.apps.retention import run as run_retention

    if not once:  # the job retries what fails: only what it can't (its settings, say) ends it, exit 1
        code = 0
        try:
            asyncio.run(stopping.stoppable(lambda requested: run_retention(RetentionSettings(),
                                                                           stop_requested=requested)))  # fmt: skip
        except Exception as e:
            typer.echo(f"retention sweep failed: {type(e).__name__}")
            code = 1
        stopping.leave(code)  # past interpreter finalization, where temporalio's bridge can crash
    try:
        done = asyncio.run(run_retention(RetentionSettings(), once=True))
    except Exception as e:  # its failure raised
        typer.echo(f"retention sweep failed: {type(e).__name__}")
        raise typer.Exit(1) from None
    if done is None:
        typer.echo("another retention sweep is running")
        raise typer.Exit(1)
    typer.echo(f"retention sweep {done.id}: {'succeeded' if done.succeeded else 'failed'}")
    raise typer.Exit(0 if done.succeeded else 1)


@app.command("ingress")
def ingress(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8001, min=1, max=65535)) -> None:
    """Serve webhook ingress, `/hooks/<endpoint_id>` (engine 2b spec §8.3), in a development deployment only until
    engine 2b-4. The server's own X-Forwarded-For handling stays off: ingress believes it only from the proxies in
    DEWPOINT_INGRESS_TRUSTED_PROXIES."""
    import uvicorn

    from dewpoint.apps.ingress.config import IngressSettings
    from dewpoint.apps.ingress.main import (
        IngressRefusedError,
        create_app,
        refuse_key_encryption_key,
        require_development,
    )

    try:
        refuse_key_encryption_key(os.environ)
    except IngressRefusedError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(2) from None
    settings = IngressSettings()  # read from the environment

    async def _check() -> None:
        engine = make_engine(settings.database_url)
        try:
            await require_development(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    try:
        asyncio.run(_check())
    except IngressRefusedError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(2) from None
    # log_config=None: uvicorn's own logging configuration would replace the process's (dewpoint.core.logs), its
    # records quoting an exception's text; log_level keeps its INFO lines (startup, each request).
    uvicorn.run(
        create_app(settings),
        host=host,
        port=port,
        proxy_headers=False,
        server_header=False,
        log_config=None,
        log_level="info",
    )


@asynccontextmanager
async def _temporal() -> AsyncIterator[Client]:
    """A Temporal client, once this process's namespace is the one this deployment recorded (engine 2b spec §2.1).
    Its payloads are encrypted with each tenant's key, read through this process's database role (§6.2–6.3)."""
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        try:
            recorded = await verify_environment(sessionmaker, settings)
        except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
            typer.echo(f"ERROR: {e}")
            raise typer.Exit(2) from None
        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
        try:
            client = await temporal_connect(settings, recorded.environment, data_converter=data_converter(keys))
        except TemporalConfigError as e:
            raise _refused(e) from None
        yield client
    finally:
        await engine.dispose()


@platform_cli.command("init-environment")
def platform_init_environment(
    environment: str | None = typer.Option(
        None, "--environment", help="production or development (default: DEWPOINT_ENVIRONMENT, else production)"
    ),
    namespace: str | None = typer.Option(
        None, "--temporal-namespace", help="the Temporal namespace (default: DEWPOINT_TEMPORAL_NAMESPACE)"
    ),
) -> None:
    """Record, once, whether this deployment is production or development and which Temporal namespace it uses
    (engine 2b spec §2.1). The same values again change nothing; other values are refused. A development setup needs
    its own database and namespace: the label proves nothing about the data."""
    settings = get_settings()
    env = environment or settings.environment
    ns = namespace or settings.temporal_namespace

    async def _go() -> None:
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                await record_environment(s, environment=env, namespace=ns)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_go())
    except (ValueError, EnvironmentMismatchError) as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(2) from None
    typer.echo(f"this deployment is {env}, with the Temporal namespace `{ns}`")


@platform_cli.command("disable-production-runs")
def platform_disable_production_runs(
    wait: float = typer.Option(
        START_DEADLINE.total_seconds(), "--wait", help="seconds to wait for starts already made to settle"
    ),
) -> None:
    """Turn production runs off (engine 2b spec §2.4), audited: queued requests wait, started runs continue. Then wait
    for the starts already made to settle; exit 3, with their ids, while any is unresolved (the gate stays off). Run
    as dewpoint_admin. Turning them on is 2b-4's, with its readiness checks."""
    settings = get_settings()

    async def _go() -> list[uuid.UUID]:
        engine = make_engine(settings.database_url)
        try:
            return await disable_and_wait(make_sessionmaker(engine), deadline=timedelta(seconds=wait))
        finally:
            await engine.dispose()

    left = asyncio.run(_go())
    if left:
        many = "start is" if len(left) == 1 else "starts are"
        typer.echo(f"production runs are off; {len(left)} {many} still unresolved: {', '.join(map(str, left))}")
        raise typer.Exit(3)
    typer.echo("production runs are off; no start is left unresolved")


class CapacityApiError(Exception):
    """The API refused a platform admin's command: its error code, never more."""


def _api_client(base: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base, timeout=30.0)


async def capacity_via_api(
    client: httpx.AsyncClient, *, email: str, password: str, code: str, change: dict[str, object], attestation: str
) -> dict[str, object]:
    """The ingress capacity changed through the platform admin's API (D11, the owner's ruling on the 2b-4b M3
    checkpoint 3). What the capacity is then."""
    return await _as_platform_admin(client, email=email, password=password, code=code, method="PATCH",
                                    path="/api/v1/admin/platform/ingress-capacity",
                                    body={**change, "attestation": attestation})  # fmt: skip


async def boundary_via_api(
    client: httpx.AsyncClient, *, email: str, password: str, code: str, evidence: dict[str, str]
) -> dict[str, object]:
    """A namespace boundary recorded through the platform admin's API (D11, the owner's ruling on the 2b-4b M4
    design). The row as the API shows it."""
    return await _as_platform_admin(client, email=email, password=password, code=code, method="POST",
                                    path="/api/v1/admin/platform/namespace-boundaries",
                                    body=dict(evidence))  # fmt: skip


async def _as_platform_admin(
    client: httpx.AsyncClient, *, email: str, password: str, code: str, method: str, path: str,
    body: dict[str, object],
) -> dict[str, object]:  # fmt: skip
    """One platform admin's call (D11): signed in with the password, then the authenticator's code (a second factor
    proven now, so fresh), the call made on that session, which is then ended. Its answer."""
    token: str | None = None
    csrf = ""

    async def call(method: str, path: str, body: dict[str, object] | None = None) -> httpx.Response:
        nonlocal token
        headers = {"X-Dewpoint-Client": "web", **({"X-CSRF-Token": csrf} if csrf else {}),
                   **({"Cookie": f"{SESSION_COOKIE}={token}"} if token else {})}  # fmt: skip
        answer = await client.request(method, path, json=body, headers=headers)
        token = answer.cookies.get(SESSION_COOKIE) or token  # sent by hand: the client's own jar keeps none
        client.cookies.clear()
        if answer.status_code >= 400:
            error = (
                answer.json().get("error")
                if answer.headers.get("content-type", "").startswith("application/json")
                else None
            )
            raise CapacityApiError(str(error or answer.status_code))
        return answer

    csrf = (await call("POST", "/api/v1/auth/login", {"email": email, "password": password})).json()["csrf_token"]
    csrf = (await call("POST", "/api/v1/auth/mfa/totp", {"code": code})).json()["csrf_token"]
    try:
        answered = await call(method, path, body)
        result: dict[str, object] = answered.json()
        return result
    finally:
        try:
            await call("POST", "/api/v1/auth/logout")
        except (CapacityApiError, httpx.HTTPError):
            pass


@platform_cli.command("record-namespace-boundary")
def platform_record_namespace_boundary(
    api: str = typer.Option(..., "--api", envvar="DEWPOINT_API_URL", help="the API's origin, as the web reaches it"),
    email: str = typer.Option(..., "--email", help="the platform admin's email: you sign in as them"),
    proof: str = typer.Option(..., "--proof", help="D12's proof record (the JSON lines DEWPOINT_PROOF_OUT wrote)"),
    name: str = typer.Option(..., "--name", help="the boundary's name, kept while the boundary holds: a rebuilt "
                             "server recorded under the same name doesn't strand an erasure relying on it"),
    attestation: str = typer.Option(..., "--attestation", help="where and how D12 was proven, kept with the row and "
                                    "in the audit"),
) -> None:  # fmt: skip
    """Record this deployment's namespace boundary (D3g) through the platform admin's API (D11), tied to D12's proof
    and to the server and namespace it holds for (2b-4b M4). First the proof record: a whole pass, both
    configurations' inventories naming one server build. Then Temporal, with this deployment's own settings: the
    namespace's id, its TLS verified, its retention at most 30 days, its archival disabled. Then you sign in with your
    password and your authenticator's code. A development deployment's boundary only: production's waits for
    real-target qualification. Exit 2 on a refused proof or setting, 1 on what Temporal shows."""
    try:
        evidence = proof_evidence(Path(proof).read_bytes())
    except (OSError, ProofRefusedError) as e:
        typer.echo(f"ERROR: the proof record is refused: {e if isinstance(e, ProofRefusedError) else type(e).__name__}")
        raise typer.Exit(2) from None
    settings = get_settings()

    async def _described(s: AsyncSession) -> Any:
        environment = await _verified_namespace(s, settings)
        try:
            client = await temporal_connect(settings, environment)
            return await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=settings.temporal_namespace)
            )
        except TemporalConfigError as e:
            raise _refused(e) from None
        except Exception as e:  # unreachable, refused: nothing recorded on an unknown
            typer.echo(f"PROBLEM: Temporal couldn't be asked ({type(e).__name__})")
            raise typer.Exit(1) from None

    answer = asyncio.run(_in_session(_described))
    problems = temporal_problems(answer, plaintext=settings.temporal_insecure_dev)
    for problem in problems:
        typer.echo(f"PROBLEM: {problem}")
    if problems:
        raise typer.Exit(1)
    recorded = {"name": name, "namespace": settings.temporal_namespace, "namespace_id": answer.namespace_info.id,
                "server_build": evidence.server_build, "proof_digest": evidence.digest,
                "attestation": attestation}  # fmt: skip
    password = typer.prompt("Password", hide_input=True)
    code = typer.prompt("Authenticator code")

    async def _go() -> dict[str, object]:
        async with _api_client(api) as client:
            return await boundary_via_api(client, email=email, password=password, code=code, evidence=recorded)

    try:
        shown = asyncio.run(_go())
    except (CapacityApiError, httpx.HTTPError) as e:
        typer.echo(f"ERROR: the API refused it: {e}" if isinstance(e, CapacityApiError) else "ERROR: the API is "
                   f"unreachable ({type(e).__name__})")  # fmt: skip
        raise typer.Exit(2) from None
    typer.echo(
        f"namespace boundary {shown['id']} recorded: {name}, namespace {recorded['namespace']} "
        f"({recorded['namespace_id']}), server {evidence.server_build}, proof {evidence.digest}"
    )


@platform_cli.command("set-ingress-capacity")
def platform_set_ingress_capacity(
    api: str = typer.Option(..., "--api", envvar="DEWPOINT_API_URL", help="the API's origin, as the web reaches it"),
    email: str = typer.Option(..., "--email", help="the platform admin's email: you sign in as them"),
    attestation: str = typer.Option(..., "--attestation", help="how and where the starts were measured, kept in the "
                                    "audit with the change"),
    starts: float | None = typer.Option(None, "--starts-per-s", help="sustained starts a second, measured on this "
                                        "deployment's own Temporal (tests/probes/test_ingress_starts.py)"),
    headroom: float | None = typer.Option(None, "--headroom", help="the share of them ingress may use: above 0, at "
                                          "most 1"),
    wait: int | None = typer.Option(None, "--queue-wait-s", help="the agreed wait, in seconds, a tenant's queued "
                                    "webhook requests may stand for"),
    unset: bool = typer.Option(False, "--unset", help="unset all three: the development-only rates and cap"),
) -> None:  # fmt: skip
    """Change this deployment's ingress capacity through the platform admin's API (D11): you sign in with your password
    and your authenticator's code, and the API audits the change with your id and the attestation. A value left out
    keeps what it was; `--unset` unsets all three, which a production deployment whose runs are on refuses. Until the
    starts and the headroom are set, ingress keeps its development-only rates; until the wait is too, its
    development-only cap."""
    given: dict[str, object] = {
        k: v for k, v in (("starts_per_s", starts), ("headroom", headroom), ("queue_wait_s", wait)) if v is not None
    }
    if unset == bool(given):
        typer.echo("ERROR: give the ingress capacity's values to change, or --unset alone")
        raise typer.Exit(2)
    password = typer.prompt("Password", hide_input=True)
    code = typer.prompt("Authenticator code")

    async def _go() -> dict[str, object]:
        async with _api_client(api) as client:
            change: dict[str, object] = {"unset": True} if unset else given
            return await capacity_via_api(client, email=email, password=password, code=code, change=change,
                                          attestation=attestation)  # fmt: skip

    try:
        now = asyncio.run(_go())
    except (CapacityApiError, httpx.HTTPError) as e:
        typer.echo(f"ERROR: the API refused it: {e}" if isinstance(e, CapacityApiError) else "ERROR: the API is "
                   f"unreachable ({type(e).__name__})")  # fmt: skip
        raise typer.Exit(2) from None
    if now["starts_per_s"] is None and now["headroom"] is None and now["queue_wait_s"] is None:
        typer.echo("ingress capacity unset: the development-only rates and limit")
        return
    problems = now.get("problems")
    missing = [str(name) for name in problems] if isinstance(problems, list) else []
    if missing:  # the limit in force is the development-only one: never shown as agreed (the fresh review 5's M4)
        if now["starts_per_s"] is None or now["headroom"] is None:
            typer.echo(f"ingress capacity incomplete ({', '.join(missing)} unset): the development-only rates and "
                       f"limit, {now['limit']} requests' outstanding work at most")  # fmt: skip
        else:  # the rates derived already (the fresh review 6's M3)
            typer.echo(f"ingress capacity incomplete ({', '.join(missing)} unset): event rates from "
                       f"{now['starts_per_s']} starts a second measured, {now['headroom']} of them for ingress; the "
                       f"development-only limit, {now['limit']} requests' outstanding work at most")  # fmt: skip
        return
    typer.echo(f"ingress capacity: {now['starts_per_s']} starts a second measured, {now['headroom']} of them for "
               f"ingress, a {now['queue_wait_s']} s wait: the deployment's outstanding work at most {now['limit']} "
               "requests")  # fmt: skip


def _alembic_upgrade() -> int:
    """`alembic upgrade head`, run as Compose's migrate step ran it: its exit code."""
    return subprocess.run(["alembic", "upgrade", "head"], check=False).returncode  # noqa: S607 (the image's alembic)


async def _revision(url: str) -> str | None:
    """The schema's revision; None before the first migration."""
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as s:
            if (await s.execute(text("select to_regclass('public.alembic_version')"))).scalar() is None:
                return None
            found = (await s.execute(text("select version_num from alembic_version"))).scalar()
            return None if found is None else str(found)
    finally:
        await engine.dispose()


@deployment_cli.command("migrate")
def deployment_migrate() -> None:
    """The schema migrated to head on the prescribed path (2b-4b M4 recovery, the plan's ruling 7): its intent recorded
    off the database host first, then `alembic upgrade head`, then its outcome. It refuses in production without the
    administration sink. It claims nothing about an administrator who runs Alembic directly: that's the trusted
    exception, which the monitor sees only as persistent drift (`admin_revision_unrecorded`)."""
    settings = get_settings()
    sink = recovery_commands.required_sink(settings)
    action = uuid.uuid4()
    if sink is not None:  # its failure stops the migration before it starts
        sink.write(recorded("migration", "intent", action, target="head",
                            **{"from": asyncio.run(_revision(settings.database_url))}))  # fmt: skip
    code = _alembic_upgrade()
    if sink is not None:
        sink.write(recorded("migration", "outcome", action, status="succeeded" if code == 0 else "failed", exit=code,
                            to=asyncio.run(_revision(settings.database_url))))  # fmt: skip
    raise typer.Exit(code)


@deployment_cli.command("set-current")
def deployment_set_current(
    build: str | None = typer.Option(None, "--build-id", help="the build new runs start on (default: this one)"),
    wait: float = typer.Option(60.0, "--wait", help="seconds to wait for that build's workers to poll"),
) -> None:
    """Make a build the one new runs start on (spec §7). A run already started stays on its build until it ends."""
    target = build or this_build()

    async def _go() -> None:
        async with _temporal() as client:
            await set_current(client, target, wait_s=wait)

    asyncio.run(_go())
    typer.echo(f"current: {target}")


@deployment_cli.command("status")
def deployment_status() -> None:
    """The build new runs start on, and every version with its status: a draining one still serves its runs."""

    async def _go() -> Deployment:
        async with _temporal() as client:
            return await describe(client)

    deployment = asyncio.run(_go())
    typer.echo(f"current: {deployment.current or 'none'}")
    for v in deployment.versions:
        typer.echo(f"{v.build_id}  {v.status}")


@dev_cli.command("run")
def dev_run_command(
    workflow_id: uuid.UUID,
    tenant: str = typer.Option(..., "--tenant", help="tenant id"),
    input_file: str | None = typer.Option(None, "--input", help="JSON input for the active version"),
    simulate: bool = typer.Option(False, "--simulate", help="Plugin steps call simulate(): nothing is sent"),
    wait: float = typer.Option(0.0, "--wait", help="seconds to wait for the end the database records (0: don't)"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="retry a request (default: a new one)"),
) -> None:
    """Admit a run of a workflow's active version (source `dev`); the dispatcher starts it. Run as dewpoint_dispatch.
    Exit 0 when admitted (or, with --wait, when the run succeeded), 1 when it ended otherwise, 2 when it wasn't
    admitted, 3 when the wait ran out."""
    payload = json.loads(Path(input_file).read_text()) if input_file else {}
    if not isinstance(payload, dict):  # a run's input is an object: anything else could never start
        typer.echo("ERROR: --input must hold a JSON object")
        raise typer.Exit(2)
    settings = get_settings()
    tenant_id = uuid.UUID(tenant)

    async def _go() -> tuple[uuid.UUID, dev_run.Ended | None]:
        engine = make_engine(settings.database_url)
        try:
            sessionmaker = make_sessionmaker(engine)
            keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
            request = await dev_run.admit(
                sessionmaker, keys, tenant_id=tenant_id, workflow_id=workflow_id, input=payload, simulate=simulate,
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )  # fmt: skip
            if wait <= 0:
                return request.id, None
            return request.id, await dev_run.wait_for_end(sessionmaker, tenant_id, request.id, within=wait)
        finally:
            await engine.dispose()

    try:
        request_id, end = asyncio.run(_go())
    except admission.AdmissionRefusedError as e:
        for message in e.messages:
            typer.echo(f"ERROR: {message}")
        raise typer.Exit(2) from None
    except dev_run.RequestNotRetainedError:
        typer.echo("ERROR: request_not_retained: the request under this idempotency key is past its tenant's "
                   "retention cutoff")  # fmt: skip
        raise typer.Exit(2) from None
    except (admission.WorkflowNotFoundError, admission.IdempotencyConflictError) as e:
        typer.echo(f"ERROR: {e or type(e).__name__}")
        raise typer.Exit(2) from None
    if wait <= 0:
        typer.echo(f"request {request_id} queued")
        return
    if end is None:
        typer.echo(f"WARNING: request {request_id} hasn't ended after {wait:g} s")
        raise typer.Exit(3)
    detail = ": ".join(part for part in (end.code, end.message) if part)
    typer.echo(f"{end.what} {request_id} {end.status}" + (f": {detail}" if detail else ""))
    if (end.what, end.status) != ("run", "succeeded"):
        raise typer.Exit(1)


def _ports(given: str | None) -> tuple[int, int] | None:
    if given is None:
        return None
    low, _, high = given.partition("-")
    if not low.isdigit() or (high and not high.isdigit()):
        raise ValueError("--ports is a port or a range, such as 443 or 8000-8100.")
    return int(low), int(high or low)


@egress_cli.command("add")
def egress_add(
    network: str = typer.Argument(..., help="a strict CIDR, such as 10.20.0.0/16"),
    tenant: str | None = typer.Option(None, "--tenant", help="the tenant this entry is for"),
    every_tenant: bool = typer.Option(False, "--every-tenant", help="an entry for every tenant, asked for explicitly"),
    ports: str | None = typer.Option(None, "--ports", help="a port or a range (default: any)"),
    note: str = typer.Option("", "--note"),
    allow_sensitive: bool = typer.Option(
        False, "--allow-sensitive", help="confirm a short prefix, loopback, link-local or metadata network"
    ),
) -> None:
    """Let one tenant's plugins (or, explicitly, every tenant's) reach a private network; audited."""
    try:
        tenant_id = uuid.UUID(tenant) if tenant is not None else None
        if tenant_id is not None and every_tenant:
            raise ValueError("An entry is for one tenant or for every tenant, not both.")

        async def _run(s: AsyncSession) -> uuid.UUID:
            async with s.begin():
                return await allowlist.add(
                    s, network=network, ports=_ports(ports), tenant_id=tenant_id, note=note,
                    every_tenant=every_tenant, confirm_sensitive=allow_sensitive,
                )  # fmt: skip

        entry_id = asyncio.run(_in_session(_run))
    except ValueError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(2) from None
    typer.echo(f"added {entry_id}")


def _port_text(low: int | None, high: int | None) -> str:
    if low is None or high is None:
        return "any"
    return str(low) if low == high else f"{low}-{high}"


@egress_cli.command("list")
def egress_list() -> None:
    """Every entry: id, network, ports, tenant (* for every tenant), note."""

    async def _run(s: AsyncSession) -> list[str]:
        async with s.begin():
            rows = await allowlist.list_all(s)
        return [f"{r.id} {r.network} {_port_text(r.port_low, r.port_high)} {r.tenant_id or '*'} {r.note}" for r in rows]

    for line in asyncio.run(_in_session(_run)):
        typer.echo(line)


@egress_cli.command("remove")
def egress_remove(entry_id: str = typer.Argument(...)) -> None:
    """Remove an entry; audited. Exit 1 when there is none."""

    async def _run(s: AsyncSession) -> bool:
        async with s.begin():
            return await allowlist.remove(s, uuid.UUID(entry_id))

    try:
        removed = asyncio.run(_in_session(_run))
    except ValueError:
        typer.echo("ERROR: not an entry id")
        raise typer.Exit(2) from None
    if not removed:
        typer.echo("no such entry")
        raise typer.Exit(1)
    typer.echo("removed")


@api_cli.command("openapi")
def api_openapi() -> None:
    """Print the API's OpenAPI schema, exactly as the API serves it, with no server or settings (the web client is
    generated from it)."""
    from dewpoint.apps.api.openapi import schema

    typer.echo(json.dumps(schema(), indent=2, sort_keys=True))
