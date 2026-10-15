# SPDX-License-Identifier: Apache-2.0
"""Admission (engine 2b spec §7.2; revision 7): a run request frozen inside its caller's READ COMMITTED transaction,
which it never commits. The caller has authorized it (`run.start` for an interactive source; a durable source by its
binding or schedule) and commits it with whatever else it writes.

In §7.2's order:
1. the idempotency key is looked up first: an existing request is compared, with its own stored key version, and an
   exact retry returns it as it is now, whatever changed since (a rotation, the gate, the active version, a disable);
   another request under the key is a conflict;
2. a new key passes the mutable checks: the tenant is active (not erasing, nor erased); the gate, for an interactive
   source; the workflow's admission lock, enabled, its active version, the current build's ABI (as the dispatcher last
   recorded it: a missing or stale record fails closed), the closure executable under the lifecycle locks; the input
   schema;
3. it's digested with the tenant's active key version, its trigger claimed, the secret index seeded, its envelope
   stored and the request inserted, `ON CONFLICT DO NOTHING`, with one audit entry, all in one savepoint: a concurrent
   insert that won the key rolls this call back, claims and envelope included, and the winner is compared instead.

A durable source's refusal is kept as a `refused` request with its reason, never lost; an interactive one's is raised.
The request's id is its run's, once it starts: its claims and envelope are owned by it from the start.

A CSV start (2b-3a, §8.1) is a manual start or a re-run given a staged upload: its digest covers what was asked, so an
exact retry is recognized without the rows, and returned only to the upload's owner. A new key locks the upload and
checks it (its tenant, owner and workflow, not expired, not consumed: a consumed one sends the start back to its key,
which a concurrent start under it has taken), builds its rows against the frozen version's declaration, claims them
with the rest of the trigger, keeps the mapping, headers and skipped rows as the request's CSV record, and consumes the
upload, all in the same savepoint."""

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import csv_uploads, workflow_ops
from dewpoint.apps.csv_input import Built, CsvFileError, RowError, build_rows, mapping_problems, read_table
from dewpoint.apps.inputs import (
    INPUT_INVALID,
    NOT_FINITE,
    RESERVED_INPUT,
    TOO_DEEP,
    InputRefusedError,
    claim_input,
    holds_non_finite,
    nests_too_deep,
)
from dewpoint.apps.workflow_ops import abi_reasons
from dewpoint.core.audit import service as audit
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.models.requests import CurrentBuild, RunRequest
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.models.uploads import CsvUpload
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
from dewpoint.core.plugins import lifecycle
from dewpoint.core.requests import digest as digests
from dewpoint.core.tenancy import lifecycle as tenant_lifecycle
from dewpoint.core.workflows import drafts
from dewpoint.core.workflows.service import DraftConflictError, lock_for_admission, other_abi
from dewpoint.engine.graph import seeds
from dewpoint.engine.graph.csv import RESERVED, trigger_schema
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.runtime.activities import LIVE, SIMULATE

INTERACTIVE = ("manual", "rerun", "dev")  # refused while the gate is off; a refusal is raised
DURABLE = ("schedule", "webhook")  # recorded while the gate is off (§2.5); a refusal is a `refused` request
# A current-build record older than this is no record (the owner's ruling). Aged by the statement's time, never the
# transaction's start: a caller that admits several requests in one long transaction sees it go stale.
BUILD_STALE = timedelta(minutes=2)

TENANT_ERASING = "tenant_erasing"
PRODUCTION_RUNS_DISABLED = "production_runs_disabled"
ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
WORKFLOW_DISABLED = "workflow_disabled"
NOT_ACTIVE = "not_active"
NO_CURRENT_BUILD = "no_current_build"
VERSION_UNUSABLE = "version_unusable"
NODE_TYPE_RETIRED = "node_type_retired"
CEL_PROFILE_RETIRED = "cel_profile_retired"
CSV_NOT_DECLARED = "csv_not_declared"
CSV_MAPPING_INVALID = "csv_mapping_invalid"
UPLOAD_NOT_FOUND = "upload_not_found"
UPLOAD_EXPIRED = "upload_expired"
UPLOAD_CONSUMED = "upload_consumed"
TARGET_INVALID = "target_invalid"
CSV_NOT_SIMULATED = "csv_not_simulated"
CSV_NOT_SIMULATED_MESSAGE = (
    "This draft's input takes a CSV file, which a simulation can't be given yet: simulate one of its steps instead."
)
# A seeds refusal's code (S2; the simulation design §5.2): the first of these among its problems, every problem listed.
SEED_CODES = (seeds.SEED_ALIAS, seeds.SEED_UNKNOWN, seeds.SEED_MISSING, seeds.SEED_INVALID)
_LISTED = 5  # a refusal lists this many of the CSV's problems

