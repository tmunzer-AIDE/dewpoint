# SPDX-License-Identifier: Apache-2.0
"""`dewpoint retention` (engine 2b spec §10.3): its own process, as `dewpoint_retention_login`, the only login that
deletes retained data. It sweeps every tenant every interval; a sweep that fails is logged (its error's type only) and
the next one tried. It never decrypts anything, so its settings, from its environment only, hold no key."""

import asyncio

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.retention.sweep import BATCH, Sweep
from dewpoint.core.retention.sweep import sweep as sweep_all

log = structlog.get_logger("dewpoint.retention")


class RetentionSettings(BaseSettings):
    # The environment only, never a `.env` file: a shared one may hold the key-encryption key.
    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=None, extra="ignore", hide_input_in_errors=True)

    database_url: str  # the retention login's
    # Many sweeps within the SLO's day (§10.3): a failed one is retried an interval later.
    retention_interval_s: float = Field(default=3600, ge=60, le=6 * 3600)
    retention_batch: int = Field(default=BATCH, ge=1, le=10_000)


async def run(settings: RetentionSettings, *, once: bool = False) -> Sweep | None:
    """Sweeps every interval, for as long as the process lives; with `once`, one sweep, which it returns (None when
    another process is sweeping; its failure raised)."""
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        while True:
            if once:
                return await sweep_all(sessionmaker, batch=settings.retention_batch)
            try:
                await sweep_all(sessionmaker, batch=settings.retention_batch)
            except Exception as e:  # the database unreachable, say: the next interval tries again
                log.error("retention_sweep_failed", error=type(e).__name__)
            await asyncio.sleep(settings.retention_interval_s)
    finally:
        await engine.dispose()
