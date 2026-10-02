# SPDX-License-Identifier: Apache-2.0
"""Claims in the worker (engine 2b spec §3.2–3.4, §4.2). Every resolution happens in an activity and is checked
against the stored row: the tenant is the one the activity's server-built workflow id names, and the run it names is
the claim's owner or holds a grant. Every refusal looks the same, whatever its cause (`claim_unavailable`).

`cel.evaluate` resolves the handles among its bindings, or a template's parts, evaluates, and claims a result that read
sensitive data, or whose expression does: the workflow gets its handle, never the value (§3.6, §4.2). A handle whose
pointer passed POINTER_MAX is derived: what it addresses is copied, as stored, into a claim of its own (§3.2)."""

import asyncio
import json
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from dewpoint.apps.inputs import FORGED, reasons
from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT, Index, SecretIndexLimitError
from dewpoint.core.claims.service import CLAIM_UNAVAILABLE, ClaimUnavailableError, NewClaim
from dewpoint.engine.cel import evaluate as cel
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.bind import BindingError, bind_item, check_json
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.handles import (
    MISSING,
    RESERVED,
    ClaimRef,
    Fetch,
    NestingError,
    StoredClaim,
    contains_marker,
    escape,
    handles_in,
    part,
    resolve_value,
    tokens,
)
from dewpoint.engine.matcher import Matcher
from dewpoint.engine.runtime.activities import (
    ChildInput,
    ChildInputResult,
    Claiming,
    DeriveInput,
    DeriveResult,
    GrantInput,
    MessageInput,
    MessageResult,
    SpillInput,
    StepInput,
)
from dewpoint.engine.runtime.execution import INTERNAL_ERROR, VERSION_UNUSABLE
from dewpoint.engine.runtime.ids import run_of, tenant_of
from dewpoint.engine.runtime.projection import REDACTED
from dewpoint.engine.runtime.resolve import Part, ValueFailure, join
from dewpoint.engine.runtime.scheduler import assembled
from dewpoint.engine.runtime.size import inline_limit
from dewpoint.engine.sensitive import MIN_SECRET, marked_positions
from dewpoint.engine.split import ForgedHandleError, json_bytes, split
from dewpoint.engine.taint import Shape, from_schema, tainted_positions

UNAVAILABLE = "A claim this run may not read, or that doesn't exist."
UNREADABLE = (ClaimUnavailableError, NestingError)  # a claim refused as `claim_unavailable`: nested past the bound too
NO_CHILD_VERSION = "The sub-flow's pinned version isn't there, so its input can't be checked or split for it."
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

    async def index(self, tenant_id: str, root_run_id: str) -> Index:
        """The run tree's secret index (§3.7): every string of MIN_SECRET characters or more in its tainted claims,
        and its version, which every extension changes."""
        ...

    async def index_version(self, tenant_id: str, root_run_id: str) -> int:
        """The index's version alone: whether a copy read earlier is stale."""
        ...

    async def remember(self, tenant_id: str, root_run_id: str, strings: Sequence[str]) -> Index:
        """Strings of new tainted claims, added to the tree's index: the index as it is then, with every extension
        before this one (they're serialized). Raises SecretIndexLimitError past its bounds, changing nothing."""
        ...


SECRETS_CACHE = 256  # run trees whose index and automaton a worker process keeps, the most recently used


@dataclass(frozen=True)
class Secrets:
    """A run tree's secret index at one version, its automaton, and its strings as a set."""

    index: Index
    matcher: Matcher
    known: frozenset[str]


SECRETS: "OrderedDict[tuple[str, str], Secrets]" = OrderedDict()
# The builds running, one per run tree and version (and event loop): every boundary that misses the cache meanwhile
# waits for it instead of building the same automaton again (the owner's review of I3).
_BUILDING: "dict[tuple[asyncio.AbstractEventLoop, str, str, int], asyncio.Future[Secrets]]" = {}


def _built(index: Index) -> Secrets:
    return Secrets(index, Matcher(index.strings), frozenset(index.strings))


