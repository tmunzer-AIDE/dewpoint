# SPDX-License-Identifier: Apache-2.0
"""The worker's `RunStore` over the database, as the worker role and inside the run's tenant (spec §8).

A projection the database refuses for its data (SQLSTATE class 22 or 23) would be refused on every retry, and no
later write of its run would land. It's written again row by row: a row refused again is logged and skipped, so the
others, and the run's end, land. Any other error is left to Temporal's retries: the database may take it later."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.exceptions import ApplicationError

from dewpoint.core.claims import secret_index
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.claims import SecretIndex
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.plugins.registry import load_node_types
from dewpoint.core.runs import service as runs
from dewpoint.engine.handles import StoredClaim
from dewpoint.engine.runtime.activities import ProjectInput, RunStart, RunSummary, StepRow, VersionData
from dewpoint.engine.runtime.execution import INTERNAL_ERROR

REFUSED = ("22", "23")  # SQLSTATE classes: data exceptions, integrity violations
_log = structlog.get_logger("dewpoint.worker")


def _refused(e: DBAPIError) -> str | None:
    """The SQLSTATE of an error the database would give again for the same data; None for any other."""
    state = getattr(e.orig, "sqlstate", None)
    return state if isinstance(state, str) and state[:2] in REFUSED else None


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
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource | None = None) -> None:
        """`keys`: the tenants' data keys, which claims and secret indexes are sealed with (engine 2b spec §3.1,
        §3.7). A store without them reads and writes no claims, and knows no secrets."""
        self.sessionmaker = sessionmaker
        self.cipher = ClaimCipher(keys) if keys is not None else None
        self.index_cipher = ClaimCipher(keys, purpose=secret_index.PURPOSE) if keys is not None else None

    def _claims(self) -> ClaimCipher:
        if self.cipher is None:
            raise ApplicationError("This worker's store reads no claims.", type=INTERNAL_ERROR, non_retryable=True)
        return self.cipher

    async def write_inputs(self, tenant_id: str, new: Sequence[tuple[claims.NewClaim, str]]) -> None:
        cipher = self._claims()
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            for claim, pointer in new:
                await claims.write_input(s, cipher, uuid.UUID(tenant_id), claim, pointer=pointer)

    async def grant(
        self, tenant_id: str, *, granted_by: str, to: str, claim_ids: Sequence[str], root_run_id: str
    ) -> None:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            await claims.grant(
                s,
                uuid.UUID(tenant_id),
                granted_by=uuid.UUID(granted_by),
                to=uuid.UUID(to),
                claim_ids=[uuid.UUID(c) for c in claim_ids],
                root_run_id=uuid.UUID(root_run_id),
            )

    async def input_schema(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            v = await s.get(WorkflowVersion, uuid.UUID(version_id))
        if v is None:
            return None
        return dict((v.graph.get("settings") or {}).get("input_schema", {"type": "object"}))

    async def index(self, tenant_id: str, root_run_id: str) -> secret_index.Index:
        if self.index_cipher is None:
            return secret_index.Index(0, ())
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            return await secret_index.read(s, self.index_cipher, uuid.UUID(tenant_id), uuid.UUID(root_run_id))

    async def index_version(self, tenant_id: str, root_run_id: str) -> int:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            found = await s.execute(
                select(SecretIndex.version).where(SecretIndex.root_run_id == uuid.UUID(root_run_id))
            )
            return found.scalar_one_or_none() or 0

    async def remember(self, tenant_id: str, root_run_id: str, strings: Sequence[str]) -> secret_index.Index:
        if not strings:
            return await self.index(tenant_id, root_run_id)
        if self.index_cipher is None:
            raise ApplicationError("This worker's store knows no secrets.", type=INTERNAL_ERROR, non_retryable=True)
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            return await secret_index.extend(
                s, self.index_cipher, uuid.UUID(tenant_id), uuid.UUID(root_run_id), list(strings)
            )

    async def fetch(self, tenant_id: str, run_id: str, claim_id: str) -> StoredClaim:
        cipher = self._claims()
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            found = await claims.fetch(
                s, cipher, uuid.UUID(tenant_id), run_id=uuid.UUID(run_id), claim_id=uuid.UUID(claim_id)
            )
        return StoredClaim(found.value, found.sensitive_pointers)

    async def write(
        self,
        tenant_id: str,
        new: Sequence[claims.NewClaim],
        *,
        kind: str,
        step_id: str | None,
        iteration_key: str | None,
    ) -> None:
        cipher = self._claims()
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            for claim in new:
                await claims.write_output(
                    s,
                    cipher,
                    uuid.UUID(tenant_id),
                    claim,
                    kind=kind,
                    step_id=uuid.UUID(step_id) if step_id else None,
                    iteration_key=iteration_key,
                    attempt=None,
                )

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
                subflow_version_ids=dict(sorted(v.subflow_version_ids.items())),
                failure_handler_version_id=str(v.failure_handler_version_id) if v.failure_handler_version_id else None,
                engine_abi=v.engine_abi,
                open_scopes_cap=v.open_scopes_cap,
                loop_depth=v.loop_depth,
            )

    async def project(self, data: ProjectInput) -> None:
        tenant = uuid.UUID(data.tenant_id)
        try:
            async with self.sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant)
                if data.start is not None:
                    await _start(s, tenant, data.start)
                await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
                if data.run is not None:
                    await _finish(s, data.run)
        except DBAPIError as e:
            if _refused(e) is None:
                raise
            await self._one_by_one(tenant, data)

    async def _one_by_one(self, tenant: uuid.UUID, data: ProjectInput) -> None:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            if data.start is not None:
                try:
                    async with s.begin_nested():
                        await _start(s, tenant, data.start)
                except DBAPIError as e:
                    state = _refused(e)
                    if state is None:
                        raise
                    _log.warning("projection_start_refused", run_id=data.start.run_id, sqlstate=state)
            for row in data.steps:
                try:
                    async with s.begin_nested():
                        await runs.upsert_steps(s, tenant, [_row(row)])
                except DBAPIError as e:
                    state = _refused(e)
                    if state is None:
                        raise
                    _log.warning(
                        "projection_row_refused",
                        run_id=row.run_id,
                        step_id=row.step_id,
                        iteration_key=row.iteration_key,
                        attempt=row.attempt,
                        sqlstate=state,
                    )
            if data.run is not None:
                try:
                    async with s.begin_nested():
                        await _finish(s, data.run)
                except DBAPIError as e:
                    state = _refused(e)
                    if state is None:
                        raise
                    _log.warning("projection_run_refused", run_id=data.run.run_id, sqlstate=state)


async def _start(s: AsyncSession, tenant: uuid.UUID, start: RunStart) -> None:
    await runs.ensure_run(
        s,
        run_id=uuid.UUID(start.run_id),
        tenant_id=tenant,
        workflow_id=uuid.UUID(start.workflow_id),
        version_id=uuid.UUID(start.version_id),
        mode=start.mode,
        kind=start.kind,
        parent_run_id=uuid.UUID(start.parent_run_id),
        parent_step_id=uuid.UUID(start.parent_step_id) if start.parent_step_id else None,
        parent_iteration_key=start.parent_iteration_key,
        started_at=datetime.fromisoformat(start.started_at),
    )


async def _finish(s: AsyncSession, run: RunSummary) -> None:
    await runs.finish_run(
        s,
        uuid.UUID(run.run_id),
        status=run.status,
        ended_at=datetime.fromisoformat(run.ended_at),
        error_code=run.error_code,
        error_message=run.error_message,
        iterations=run.iterations,
        if_running=run.if_running,
    )
