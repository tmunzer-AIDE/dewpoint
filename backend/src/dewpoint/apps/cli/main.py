# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
from dewpoint.apps.worker.deployment import Deployment, describe, set_current, this_build
from dewpoint.apps.worker.main import run as run_worker
from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto.kek import KekSet, UnknownKekError
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.core.plugins.registry import (
    ContractChangedError,
    MissingNodeTypeError,
    ensure_cel_profile,
    list_node_types,
    sync_plugins,
)
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import LIVE, SIMULATE, RunResult
from dewpoint.engine.runtime.workflow import RunGraph
from dewpoint.sdk import ManifestError

app = typer.Typer(no_args_is_help=True)
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
            return await keyring.rotate(s, tenant_id)

    typer.echo(f"active data key version: {asyncio.run(_in_session(_run))}")


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


@app.command("worker")
def worker() -> None:
    """Run the Temporal worker: RunGraph and its activities, and cel.evaluate when DEWPOINT_CEL_SOCKET is set."""
    asyncio.run(run_worker(get_settings()))


async def _temporal() -> Client:
    settings = get_settings()
    return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)


@deployment_cli.command("set-current")
def deployment_set_current(
    build: str | None = typer.Option(None, "--build-id", help="the build new runs start on (default: this one)"),
    wait: float = typer.Option(60.0, "--wait", help="seconds to wait for that build's workers to poll"),
) -> None:
    """Make a build the one new runs start on (spec §7). A run already started stays on its build until it ends."""
    target = build or this_build()

    async def _go() -> None:
        await set_current(await _temporal(), target, wait_s=wait)

    asyncio.run(_go())
    typer.echo(f"current: {target}")


@deployment_cli.command("status")
def deployment_status() -> None:
    """The build new runs start on, and every version with its status: a draining one still serves its runs."""

    async def _go() -> Deployment:
        return await describe(await _temporal())

    deployment = asyncio.run(_go())
    typer.echo(f"current: {deployment.current or 'none'}")
    for v in deployment.versions:
        typer.echo(f"{v.build_id}  {v.status}")


async def dev_run_version(
    settings: Settings,
    client: Client,
    *,
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    trigger: dict[str, object],
    simulate: bool = False,
    wait: bool = True,
) -> tuple[uuid.UUID, RunResult | None]:
    engine = make_engine(settings.database_url)
    try:
        run_id = await start_run(
            make_sessionmaker(engine),
            client,
            settings,
            tenant_id=tenant_id,
            version_id=version_id,
            trigger=trigger,
            mode=SIMULATE if simulate else LIVE,
        )
    finally:
        await engine.dispose()
    if not wait:
        return run_id, None
    return run_id, await client.get_workflow_handle_for(RunGraph.run, str(run_id)).result()


@dev_cli.command("run")
def dev_run(
    version_id: uuid.UUID,
    tenant: str = typer.Option(..., "--tenant", help="tenant id"),
    input_file: str | None = typer.Option(None, "--input", help="JSON trigger payload (test data only until 2b)"),
    simulate: bool = typer.Option(False, "--simulate", help="Plugin steps call simulate(): nothing is sent"),
    wait: bool = typer.Option(True, "--wait/--no-wait"),
) -> None:
    """Start a run of a workflow's active version. Development only: 2b brings admission and triggers."""
    trigger = json.loads(Path(input_file).read_text()) if input_file else {}
    if not isinstance(trigger, dict):  # a run's trigger is an object: anything else could never start
        typer.echo("ERROR: --input must hold a JSON object")
        raise typer.Exit(2)

    async def _go() -> tuple[uuid.UUID, RunResult | None]:
        settings = get_settings()
        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        return await dev_run_version(
            settings,
            client,
            tenant_id=uuid.UUID(tenant),
            version_id=version_id,
            trigger=trigger,
            simulate=simulate,
            wait=wait,
        )

    try:
        run_id, result = asyncio.run(_go())
    except NotAdmissibleError as e:
        for reason in e.reasons:
            typer.echo(f"ERROR: {reason}")
        raise typer.Exit(2) from None
    except StartRefusedError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1) from None
    except StartUncertainError as e:
        typer.echo(f"WARNING: {e}")
        raise typer.Exit(3) from None
    typer.echo(f"run {run_id}")
    if result is not None:
        typer.echo(json.dumps(asdict(result), indent=2, sort_keys=True))
        if result.status != "succeeded":
            raise typer.Exit(1)
