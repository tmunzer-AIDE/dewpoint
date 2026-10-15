# SPDX-License-Identifier: Apache-2.0
"""`dewpoint retention` (engine 2b spec §10.3): its own process, as `dewpoint_retention_login`, the only login that
deletes retained data. It sweeps every tenant every interval; a sweep that fails is logged (its error's type only) and
the next one tried. It never decrypts anything, so its settings, from its environment only, hold no key.

It also carries every tenant erasure on (2b-4a M4, `apps.erasure`): a pass every `erasure_interval_s`, and the
reconciliation of completed erasures with every sweep. Both need Temporal, which it reaches with a plain client (no
payload is ever decoded), and only once its namespace is the one the deployment recorded (engine 2b spec §2.1; the
owner's ruling: erasure pauses and deletes Temporal resources): until then it makes no Temporal call, alerts every
interval (`erasure_namespace_mismatch`, `erasure_environment_unrecorded`) and keeps sweeping. Without
`DEWPOINT_TEMPORAL_ADDRESS`, an erasure under way is alerted on every interval (`erasures_unattended`), never carried on
unseen."""

import asyncio

import structlog
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client

from dewpoint.apps.erasure.bound import reconcile_erased
from dewpoint.apps.erasure.process import erase_pass
from dewpoint.apps.stopping import pause
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.platform.service import EnvironmentMismatchError, EnvironmentNotRecordedError, check_namespace
from dewpoint.core.retention.sweep import BATCH, Sweep
from dewpoint.core.retention.sweep import sweep as sweep_all
from dewpoint.core.temporal_connect import TemporalConfigError, TemporalConnection, refresh_token
from dewpoint.core.temporal_connect import connect as temporal_connect

log = structlog.get_logger("dewpoint.retention")


class RetentionSettings(TemporalConnection):
    # The environment only, never a `.env` file: a shared one may hold the key-encryption key.
    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=None, extra="ignore", hide_input_in_errors=True)

    database_url: str  # the retention login's
    # Many sweeps within the SLO's day (§10.3): a failed one is retried an interval later.
    retention_interval_s: float = Field(default=3600, ge=60, le=6 * 3600)
    retention_batch: int = Field(default=BATCH, ge=1, le=10_000)
    erasure_interval_s: float = Field(default=60, ge=5, le=3600)  # a pass over the erasures under way
    temporal_address: str | None = None  # none: no erasure is carried on, and each one under way is alerted on
    temporal_namespace: str = "default"


async def connect(settings: RetentionSettings, recorded_environment: str) -> Client:
    """A plain client: the erasure calls the service directly and decodes no payload, so it needs no key. Its
    security is §10.4's (`core/temporal_connect.py`)."""
    return await temporal_connect(settings, recorded_environment, identity="dewpoint-retention")


async def _erasure_client(sessionmaker: async_sessionmaker[AsyncSession], settings: RetentionSettings) -> Client | None:
    """Temporal for erasure work, once this process's namespace is the deployment's recorded one; None (alerted)
    before any call otherwise."""
    try:
        async with sessionmaker() as s:
            recorded = await check_namespace(s, settings.temporal_namespace)
    except EnvironmentNotRecordedError:
        log.error("erasure_environment_unrecorded")
        return None
    except EnvironmentMismatchError:
        log.error("erasure_namespace_mismatch", configured=settings.temporal_namespace)
        return None
    try:
        return await connect(settings, recorded.environment)
    except TemporalConfigError as e:  # its §10.4 settings refused: never connected, alerted each interval
        log.error("erasure_temporal_refused", reason=str(e))
        return None


async def _unattended(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as s:
        waiting: int = (await s.execute(text("SELECT erasures_unfinished()"))).scalar_one()  # a count (M3)
    if waiting:
        log.error("erasures_unattended", erasures=int(waiting))


async def run(
    settings: RetentionSettings, *, once: bool = False, stop_requested: asyncio.Event | None = None
) -> Sweep | None:
    """Sweeps every `retention_interval_s` and carries erasures on every `erasure_interval_s`, until a stop is
    requested (`stop_requested`, set by SIGTERM or SIGINT: apps/stopping.py): the step in hand ends, and no other
    begins (the owner's ruling T1); a sweep or a pass still running when Compose's grace ends is cut, and the next
    process resumes it. With `once`, one sweep, which it returns (None when another process is sweeping; its failure
    raised)."""
    requested = stop_requested if stop_requested is not None else asyncio.Event()
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        if once:
            return await sweep_all(sessionmaker, batch=settings.retention_batch)
        client: Client | None = None
        every = max(1, round(settings.retention_interval_s / settings.erasure_interval_s))  # passes between sweeps
        tick = 0
        while not requested.is_set():
            if settings.temporal_address and client is None:
                try:
                    client = await _erasure_client(sessionmaker, settings)
                except Exception as e:  # Temporal or the database unreachable: tried again next interval
                    log.error("erasure_temporal_unreachable", error=type(e).__name__)
            if client is not None and settings.temporal_bearer_token_file:  # a rotated token, without a restart
                await refresh_token(client, settings.temporal_bearer_token_file)
            if tick % every == 0 and not requested.is_set():
                try:
                    await sweep_all(sessionmaker, batch=settings.retention_batch)
                except Exception as e:  # the database unreachable, say: the next interval tries again
                    log.error("retention_sweep_failed", error=type(e).__name__)
                if client is not None and not requested.is_set():
                    try:
                        await reconcile_erased(sessionmaker, client)
                    except Exception as e:
                        log.error("erasure_reconciliation_failed", error=type(e).__name__)
            if not requested.is_set():
                try:
                    if client is not None:
                        await erase_pass(sessionmaker, client)
                    elif not settings.temporal_address:
                        await _unattended(sessionmaker)
                except Exception as e:
                    log.error("erasure_pass_failed", error=type(e).__name__)
            tick += 1
            await pause(requested, settings.erasure_interval_s)
    finally:
        await engine.dispose()
    log.info("retention_stopped")
    return None
