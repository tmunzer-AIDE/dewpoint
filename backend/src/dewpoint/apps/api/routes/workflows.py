# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import workflow_ops, workflow_summary
from dewpoint.apps.api.deps import get_keyring
from dewpoint.apps.api.responses import (
    ActivatedOut,
    DraftSavedOut,
    OptionsOut,
    PublishedOut,
    ValidationOut,
    VersionDetailOut,
    VersionOut,
    WorkflowDetailOut,
    WorkflowDocument,
    WorkflowOut,
    WorkflowUpdatedOut,
)
from dewpoint.apps.api.routes.node_types import ask_and_wait, options_reply, still_current
from dewpoint.core.authz.permissions import P
from dewpoint.core.config import Settings
from dewpoint.core.connections.declared import declared_types
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
from dewpoint.core.models.connections import Connection
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins import calls, registry
from dewpoint.core.workflows import portable, service
from dewpoint.engine.graph.model import GraphFormatError, parse_graph
from dewpoint.engine.graph.validate import PICKER

router = APIRouter(prefix="/api/v1", tags=["workflows"])
EMPTY_DRAFT: dict[str, Any] = {"graph_format": 1, "nodes": [], "edges": []}


class WorkflowCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    draft: dict[str, Any] | None = None


class WorkflowPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None


class ActivateIn(BaseModel):
    version_id: uuid.UUID


class PublishIn(BaseModel):
    """What the editor showed when it asked to publish (4b ruling 17). Extra keys are refused: a misspelt expectation
    must never be dropped silently, publishing what nobody confirmed."""

    model_config = ConfigDict(extra="forbid")
    expected_latest_version: int | None = Field(default=None, ge=0, strict=True)  # 0: no version yet


def _revision(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(428, detail={"error": "revision_required"})
    try:
        return int(if_match.strip().strip('"'))
    except ValueError:
        raise HTTPException(400, detail={"error": "bad_revision"}) from None


def _check_format(draft: Any) -> None:
    try:
        parse_graph(draft)
    except GraphFormatError as e:
        raise HTTPException(
            422, detail={"error": "invalid", "diagnostics": [d.to_json() for d in e.diagnostics]}
        ) from None


async def _get(db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, *, for_update: bool = False) -> Workflow:
    wf = await service.get_workflow(db, ctx.tenant_id, workflow_id, for_update=for_update)
    if wf is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return wf


def _last(run: workflow_summary.LastRun | None) -> dict[str, str] | None:
    return None if run is None else {"status": run.status, "at": run.at.isoformat()}


async def _summaries(db: AsyncSession, tenant_id: uuid.UUID, wfs: list[Workflow]) -> list[dict[str, object]]:
    """Each workflow's row (B3), in a fixed number of reads whatever their number: the active versions, the lifecycle
    states of every entry they use, the last runs and the 24-hour counts, each read once for all."""
    ids = [wf.id for wf in wfs]
    actives = await service.active_versions(db, tenant_id, ids)
    blocked = await service.blocked_by_many(db, actives.values())
    stats = await workflow_summary.run_stats(db, tenant_id, ids)
    hashes = await workflow_summary.HASHES.of([(wf.id, wf.draft_revision, wf.draft) for wf in wfs])
    out: list[dict[str, object]] = []
    for wf in wfs:
        active = actives.get(wf.id)
        stops = blocked[active.id] if active else []
        runs = stats[wf.id]
        out.append(
            {
                "id": str(wf.id),
                "name": wf.name,
                "enabled": wf.enabled,
                "draft_revision": wf.draft_revision,
                "active_version_id": str(active.id) if active else None,
                "active_version_number": active.number if active else None,
                "executable": (not stops) if active else None,
                "blocked_by": stops,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "unpublished_changes": active is None or hashes[wf.id] != active.graph_hash,
                "draft_graph_hash": hashes[wf.id],
                "last_run": _last(runs.last_live),
                "last_simulation": _last(runs.last_simulated),
                "runs_24h": {"live": runs.live_24h, "simulate": runs.simulated_24h},
                "needs_attention": workflow_summary.attention(runs, published=active is not None, blocked=stops),
            }
        )
    return out


async def _summary(db: AsyncSession, wf: Workflow) -> dict[str, object]:
    """One workflow just read, created or changed: its server-set columns (`updated_at`) are read back first."""
    await db.refresh(wf)
    return (await _summaries(db, wf.tenant_id, [wf]))[0]


def _version_out(v: WorkflowVersion, active_id: uuid.UUID | None, blocked: list[str]) -> dict[str, object]:
    return {
        "id": str(v.id),
        "number": v.number,
        "published_at": v.published_at.isoformat(),
        "published_by": str(v.published_by) if v.published_by else None,
        "graph_hash": v.graph_hash,
        "version_hash": v.version_hash,
        "cel_profile": v.cel_profile,
        "engine_abi": v.engine_abi,
        "node_refs": v.node_refs,
        "active": v.id == active_id,
        "executable": not blocked,
        "blocked_by": blocked,
    }


@router.get("/t/{tenant_id}/workflows", response_model=list[WorkflowOut])
async def list_workflows(
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, object]]:
    return await _summaries(db, ctx.tenant_id, await service.list_workflows(db, ctx.tenant_id))