GATE_OFF = (
    "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts "
    "(engine 2b spec §2)."
)
NO_BUILD = (
    "No current build has been recorded lately, so this run's engine ABI can't be checked: the dispatcher records "
    "it while it runs."
)


class AdmissionRefusedError(Exception):
    """An interactive request admission refused: its `reason` code (§9) and what to tell the caller."""

    def __init__(self, reason: str, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.reason, self.messages = reason, messages


class IdempotencyConflictError(Exception):
    """Another request under the same idempotency key (409 `idempotency_conflict`)."""


class WorkflowNotFoundError(LookupError):
    """No such workflow in the caller's tenant."""


class DraftInvalidError(Exception):
    """A draft simulation's draft that can't run (B8; the simulation design §6.3, step 4): what blocks it, with what it
    would report and the validator's warnings."""

    def __init__(self, blocking: list[Diagnostic], reported: list[Diagnostic], warnings: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.code for d in blocking))
        self.blocking, self.reported, self.warnings = blocking, reported, warnings


class SeedsRefusedError(Exception):
    """A step's seeds its contract doesn't take (S2; the simulation design §5.2): every problem, and the refusal's code,
    the first of `SEED_CODES` among them."""

    def __init__(self, problems: list[seeds.SeedProblem]) -> None:
        super().__init__("; ".join(f"{p.code} {p.pointer}" for p in problems))
        self.problems = problems
        self.reason = next(code for code in SEED_CODES if any(p.code == code for p in problems))


@dataclass(frozen=True)
class CsvStart:
    """A start's CSV: the staged upload, the mapping from declared column names to its headers, and whether rows that
    break a rule are skipped (recorded) rather than refusing the start."""

    upload_id: uuid.UUID
    mapping: dict[str, str]
    skip_invalid: bool = False

    def digested(self) -> dict[str, Any]:
        return {"upload_id": str(self.upload_id), "mapping": dict(self.mapping), "skip_invalid": self.skip_invalid}


@dataclass(frozen=True)
class Rerun:
    """A re-run's identity: the request (or, from before 2b-2, the run) it re-runs, and the new input (and CSV) it was
    given, if any. Its idempotency digest covers this in place of the input it admits, so an exact retry is recognized,
    and another request under the key refused, without rebuilding the old input, which retention may have removed."""

    of: uuid.UUID
    input: dict[str, Any] | None = None
    csv: CsvStart | None = None

    def digested(self) -> dict[str, Any]:
        digested: dict[str, Any] = {"rerun_of": str(self.of), "input": self.input}
        if self.csv is not None:  # only then: earlier re-runs' digests stay what they were
            digested["csv"] = self.csv.digested()
        return digested


@dataclass(frozen=True)
class Simulation:
    """A draft simulation's identity (B8; the simulation design §6.3): the draft revision it simulates, and for a step
    alone (S2) its target and seeds, given or absent by pointer. Its idempotency digest covers it beside the input, so
    the digests of the requests that aren't simulations keep their bytes."""

    revision: int
    target: uuid.UUID | None = None
    values: dict[str, Any] = field(default_factory=dict)
    absent: tuple[str, ...] = ()

    def digested(self) -> dict[str, Any]:
        digested: dict[str, Any] = {"draft_revision": self.revision}
        if self.target is not None:
            digested |= {"target": str(self.target), "values": self.values, "absent": sorted(self.absent)}
        return digested


@dataclass(frozen=True)
class Admitted:
    request: RunRequest
    new: bool  # False: an exact retry, the frozen request as it is now