async def secrets_for(index: Index, tenant: str, root: str) -> Secrets:
    """`index` (just read or extended) with its automaton: built once per version, in a worker thread, and cached
    with it (§3.7; the review's I3: at the index's bounds a build takes about a second, which on the event loop
    stalled every activity and workflow task of the worker). Boundaries that miss the cache while it's built share
    the build; the cache keeps the newest version built, and an older index asked for is still the one returned."""
    key = (tenant, root)
    held = SECRETS.get(key)
    if held is None or held.index.version != index.version:
        building = (asyncio.get_running_loop(), tenant, root, index.version)
        build = _BUILDING.get(building)
        if build is None:
            build = _BUILDING[building] = asyncio.ensure_future(asyncio.to_thread(_built, index))
            build.add_done_callback(lambda _: _BUILDING.pop(building, None))
        held = await asyncio.shield(build)  # a boundary cancelled meanwhile leaves the build to the others
        cached = SECRETS.get(key)
        if cached is None or cached.index.version < held.index.version:  # never an older version over a newer
            SECRETS[key] = held
    if key in SECRETS:
        SECRETS.move_to_end(key)
    while len(SECRETS) > SECRETS_CACHE:
        SECRETS.popitem(last=False)
    return held


async def secrets_of(store: ClaimStore, tenant: str, root: str) -> Secrets:
    """The tree's index as it is now, with its automaton (§3.7): read again, and built, only when its version moved
    since this process last held it, which a version check tells."""
    held = SECRETS.get((tenant, root))
    if held is not None and await store.index_version(tenant, root) == held.index.version:
        return await secrets_for(held.index, tenant, root)
    return await secrets_for(await store.index(tenant, root), tenant, root)


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
    store: ClaimStore, tenant: str, run: str, claims: Claiming, results: list[tuple[int, Any]], *, tainted: bool = True
) -> dict[int, dict[str, Any]]:
    """`results` (an index and a value each) written as claims, tainted (their strings join the index) or, past 64
    KiB, as size claims (§5.1): each index's outcome, now its handle."""
    if not results:
        return {}
    sensitive = ("",) if tainted else ()
    rows = [
        NewClaim(_claim_id(claims.seed, i), value, sensitive, uuid.UUID(run), uuid.UUID(claims.root_run_id))
        for i, value in results
    ]
    if tainted:  # the extension first: past the index's bounds, nothing is written (§3.7)
        try:
            await store.remember(tenant, claims.root_run_id, sorted({t for _, v in results for t in _strings(v)}))
        except SecretIndexLimitError as e:  # the step fails with the bound's code, never retried (review I4)
            return {i: {"error": SECRET_INDEX_LIMIT, "message": str(e)} for i, _ in results}
    await store.write(tenant, rows, kind="cel", step_id=claims.step_id, iteration_key=claims.iteration_key)
    return {i: {"ok": ClaimRef(str(row.id)).to_json()} for (i, _), row in zip(results, rows, strict=True)}


def _large(value: Any) -> bool:
    """Larger than the workflow may hold inline (§5.1): a size claim, untainted."""
    return json_bytes(value) > inline_limit()


def _repeats(value: Any, secrets: Matcher) -> bool:
    """Whether a plain value's text repeats a secret the run knows: it's claimed with taint, as output is (§3.6)."""
    if isinstance(value, str):
        return bool(secrets.found(value))
    if isinstance(value, dict):
        return any(secrets.found(k) or _repeats(v, secrets) for k, v in value.items())
    if isinstance(value, list):
        return any(_repeats(v, secrets) for v in value)
    return False


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
    secrets = (await secrets_of(store, tenant, root)).matcher
    return [
        {**o, "message": secrets.mask(str(o.get("message", "")), REDACTED)} if "error" in o else o for o in outcomes
    ]


