# SPDX-License-Identifier: Apache-2.0
"""Claims in the worker (engine 2b spec §3.2–3.4, §4.2). Every resolution happens in an activity and is checked
against the stored row: the tenant is the one the activity's server-built workflow id names, and the run it names is
the claim's owner or holds a grant. Every refusal looks the same, whatever its cause (`claim_unavailable`).

`cel.evaluate` resolves the handles among its bindings, or a template's parts, evaluates, and claims a result that read
sensitive data, or whose expression does: the workflow gets its handle, never the value (§3.6, §4.2). A handle whose
pointer passed POINTER_MAX is derived: what it addresses is copied, as stored, into a claim of its own (§3.2)."""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from dewpoint.apps.inputs import FORGED, reasons
from dewpoint.core.claims.service import CLAIM_UNAVAILABLE, ClaimUnavailableError, NewClaim
from dewpoint.engine.cel import evaluate as cel
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.bind import BindingError, bind_item, check_json
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.handles import (
    MISSING,
    ClaimRef,
    Fetch,
    StoredClaim,
    contains_marker,
    handles_in,
    part,
    resolve_value,
)
from dewpoint.engine.matcher import Matcher
from dewpoint.engine.runtime.activities import (
    ChildInput,
    ChildInputResult,
    Claiming,
    DeriveInput,
    DeriveResult,
    GrantInput,
    StepInput,
)
from dewpoint.engine.runtime.execution import INTERNAL_ERROR
from dewpoint.engine.runtime.ids import run_of, tenant_of
from dewpoint.engine.runtime.projection import REDACTED
from dewpoint.engine.runtime.resolve import Part, ValueFailure, join
from dewpoint.engine.sensitive import MIN_SECRET
from dewpoint.engine.split import ForgedHandleError, split
from dewpoint.engine.taint import from_schema, tainted_positions

UNAVAILABLE = "A claim this run may not read, or that doesn't exist."
_OUTPUTS = uuid.uuid5(uuid.NAMESPACE_URL, "dewpoint:claims:output")  # a step output's claim ids are derived under it
_INPUTS = uuid.uuid5(uuid.NAMESPACE_URL, "dewpoint:claims:child-input")  # a child input's, under it


class LeftPlainError(Exception):
    """A split left plain data at a sensitive or undeclared position: a bug, never returned (§3.6)."""


Evaluate = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class ClaimStore(Protocol):
    async def fetch(self, tenant_id: str, run_id: str, claim_id: str) -> StoredClaim:
        """A whole claim, for `run_id`: its owner, or a run it was granted to. Raises ClaimUnavailableError."""
        ...

    async def write(
        self,
        tenant_id: str,
        claims: Sequence[NewClaim],
        *,
        kind: str,
        step_id: str | None,
        iteration_key: str | None,
    ) -> None:
        """Claims made during a run (`step_outputs`), written once: a retry writes the same rows."""
        ...

    async def write_inputs(self, tenant_id: str, claims: Sequence[tuple[NewClaim, str]]) -> None:
        """Claims made before a run starts (`run_inputs`), each with where in its input it came from."""
        ...

    async def grant(
        self, tenant_id: str, *, granted_by: str, to: str, claim_ids: Sequence[str], root_run_id: str
    ) -> None:
        """`to` may read the claims, which `granted_by` owns or holds a grant on (§3.4). Raises
        ClaimUnavailableError, granting nothing, for any other."""
        ...

    async def input_schema(self, tenant_id: str, version_id: str) -> Mapping[str, Any] | None:
        """A version's input schema, what a sub-flow's input is checked and split by (§3.4); None if there's no
        such version."""
        ...

    async def secrets(self, tenant_id: str, root_run_id: str) -> tuple[str, ...]:
        """The run tree's secret index (§3.7): every string of MIN_SECRET characters or more in its tainted claims."""
        ...

    async def remember(self, tenant_id: str, root_run_id: str, strings: Sequence[str]) -> None:
        """Strings of new tainted claims, added to the tree's index. Raises SecretIndexLimitError past its bounds."""
        ...


def caller() -> tuple[str, str]:
    """The tenant and the run the current activity's server-built workflow id names (§3.3, §6.1): a batch's is its
    run's."""
    workflow_id = activity.info().workflow_id or ""
    tenant, run = tenant_of(workflow_id), run_of(workflow_id)
    if tenant is None or run is None:
        raise ApplicationError("This activity's workflow id names no run.", type=INTERNAL_ERROR, non_retryable=True)
    return tenant, run


def _fetcher(store: ClaimStore, tenant: str, run: str) -> Fetch:
    async def fetch(claim_id: str) -> StoredClaim:
        return await store.fetch(tenant, run, claim_id)

    return fetch