class _Refused(Exception):
    def __init__(self, reason: str, messages: list[str], version_id: uuid.UUID | None = None) -> None:
        self.reason, self.messages, self.version_id = reason, messages, version_id


class _Consumed(Exception):
    """The upload was consumed: by a start under this key (an exact retry), or another (`upload_consumed`)."""


@dataclass(frozen=True)
class _Frozen:
    version_id: uuid.UUID
    envelope_id: uuid.UUID
    details: dict[str, object]  # the audit entry's, beyond the request's own


@dataclass(frozen=True)
class _DraftFrozen:
    snapshot_id: uuid.UUID
    envelope_id: uuid.UUID
    revision: int
    target: uuid.UUID | None
    checks: list[dict[str, Any]]  # what it reports, kept on the request
    details: dict[str, object]


async def _before_insert() -> None:
    """Runs between a new request's claims and its insert. A no-op; the race tests commit a competing request here."""


async def _after_upload_locked() -> None:
    """Runs once a CSV start holds its upload's row lock. A no-op; the race tests start a competing start here."""


async def admit_request(
    s: AsyncSession,
    keys: KeySource,
    *,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    source: str,
    actor_id: uuid.UUID | None,
    mode: str,
    idempotency_key: str,
    input: dict[str, Any],
    rerun: Rerun | None = None,
    csv: CsvStart | None = None,
    details: dict[str, object] | None = None,
) -> Admitted:
    """The request under `idempotency_key`: an exact retry's, or a new one, frozen. A re-run's digest covers its
    `rerun` identity in place of `input`, and a CSV start's its `csv` beside it. Raises IdempotencyConflictError,
    WorkflowNotFoundError, or, for an interactive source, AdmissionRefusedError."""
    if source not in INTERACTIVE + DURABLE or mode not in (LIVE, SIMULATE):
        raise ValueError(f"no such source or mode: {source}, {mode}")
    if csv is not None and source not in ("manual", "rerun"):
        raise ValueError(f"a {source} start takes no CSV")
    if source in INTERACTIVE and nests_too_deep(input):  # before its key's digest reads it (issue #88, the review's L2)
        raise AdmissionRefusedError(INPUT_INVALID, [TOO_DEEP])
    if source in INTERACTIVE and holds_non_finite(input):  # which its key's digest can't encode, nor its claims
        raise AdmissionRefusedError(INPUT_INVALID, [NOT_FINITE])
    await lifecycle.assert_read_committed(s)
    await tenant_scope(s, tenant_id)
    fields: dict[str, Any] = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": input}
    if rerun is not None:
        digested = {**fields, "input": rerun.digested()}
    elif csv is not None:
        digested = {**fields, "input": {"input": input, "csv": csv.digested()}}
    else:
        digested = fields
    owner = actor_id if csv is not None else None  # a CSV start's exact retry is its upload owner's only
    existing = await _by_key(s, idempotency_key)
    if existing is not None:
        return await _retry(keys, tenant_id, existing, digested, owner)
    request_id = uuid.uuid4()
    savepoint = await s.begin_nested()
    try:
        frozen = await _frozen(s, keys, tenant_id, request_id, fields, actor_id, rerun, csv)
    except _Consumed:
        await savepoint.rollback()
        existing = await _by_key(s, idempotency_key)  # its consumer has committed: under this key, an exact retry
        if existing is not None:
            return await _retry(keys, tenant_id, existing, digested, owner)
        raise AdmissionRefusedError(UPLOAD_CONSUMED, ["This upload has already started a run."]) from None
    except _Refused as refused:
        await savepoint.rollback()
        if source in INTERACTIVE:
            raise AdmissionRefusedError(refused.reason, refused.messages) from None
        return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, None, None, refused,
                             rerun, extra=details)  # fmt: skip
    await _before_insert()
    admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, frozen.version_id,
                             frozen.envelope_id, rerun=rerun, extra={**frozen.details, **(details or {})})  # fmt: skip
    if admitted.new:
        await savepoint.commit()
    else:
        await savepoint.rollback()  # another transaction won the key: this call's claims and envelope go with it
        return await _retry(keys, tenant_id, await _winner(s, idempotency_key), digested, owner)
    return admitted


