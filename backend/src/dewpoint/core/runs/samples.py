# SPDX-License-Identifier: Apache-2.0
"""A step's newest sample (sub-project 4, B7; 4c-2a rulings 9, 10): the preview of its output in an ended run of its
workflow, with the version it ran as and the connections it opened, so the editor can say whether it still
represents the draft. Only API reads use it, within the tenant's retention (core/retention/cutoff.py).

The search is bounded: the newest SCAN_RUNS ended runs of the workflow. So "no sample" means none there, which the
answer says by how many runs it searched."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Integer, cast, func, select, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dewpoint.core.models.connections import Connection
from dewpoint.core.models.runs import Run, RunStep, RunStepConnection
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.plugins import registry
from dewpoint.core.retention.cutoff import Cutoff, kept
from dewpoint.sdk.fields import CONNECTION

SCAN_RUNS = 200  # the newest ended runs of a workflow a sample is looked for in (ruling 9)


def as_uuid(value: Any) -> uuid.UUID | None:
    """A graph's text read as a UUID, as the engine and the worker read ids: `ABC…` and `abc…` are the same one."""
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class UsedConnection:
    connection_id: uuid.UUID
    type: str
    name: str  # its name now, or as recorded when it's gone
    revision: int  # as the attempt used it
    current_revision: int | None  # None: deleted since
    context: Mapping[str, Any]

    @property
    def state(self) -> Literal["unchanged", "changed", "deleted"]:
        if self.current_revision is None:
            return "deleted"
        return "unchanged" if self.current_revision == self.revision else "changed"


@dataclass(frozen=True)
class Sample:
    run_id: uuid.UUID
    run_kind: str
    mode: str
    version_id: uuid.UUID
    version_number: int
    iteration_key: str
    attempt: int
    captured_at: datetime | None
    output: Any  # the stored preview: redacted and cut where it was (engine-core spec §8)
    node: Mapping[str, Any] | None  # the step as its version wrote it
    connections: tuple[UsedConnection, ...]  # one per connection and revision the attempt opened
    names_connection: bool  # the step, as its version wrote it, names a connection in a field its type marks for one


@dataclass(frozen=True)
class Search:
    sample: Sample | None
    searched: int  # the ended runs looked in, at most SCAN_RUNS


async def newest(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    step_id: uuid.UUID,
    *,
    iteration_key: str | None,
    at: Cutoff,
) -> Search:
    root = aliased(Run)
    candidates = (  # ended ones only, before the limit: a run still going never takes a place
        select(Run.id, Run.kind, Run.mode, Run.workflow_version_id, Run.ended_at)
        .join(root, (root.id == Run.root_run_id) & (root.tenant_id == Run.tenant_id))
        .where(Run.tenant_id == tenant_id, Run.workflow_id == workflow_id)
        .where(Run.status != "running", Run.ended_at.is_not(None), kept(root.ended_at, at))
        .order_by(Run.ended_at.desc(), Run.id.desc())
        .limit(SCAN_RUNS)
        .cte("candidates")
    )
    # "l:3/m:10" → {3,10}: the first iteration is the lowest index, by number (`l:2` before `l:10`).
    number = cast(
        func.string_to_array(func.regexp_replace(RunStep.iteration_key, "[a-z][a-z0-9_]*:", "", "g"), "/"),
        ARRAY(Integer),
    )
    picked = (
        select(RunStep.iteration_key, RunStep.attempt, RunStep.ended_at, RunStep.output_preview)
        .where(
            RunStep.run_id == candidates.c.id,
            RunStep.tenant_id == tenant_id,
            RunStep.step_id == step_id,
            RunStep.status == "succeeded",
            *([RunStep.iteration_key == iteration_key] if iteration_key is not None else []),
        )
        .order_by(number, RunStep.attempt.desc())
        .limit(1)
        .lateral("picked")
    )
    best = (
        select(
            candidates.c.id,
            candidates.c.kind,
            candidates.c.mode,
            candidates.c.workflow_version_id,
            picked.c.iteration_key,
            picked.c.attempt,
            picked.c.ended_at,
            picked.c.output_preview,
        )
        .select_from(candidates)
        .join(picked, true())
        # the newest captured: the row's end first, then its run's (B7's "newest succeeded row")
        .order_by(picked.c.ended_at.desc().nulls_last(), candidates.c.ended_at.desc(), candidates.c.id.desc())
        .limit(1)
        .subquery("best")
    )
    # One statement, so one snapshot: the count describes exactly the runs the answer was chosen among.
    searched = select(func.count()).select_from(candidates).scalar_subquery()
    one = select(true()).subquery("one")  # a single row, so the count comes back when no sample does
    row = (await s.execute(select(searched.label("searched"), best).select_from(one).outerjoin(best, true()))).one()
    found = row if row.id is not None else None
    if found is None:
        return Search(None, row.searched)
    version = (
        await s.execute(
            select(WorkflowVersion.number, WorkflowVersion.graph, WorkflowVersion.connection_ids).where(
                WorkflowVersion.id == found.workflow_version_id, WorkflowVersion.tenant_id == tenant_id
            )
        )
    ).one()
    nodes = version.graph.get("nodes", []) if isinstance(version.graph, dict) else []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == str(step_id)), None)
    used = await s.execute(
        select(
            RunStepConnection.connection_id, RunStepConnection.type, RunStepConnection.name,
            RunStepConnection.revision, RunStepConnection.context, Connection.name.label("now_name"),
            Connection.revision.label("now_revision"),
        )
        .outerjoin(
            Connection,
            (Connection.id == RunStepConnection.connection_id) & (Connection.tenant_id == RunStepConnection.tenant_id),
        )
        .where(
            RunStepConnection.run_id == found.id, RunStepConnection.step_id == step_id,
            RunStepConnection.iteration_key == found.iteration_key, RunStepConnection.attempt == found.attempt,
        )
        .order_by(RunStepConnection.connection_id, RunStepConnection.revision)
    )  # fmt: skip
    return Search(
        Sample(
            run_id=found.id,
            run_kind=found.kind,
            mode=found.mode,
            version_id=found.workflow_version_id,
            version_number=version.number,
            iteration_key=found.iteration_key,
            attempt=found.attempt,
            captured_at=found.ended_at,
            output=found.output_preview,
            node=node,
            connections=tuple(
                UsedConnection(
                    r.connection_id,
                    r.type,
                    r.now_name if r.now_name is not None else r.name,
                    r.revision,
                    r.now_revision,
                    dict(r.context),
                )  # fmt: skip
                for r in used
            ),
            names_connection=await _names_connection(s, node, set(version.connection_ids or ())),
        ),
        row.searched,
    )


async def _names_connection(s: AsyncSession, node: Mapping[str, Any] | None, recorded: set[uuid.UUID]) -> bool:
    """Whether the step names one of its version's connections in a field its type marks for one: the worker's own
    rule (`DbConnections.named_by`), never a value that merely looks like a connection's id."""
    ref = node.get("type") if node is not None else None
    written = node.get("config") if node is not None else None
    if not isinstance(ref, str) or not isinstance(written, dict):
        return False
    for row in await registry.load_node_types(s, {ref}):
        props = row.manifest.get("config_schema", {}).get("properties", {})
        fields = [name for name, prop in props.items() if isinstance(prop, dict) and prop.get(CONNECTION)]
        if any(as_uuid(written.get(f)) in recorded for f in fields):
            return True
    return False