def unforged(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The evaluator's outcomes, a value that holds the marker refused: CEL can build such a map, and it's no handle
    (§3.2)."""
    return [{"error": cel.EVALUATION_ERROR, "message": RESERVED} if "ok" in o and contains_marker(o["ok"]) else o
            for o in outcomes]  # fmt: skip


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
        except UNREADABLE:
            outcomes[i] = {"error": CLAIM_UNAVAILABLE, "message": UNAVAILABLE}
            continue
        except BindingError as e:
            outcomes[i] = {"error": cel.TYPE_MISMATCH, "message": str(e)}
            continue
        tainted[i] = tainted[i] or read_tainted
        ready.append((i, plain))
    if ready:
        answered = unforged(await evaluate({**request, "bindings": [b for _, b in ready]}))
        for (i, _), outcome in zip(ready, answered, strict=True):
            outcomes[i] = outcome
    done = [o if o is not None else {"error": cel.EVALUATION_ERROR, "message": UNAVAILABLE} for o in outcomes]
    if claims.decision:  # a declassified decision comes back plain, only as a decision (§4.3; review I1)
        for i, o in enumerate(done):
            if "ok" in o and not _decides(o["ok"], claims.decides):
                done[i] = {"error": cel.TYPE_MISMATCH, "message": NOT_DECIDED.get(claims.decides, NOT_DECIDED["bool"])}
    else:
        secrets = (await secrets_of(store, tenant, claims.root_run_id)).matcher
        results = [(i, o["ok"]) for i, o in enumerate(done) if "ok" in o and (tainted[i] or _repeats(o["ok"], secrets))]
        claimed = {i for i, _ in results}
        large = [(i, o["ok"]) for i, o in enumerate(done) if "ok" in o and i not in claimed and _large(o["ok"])]
        for i, outcome in (await _claimed(store, tenant, run, claims, results)).items():
            done[i] = outcome
        for i, outcome in (await _claimed(store, tenant, run, claims, large, tainted=False)).items():
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
            except UNREADABLE:
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
    if not tainted and not _repeats(text, (await secrets_of(store, tenant, claims.root_run_id)).matcher):
        if _large(text):
            return (await _claimed(store, tenant, run, claims, [(0, text)], tainted=False))[0]
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
    except UNREADABLE:
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


def config_secrets(config: Any, schema: Mapping[str, Any]) -> list[str]:
    """The strings a step's config holds where the node's config schema marks it `x-sensitive` (§3.6): a value only
    the config marks sensitive, resolved now. They join the index before the attempt, so whatever echoes them is
    masked. Undeclared positions don't count: a node's free-form input is no secret of its own."""
    out: list[str] = []
    for pointer in marked_positions(config, schema):
        found: Any = config
        for token in tokens(pointer):
            found = found[int(token)] if isinstance(found, list) else found[token]
        out += _strings(found)
    return sorted(set(out))


async def claim_output(output: Any, schema: Mapping[str, Any], step: StepInput, store: ClaimStore) -> Any:
    """A step's output as it may leave the activity: split by the node's output schema, what's sensitive or
    undeclared, and text that repeats a secret the run knows, claimed; their strings join the index. Then what's
    larger than 64 KiB, and the envelope down to the inline limit the workflow sent (§5.1, §5.4). What the run
    knows is the index at this boundary, not the copy read before the attempt (`seen`, §3.7): another activity may
    have extended it meanwhile, or does while this one splits, which the extension that follows shows. The claims'
    ids come from the attempt and their place, so writing them again writes the same rows."""
    tenant, run = caller()
    root = step.root_run_id or run
    seed = uuid.uuid5(_OUTPUTS, f"{run}/{step.step_id}/{step.iteration_key}/{step.attempt}")
    held = await secrets_of(store, tenant, root)
    while True:  # past the index's bounds, nothing is written: the extension comes first
        done = split(
            output,
            schema,
            lambda pointer: str(uuid.uuid5(seed, pointer)),
            known=held.matcher,
            envelope=step.inline_limit,
        )
        merged = await store.remember(tenant, root, done.secrets)
        wrote = not held.known.issuperset(done.secrets)  # an extension makes one new version (§3.7)
        if merged.version == held.index.version + (1 if wrote else 0):
            break
        held = await secrets_for(merged, tenant, root)  # extended since by another activity: split again against it
    rows = [
        NewClaim(uuid.UUID(c.id), c.value, ("",) if c.tainted else (), uuid.UUID(run), uuid.UUID(root))
        for c in done.claims
    ]
    if rows:
        await store.write(tenant, rows, kind="output", step_id=step.step_id, iteration_key=step.iteration_key)
    if tainted_positions(done.envelope, from_schema(schema)):
        raise LeftPlainError("A step's output kept plain data at a sensitive position.")
    return done.envelope


# --- the tainted filter (§4.4) ---------------------------------------------------------------------------------------

FILTER_BATCH = 1_000  # items per evaluator request
NOT_A_LIST = "`items` must be a list."
NOT_A_DECISION = "`predicate` must give true or false."
NOT_DECIDED = {
    "bool": "A listed decision must give true or false.",
    "int": "A listed loop's count must be a whole number.",
}


def _decides(value: Any, kind: str) -> bool:
    """Whether a declassified decision's value is of the type it decides with: only that comes back plain (I1)."""
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, bool)


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
    except UNREADABLE:
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
        try:
            await store.remember(tenant, claims.root_run_id, sorted(set(_strings(kept))))
        except SecretIndexLimitError as e:  # the step fails with the bound's code, never retried (review I4)
            return {"error": SECRET_INDEX_LIMIT, "message": str(e)}
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
    except UNREADABLE:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None


