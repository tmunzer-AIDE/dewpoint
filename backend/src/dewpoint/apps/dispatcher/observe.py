# SPDX-License-Identifier: Apache-2.0
"""What the dispatcher observes each cycle, before any dispatch transaction (engine 2b spec §2.7, §7.3): the
deployment's current build, as Temporal reports it, recorded with when it was observed for admission's ABI check (the
owner's ruling on 2b-2); and the dispatcher's own report, health evidence for 2b-4's readiness checks."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.platform.service import record_current_build, record_dispatcher
from dewpoint.engine.runtime.build import abi_of

# What every live instance of the current build must hold before anything is dispatched to it (§2.7).
REQUIRED = ("cel_request_size_guard", "claim_check", "payload_codec")


@dataclass(frozen=True)
class Build:
    build_id: str
    engine_abi: int


async def observe(sessionmaker: async_sessionmaker[AsyncSession], current: str | None) -> Build | None:
    """The current build Temporal reported (`current`), recorded; None when there's none. An old record is then left
    to age, so admission fails closed once it's stale. Whether its workers are ready is checked at every dispatch."""
    abi = abi_of(current) if current else None
    if current is None or abi is None:  # none current, or not a Dewpoint build's id
        return None
    build = Build(current, abi)
    async with sessionmaker() as s, s.begin():
        await record_current_build(s, build.build_id, build.engine_abi)
    return build


async def report(
    sessionmaker: async_sessionmaker[AsyncSession],
    instance_id: uuid.UUID,
    build_id: str,
    details: dict[str, object],
    *,
    kind: str = "dispatcher",
) -> None:
    async with sessionmaker() as s, s.begin():
        await record_dispatcher(s, instance_id=instance_id, kind=kind, build_id=build_id, details=details)