async def admit_draft(
    s: AsyncSession,
    keys: KeySource,
    ctx: TenantContext,
    *,
    workflow_id: uuid.UUID,
    idempotency_key: str,
    input: dict[str, Any],
    simulation: Simulation,
    settings: Settings,
) -> Admitted:
    """A draft simulation's request under `idempotency_key` (B8; the simulation design §6.3): an exact retry's, as it
    is now, whatever the draft became; or a new one, `simulate` and `manual`, frozen on a snapshot of the revision it
    names. Raises IdempotencyConflictError, WorkflowNotFoundError, DraftConflictError (another revision),
    DraftInvalidError (what can't run), SeedsRefusedError, AdmissionRefusedError."""
    if nests_too_deep(input) or nests_too_deep(simulation.values):  # before its key's digest reads them
        raise AdmissionRefusedError(INPUT_INVALID, [TOO_DEEP])
    await lifecycle.assert_read_committed(s)
    await tenant_scope(s, ctx.tenant_id)
    fields: dict[str, Any] = {"source": "manual", "workflow_id": workflow_id, "mode": SIMULATE, "input": input}
    digested = {**fields, "draft": simulation.digested()}
    existing = await _by_key(s, idempotency_key)
    if existing is not None:
        return await _retry(keys, ctx.tenant_id, existing, digested)
    request_id = uuid.uuid4()
    savepoint = await s.begin_nested()
    try:
        frozen = await _draft_frozen(s, keys, ctx, request_id, fields, simulation, settings)
    except _Refused as refused:
        await savepoint.rollback()
        raise AdmissionRefusedError(refused.reason, refused.messages) from None
    await _before_insert()
    admitted = await _insert(s, keys, ctx.tenant_id, request_id, ctx.user.id, idempotency_key, digested, None,
                             frozen.envelope_id, extra=frozen.details, draft=frozen)  # fmt: skip
    if admitted.new:
        await savepoint.commit()
    else:
        await savepoint.rollback()  # another transaction won the key: this call's claims, envelope and snapshot go
        return await _retry(keys, ctx.tenant_id, await _winner(s, idempotency_key), digested)
    return admitted


async def record_refused(
    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, source: str, mode: str,
    idempotency_key: str, reason: str, messages: list[str], details: dict[str, object] | None = None,
) -> RunRequest:  # fmt: skip
    """A durable source's refusal decided before admission, a paused or deleted schedule's tick (§8.2): a `refused`
    request under its key, frozen like any, never lost; an exact retry finds it. Raises IdempotencyConflictError when
    the key holds another request."""
    if source not in DURABLE:
        raise ValueError(f"only a durable source's refusal is recorded: {source}")
    await tenant_scope(s, tenant_id)
    fields: dict[str, Any] = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": {}}
    existing = await _by_key(s, idempotency_key)
    if existing is not None:
        return (await _retry(keys, tenant_id, existing, fields)).request
    refused = _Refused(reason, messages)
    inserted = await _insert(s, keys, tenant_id, uuid.uuid4(), None, idempotency_key, fields, None, None, refused,
                             extra=details)  # fmt: skip
    return inserted.request


async def admitted_under(
    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, idempotency_key: str, source: str,
    workflow_id: uuid.UUID, mode: str, rerun: Rerun, actor_id: uuid.UUID | None = None,
) -> RunRequest | None:  # fmt: skip
    """The request an exact retry of this re-run finds under its key, before its input is rebuilt; None when the key
    is free. Raises IdempotencyConflictError for another request under the key, or, for a re-run with a new CSV, one
    another user admitted, or AdmissionRefusedError for a new input past the input limit, read before its digest
    (issue #88, the review's L2), or holding NaN or an infinity, which its digest can't encode."""
    if rerun.input is not None and nests_too_deep(rerun.input):
        raise AdmissionRefusedError(INPUT_INVALID, [TOO_DEEP])
    if rerun.input is not None and holds_non_finite(rerun.input):
        raise AdmissionRefusedError(INPUT_INVALID, [NOT_FINITE])
    await tenant_scope(s, tenant_id)
    existing = await _by_key(s, idempotency_key)
    if existing is None:
        return None
    fields = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": rerun.digested()}
    owner = actor_id if rerun.csv is not None else None
    return (await _retry(keys, tenant_id, existing, fields, owner)).request


