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

from dewpoint.core.claims.service import CLAIM_UNAVAILABLE, ClaimUnavailableError, NewClaim
from dewpoint.engine.cel import evaluate as cel
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.bind import BindingError, check_json
from dewpoint.engine.handles import MISSING, ClaimRef, Fetch, StoredClaim, contains_marker, part, resolve_value
from dewpoint.engine.runtime.activities import Claiming, DeriveInput, DeriveResult
from dewpoint.engine.runtime.execution import INTERNAL_ERROR
from dewpoint.engine.runtime.ids import run_of, tenant_of
from dewpoint.engine.runtime.resolve import Part, ValueFailure, join

UNAVAILABLE = "A claim this run may not read, or that doesn't exist."

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
    return {i: {"ok": ClaimRef(str(row.id)).to_json()} for (i, _), row in zip(results, rows, strict=True)}


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
    if claims.decision:  # a declassified decision comes back plain (§4.3)
        return done
    results = [(i, o["ok"]) for i, o in enumerate(done) if "ok" in o and tainted[i]]
    for i, outcome in (await _claimed(store, tenant, run, claims, results)).items():
        done[i] = outcome
    return done


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
        return {"error": e.failure.code, "message": e.failure.message}
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
