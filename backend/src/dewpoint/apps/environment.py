# SPDX-License-Identifier: Apache-2.0
"""The check every process that talks to Temporal runs before it connects (engine 2b spec §2.1): its configured
namespace must be the one this deployment recorded. The worker and the CLI's Temporal commands run it; the API never
talks to Temporal."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.config import Settings
from dewpoint.core.models.platform import PlatformSettings
from dewpoint.core.platform.service import check_namespace


async def verify_environment(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> PlatformSettings:
    """The deployment's record. Raises EnvironmentNotRecordedError or EnvironmentMismatchError: don't connect."""
    async with sessionmaker() as s:
        return await check_namespace(s, settings.temporal_namespace)