async def _by_key(s: AsyncSession, idempotency_key: str) -> RunRequest | None:
    query = (
        select(RunRequest)
        .where(RunRequest.idempotency_key == idempotency_key)
        .execution_options(populate_existing=True)
    )
    return (await s.execute(query)).scalar_one_or_none()


async def _winner(s: AsyncSession, idempotency_key: str) -> RunRequest:
    """The request a concurrent transaction froze under the key, which this one's insert just ran into."""
    winner = await _by_key(s, idempotency_key)
    if winner is None:
        raise RuntimeError("An idempotency key taken by a request that isn't there.")
    return winner


async def _retry(
    keys: KeySource, tenant_id: uuid.UUID, existing: RunRequest, fields: dict[str, Any], owner: uuid.UUID | None = None
) -> Admitted:
    """`existing` as an exact retry finds it; IdempotencyConflictError for another request under the key, or for a
    CSV start another user made (`owner`, the caller, must be its actor, the upload's owner): no different answer
    tells it apart from any other conflict."""
    if not await digests.matches(keys, str(tenant_id), existing.digest, existing.digest_key_version, **fields):
        raise IdempotencyConflictError("Another request was made under this idempotency key.")
    if owner is not None and existing.actor_id != owner:
        raise IdempotencyConflictError("Another request was made under this idempotency key.")
    return Admitted(existing, new=False)


async def _frozen(
    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, request_id: uuid.UUID, fields: dict[str, Any],
    actor_id: uuid.UUID | None, rerun: Rerun | None, csv: CsvStart | None,
) -> _Frozen:  # fmt: skip
    """The mutable checks, then the trigger claimed and its envelope stored (a CSV start's rows built and its upload
    consumed first): the frozen version, the envelope and what the audit entry adds."""
    await _open(s, tenant_id, fields)
    workflow = await lock_for_admission(s, tenant_id, fields["workflow_id"])  # stands until the request is frozen
    if workflow is None:
        raise WorkflowNotFoundError(str(fields["workflow_id"]))
    if not workflow.enabled:
        raise _Refused(WORKFLOW_DISABLED, ["The workflow is disabled."])
    if workflow.active_version_id is None:
        raise _Refused(NOT_ACTIVE, ["The workflow has no active version."])
    version = await s.get(WorkflowVersion, workflow.active_version_id)
    if version is None:
        raise RuntimeError("A workflow's active version that isn't there.")
    build = await _current_build(s)
    if build is None:
        raise _Refused(NO_CURRENT_BUILD, [NO_BUILD], version.id)
    stale = await other_abi(s, version.closure_version_ids, build)  # versions never change: no lock needed
    if stale:
        raise _Refused(VERSION_UNUSABLE, abi_reasons(version.id, stale, build), version.id)
    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
    if blocked:
        reason = NODE_TYPE_RETIRED if any(e.kind == "node" for e in blocked) else CEL_PROFILE_RETIRED
        raise _Refused(reason, [f"{entry} has been retired." for entry in blocked], version.id)
    settings = version.graph.get("settings") or {}
    value: dict[str, Any] = fields["input"]
    retained = rerun is not None and rerun.input is None and csv is None  # a re-run's own input, rebuilt
    if not retained and any(name in value for name in RESERVED):  # only a CSV upload supplies them (§8.1)
        raise _Refused(INPUT_INVALID, [RESERVED_INPUT], version.id)
    built: _Built | None = None
    if csv is not None:
        if not settings.get("csv"):
            raise _Refused(CSV_NOT_DECLARED, ["This workflow takes no CSV."], version.id)
        built = await _rows(s, keys, tenant_id, fields["workflow_id"], actor_id, csv, settings["csv"], version.id)
        value = {**value, "rows": built.rows, "row_count": len(built.rows)}
    try:
        envelope = await claim_input(
            s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id, schema=trigger_schema(settings),
            value=value, off_loop=csv is not None or retained,  # the work a CSV slot bounds: a CSV's rows, perhaps
        )  # fmt: skip
    except InputRefusedError as e:
        raise _Refused(e.reason, e.reasons, version.id) from None
    envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
    if built is None or csv is None:
        return _Frozen(version.id, envelope_id, {})
    record = {
        "mapping": dict(csv.mapping),
        "headers": built.headers,
        "row_count": len(built.rows),
        "skipped": [{"row": row, "code": code} for row, code in built.skipped],  # every one, its first rule
        "errors": [asdict(e) for e in built.errors],  # the first ones, in detail
        "error_count": built.error_count,
    }
    await claims.write_csv_record(s, ClaimCipher(keys), tenant_id, request_id=request_id, record=record)
    await s.execute(
        update(CsvUpload)
        .where(CsvUpload.id == csv.upload_id)
        .values(staged=None, consumed_by=request_id, consumed_at=func.now())
    )
    return _Frozen(version.id, envelope_id, {"csv_digest": built.file_digest.hex(), "csv_rows": len(built.rows),
                                             "csv_skipped": len(built.skipped)})  # fmt: skip


