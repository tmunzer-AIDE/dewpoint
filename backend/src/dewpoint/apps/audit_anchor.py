# SPDX-License-Identifier: Apache-2.0
"""Compose's anchor job, `dewpoint audit anchor --every <seconds>`: an anchor run, then a wait, until a stop is
requested (SIGTERM or SIGINT: apps/stopping.py). The run in hand ends and no other begins; the wait ends at once. A run
that fails ends the job, its exception raised, never retried: a job that stopped anchoring ends where `docker compose
ps -a` shows it (Compose's `restart: "no"`)."""

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from dewpoint.apps import stopping

log = structlog.get_logger("dewpoint.audit_anchor")


async def run(anchor: Callable[[], Awaitable[int]], *, every: float, stop_requested: asyncio.Event,
              anchored: Callable[[int], None]) -> None:  # fmt: skip
    """`anchor()` every `every` seconds, each count it returns given to `anchored`, until `stop_requested` is set."""
    while not stop_requested.is_set():
        anchored(await anchor())
        await stopping.pause(stop_requested, every)
    log.info("audit_anchor_stopped")