def _claim_id(seed: str, index: int) -> uuid.UUID:
    """A result's claim id: the same for the same request, on a retry."""
    return uuid.uuid5(uuid.UUID(seed), str(index))


async def _bindings(
    bindings: Mapping[str, Any], declarations: Mapping[str, str], fetch: Fetch
) -> tuple[dict[str, Any], bool]:
    """One binding set with its handles resolved and type-checked now, as binding checks a plain one, and whether
    any of them read sensitive data."""
    out: dict[str, Any] = {}
    tainted = False
    for name, value in bindings.items():
        if not contains_marker(value):
            out[name] = value
            continue
        found = await resolve_value(value, fetch)
        if found.value is MISSING:
            raise BindingError(f"`{name}` is missing")
        if not T.conforms(declarations.get(name, T.DYN), found.value):
            raise BindingError(f"`{name}` doesn't match its declared type {declarations.get(name, T.DYN)}")
        check_json(name, found.value)
        out[name], tainted = found.value, tainted or found.tainted
    return out, tainted


async def _claimed(
    store: ClaimStore, tenant: str, run: str, claims: Claiming, results: list[tuple[int, Any]]
) -> dict[int, dict[str, Any]]:
    """`results` (an index and a value each) written as tainted claims: each index's outcome, now its handle."""
    if not results:
        return {}
    rows = [
        NewClaim(_claim_id(claims.seed, i), value, ("",), uuid.UUID(run), uuid.UUID(claims.root_run_id))
        for i, value in results
    ]
    await store.write(tenant, rows, kind="cel", step_id=claims.step_id, iteration_key=claims.iteration_key)
    await store.remember(tenant, claims.root_run_id, sorted({t for _, v in results for t in _strings(v)}))
    return {i: {"ok": ClaimRef(str(row.id)).to_json()} for (i, _), row in zip(results, rows, strict=True)}


def _strings(value: Any) -> list[str]:
    """The strings of a claimed value the index takes (MIN_SECRET characters or more), keys included."""
    if isinstance(value, str):
        return [value] if len(value) >= MIN_SECRET else []
    if isinstance(value, dict):
        return [t for k, v in value.items() for t in (*_strings(k), *_strings(v))]
    if isinstance(value, list):
        return [t for v in value for t in _strings(v)]
    return []


async def _masked(outcomes: list[dict[str, Any]], store: ClaimStore, tenant: str, root: str) -> list[dict[str, Any]]:
    """Every error message masked against the run tree's secrets before it leaves the activity (§3.7)."""
    if not any("error" in o for o in outcomes):
        return outcomes
    secrets = Matcher(await store.secrets(tenant, root))
    return [
        {**o, "message": secrets.mask(str(o.get("message", "")), REDACTED)} if "error" in o else o for o in outcomes
    ]


async def evaluate_claimed(
    request: dict[str, Any], claims: Claiming, store: ClaimStore, evaluate: Evaluate
) -> list[dict[str, Any]]:
    """`cel.evaluate` over bindings that may hold handles (§4.2): one outcome per binding set, in order. A set whose
    handles can't be resolved fails alone (`claim_unavailable`, or `type_mismatch` for a value of the wrong type)."""
    tenant, run = caller()
    fetch = _fetcher(store, tenant, run)
    sets = request["bindings"]
    outcomes: list[dict[str, Any] | None] = [None] * len(sets)
    tainted = [claims.tainted] * len(sets)
    ready: list[tuple[int, dict[str, Any]]] = []
    for i, bindings in enumerate(sets):
        try:
            plain, read_tainted = await _bindings(bindings, request["declarations"], fetch)
        except ClaimUnavailableError:
            outcomes[i] = {"error": CLAIM_UNAVAILABLE, "message": UNAVAILABLE}
            continue
        except BindingError as e:
            outcomes[i] = {"error": cel.TYPE_MISMATCH, "message": str(e)}
            continue
        tainted[i] = tainted[i] or read_tainted
        ready.append((i, plain))
    if ready:
        answered = await evaluate({**request, "bindings": [b for _, b in ready]})
        for (i, _), outcome in zip(ready, answered, strict=True):
            outcomes[i] = outcome
    done = [o if o is not None else {"error": cel.EVALUATION_ERROR, "message": UNAVAILABLE} for o in outcomes]
    if not claims.decision:  # a declassified decision comes back plain (§4.3)
        results = [(i, o["ok"]) for i, o in enumerate(done) if "ok" in o and tainted[i]]
        for i, outcome in (await _claimed(store, tenant, run, claims, results)).items():
            done[i] = outcome
    return await _masked(done, store, tenant, claims.root_run_id)