async def _draft_frozen(
    s: AsyncSession, keys: KeySource, ctx: TenantContext, request_id: uuid.UUID, fields: dict[str, Any],
    simulation: Simulation, settings: Settings,
) -> _DraftFrozen:  # fmt: skip
    """§6.3's steps 2 to 7: the tenant and the gate; the workflow's admission lock (enabled or not, published or not:
    D-b1); the revision; the draft checked, blocking and reported; the current build of its ABI and its pins'; the
    input against the draft's trigger schema, or the step's seeds against its contract, claimed into the envelope; and
    the snapshot found or made, held against the sweep until the request is committed."""
    tenant_id = ctx.tenant_id
    await _open(s, tenant_id, fields)
    if await lock_for_admission(s, tenant_id, fields["workflow_id"]) is None:
        raise WorkflowNotFoundError(str(fields["workflow_id"]))
    found = select(Workflow).where(Workflow.id == fields["workflow_id"]).execution_options(populate_existing=True)
    wf = (await s.execute(found)).scalar_one()
    if wf.draft_revision != simulation.revision:
        raise DraftConflictError(wf.draft_revision)
    checked = await workflow_ops.check_draft(s, tenant_id, wf.draft, settings)
    sim = await workflow_ops.simulatable(s, ctx, wf, checked)
    if sim.new is None or checked.graph is None or checked.context is None:
        raise DraftInvalidError(sim.blocking, sim.reported, sim.warnings)
    build = await _current_build(s)
    if build is None:
        raise _Refused(NO_CURRENT_BUILD, [NO_BUILD])
    if sim.new.engine_abi != build:
        raise _Refused(VERSION_UNUSABLE, [
            f"This draft is simulated for engine ABI {sim.new.engine_abi}, this server's, and the current build runs "
            f"ABI {build}: simulate it again once they're the same build."
        ])  # fmt: skip
    stale = await other_abi(s, sim.new.closure_version_ids, build)  # its pins'
    if stale:
        raise _Refused(VERSION_UNUSABLE, abi_reasons(wf.id, stale, build))
    schema: dict[str, Any]
    value: dict[str, Any]
    if simulation.target is None:
        if workflow_ops.declares_csv(sim.new.graph):  # only an upload gives its rows, and none comes here (D-b7)
            raise _Refused(CSV_NOT_SIMULATED, [CSV_NOT_SIMULATED_MESSAGE])
        if any(name in fields["input"] for name in RESERVED):  # only a CSV upload supplies them: none here (D-b8)
            raise _Refused(INPUT_INVALID, [RESERVED_INPUT])
        schema, value = trigger_schema(sim.new.graph.get("settings") or {}), fields["input"]
    else:
        contract = await asyncio.to_thread(seeds.contract, checked.graph, checked.context, simulation.target)
        if contract.refused is not None:
            raise _Refused(TARGET_INVALID, [contract.refused])
        problems = seeds.check(contract, simulation.values, simulation.absent)
        if problems:
            raise SeedsRefusedError(problems)
        schema, value = _seeded(contract), {"values": dict(simulation.values), "absent": sorted(simulation.absent)}
    try:
        envelope = await claim_input(s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id,
                                     schema=schema, value=value, against_schema=simulation.target is None)  # fmt: skip
    except InputRefusedError as e:
        raise _Refused(e.reason, e.reasons) from None
    envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
    snapshot = await drafts.snapshot_for(s, wf, sim.new, revision=wf.draft_revision, created_by=ctx.user.id)
    details: dict[str, object] = {"draft_snapshot_id": str(snapshot.id), "draft_revision": wf.draft_revision,
                                  "graph_hash": snapshot.graph_hash}  # fmt: skip
    if simulation.target is not None:
        details["target_step_id"] = str(simulation.target)
    if snapshot.declassified:
        details["declassify"] = snapshot.declassified
    checks = [d.to_json() for d in sim.reported]
    return _DraftFrozen(snapshot.id, envelope_id, wf.draft_revision, simulation.target, checks, details)