@router.post("/t/{tenant_id}/workflows", status_code=201, response_model=WorkflowDetailOut)
async def create(
    body: WorkflowCreateIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    draft = body.draft if body.draft is not None else EMPTY_DRAFT
    _check_format(draft)
    try:
        wf = await service.create_workflow(db, ctx, name=body.name, draft=draft)
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "draft": wf.draft}


@router.get("/t/{tenant_id}/workflows/{workflow_id}", response_model=WorkflowDetailOut)
async def get_one(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    return {**await _summary(db, wf), "draft": wf.draft}


@router.put("/t/{tenant_id}/workflows/{workflow_id}/draft", response_model=DraftSavedOut)
async def put_draft(
    workflow_id: uuid.UUID,
    draft: dict[str, Any] = Body(...),
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    expected = _revision(if_match)
    _check_format(draft)
    wf = await _get(db, ctx, workflow_id)
    try:
        revision = await service.save_draft(db, wf, expected_revision=expected, draft=draft)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    active = await service.locked_active_version(db, wf.id)  # never `wf.active_version_id`: it may predate the swap
    saved = await workflow_summary.hash_now(draft)
    return {
        "draft_revision": revision,
        "unpublished_changes": active is None or saved != active.graph_hash,
        "graph_hash": saved,
        "active_version_id": str(active.id) if active else None,
        "active_version_number": active.number if active else None,
    }


@router.patch("/t/{tenant_id}/workflows/{workflow_id}", response_model=WorkflowUpdatedOut)
async def patch(
    workflow_id: uuid.UUID,
    body: WorkflowPatchIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        warnings = await workflow_ops.update(db, ctx, wf, name=body.name, enabled=body.enabled)
    except workflow_ops.NotActivatableError as e:
        diagnostics = [d.to_json() for d in e.errors]
        raise HTTPException(422, detail={"error": "not_enableable", "diagnostics": diagnostics}) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "warnings": [w.to_json() for w in warnings]}


@router.post("/t/{tenant_id}/workflows/{workflow_id}/validate", response_model=ValidationOut)
async def validate_draft(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    checked = await workflow_ops.check_draft(db, ctx.tenant_id, wf.draft, settings)
    result = checked.result
    expressions = result.expressions if result is not None else ()
    return {
        "draft_revision": wf.draft_revision,
        "valid": not any(d.severity == "error" for d in checked.diagnostics),
        "diagnostics": [d.to_json() for d in checked.diagnostics],
        # How each CEL value runs, for the editor (spec §5.10): "local" runs inline, "activity" as a separate step.
        "expressions": [{"node": r.node, "field": r.field, "mode": r.mode, "reason": r.reason} for r in expressions],
        # The steps that may not run on every path: the canvas's "conditional" badge (ledger ruling 70).
        "conditional_steps": list(result.conditional_steps) if result is not None else [],
        # Which values read sensitive data, and what each declassified site reveals (engine 2b spec §4.1, §4.3).
        "taint": {
            "sites": [{"node": n, "field": f} for n, f in (result.tainted_sites if result is not None else ())],
            "declassified": [
                {"node": n, "field": f, "reveals": r} for n, f, r in (result.declassified if result is not None else ())
            ],
        },
    }


@router.post("/t/{tenant_id}/workflows/{workflow_id}/publish", status_code=201, response_model=PublishedOut)
async def publish(
    workflow_id: uuid.UUID,
    body: PublishIn | None = None,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    expected = _revision(if_match)
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        out = await workflow_ops.publish(
            db,
            ctx,
            wf,
            expected_revision=expected,
            settings=settings,
            expected_latest_version=body.expected_latest_version if body else None,
        )
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    except service.VersionChangedError as e:
        raise HTTPException(409, detail={"error": "version_changed", "latest_version": e.latest}) from None
    if out.version is None:
        diagnostics = [d.to_json() for d in [*out.errors, *out.warnings]]
        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics})
    return {
        "version_id": str(out.version.id),
        "number": out.version.number,
        "warnings": [d.to_json() for d in out.warnings],
    }


@router.get("/t/{tenant_id}/workflows/{workflow_id}/versions", response_model=list[VersionOut])
async def versions(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    wf = await _get(db, ctx, workflow_id)
    return [
        _version_out(v, wf.active_version_id, await service.blocked_by(db, v))
        for v in await service.list_versions(db, wf.id)
    ]


@router.get("/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", response_model=VersionDetailOut)
async def version(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    v = await service.get_version(db, wf.id, version_id)
    if v is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        **_version_out(v, wf.active_version_id, await service.blocked_by(db, v)),
        "graph": v.graph,
        "expressions": [
            {"node": e.get("node"), "field": e["field"], "mode": e["mode"], "reason": e.get("reason")}
            for e in v.expressions
        ],
    }


@router.post("/t/{tenant_id}/workflows/{workflow_id}/activate", response_model=ActivatedOut)
async def activate(
    workflow_id: uuid.UUID,
    body: ActivateIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id, for_update=True)
    version = await service.get_version(db, wf.id, body.version_id)
    if version is None:
        raise HTTPException(404, detail={"error": "not_found"})
    try:
        warnings = await workflow_ops.activate(db, ctx, wf, version)
    except workflow_ops.NotActivatableError as e:
        diagnostics = [d.to_json() for d in e.errors]
        raise HTTPException(422, detail={"error": "not_activatable", "diagnostics": diagnostics}) from None
    return {"active_version_id": str(version.id), "number": version.number, "warnings": [w.to_json() for w in warnings]}


class WorkflowImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelt `bind` must never import with every binding left open
    name: str = Field(min_length=1, max_length=100)
    document: WorkflowDocument
    bind: dict[str, uuid.UUID] = Field(default_factory=dict)  # binding id -> one of this tenant's; absent: unbound


def _bad_binding(binding: str, reason: str) -> HTTPException:
    return HTTPException(422, detail={"error": "bad_binding", "binding": binding, "reason": reason})


async def _config_schemas(db: AsyncSession, graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The config schema of each step type the graph names that this server knows, in any state: a retired type's
    schema still says where its ids are. Called on a graph whose format is checked (each type a valid ref)."""
    refs = {n["type"] for n in graph.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("type"), str)}
    return {row.ref: row.manifest.get("config_schema") or {} for row in await registry.load_node_types(db, refs)}


async def _labels(
    db: AsyncSession, tenant_id: uuid.UUID, found: list[tuple[portable.Site, str]]
) -> dict[tuple[str, str], str]:
    """Each (kind, canonical id) the draft holds, to its name in this tenant; an id it doesn't name gets none."""
    wanted: dict[str, set[uuid.UUID]] = {"connection": set(), "workflow": set()}
    for site, value in found:
        wanted[site.kind].add(uuid.UUID(value))
    labels: dict[tuple[str, str], str] = {}
    for model, kind in ((Connection, "connection"), (Workflow, "workflow")):
        if wanted[kind]:
            ids = sorted(wanted[kind], key=str)
            rows = await db.execute(select(model.id, model.name).where(model.tenant_id == tenant_id, model.id.in_(ids)))
            labels.update({(kind, str(row.id)): row.name for row in rows})
    return labels


def _not_portable(e: portable.NotPortableError) -> HTTPException:
    return HTTPException(422, detail={"error": "not_portable", "problems": [p.to_json() for p in e.problems]})


@router.get("/t/{tenant_id}/workflows/{workflow_id}/export", response_model=WorkflowDocument)
async def export(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    """The saved draft as a file, every id of this tenant's replaced by a typed placeholder (B12). Refused, never
    approximated, when that can't be done for certain (4b ruling 18), or when the draft holds a value written into a
    field marked sensitive, which the file would carry (ledger M25): every reason at once, by the validator's rule."""
    wf = await _get(db, ctx, workflow_id)
    schemas = await _config_schemas(db, wf.draft)
    problems: list[portable.Problem] = []
    found: list[tuple[portable.Site, str]] = []
    try:
        found = portable.held(wf.draft, schemas)
    except portable.NotPortableError as e:
        problems.extend(e.problems)
    checked = await workflow_ops.check_draft(db, ctx.tenant_id, wf.draft, settings)
    problems.extend(portable.sensitive_problems(checked.diagnostics))
    if problems:
        raise _not_portable(portable.NotPortableError(problems))
    labels = await _labels(db, ctx.tenant_id, found)
    return portable.export_document(wf.name, wf.draft, schemas, labels)


@router.post("/t/{tenant_id}/workflows/import", status_code=201, response_model=WorkflowDetailOut)
async def import_workflow(
    body: WorkflowImportIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A new workflow from a file (B12), checked whole before anything is written (4b ruling 18): the graph's format;
    each step's type and each binding's sites against this server's schemas, with no id embedded where a binding goes;
    then each chosen id against this tenant's own connections (of the binding's type) and workflows."""
    graph = body.document.graph
    _check_format(graph)
    schemas = await _config_schemas(db, graph)
    bindings = [b.model_dump() for b in body.document.bindings]
    problems = portable.check_document(graph, bindings, schemas)
    if problems:
        raise HTTPException(422, detail={"error": "bad_document", "problems": [p.to_json() for p in problems]})
    by_id = {b.id: b for b in body.document.bindings}
    for key, chosen in body.bind.items():
        binding = by_id.get(key)
        if binding is None:
            raise _bad_binding(key, "unexpected")
        if binding.kind == "connection":
            found = (
                await db.execute(
                    select(Connection.type).where(Connection.tenant_id == ctx.tenant_id, Connection.id == chosen)
                )
            ).scalar_one_or_none()
            if found is None:
                raise _bad_binding(key, "unknown")
            if found != binding.type:
                raise _bad_binding(key, "wrong_type")
        elif (
            await db.execute(select(Workflow.id).where(Workflow.tenant_id == ctx.tenant_id, Workflow.id == chosen))
        ).scalar_one_or_none() is None:
            raise _bad_binding(key, "unknown")
    draft = portable.apply(graph, bindings, {key: str(value) for key, value in body.bind.items()}, schemas)
    _check_format(draft)
    try:
        wf = await service.create_workflow(db, ctx, name=body.name, draft=draft, source="import")
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "draft": wf.draft}


class InputOptionsIn(BaseModel):
    field: str = Field(min_length=1, max_length=200)
    query: str = Field(default="", max_length=200)


@router.post("/t/{tenant_id}/workflows/{workflow_id}/input-options", response_model=OptionsOut)
async def input_options(
    workflow_id: uuid.UUID,
    body: InputOptionsIn,
    request: Request,
    ctx: TenantContext = Depends(require(P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, Any]:
    """A start form's choices for one of its pickers (plugins-3 D19): the picker's node's `options()` on a worker,
    through the connection the active version's publisher wrote, which anyone who may start the workflow may list."""
    wf = await _get(db, ctx, workflow_id)
    version = await service.get_version(db, wf.id, wf.active_version_id) if wf.active_version_id else None
    if version is None:
        raise HTTPException(404, detail={"error": "not_published"})
    if not wf.enabled:  # no wider than a run (the 3a-2 review's finding 5): a disabled workflow can't be started
        raise HTTPException(409, detail={"error": "workflow_disabled"})
    props = version.input_schema.get("properties")
    prop = props.get(body.field) if isinstance(props, dict) else None
    picker = prop.get(PICKER) if isinstance(prop, dict) else None
    if not isinstance(picker, dict) or not all(isinstance(picker.get(k), str) for k in ("node", "field", "connection")):
        raise HTTPException(422, detail={"error": "not_a_picker"})
    rows = await registry.load_node_types(db, [picker["node"]])
    row = next((r for r in rows if r.state != "retired"), None)
    if row is None or picker["field"] not in row.manifest.get("options", []):
        raise HTTPException(404, detail={"error": "unknown_node_type"})
    try:
        connection_id = uuid.UUID(picker["connection"])
    except ValueError:
        raise HTTPException(422, detail={"error": "not_a_picker"}) from None
    conn = (
        await db.execute(
            select(Connection).where(Connection.id == connection_id, Connection.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    # Only a connection publish checked and recorded: a version published before pickers were checked may name any.
    recorded = connection_id in (version.connection_ids or [])
    kind = (await declared_types(db)).get(conn.type) if conn is not None else None
    if conn is None or kind is None or not recorded or conn.type not in row.manifest.get("credentials", []):
        raise HTTPException(422, detail={"error": "connection_unavailable"})
    revision, type_hash = conn.revision, kind.hash

    async def ask(s: AsyncSession) -> uuid.UUID:
        return await calls.ask_options(
            s, ctx.tenant_id, node_ref=row.ref, field=picker["field"], connection_id=connection_id, revision=revision,
            query=body.query, type_hash=type_hash,
        )  # fmt: skip

    reply = options_reply(await ask_and_wait(request, db, keyring, ctx.tenant_id, ask))
    await still_current(request, ctx.tenant_id, connection_id, revision)
    return reply