async def join_claimed(parts: list[Any], claims: Claiming, store: ClaimStore) -> dict[str, Any]:
    """A template whose parts are handles, joined here once they're resolved (§4.2): its text, claimed when any part
    read sensitive data."""
    tenant, run = caller()
    fetch = _fetcher(store, tenant, run)
    read: list[str | Part] = []
    tainted = claims.tainted
    for p in parts:
        if isinstance(p, str):
            read.append(p)
            continue
        found = Part.from_json(p)
        if found.found is not MISSING and contains_marker(found.found):
            try:
                resolved = await resolve_value(found.found, fetch)
            except ClaimUnavailableError:
                return {"error": CLAIM_UNAVAILABLE, "message": UNAVAILABLE}
            found = Part(resolved.value, found.default, found.path)
            tainted = tainted or resolved.tainted
        read.append(found)
    try:
        text = join(read)
    except ValueFailure as e:
        [failed] = await _masked(
            [{"error": e.failure.code, "message": e.failure.message}], store, tenant, claims.root_run_id
        )
        return failed
    if not tainted:
        return {"ok": text}
    return (await _claimed(store, tenant, run, claims, [(0, text)]))[0]


async def derive(data: DeriveInput, store: ClaimStore) -> DeriveResult:
    """`claims.derive` (§3.2): whether a handle addresses anything, and null; past POINTER_MAX, what it addresses as
    a claim of its own, owned by the calling run."""
    tenant, run = caller()
    source = ClaimRef.of(data.handle)
    if source is None:
        raise ApplicationError("Not a handle.", type=INTERNAL_ERROR, non_retryable=True)
    try:
        found = await part(source, _fetcher(store, tenant, run))
    except ClaimUnavailableError:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    if found is None:
        return DeriveResult(None, present=False)
    if found.value is None:
        return DeriveResult(None)
    if not source.too_long():
        return DeriveResult(source.to_json())
    new = NewClaim(uuid.UUID(data.claim_id), found.value, found.sensitive_pointers, uuid.UUID(run),
                   uuid.UUID(data.root_run_id))  # fmt: skip
    await store.write(tenant, [new], kind="derived", step_id=data.step_id, iteration_key=data.iteration_key)
    return DeriveResult(ClaimRef(data.claim_id).to_json())


# --- the step boundary (§3.6) --------------------------------------------------------------------------------------


async def resolved_config(config: dict[str, Any], store: ClaimStore) -> dict[str, Any]:
    """A step's config with its handles resolved, for the run the activity's workflow id names (§3.3). Raises
    ClaimUnavailableError."""
    if not contains_marker(config):
        return config
    tenant, run = caller()
    found = await resolve_value(config, _fetcher(store, tenant, run))
    return dict(found.value)


async def claim_output(
    output: Any, schema: Mapping[str, Any], step: StepInput, store: ClaimStore, known: Sequence[str]
) -> Any:
    """A step's output as it may leave the activity: split by the node's output schema, what's sensitive or
    undeclared, and text that repeats a secret the run knows (`known`), claimed; their strings join the index. The
    claims' ids come from the attempt and their place, so writing them again writes the same rows."""
    tenant, run = caller()
    root = step.root_run_id or run
    seed = uuid.uuid5(_OUTPUTS, f"{run}/{step.step_id}/{step.iteration_key}/{step.attempt}")
    done = split(output, schema, lambda pointer: str(uuid.uuid5(seed, pointer)), known=known, sizes=False)
    rows = [
        NewClaim(uuid.UUID(c.id), c.value, ("",) if c.tainted else (), uuid.UUID(run), uuid.UUID(root))
        for c in done.claims
    ]
    await store.remember(tenant, root, done.secrets)  # first: past the index's bounds, nothing is written
    if rows:
        await store.write(tenant, rows, kind="output", step_id=step.step_id, iteration_key=step.iteration_key)
    if tainted_positions(done.envelope, from_schema(schema)):
        raise LeftPlainError("A step's output kept plain data at a sensitive position.")
    return done.envelope


# --- the tainted filter (§4.4) ---------------------------------------------------------------------------------------

FILTER_BATCH = 1_000  # items per evaluator request
NOT_A_LIST = "`items` must be a list."
NOT_A_DECISION = "`predicate` must give true or false."