def _seeded(contract: seeds.SeedContract) -> dict[str, Any]:
    """The seeds' envelope schema, each entry's own: a value is split as the run's input would be (§5.3), a sensitive
    one, or a sensitive part of one, claimed, a handle. Never checked against it: `seeds.check` has."""
    values = {e.pointer: {**(e.schema or {}), **({"x-sensitive": True} if e.sensitive else {})}
              for e in contract.entries}  # fmt: skip
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "values": {"type": "object", "additionalProperties": False, "properties": values},
            "absent": {"type": "array", "items": {"type": "string"}},
        },
    }


async def _open(s: AsyncSession, tenant_id: uuid.UUID, fields: dict[str, Any]) -> None:
    """The tenant starts runs: it's active (an erasure's step 1 waits for this request, or this one sees `erasing`),
    and, for an interactive source, the gate is open."""
    await tenant_lifecycle.hold_shared(s, tenant_id)
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None:
        raise WorkflowNotFoundError(str(fields["workflow_id"]))
    if tenant.status != "active":  # erasing, or erased: a retained tombstone is never eligible again
        raise _Refused(TENANT_ERASING, ["This tenant is being erased: it starts no run."])
    if fields["source"] in INTERACTIVE:
        platform = await recorded(s)
        if platform is None:
            raise _Refused(ENVIRONMENT_NOT_RECORDED, [NOT_RECORDED])
        if platform.environment == PRODUCTION and not platform.production_runs:
            raise _Refused(PRODUCTION_RUNS_DISABLED, [GATE_OFF])


async def _current_build(s: AsyncSession) -> int | None:
    """The current build's engine ABI, as the dispatcher recorded it lately; None: no record, or a stale one."""
    found = await s.execute(
        select(CurrentBuild.engine_abi).where(CurrentBuild.observed_at >= func.statement_timestamp() - BUILD_STALE)
    )
    return found.scalar_one_or_none()


@dataclass(frozen=True)
class _Built:
    headers: list[str]
    rows: list[dict[str, Any]]
    skipped: list[tuple[int, str]]  # every skipped record: its number and the first rule it broke
    errors: list[RowError]  # the first ones, in detail
    error_count: int
    file_digest: bytes


def _row_message(e: RowError) -> str:
    return f"The CSV's row {e.row}, column `{e.column}`: {e.code}." if e.column else f"The CSV's row {e.row}: {e.code}."


