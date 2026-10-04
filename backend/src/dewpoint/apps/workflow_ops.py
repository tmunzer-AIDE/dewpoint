# SPDX-License-Identifier: Apache-2.0
"""Validate, publish and activate workflows: wires core storage to the engine validator (spec §4.4–4.5)."""

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
from dewpoint.core.config import Settings
from dewpoint.core.http import TenantContext
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins import lifecycle, registry
from dewpoint.core.workflows import service
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Graph, GraphFormatError, graph_hash, graph_json, parse_graph, version_hash
from dewpoint.engine.graph.validate import (
    MAX_SUBFLOW_DEPTH,
    SubflowInfo,
    ValidationContext,
    ValidationResult,
    referenced_workflows,
    validate,
)
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest
from dewpoint.engine.runtime.bounds import BoundError, pinned
from dewpoint.engine.runtime.program import compile_program


async def _lifecycle_locked() -> None:
    """Hook that runs right after the lifecycle locks are held. A no-op; the race tests pause here."""


def declares_csv(graph: Mapping[str, Any]) -> bool:
    """Whether a version's graph document declares a CSV (engine 2b spec §8.1)."""
    return bool((graph.get("settings") or {}).get("csv"))


@dataclass(frozen=True)
class Checked:
    graph: Graph | None
    diagnostics: list[Diagnostic]
    pins: dict[uuid.UUID, WorkflowVersion]  # pinned workflow id -> its active version
    result: ValidationResult | None


async def check_draft(s: AsyncSession, tenant_id: uuid.UUID, draft: Any, settings: Settings) -> Checked:
    try:
        graph = parse_graph(draft)
    except GraphFormatError as e:
        return Checked(None, list(e.diagnostics), {}, None)
    rows = await registry.load_node_types(s, {n.type for n in graph.nodes})
    catalog = Catalog(spec_from_manifest(r.manifest, r.state) for r in rows)
    pins = await service.active_versions(s, tenant_id, referenced_workflows(graph))
    ctx = ValidationContext(
        catalog=catalog,
        subflows={
            wid: SubflowInfo(
                wid, v.id, v.input_schema, v.output_schema, v.output_taint, declares_csv=declares_csv(v.graph)
            )
            for wid, v in pins.items()
        },
        max_run_duration=timedelta(days=settings.max_run_duration_days),
    )
    result = await asyncio.to_thread(validate, graph, ctx)  # CPU-bound: keep the event loop serving others
    return Checked(graph, list(result.diagnostics), pins, result)


@dataclass(frozen=True)
class Published:
    version: WorkflowVersion | None
    errors: list[Diagnostic]
    warnings: list[Diagnostic]


class NotActivatableError(Exception):
    def __init__(self, errors: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.message for d in errors))
        self.errors = errors


def _depth(pins: Mapping[uuid.UUID, WorkflowVersion]) -> int:
    return 1 + max(v.closure_depth for v in pins.values()) if pins else 0


def _pin_errors(workflow_id: uuid.UUID, pins: Mapping[uuid.UUID, WorkflowVersion]) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    if any(wid == workflow_id or workflow_id in v.closure_workflow_ids for wid, v in pins.items()):
        out.append(
            Diagnostic(
                code="subflow.cycle",
                message="This workflow would end up running itself.",
                fix="Remove the step that runs it, directly or through another workflow.",
            )
        )
    depth = _depth(pins)
    if depth > MAX_SUBFLOW_DEPTH:
        out.append(
            Diagnostic(
                code="subflow.too_deep",
                message=f"Sub-flows can be nested at most {MAX_SUBFLOW_DEPTH} deep; this would be {depth}.",
            )
        )
    return out


def _lifecycle_errors(current: Mapping[lifecycle.Entry, str], *, refuse_deprecated: bool) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for entry, state in sorted(current.items()):
        if state in ("retired", "missing"):
            out.append(
                Diagnostic(code="lifecycle.retired", message=f"{entry} has been retired.", fix="Replace what uses it.")
            )
        elif state == "deprecated" and refuse_deprecated:
            out.append(
                Diagnostic(
                    code="lifecycle.deprecated",
                    message=f"{entry} is deprecated; new versions can't use it.",
                    fix="Migrate to its newer version.",
                )
            )
    return out