async def filter_claimed(
    request: dict[str, Any], spec: dict[str, Any], claims: Claiming, store: ClaimStore, evaluate: Evaluate
) -> dict[str, Any]:
    """A filter run whole here (§4.4): its items resolved, its predicate evaluated per item in the evaluator, and the
    kept items stored as a claim, tainted when the items or the predicate are. The outcome: the claim's handle, the
    kept count and the input count; no per-item decision leaves the activity."""
    tenant, run = caller()
    fetch = _fetcher(store, tenant, run)
    record = ExpressionRecord.from_json(spec["record"])
    try:
        found = await resolve_value(spec["items"], fetch)
        base, base_tainted = await _bindings(request["bindings"][0], request["declarations"], fetch)
    except ClaimUnavailableError:
        return {"error": CLAIM_UNAVAILABLE, "message": UNAVAILABLE}
    except BindingError as e:
        [failed] = await _masked([{"error": cel.TYPE_MISMATCH, "message": str(e)}], store, tenant, claims.root_run_id)
        return failed
    items = found.value
    if not isinstance(items, list):
        return {"error": cel.TYPE_MISMATCH, "message": NOT_A_LIST}
    kept: list[Any] = []
    for start in range(0, len(items), FILTER_BATCH):
        try:
            sets = [
                bind_item(record, base, item, start + i) for i, item in enumerate(items[start : start + FILTER_BATCH])
            ]
        except BindingError as e:
            [failed] = await _masked(
                [{"error": cel.TYPE_MISMATCH, "message": str(e)}], store, tenant, claims.root_run_id
            )
            return failed
        for i, outcome in enumerate(await evaluate({**request, "bindings": sets}), start):
            if "error" in outcome:  # the filter fails at its first failing item
                [failed] = await _masked([outcome], store, tenant, claims.root_run_id)
                return failed
            if not isinstance(outcome["ok"], bool):
                return {"error": cel.TYPE_MISMATCH, "message": NOT_A_DECISION}
            if outcome["ok"]:
                kept.append(items[i])
    tainted = claims.tainted or found.tainted or base_tainted
    claim_id = _claim_id(claims.seed, 0)
    new = NewClaim(claim_id, kept, ("",) if tainted else (), uuid.UUID(run), uuid.UUID(claims.root_run_id))
    if tainted:
        await store.remember(tenant, claims.root_run_id, sorted(set(_strings(kept))))
    await store.write(tenant, [new], kind="filter", step_id=claims.step_id, iteration_key=claims.iteration_key)
    return {"ok": {"items": ClaimRef(str(claim_id)).to_json(), "count": len(kept), "input": len(items)}}


# --- crossing between runs (§3.4) ----------------------------------------------------------------------------------


async def _closure(claim_ids: Sequence[str], fetch: Fetch) -> list[str]:
    """`claim_ids` and every claim nested in them: what a run must be granted to resolve their handles."""
    seen: set[str] = set()
    queue = list(claim_ids)
    while queue:
        claim_id = queue.pop()
        if claim_id in seen:
            continue
        seen.add(claim_id)
        queue.extend(h.id for _, h in handles_in((await fetch(claim_id)).value))
    return sorted(seen)


async def _granted(store: ClaimStore, tenant: str, run: str, to: str, value: Any, root: str) -> None:
    ids = await _closure([h.id for _, h in handles_in(value)], _fetcher(store, tenant, run))
    if ids:
        await store.grant(tenant, granted_by=run, to=to, claim_ids=ids, root_run_id=root)


async def grant(data: GrantInput, store: ClaimStore) -> None:
    """`claims.grant`: the calling run grants the handles in `value`, and the claims they nest, to `to_run_id`."""
    tenant, run = caller()
    try:
        await _granted(store, tenant, run, data.to_run_id, data.value, data.root_run_id)
    except ClaimUnavailableError:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None


async def child_input(data: ChildInput, store: ClaimStore) -> ChildInputResult:
    """`claims.child_input` (§3.4, §3.5): the calling run's input for its child, checked against the child's schema
    with its values resolved, then split for the child with the run's own handles left in place; those, and the
    claims they nest, are granted to the child, and the new claims' secrets join the tree's index. A child whose
    version isn't there gets its input as it is: it fails loading it, before it reads anything."""
    tenant, run = caller()
    schema = await store.input_schema(tenant, data.version_id)
    if schema is None:
        return ChildInputResult(trigger=data.value)
    try:
        resolved = await resolve_value(data.value, _fetcher(store, tenant, run))
    except ClaimUnavailableError:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    refused = reasons(schema, resolved.value)
    if refused:
        return ChildInputResult(reasons=refused)
    seed = uuid.uuid5(_INPUTS, data.child_run_id)
    try:
        done = split(
            data.value,
            schema,
            lambda pointer: str(uuid.uuid5(seed, pointer)),
            known=await store.secrets(tenant, data.root_run_id),
            handles=True,
        )
    except ForgedHandleError:
        return ChildInputResult(reasons=[FORGED])
    child, root = uuid.UUID(data.child_run_id), uuid.UUID(data.root_run_id)
    rows = [
        (NewClaim(uuid.UUID(c.id), c.value, ("",) if c.tainted else (), child, root), c.pointer) for c in done.claims
    ]
    await store.remember(tenant, data.root_run_id, done.secrets)
    if rows:
        await store.write_inputs(tenant, rows)
    try:
        await _granted(store, tenant, run, data.child_run_id, data.value, data.root_run_id)
    except ClaimUnavailableError:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    return ChildInputResult(trigger=done.envelope)