async def _rows(
    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, workflow_id: uuid.UUID, actor_id: uuid.UUID | None,
    csv: CsvStart, declared: dict[str, Any], version_id: uuid.UUID,
) -> _Built:  # fmt: skip
    """The upload's rows, built against the frozen version's declaration, its row locked until the caller commits:
    its tenant, owner and workflow the caller's (else it's not found, whoever's it is), not consumed, not expired."""
    query = (
        select(CsvUpload, CsvUpload.expires_at > func.statement_timestamp())
        .where(CsvUpload.id == csv.upload_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    found = (await s.execute(query)).one_or_none()
    await _after_upload_locked()
    upload, live = found if found is not None else (None, False)
    if upload is None or (upload.tenant_id, upload.owner_id, upload.workflow_id) != (tenant_id, actor_id, workflow_id):
        raise _Refused(UPLOAD_NOT_FOUND, ["There's no such upload of yours for this workflow."], version_id)
    if upload.consumed_by is not None or upload.staged is None:
        raise _Consumed
    if not live:
        raise _Refused(UPLOAD_EXPIRED, ["This upload has expired: upload the file again."], version_id)
    data = await ClaimCipher(keys, purpose=csv_uploads.PURPOSE).open(str(tenant_id), str(upload.id), upload.staged)
    headers, built = await asyncio.to_thread(_built_rows, data, declared, csv, version_id)  # the session: the loop's
    if built.skipped and not csv.skip_invalid:
        raise _Refused(INPUT_INVALID, [_row_message(e) for e in built.errors[:_LISTED]], version_id)
    return _Built(headers, built.rows, built.skipped, built.errors, built.error_count, upload.file_digest)


def _built_rows(data: bytes, declared: dict[str, Any], csv: CsvStart, version_id: uuid.UUID) -> tuple[list[str], Built]:
    """The staged file's headers and rows, built against the declaration: CPU only (seconds at the caps), which the
    caller runs off the event loop, inside its CSV slot (the owner's ruling 2 on 2b-4b's M3 checkpoint)."""
    try:  # under the frozen version's caps, which may be lower than those it was uploaded under
        table = read_table(data, max_rows=int(declared["max_rows"]), max_bytes=csv_uploads.byte_cap(declared))
    except CsvFileError as e:
        raise _Refused(INPUT_INVALID, [f"The CSV file: {e.code}."], version_id) from None
    columns = declared["columns"]
    problems = mapping_problems(columns, csv.mapping, table.headers)
    if problems:
        messages = [f"The mapping's column `{p['column']}`: {p['code']}." for p in problems[:_LISTED]]
        raise _Refused(CSV_MAPPING_INVALID, messages, version_id)
    return table.headers, build_rows(table, columns, csv.mapping)


async def _insert(
    s: AsyncSession,
    keys: KeySource,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    idempotency_key: str,
    fields: dict[str, Any],
    version_id: uuid.UUID | None,
    envelope_id: uuid.UUID | None,
    refused: _Refused | None = None,
    rerun: Rerun | None = None,
    extra: dict[str, object] | None = None,
    draft: _DraftFrozen | None = None,
) -> Admitted:
    """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key. A
    draft simulation's (`draft`) is frozen on its snapshot."""
    key_version, digest = await digests.digest(keys, str(tenant_id), **fields)  # the tenant's active key (§7.2)
    status = "refused" if refused else "queued"
    row = {
        "id": request_id,
        "tenant_id": tenant_id,
        "workflow_id": fields["workflow_id"],
        "workflow_version_id": refused.version_id if refused else version_id,
        "source": fields["source"],
        "actor_id": actor_id,
        "mode": fields["mode"],
        "idempotency_key": idempotency_key,
        "digest": digest,
        "digest_key_version": key_version,
        "status": status,
        "reason": refused.reason if refused else None,
        "ended_at": func.now() if refused else None,
        "envelope_id": envelope_id,
    }
    if draft is not None:
        row |= {"draft_snapshot_id": draft.snapshot_id, "target_step_id": draft.target,
                "draft_revision": draft.revision, "admission_checks": draft.checks}  # fmt: skip
    written = await s.execute(
        insert(RunRequest)
        .values(row)
        .on_conflict_do_nothing(constraint="run_requests_idempotency")
        .returning(RunRequest.id)
    )
    if written.scalar_one_or_none() is None:
        if refused:
            return await _retry(keys, tenant_id, await _winner(s, idempotency_key), fields)
        return Admitted(RunRequest(id=request_id), new=False)
    details: dict[str, object] = {"workflow_id": str(fields["workflow_id"]), "source": fields["source"],
                                  "mode": fields["mode"], "status": status}  # fmt: skip
    if row["workflow_version_id"]:
        details["version_id"] = str(row["workflow_version_id"])
    if refused:
        details["reason"] = refused.reason
    if rerun is not None:
        details["rerun_of"] = str(rerun.of)
    details.update(extra or {})
    await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action="run.request", target_type="run_request",
                       target_id=str(request_id), details=details)  # fmt: skip
    request = await s.get(RunRequest, request_id, populate_existing=True)
    if request is None:
        raise RuntimeError("A request this transaction inserted that isn't there.")
    return Admitted(request, new=True)