@dataclass
class _Reclassified:
    """Parent handles a child's schema makes sensitive, claimed again for the child (`_reclassify`)."""

    seed: uuid.UUID
    child: uuid.UUID
    root: uuid.UUID
    rows: list[tuple[NewClaim, str]] = field(default_factory=list)
    strings: set[str] = field(default_factory=set)


async def _reclassify(value: Any, shape: Shape, fetch: Fetch, made: _Reclassified, pointer: str = "") -> Any:
    """`value` with every parent handle the child's schema makes sensitive (`shape`) replaced by a claim of the child,
    tainted whole, its text indexed (§3.4, §3.7): a claim made for its size only is plain, and nothing indexed it,
    but the child takes it for sensitive. One tainted whole already was indexed when it was made, and stays."""
    handle = ClaimRef.of(value)
    if handle is not None:
        if not shape.tainted:
            return value
        stored = await part(handle, fetch)
        if stored is None or stored.sensitive_pointers == ("",):
            return value
        claim_id = uuid.uuid5(made.seed, "reclassified:" + pointer)
        made.rows.append((NewClaim(claim_id, stored.value, ("",), made.child, made.root), pointer))
        made.strings.update(_strings((await resolve_value(value, fetch)).value))
        return ClaimRef(str(claim_id)).to_json()
    if isinstance(value, dict):
        return {
            k: await _reclassify(v, shape.field(k), fetch, made, pointer + "/" + escape(k)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [await _reclassify(v, shape.element(), fetch, made, f"{pointer}/{i}") for i, v in enumerate(value)]
    return value


async def child_input(data: ChildInput, store: ClaimStore) -> ChildInputResult:
    """`claims.child_input` (§3.4, §3.5): the calling run's input for its child, checked against the child's schema
    with its values resolved, then split for the child with the run's own handles left in place, except those the
    child's schema makes sensitive, which are claimed again for the child (`_reclassify`); the run's handles, and the
    claims they nest, are granted to the child, and the new claims' secrets join the tree's index. With no version to
    read the schema from, the crossing fails here: the child never starts, so its history never holds the input
    unsplit."""
    tenant, run = caller()
    schema = await store.input_schema(tenant, data.version_id)
    if schema is None:
        raise ApplicationError(NO_CHILD_VERSION, type=VERSION_UNUSABLE, non_retryable=True)
    fetch = _fetcher(store, tenant, run)
    seed = uuid.uuid5(_INPUTS, data.child_run_id)
    made = _Reclassified(seed, uuid.UUID(data.child_run_id), uuid.UUID(data.root_run_id))
    try:
        resolved = await resolve_value(data.value, fetch)
        refused = reasons(schema, resolved.value)
        if refused:
            return ChildInputResult(reasons=refused)
        value = await _reclassify(data.value, from_schema(schema), fetch, made)
    except UNREADABLE:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    try:
        done = split(
            value,
            schema,
            lambda pointer: str(uuid.uuid5(seed, pointer)),
            known=(await secrets_of(store, tenant, data.root_run_id)).matcher,
            handles=True,
        )
    except ForgedHandleError:
        return ChildInputResult(reasons=[FORGED])
    rows = made.rows + [
        (NewClaim(uuid.UUID(c.id), c.value, ("",) if c.tainted else (), made.child, made.root), c.pointer)
        for c in done.claims
    ]  # the reclassified first: the split's may nest them
    try:
        await store.remember(tenant, data.root_run_id, sorted(made.strings | set(done.secrets)))
    except SecretIndexLimitError as e:  # the step fails with the bound's code, never retried (review I4)
        raise ApplicationError(str(e), type=SECRET_INDEX_LIMIT, non_retryable=True) from None
    if rows:
        await store.write_inputs(tenant, rows)
    try:
        await _granted(store, tenant, run, data.child_run_id, data.value, data.root_run_id)
    except UNREADABLE:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    return ChildInputResult(trigger=done.envelope)


async def spill(data: SpillInput, store: ClaimStore) -> None:
    """`claims.spill` (§5.2): the workflow's values written as size claims owned by its run, untainted (the workflow
    holds nothing sensitive in plain), before a command carries their handles. Written again, a claim must hold the
    same content (hash-checked), or nothing is written."""
    tenant, run = caller()
    rows: dict[str, list[NewClaim]] = {}
    for entry in data.claims:
        value: Any
        kind = entry.get("kind", "spill")
        if "assemble" in entry:  # a collection as one list, from its segments (§5.3)
            value = await assembled(entry["assemble"], lambda claim_id: _stored(claim_id, store, tenant, run))
            claim = NewClaim(uuid.UUID(entry["id"]), value, (), uuid.UUID(run), uuid.UUID(data.root_run_id or run))
            rows.setdefault(kind, []).append(claim)
            continue
        if "concat" in entry:  # a list written in parts: joined, so its handle addresses each item by position
            value = [item for part in entry["concat"] for item in await _stored(part, store, tenant, run)]
            claim = NewClaim(uuid.UUID(entry["id"]), value, (), uuid.UUID(run), uuid.UUID(data.root_run_id or run))
            rows.setdefault(kind, []).append(claim)
            continue
        value = entry["value"]
        if entry.get("prev"):  # a container claimed again: its earlier keys are read through the claim before
            value = {**await _forwarding(entry["prev"], store, tenant, run), **value}
        claim = NewClaim(uuid.UUID(entry["id"]), value, (), uuid.UUID(run), uuid.UUID(data.root_run_id or run))
        rows.setdefault(kind, []).append(claim)
    for kind, new in rows.items():
        await store.write(tenant, new, kind=kind, step_id=data.step_id, iteration_key=data.iteration_key)


async def _stored(claim_id: str, store: ClaimStore, tenant: str, run: str) -> Any:
    try:
        return (await store.fetch(tenant, run, claim_id)).value
    except UNREADABLE:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None


async def _forwarding(prev: str, store: ClaimStore, tenant: str, run: str) -> dict[str, Any]:
    """A container's earlier claim, as handles: each key to where its value is (§5.3), the earlier claim or the one it
    forwarded to already, so any key is read in two hops at most."""
    try:
        before = (await store.fetch(tenant, run, prev)).value
    except UNREADABLE:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    return {
        k: v if ClaimRef.of(v) is not None else ClaimRef(prev, "/" + escape(k)).to_json() for k, v in before.items()
    }


async def message(data: MessageInput, store: ClaimStore) -> MessageResult:
    """`claims.message`: a failure's message (`flow.fail`), as it may be recorded: its handles resolved, and every
    secret the run knows masked, against the index as it is now (§3.7, §4.6), a literal's too: it may repeat a secret
    learned since it was written. The workflow holds no secret to mask with, and the message becomes the run's
    error, its result's and its failure handler's."""
    tenant, run = caller()
    try:
        found = await resolve_value(data.value, _fetcher(store, tenant, run))
    except UNREADABLE:
        raise ApplicationError(UNAVAILABLE, type=CLAIM_UNAVAILABLE, non_retryable=True) from None
    value = "" if found.value is MISSING or found.value is None else found.value
    text = value if isinstance(value, str) else json.dumps(value)
    return MessageResult((await secrets_of(store, tenant, data.root_run_id)).matcher.mask(text, REDACTED))