def abi_reasons(version_id: uuid.UUID, stale: list[tuple[uuid.UUID, int]], current: int) -> list[str]:
    """Why `version_id` can't start runs on the current build, of engine ABI `current`: it, or a version it runs, was
    published for another. A version runs only on a build of its ABI (spec §7): an older one is published again with
    the current build, and a newer one waits for its own build to be made current."""

    def remedy(abi: int, what: str) -> str:
        if abi > current:
            return f"make a build of ABI {abi} current first"
        return f"publish {what} again with a build of ABI {current}"

    return [
        f"This version was published for engine ABI {abi}, and the current build runs ABI {current}: "
        f"{remedy(abi, 'the workflow')}."
        if other == version_id
        else f"Version {other}, a sub-flow or failure handler it runs, was published for engine ABI {abi}, and the "
        f"current build runs ABI {current}: {remedy(abi, 'that workflow')}, then this one."
        for other, abi in stale
    ]


async def _pin_abi_errors(s: AsyncSession, pins: list[WorkflowVersion]) -> list[Diagnostic]:
    """Every version a new one would run must be of the ABI it's published for, this build's (spec §7): so a parent is
    published again only after its sub-flows and failure handler."""
    stale = await service.other_abi(s, [i for v in pins for i in v.closure_version_ids], ENGINE_ABI)
    return [
        Diagnostic(
            code="subflow.engine_abi",
            message=f"Version {other}, a sub-flow or failure handler this workflow would run, was published for engine "
            f"ABI {abi}, and this build publishes ABI {ENGINE_ABI}.",
            fix="Publish that workflow again first.",
        )
        for other, abi in stale
    ]


_DECLASSIFY_FORBIDDEN = Diagnostic(
    code="declassify.forbidden",
    field="/settings/declassify",
    message="Publishing a workflow that declassifies sensitive data needs the workflow.declassify permission "
    "(tenant admins and owners).",
)


