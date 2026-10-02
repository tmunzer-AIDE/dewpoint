# SPDX-License-Identifier: Apache-2.0
"""An engine worker instance records what its build can do, and proves it (engine 2b spec §2.7). At startup and every
HEALTH_INTERVAL_S seconds it checks that its KEK wraps and unwraps a key and that its database role may read data
keys — what `payload_codec` needs of the instance — and records the result with its build and capabilities. One that
fails stops polling and exits: it never keeps taking tasks. The dispatcher (2b-2) and the readiness checks (2b-4)
read the records; a row that hasn't been checked lately is an instance that isn't live.

The check is deliberately light. The grant says nothing about what the role's RLS-scoped reads return, and the KEK
round trip uses a fresh key, not the stored ones: a wrong KEK under the right id passes both. Lifting the production
gate (2b-4) unwraps every stored key and reads each tenant's key along the workers' own path (spec §10.6).

A database that doesn't answer is an outage, not a failed check: the engine rides it out (its rows catch up), so the
instance keeps polling, records nothing, and its row goes stale. A record it can't write is logged the same way."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.platform.service import record_worker

log = structlog.get_logger()

# Compiled into the build: what every live instance of the current build must hold before runs start on it (2b-2).
CAPABILITIES = ("cel_request_size_guard", "claim_check", "payload_codec")
# What `claim_check` proves the role may do (engine 2b spec §2.7): read and write claims, grants and the secret index.
CLAIM_PRIVILEGES = (
    ("run_inputs", "SELECT"),
    ("run_inputs", "INSERT"),
    ("step_outputs", "SELECT"),
    ("step_outputs", "INSERT"),
    ("claim_grants", "SELECT"),
    ("claim_grants", "INSERT"),
    ("run_secret_index", "SELECT"),
    ("run_secret_index", "INSERT"),
    ("run_secret_index", "UPDATE"),
)
_CLAIMS = "SELECT " + " AND ".join(f"has_table_privilege('{t}', '{p}')" for t, p in CLAIM_PRIVILEGES)
HEALTH_INTERVAL_S = 30.0


class WorkerUnhealthyError(Exception):
    """This instance failed its self-check: it stopped polling, and recorded itself unhealthy where it could."""


async def self_check(keyring: Keyring, sessionmaker: async_sessionmaker[AsyncSession]) -> bool | None:
    """True when this instance can encrypt for its tenants, its KEK wrapping and unwrapping and its role reading data
    keys (`payload_codec`), and its claim store answers, its role reading and writing claims (`claim_check`). False
    when any is definitely not so. None when the database didn't answer: nothing is proven either way."""
    try:
        keyring.self_check()
    except Exception as e:  # whatever fails, the answer is the same: this instance can't unwrap keys
        log.error("worker_self_check_failed", check="kek", error=type(e).__name__)
        return False
    try:
        async with sessionmaker() as s:  # the grants, read from the catalog: an answer, whichever tenant is asked for
            readable: bool = (await s.execute(text("SELECT has_table_privilege('data_keys', 'SELECT')"))).scalar_one()
            claims: bool = (await s.execute(text(_CLAIMS))).scalar_one()
    except Exception as e:
        log.warning("worker_self_check_unanswered", error=type(e).__name__)
        return None
    if not readable:
        log.error("worker_self_check_failed", check="data_keys")
    if not claims:
        log.error("worker_self_check_failed", check="claims")
    return readable and claims


def reporter(
    sessionmaker: async_sessionmaker[AsyncSession], instance_id: uuid.UUID, build_id: str
) -> Callable[[bool], Awaitable[None]]:
    async def report(healthy: bool) -> None:
        async with sessionmaker() as s, s.begin():
            await record_worker(
                s, instance_id=instance_id, build_id=build_id, capabilities=CAPABILITIES, healthy=healthy
            )

    return report


async def start_healthy(check: Callable[[], Awaitable[bool | None]], report: Callable[[bool], Awaitable[None]]) -> None:
    """Before any worker polls: raises WorkerUnhealthyError unless the check passes. An instance that can't prove itself
    yet doesn't start, whatever the reason."""
    healthy = await check()
    await report(healthy is True)
    if healthy is not True:
        raise WorkerUnhealthyError("This worker couldn't prove its capabilities at startup: it never polled.")


async def watch(
    check: Callable[[], Awaitable[bool | None]],
    report: Callable[[bool], Awaitable[None]],
    stop: Callable[[], Awaitable[None]],
    *,
    interval_s: float = HEALTH_INTERVAL_S,
) -> None:
    """Every `interval_s`: check, and record the result. A failed check stops the workers polling (`stop`, which lets
    running attempts finish within the shutdown grace), then raises WorkerUnhealthyError. An unanswered one records
    nothing and changes nothing."""
    while True:
        await asyncio.sleep(interval_s)
        healthy = await check()
        if healthy is None:
            continue
        try:
            await report(healthy)
        except Exception as e:  # an outage: the row goes stale, and stale rows aren't live instances
            log.warning("worker_health_not_recorded", error=type(e).__name__)
        if not healthy:
            await stop()
            raise WorkerUnhealthyError("This worker failed its self-check: it stopped polling.")
