# SPDX-License-Identifier: Apache-2.0
"""What this deployment is (engine 2b spec §2.1): production or development, and the Temporal namespace it uses,
recorded once. A process that talks to Temporal checks its configured namespace against the record before it starts,
so a development database can't drive a namespace it wasn't set up for, and a production database can't either. The
label proves nothing about the data: keeping development's database and namespace apart from production's is the
operator's job."""

from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.platform import PlatformSettings

PRODUCTION = "production"
DEVELOPMENT = "development"
ENVIRONMENTS = (PRODUCTION, DEVELOPMENT)
NOT_RECORDED = (
    "This deployment's environment isn't recorded: run `dewpoint platform init-environment` (Compose's migrate step "
    "does) before starting anything that talks to Temporal."
)


class EnvironmentNotRecordedError(Exception):
    def __init__(self) -> None:
        super().__init__(NOT_RECORDED)


class EnvironmentMismatchError(Exception):
    pass


async def recorded(s: AsyncSession) -> PlatformSettings | None:
    return await s.get(PlatformSettings, 1)


async def record_environment(s: AsyncSession, *, environment: str, namespace: str) -> PlatformSettings:
    """Record it once. Recording the same values again changes nothing; other values are refused: a deployment never
    changes environment or namespace (a trigger enforces it too)."""
    if environment not in ENVIRONMENTS:
        raise ValueError(f"The environment is `production` or `development`, not `{environment}`.")
    if not namespace:
        raise ValueError("The Temporal namespace can't be empty.")
    existing = await recorded(s)
    if existing is None:
        row = PlatformSettings(id=1, environment=environment, temporal_namespace=namespace)
        s.add(row)
        await s.flush()
        return row
    if (existing.environment, existing.temporal_namespace) != (environment, namespace):
        raise EnvironmentMismatchError(
            f"This deployment is recorded as {existing.environment}, with the Temporal namespace "
            f"`{existing.temporal_namespace}`. Neither can change."
        )
    return existing


async def check_namespace(s: AsyncSession, configured: str) -> PlatformSettings:
    """The record, when this process's namespace is the recorded one. Raises otherwise: the process must not start."""
    row = await recorded(s)
    if row is None:
        raise EnvironmentNotRecordedError()
    if row.temporal_namespace != configured:
        raise EnvironmentMismatchError(
            f"This deployment uses the Temporal namespace `{row.temporal_namespace}`, but this process is configured "
            f"for `{configured}` (DEWPOINT_TEMPORAL_NAMESPACE). It won't start."
        )
    return row