async def publish(
    s: AsyncSession, ctx: TenantContext, wf: Workflow, *, expected_revision: int, settings: Settings
) -> Published:
    """Validate the draft and insert it as the new active version. `wf` must be locked FOR UPDATE."""
    if wf.draft_revision != expected_revision:
        raise service.DraftConflictError(wf.draft_revision)
    checked = await check_draft(s, ctx.tenant_id, wf.draft, settings)
    errors = [d for d in checked.diagnostics if d.severity == "error"]
    warnings = [d for d in checked.diagnostics if d.severity == "warning"]
    if checked.graph is None or checked.result is None or errors:
        return Published(None, errors, warnings)
    if checked.graph.settings.declassify and P.WORKFLOW_DECLASSIFY not in ROLE_PERMISSIONS[ctx.role]:
        return Published(None, [_DECLASSIFY_FORBIDDEN], warnings)
    errors = _pin_errors(wf.id, checked.pins)
    if errors:
        return Published(None, errors, warnings)
    pins = list(checked.pins.values())
    errors = await _pin_abi_errors(s, pins)
    if errors:
        return Published(None, errors, warnings)
    closure_node_refs = sorted({*checked.result.node_refs, *(r for v in pins for r in v.closure_node_refs)})
    closure_cel_profiles = sorted({CURRENT_CEL_PROFILE, *(p for v in pins for p in v.closure_cel_profiles)})
    entries = lifecycle.entries_for(closure_node_refs, closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    await _lifecycle_locked()
    errors = _lifecycle_errors(await lifecycle.states(s, entries), refuse_deprecated=True)
    if errors:
        return Published(None, errors, warnings)
    version_id = uuid.uuid4()
    graph_settings = checked.graph.settings
    authored = graph_hash(checked.graph)
    try:
        cap, depth = await _pinned(s, checked)
    except BoundError as e:  # engine 2b spec §5.3: the continued-input bound can't be established for it
        return Published(None, [Diagnostic(code="version.unbounded", message=str(e))], warnings)
    fh = checked.result.failure_handler_version_id
    version = await service.insert_version(
        s,
        ctx,
        wf,
        service.NewVersion(
            id=version_id,
            graph=graph_json(checked.graph),
            node_refs=list(checked.result.node_refs),
            engine_abi=ENGINE_ABI,
            cel_profile=CURRENT_CEL_PROFILE,
            subflow_version_ids=dict(checked.result.subflow_pins),
            failure_handler_version_id=checked.result.failure_handler_version_id,
            input_schema=dict(graph_settings.input_schema),
            output_schema=dict(checked.result.output_schema),
            vars_schema=dict(graph_settings.vars_schema),
            closure_version_ids=[version_id, *sorted({i for v in pins for i in v.closure_version_ids}, key=str)],
            closure_workflow_ids=[wf.id, *sorted({i for v in pins for i in v.closure_workflow_ids}, key=str)],
            closure_node_refs=closure_node_refs,
            closure_cel_profiles=closure_cel_profiles,
            closure_depth=_depth(checked.pins),
            expressions=[r.to_json() for r in checked.result.expressions],
            tainted_sites=[{"node": node, "field": fld} for node, fld in checked.result.tainted_sites],
            output_taint=dict(checked.result.output_taint),
            open_scopes_cap=cap,
            loop_depth=depth,
            declassified=[
                {"node": node, "field": fld, "reveals": reveals} for node, fld, reveals in checked.result.declassified
            ],
            graph_hash=authored,
            version_hash=version_hash(
                graph_hash=authored,
                subflow_pins=checked.result.subflow_pins,
                failure_handler_version_id=str(fh) if fh else None,
                cel_profile=CURRENT_CEL_PROFILE,
                engine_abi=ENGINE_ABI,
            ),
        ),
    )
    return Published(version, [], warnings)


async def _pinned(s: AsyncSession, checked: Checked) -> tuple[int, int]:
    """The version's open-iteration cap and loop depth (engine 2b spec §5.3): computed from its structure, pinned in
    it, so a later change of a constant can't change how a pinned run schedules."""
    if checked.graph is None or checked.result is None:
        raise ValueError("a version is published only once checked")
    rows = await registry.load_node_types(s, checked.result.node_refs)
    program = compile_program(
        graph_json(checked.graph),
        {r.ref: r.manifest for r in rows},
        [r.to_json() for r in checked.result.expressions],
        CURRENT_CEL_PROFILE,
    )
    return await asyncio.to_thread(pinned, program)  # CPU-bound: keep the event loop serving others


async def _check_runnable(s: AsyncSession, version: WorkflowVersion) -> list[Diagnostic]:
    """Lock the version's closure (shared) and re-read its lifecycle states. Raises NotActivatableError when something
    in it is retired or missing; returns warnings for deprecated entries. Used by every operation that makes a version
    an active reference again: activate, and enabling a workflow."""
    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    await _lifecycle_locked()
    current = await lifecycle.states(s, entries)
    errors = _lifecycle_errors(current, refuse_deprecated=False)
    if errors:
        raise NotActivatableError(errors)
    return [
        Diagnostic(
            code="lifecycle.deprecated",
            severity="warning",
            message=f"{entry} is deprecated.",
            fix="Publish a new version that migrates it.",
        )
        for entry, state in sorted(current.items())
        if state == "deprecated"
    ]


async def activate(s: AsyncSession, ctx: TenantContext, wf: Workflow, version: WorkflowVersion) -> list[Diagnostic]:
    """Make an existing version active (rollback). Any executable version qualifies, superseded or not.
    `wf` must be locked FOR UPDATE. Returns warnings; raises NotActivatableError if the version can't run."""
    warnings = await _check_runnable(s, version)
    await service.set_active(s, ctx, wf, version)
    return warnings


async def update(
    s: AsyncSession, ctx: TenantContext, wf: Workflow, *, name: str | None, enabled: bool | None
) -> list[Diagnostic]:
    """Rename, enable or disable. Enabling makes the active version's closure an active reference again (spec §4.5),
    so it takes the lifecycle locks and re-checks executability exactly like activate(). `wf` must be locked
    FOR UPDATE. Returns warnings; raises NotActivatableError when the active version can't run."""
    warnings: list[Diagnostic] = []
    if enabled and not wf.enabled and wf.active_version_id is not None:
        version = await service.get_version(s, wf.id, wf.active_version_id)
        if version is not None:
            warnings = await _check_runnable(s, version)
    if enabled is not None and enabled != wf.enabled:  # its schedules pause or resume: the sync follows the generation
        await s.execute(
            text("update schedules set generation = generation + 1, updated_at = now() "
                 "where workflow_id = :w and deleted_at is null"), {"w": wf.id},
        )  # fmt: skip
    await service.update_workflow(s, ctx, wf, name=name, enabled=enabled)
    return warnings
