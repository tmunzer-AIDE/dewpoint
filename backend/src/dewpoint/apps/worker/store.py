# SPDX-License-Identifier: Apache-2.0
"""The worker's `RunStore` over the database, as the worker role and inside the run's tenant (spec §8)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.exceptions import ApplicationError

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.plugins.registry import load_node_types
from dewpoint.core.runs import service as runs
from dewpoint.engine.runtime.activities import ProjectInput, StepRow, VersionData


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(row: StepRow) -> dict[str, Any]:
    return {
        **row.__dict__,
        "run_id": uuid.UUID(row.run_id),
        "step_id": uuid.UUID(row.step_id),
        "started_at": _at(row.started_at),
        "ended_at": _at(row.ended_at),
    }


class DbRunStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            v = await s.get(WorkflowVersion, uuid.UUID(version_id))
            if v is None:
                raise ApplicationError(f"version {version_id} not found", type="version_not_found", non_retryable=True)
            types = await load_node_types(s, v.node_refs)
            return VersionData(
                version_id=str(v.id),
                workflow_id=str(v.workflow_id),
                graph=v.graph,
                expressions=list(v.expressions),
                cel_profile=v.cel_profile,
                manifests={t.ref: t.manifest for t in types},
            )

    async def project(self, data: ProjectInput) -> None:
        tenant = uuid.UUID(data.tenant_id)
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
            if data.run is not None:
                await runs.finish_run(
                    s,
                    uuid.UUID(data.run.run_id),
                    status=data.run.status,
                    ended_at=datetime.fromisoformat(data.run.ended_at),
                    error_code=data.run.error_code,
                    error_message=data.run.error_message,
                    iterations=data.run.iterations,
                )
