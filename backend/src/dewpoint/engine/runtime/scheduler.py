# SPDX-License-Identifier: Apache-2.0
"""The scheduler (spec §6): node and edge states per scope, readiness, edge resolution, dead-path elimination, loop
iterations and how a run ends. It decides nothing about values or effects: the workflow runs each ready step and
reports how it ended. It is deterministic: its dicts are filled in a fixed order, and its ready queue is ordered by
(scope, topological index).

A scope is the root, or one loop iteration: `()` or `(("loop2", 7), ("loop5", 3))`. Branches don't open scopes, so
paths that split at an `if` meet again in the same scope. Each node runs or dies exactly once per scope.

Loops over more than `INLINE_ITEMS` items run in batches (2a-3b): the loop hands out one `Batch` at a time, which the
workflow runs as a child execution, and takes back its results. A batch child's scheduler runs one slice of the loop
(`start_batch`) over read-only copies of the loop's enclosing scopes, so its iteration keys are the inline ones.

Every iteration and filter item is debited from the execution's `Budget` (spec §6, one counter per logical run). An
iteration that can't be debited waits for budget, or ends the loop at the cap. A settled iteration's scope is pruned
once its loop has taken its result: only open scopes stay, which keeps a continue-as-new snapshot small.

Open iterations are capped per execution (engine 2b spec §5.3): at most the version's `OPEN_SCOPES_CAP_v` open
iteration scopes, plus one reserved per nesting level (`D`) for the progress path, the oldest open iteration at each
level. A loop step inside an iteration starts only when its loop can open an iteration at once (it waits, queued,
holding nothing); root-region loop steps are never deferred; a batch-mode loop inside an iteration holds its slot
until it ends. The deepest iteration on the path can always open one of its own loop's iterations, so it completes,
frees its scopes, and the path moves on.

The scheduler keeps the variables: numbered versions (the defaults are 0; each root `set_variables` makes the next).
A loop step inside an iteration captures the version it became ready under, and reads it when it starts, however
long the cap deferred it; every other step reads the current ones. While a queued step names an older version, each
write since keeps what it replaced (an undo record), and the snapshot keeps them too.

The live state (engine 2b spec §5.3, component 5) is every value a snapshot holds inline, the trigger aside: results
and items of open scopes, loops' item lists and what they collected, the variables and their undo records. Each is
counted at its compact JSON size as it enters and uncounted as it leaves (`live`); a restore counts again
(`recount`), and the two agree. After every change, while it passes LIVE_BUDGET, the largest spillable container
(past HANDLE_MAX) is claimed (`take_spills`, then `spilled`), ties broken by scheduling order: a scope's result set or
its item, the variables, an undo record. What's on its way to a claim still counts, and is still read inline, until
its claim is written. A reference into a claimed container reads by handle (`result_of`, `vars`): the workflow never
reads a claim. A scope's result set and the variables are claimed again as they grow: each new claim forwards to the
one before (the activity writes it), so one handle reaches every part.

A snapshot (`snapshot_format` 2, engine 2b spec §5.3) holds states, not queues: one code per node and per edge in
region order, steps and loops by their topological index. Restoring rebuilds what's queued from those states, minus
what was handed out before the snapshot and is still running."""

import bisect
import heapq
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dewpoint.engine.handles import HANDLE_MAX, ClaimRef
from dewpoint.engine.registry.control import SET_VARIABLES
from dewpoint.engine.runtime.budget import LOCAL, Answer, Ask, Budget, Need
from dewpoint.engine.runtime.program import BODY, DONE, ERROR_PORT, Program, Step

ScopeKey = tuple[tuple[str, int], ...]
ITERATION_CAP = 100_000  # loop iterations and filter items across the whole logical run (spec §4.2)
ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"
CAP_MESSAGE = "This run reached its limit of 100,000 loop iterations."
SNAPSHOT_FORMAT = 2
OPEN_SCOPES_CAP = 100  # open iteration scopes per execution, besides the progress path's reservation (§5.3)
LIVE_BUDGET = 1_048_576  # the live state a snapshot may hold, at most (§5.3, component 5)
INLINE_FLOOR = 1_024  # above the budget, activities claim outputs larger than this (§5.4)
NIL = uuid.UUID(int=0)  # the owner of a container that isn't a step's: a scope's, the variables'
CLAIMS = uuid.UUID("2b1b5e11-0000-4000-8000-000000000535")  # containers' claim ids: from where they were claimed


class NodeState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"


class EdgeState(StrEnum):
    PENDING = "pending"
    LIVE = "live"
    DEAD = "dead"


SETTLED = frozenset({NodeState.DONE, NodeState.FAILED, NodeState.DEAD})
_NODE_CODE = {
    NodeState.WAITING: "w",
    NodeState.RUNNING: "r",
    NodeState.DONE: "d",
    NodeState.FAILED: "f",
    NodeState.DEAD: "x",
}
_NODE_FROM = {c: n for n, c in _NODE_CODE.items()}
_EDGE_CODE = {EdgeState.PENDING: "p", EdgeState.LIVE: "l", EdgeState.DEAD: "x"}
_EDGE_FROM = {c: e for e, c in _EDGE_CODE.items()}
_B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
NO_CAPTURE = ".."  # a scope's captures: two characters per loop step of its region, in region order


def _capture_code(version: int) -> str:
    if not 0 <= version < len(_B62) ** 2:
        raise ValueError(f"variable version {version} is past the capture encoding")
    return _B62[version // len(_B62)] + _B62[version % len(_B62)]


def _capture_from(code: str) -> int:
    return _B62.index(code[0]) * len(_B62) + _B62.index(code[1])


def _then_wake[**P, T](fn: Callable[P, T]) -> Callable[P, T]:
    """After a change from outside, the loops the cap held back open what they can (`_settle_wakes`)."""

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        out = fn(*args, **kwargs)
        self: Scheduler = args[0]  # type: ignore[assignment]
        self._settle_wakes()
        self._enforce_budget()  # whatever changed, the live state goes back under its budget (§5.3)
        return out

    return wrapper


def size(value: Any) -> int:
    """What a value adds to the live state: its compact JSON, as the payload converter writes it."""
    return len(json.dumps(value, separators=(",", ":")))


def claimed_codes(program: Program, region: uuid.UUID | None, keys: set[str]) -> str:
    """One character per step of `region`, in region order: "c" where its result is in the scope's claim."""
    return "".join("c" if program.steps[m].key in keys else "." for m in program.regions[region].members)


def iteration_key(scope: ScopeKey) -> str:
    """`loop2:7/loop5:3`; empty for the root."""
    return "/".join(f"{loop}:{index}" for loop, index in scope)


@dataclass(frozen=True, order=True)
class Instance:
    """One step in one scope."""

    scope: ScopeKey
    step: uuid.UUID


@dataclass(frozen=True)
class Failure:
    code: str
    message: str
    attempt: int = 1

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "attempt": self.attempt}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Failure":
        return cls(str(data["code"]), str(data["message"]), int(data.get("attempt", 1)))


@dataclass(frozen=True)
class ItemsRef:
    """A loop's items in a claimed list (§5.3: pending work is cursors): `n` of them, from position `first` of the
    list `handle` addresses. Item p is the handle extended by `first + p`: no list of handles is ever built."""

    handle: dict[str, Any]
    n: int
    first: int = 0

    def to_json(self) -> list[Any]:
        return [self.handle, self.n, self.first]

    @classmethod
    def from_json(cls, raw: list[Any]) -> "ItemsRef":
        return cls(raw[0], int(raw[1]), int(raw[2]))


def count(items: "list[Any] | ItemsRef") -> int:
    return items.n if isinstance(items, ItemsRef) else len(items)


def item_at(items: "list[Any] | ItemsRef", pos: int) -> Any:
    if isinstance(items, ItemsRef):
        listed = ClaimRef.of(items.handle)
        if listed is None:
            raise ValueError("a claimed list without a handle")
        return listed.extend(items.first + pos).to_json()
    return items[pos]


def sliced(items: "list[Any] | ItemsRef", start: int, stop: int) -> "list[Any] | ItemsRef":
    if isinstance(items, ItemsRef):
        return ItemsRef(items.handle, stop - start, items.first + start)
    return items[start:stop]


@dataclass
class Box:
    """A container's claims (§5.3): the part being claimed (`sealing`: it still counts, and is still read inline,
    until its claim is written), and the newest claim's handle (`head`), which reaches every part claimed so far.
    `claims`: how many were made, which numbers the next."""

    sealing: Any = None
    head: dict[str, Any] | None = None
    claims: int = 0
    sealing_size: int = field(default=0, compare=False)  # the part's size, measured once

    def seal(self, part: Any) -> None:
        self.sealing, self.sealing_size = part, size(part)

    def bytes(self) -> int:
        return self.sealing_size + (size(self.head) if self.head is not None else 0)

    def to_json(self) -> list[Any]:
        return [self.sealing, self.head, self.claims]

    @classmethod
    def from_json(cls, raw: list[Any] | None) -> "Box":
        if not raw:
            return cls()
        box = cls(None, raw[1], int(raw[2]))
        if raw[0] is not None:
            box.seal(raw[0])
        return box


@dataclass
class Undo:
    """What one root `set_variables` write replaced, kept while a queued loop step captured a version before it:
    `vals` ({name: [old]}, or [] when there was none), or `head` once claimed. `step` names the write by its
    topological index: its assignment names are static, so a claimed record is read by name."""

    step: int
    vals: dict[str, list[Any]] | None
    head: dict[str, Any] | None = None
    sealing: bool = False

    def bytes(self) -> int:
        return size(self.vals) if self.vals is not None else size(self.head)


@dataclass(frozen=True)
class Spill:
    """A container's part on its way to a claim, for `claims.spill`: `entry` is what the activity writes."""

    owner: Instance  # the scope's (step NIL), or a loop step's
    which: str  # r, t: a scope's results, its item; v: the variables; u: an undo record; i: a loop's item list
    first: int  # the claim's number in its container
    entry: dict[str, Any]


@dataclass
class Scope:
    key: ScopeKey
    region: uuid.UUID | None
    nodes: dict[uuid.UUID, NodeState]
    edges: dict[int, EdgeState]
    results: dict[str, dict[str, Any]]  # step key -> {"output": …} and/or {"error": …} (the presence contract)
    item: Any = None
    index: int | None = None
    failure: Failure | None = None  # the unhandled failure that ended this scope
    frozen: bool = False  # an enclosing scope a batch child reads, and never runs
    seq: int = 0  # its opening order: the oldest open iterations make the progress path (§5.3)
    reserved: bool = False  # opened from its level's reserved scope
    rbox: Box = field(default_factory=Box)  # its results' claims (§5.3)
    item_sealing: bool = False  # its item is being claimed
    claimed: str = ""  # a frozen scope: which results are in its claim (`claimed_codes`)

    @property
    def settled(self) -> bool:
        return self.failure is not None or all(s in SETTLED for s in self.nodes.values())


@dataclass
class LoopRun:
    """A loop node's iterations: opened in order, at most `concurrency` at a time. `offset` is the index of
    `items[0]` (a batch child runs a slice). With `batch`, the items run in children of that many, one at a time."""

    instance: Instance
    items: list[Any] | ItemsRef
    concurrency: int
    stop_on_error: bool
    offset: int = 0
    batch: int = 0
    next: int = 0  # the next item to open, as a position in `items`
    open: list[int] = field(default_factory=list)  # open iterations, by absolute index
    collecting: set[int] = field(default_factory=set)  # settled iterations whose `collect` is being evaluated
    collected: list[Any] = field(default_factory=list)  # per item of `items`
    failures: list[dict[str, Any]] = field(default_factory=list)
    running_batch: int | None = None  # the start of the batch a child is running
    waiting: bool = False  # the next iteration waits for budget
    items_sealing: bool = False  # its inline list is being claimed: it waits for the claim, then reads by handle


@dataclass(frozen=True)
class Collect:
    """An iteration settled without an unhandled failure: evaluate the loop's `collect` in `scope`."""

    loop: Instance
    index: int
    scope: ScopeKey


@dataclass(frozen=True)
class Batch:
    """A batch of a loop's items, for a child: items `start` .. `start + len(items)`."""

    loop: Instance
    start: int
    items: list[Any] | ItemsRef


@dataclass(frozen=True)
class BatchOutcome:
    """What a batch child's slice produced: the collected values, the failed iterations, and the failure that stopped
    it under `on_item_error: stop`."""

    collected: list[Any]
    failures: list[dict[str, Any]]
    stopped: Failure | None = None


@dataclass(frozen=True)
class OuterScope:
    """An enclosing scope, as a batch child reads it: the results its region can reference, and the loop item."""

    key: ScopeKey
    results: dict[str, dict[str, Any]]
    item: Any = None
    index: int | None = None
    chain: dict[str, Any] | None = None  # the handle to its claimed results, if any were claimed (§5.3)
    claimed: str = ""  # which results are in that claim (`claimed_codes`)


@dataclass(frozen=True)
class RunEnd:
    status: str  # succeeded | failed | deadline_exceeded | cancelled
    failure: Failure | None = None
    stopped: bool = False  # ended by a stop node: workflow outputs are still evaluated

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failure": self.failure.to_json() if self.failure else None,
            "stopped": self.stopped,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RunEnd":
        failure = data.get("failure")
        return cls(str(data["status"]), Failure.from_json(failure) if failure else None, bool(data.get("stopped")))


class Scheduler:
    def __init__(self, program: Program, *, budget: Budget | None = None, prefix: str = "") -> None:
        self.program = program
        self.prefix = prefix  # the execution's workflow id: what its containers' claim ids derive from
        self.budget = budget if budget is not None else Budget(ITERATION_CAP, root=True)
        self.scopes: dict[ScopeKey, Scope] = {}
        self.loops: dict[Instance, LoopRun] = {}
        self.ended: RunEnd | None = None
        self.batch_loop: Instance | None = None  # a batch child: the loop whose slice it runs
        self.outcome: BatchOutcome | None = None  # a batch child: its slice's result, once it's done
        self._ready: list[Instance] = []
        self._collects: list[Collect] = []
        self._batches: list[Batch] = []
        self._cancels: list[Instance] = []
        self._settled: list[tuple[Instance, dict[str, Any]]] = []
        self._budget_waits: dict[str, Instance] = {}  # a need's key -> the loop waiting for it
        self._topo_of_key = {s.key: s.topo for s in program.steps.values()}
        self._members: dict[uuid.UUID | None, tuple[uuid.UUID, ...]] = {
            region: r.members for region, r in program.regions.items()
        }
        self._by_topo = {s.topo: s.id for s in program.steps.values()}
        self._edge_orders: dict[uuid.UUID | None, list[int]] = {}
        # handed out and not settled: what restoring mustn't queue again (a snapshot holds no queue)
        self._handed: set[Instance] = set()
        self._collects_out: set[tuple[Instance, int]] = set()
        self._batches_out: set[tuple[Instance, int]] = set()
        # the open-iteration cap (§5.3), pinned in the version, and the reservation: one scope per nesting level
        self.cap = program.open_scopes_cap or OPEN_SCOPES_CAP
        self.reserve = program.depth
        self._seq = 0
        self._n_open = 0  # open iteration scopes, frozen ones aside
        self._capped: set[Instance] = set()  # loops the cap holds back
        self._freed = False  # a scope or a slot was freed: the capped loops try again
        self._waking = False
        self._starting: dict[Instance, bool] = {}  # a released loop step -> whether it took its level's reserved scope
        self._held: dict[Instance, bool] = {}  # a batch-mode loop inside an iteration: it holds its slot to the end
        # queued loop steps inside iterations, not started: by scope in scheduling order, and all in one heap
        self._deferred: set[Instance] = set()
        self._deferred_by_scope: dict[ScopeKey, list[Instance]] = {}
        self._deferred_heap: list[tuple[tuple[Any, ...], Instance]] = []
        # the variables, their versions, and the captures of queued loop steps inside iterations
        self._loop_members = {
            region: tuple(m for m in members if m in program.regions) for region, members in self._members.items()
        }
        self._vars: dict[str, Any] = {}
        self.vars_version = 0
        self.undo: dict[int, Undo] = {}  # write k (version k -> k + 1): what it replaced
        self.vbox = Box()  # the variables' claims
        self._var_names = sorted(
            set(program.graph.settings.vars_schema.get("properties", {}))
            | {n for st in program.steps.values() if st.ref == SET_VARIABLES for n in st.config.get("assignments", {})}
        )  # every name a variable can have: the schema's, and what the version's writes assign
        self._spills: list[Spill] = []
        self._spills_out: set[tuple[Instance, str, int]] = set()
        self._captures: dict[Instance, int] = {}  # a queued loop step -> the version it became ready under
        self._released: dict[Instance, int] = {}  # handed out, its unit not yet started
        self._vrefs: dict[int, int] = {}  # a captured version -> the queued or released loop steps that name it
        self._live = size(self._vars)  # see `live`

    @property
    def iterations(self) -> int:
        """Iterations and filter items this execution used, its settled children's included."""
        return self.budget.used

    # --- the workflow's side ---------------------------------------------------------------------------------------

    @_then_wake
    def start(self) -> None:
        self._open_scope((), None)

    def start_batch(
        self,
        loop_step: uuid.UUID,
        outer: list[OuterScope],
        items: list[Any] | ItemsRef,
        *,
        offset: int,
        concurrency: int,
        stop_on_error: bool,
    ) -> None:
        """A batch child: rebuild the loop's enclosing scopes read-only, outermost first, and run items `offset` ..
        `offset + len(items)` of it. The loop's own scope is the last one."""
        chain = self.program.chain(self.program.steps[loop_step].region)  # innermost first
        for depth, o in enumerate(outer):
            region = chain[len(outer) - 1 - depth]
            frozen = Scope(o.key, region, {}, {}, dict(o.results), o.item, o.index, frozen=True, claimed=o.claimed)
            frozen.rbox.head = o.chain
            self.scopes[o.key] = frozen
            self._live += self._scope_bytes(frozen)
        loop_inst = Instance(outer[-1].key, loop_step)
        self.batch_loop = loop_inst
        items = items if isinstance(items, ItemsRef) else list(items)
        loop = LoopRun(loop_inst, items, concurrency, stop_on_error, offset=offset, collected=[None] * count(items))
        self.loops[loop_inst] = loop
        self._live += self._loop_bytes(loop)
        self._advance(loop)
        self._enforce_budget()

    def take_ready(self) -> list[Instance]:
        """Ready steps, in (scope, topological) order. They are running from now on. A loop step inside an iteration
        is handed out only when its loop can open an iteration at once; until then it stays queued (§5.3)."""
        ready = []
        for inst in self._ready:
            if self._iter_loop(inst):
                self._defer(inst)
            else:
                ready.append(inst)
        self._ready = []
        ready += self._start_deferred()
        ready.sort(key=self.order)
        for inst in ready:
            self.scopes[inst.scope].nodes[inst.step] = NodeState.RUNNING
        self._handed.update(ready)
        return ready

    def take_collects(self) -> list[Collect]:
        out, self._collects = self._collects, []
        self._collects_out.update((c.loop, c.index) for c in out)
        return out

    def take_batches(self) -> list[Batch]:
        out, self._batches = self._batches, []
        self._batches_out.update((b.loop, b.start) for b in out)
        return out

    def take_settled(self) -> list[tuple[Instance, dict[str, Any]]]:
        """Steps that succeeded or failed since the last call, with their result as it was when they settled (loops
        completed by their last iteration included)."""
        out, self._settled = self._settled, []
        return out

    def take_cancels(self) -> list[Instance]:
        """Running steps whose scope ended (a failure, a stop, the deadline): their work must be cancelled, and
        nothing they report later counts."""
        out, self._cancels = sorted(self._cancels, key=self.order), []
        return out

    def take_spills(self) -> list[Spill]:
        """Containers' parts to claim, as units: they only shrink the state, so a drain still starts them."""
        out, self._spills = self._spills, []
        self._spills_out.update((sp.owner, sp.which, sp.first) for sp in out)
        return out

    @_then_wake
    def spilled(self, owner: Instance, which: str, first: int) -> None:
        """A container's part is in its claim now: its handle replaces it."""
        self._spills_out.discard((owner, which, first))
        handle = ClaimRef(self._claim_id(owner, which, first)).to_json()
        if which in ("r", "t"):
            sc = self.scopes.get(owner.scope)
            if sc is None:
                return
            if which == "r" and sc.rbox.sealing is not None and sc.rbox.claims == first:
                before = sc.rbox.bytes()
                sc.rbox = Box(None, handle, first + 1)
                self._live += sc.rbox.bytes() - before
            elif which == "t" and sc.item_sealing:
                self._live += size(handle) - size(sc.item)
                sc.item, sc.item_sealing = handle, False
        elif which == "i":
            loop = self.loops.get(owner)
            if loop is None or not loop.items_sealing or not isinstance(loop.items, list):
                return
            listed = ItemsRef(handle, len(loop.items))
            self._live += size(listed.to_json()) - size(loop.items)
            loop.items, loop.items_sealing = listed, False
            self._advance(loop)
        elif which == "v" and self.vbox.sealing is not None and self.vbox.claims == first:
            before = self.vbox.bytes()
            self.vbox = Box(None, handle, first + 1)
            self._live += self.vbox.bytes() - before
        elif which == "u" and first in self.undo and self.undo[first].sealing:
            rec = self.undo[first]
            before = rec.bytes()
            rec.vals, rec.head, rec.sealing = None, handle, False
            self._live += rec.bytes() - before
            self._gc_versions()

    def give_back(
        self, steps: list[Instance], collects: list[Collect], batches: list[Batch], spills: list[Spill] | None = None
    ) -> None:
        """Work handed over but never started (drain mode, the in-flight cap): it waits in the queues again, first,
        for the continued run."""
        self._ready = steps + self._ready
        self._collects = collects + self._collects
        self._batches = batches + self._batches
        self._handed -= set(steps)
        for inst in steps:  # a loop step handed out and not started gives its slot back, and waits again
            self._starting.pop(inst, None)
            if inst in self._released:
                self._captures[inst] = self._released.pop(inst)
        self._collects_out -= {(c.loop, c.index) for c in collects}
        self._batches_out -= {(b.loop, b.start) for b in batches}
        self._spills = list(spills or []) + self._spills
        self._spills_out -= {(sp.owner, sp.which, sp.first) for sp in spills or []}

    @_then_wake
    def succeed(self, inst: Instance, output: Any, ports: tuple[str, ...] | None = None) -> None:
        """The step succeeded. `ports`: the normal ports whose edges are live (if/switch pick one); all by default."""
        self._handed.discard(inst)
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.DONE
        scope.results[step.key] = {"output": output}
        self._live += size(scope.results[step.key])
        self._settled.append((inst, scope.results[step.key]))
        live = set(step.ports if ports is None else ports)
        self._resolve(scope, step, {p for p in step.ports if p in live} - {BODY})
        self._after_settle(scope)

    @_then_wake
    def fail(self, inst: Instance, failure: Failure) -> None:
        """The step failed. Its `on_error` decides: `port` follows the error edges, `continue` the normal ones, and
        `fail` ends the scope: the run in the root, the iteration in a loop body. Either handled way, the step has an
        error and no output, so `has(steps.x.output)` is false (spec §5.3) and a reference's default applies."""
        self._handed.discard(inst)
        if self._starting.pop(inst, None) is not None:  # a loop step that failed before its loop opened
            self._freed = True
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.FAILED
        self._settled.append((inst, {"error": failure.to_json()}))
        if step.on_error == "port":
            scope.results[step.key] = {"error": failure.to_json()}
            self._live += size(scope.results[step.key])
            self._resolve(scope, step, {ERROR_PORT})
        elif step.on_error == "continue":
            scope.results[step.key] = {"error": failure.to_json()}
            self._live += size(scope.results[step.key])
            self._resolve(scope, step, set(step.ports) - {BODY})
        else:
            self._fail_scope(scope, failure)
            return
        self._after_settle(scope)

    @_then_wake
    def open_loop(
        self, inst: Instance, items: list[Any] | ItemsRef, *, concurrency: int, stop_on_error: bool, batch: int = 0
    ) -> None:
        """The loop node's `items` are known: open its first iterations, or hand out its first batch. An empty list
        completes it at once."""
        scope, step = self._running(inst)
        if scope is None:
            return
        items = items if isinstance(items, ItemsRef) else list(items)
        loop = LoopRun(inst, items, concurrency, stop_on_error, batch=batch, collected=[None] * count(items))
        self.loops[inst] = loop
        self._live += self._loop_bytes(loop)
        if batch and self._iter_loop(inst):  # it opens no scope: it holds its slot until it ends (§5.3)
            self._held[inst] = self._starting.pop(inst, False)
        self._advance(loop)

    @_then_wake
    def collected(self, loop_inst: Instance, index: int, value: Any) -> None:
        self._collects_out.discard((loop_inst, index))
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        loop.open.remove(index)
        loop.collecting.discard(index)
        self._live += size(value) - size(loop.collected[index - loop.offset])
        loop.collected[index - loop.offset] = value
        self._prune(self._iteration_scope(loop, index))
        self._advance(loop)

    @_then_wake
    def collect_failed(self, loop_inst: Instance, index: int, failure: Failure) -> None:
        """`collect` couldn't be evaluated: the iteration failed after all."""
        self._collects_out.discard((loop_inst, index))
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        self._iteration_failed(loop, index, failure)

    @_then_wake
    def batch_done(self, loop_inst: Instance, start: int, outcome: BatchOutcome) -> None:
        """A batch child finished its slice: take its results, then hand out the next batch or complete the loop. A
        slice stopped by a failed iteration (`on_item_error: stop`) fails the loop."""
        self._batches_out.discard((loop_inst, start))
        loop = self.loops.get(loop_inst)
        if loop is None or loop.running_batch != start:
            return
        loop.running_batch = None
        for n, value in enumerate(outcome.collected):
            self._live += size(value) - size(loop.collected[start + n])
            loop.collected[start + n] = value
        for f in outcome.failures:
            self._fail_entry(loop, f)
        if outcome.stopped is not None:
            self._abort(loop, outcome.stopped)
            return
        self._advance(loop)

    def cut_batch(self, loop_inst: Instance, start: int, end: int) -> None:
        """The running batch that starts at `start` ends at `end` instead: the items after it didn't fit in one payload
        with it (engine 2b spec §5.2). They go in the loop's next batch."""
        loop = self.loops.get(loop_inst)
        if loop is not None and loop.running_batch == start and start < end < loop.next:
            loop.next = end

    @_then_wake
    def batch_failed(self, loop_inst: Instance, start: int, failure: Failure) -> None:
        """A batch child failed as a whole (not one of its iterations): the loop fails with it."""
        self._batches_out.discard((loop_inst, start))
        loop = self.loops.get(loop_inst)
        if loop is None or loop.running_batch != start:
            return
        loop.running_batch = None
        self._abort(loop, failure)

    @_then_wake
    def finish(self, inst: Instance, end: RunEnd, output: Any = None) -> None:
        """A stop or fail node: record its result, then end the run (it has no edges to resolve)."""
        self._handed.discard(inst)
        scope, step = self._running(inst)
        if scope is None:
            return
        if end.failure is None:
            scope.nodes[step.id] = NodeState.DONE
            scope.results[step.key] = {"output": output}
        else:
            scope.nodes[step.id] = NodeState.FAILED
            scope.results[step.key] = {"error": end.failure.to_json()}
        self._live += size(scope.results[step.key])
        self._settled.append((inst, scope.results[step.key]))
        self.end(end)

    def end(self, end: RunEnd) -> None:
        """A stop or fail node, or the deadline: the run ends now. Every running step is cancelled."""
        if self.ended is not None:
            return
        self.ended = end
        queued = set(self._ready) | self._deferred
        for scope in self.scopes.values():
            for node_id, state in scope.nodes.items():
                if state == NodeState.RUNNING and Instance(scope.key, node_id) not in queued:
                    self._cancels.append(Instance(scope.key, node_id))
        self._ready = []
        self._clear_deferred(())
        self._starting.clear()
        self._held.clear()
        self._capped.clear()
        self._captures.clear()
        self._released.clear()
        self._vrefs.clear()
        self._gc_versions()
        self._spills = []
        self._batches = []
        self.budget.drop_local()  # a loop waiting for its next iteration opens none now
        self._budget_waits.clear()

    @_then_wake
    def answer_budget(self) -> tuple[list[Answer], Ask | None]:
        """Serve the budget's waiting needs. The loops' own answers are applied here: a granted iteration opens, a
        refused one ends its loop at the cap. The other answers (a filter's, a child's) and the Ask for the parent
        are the workflow's to deliver."""
        others: list[Answer] = []
        answers, ask = self.budget.decide()
        for a in answers:
            inst = self._budget_waits.pop(a.need.key, None) if a.need.requester == LOCAL else None
            if inst is None:
                others.append(a)
                continue
            loop = self.loops.get(inst)
            if loop is None:  # the loop ended meanwhile: give back what it was granted
                self.budget.used -= a.granted
                continue
            loop.waiting = False
            if not a.granted:
                self._abort(loop, Failure(ITERATION_CAP_EXCEEDED, CAP_MESSAGE))
                continue
            room = self._room(loop)
            if room is None:  # granted, but the cap is full: it gives the grant back and waits for a scope
                self.budget.used -= a.granted
                self._capped.add(loop.instance)
                continue
            self._open_next(loop, reserved=room)
            self._advance(loop)
        return others, ask

    def step(self, inst: Instance) -> Step:
        return self.program.steps[inst.step]

    def scope(self, key: ScopeKey) -> Scope:
        return self.scopes[key]

    # --- internals -------------------------------------------------------------------------------------------------

    def order(self, inst: Instance) -> tuple[Any, ...]:
        """The ready queue's order: scope (by its loops' topological index, then item index), then the step's (a
        scope's own containers first)."""
        step = self.program.steps.get(inst.step)
        return (tuple((self._topo_of_key[loop], i) for loop, i in inst.scope), step.topo if step else -1)

    def _running(self, inst: Instance) -> tuple[Scope | None, Step]:
        """The instance's scope, or None when its result no longer counts (the scope failed, the run ended)."""
        step = self.program.steps[inst.step]
        scope = self.scopes.get(inst.scope)
        if self.ended is not None or scope is None or scope.failure is not None or scope.frozen:
            return None, step
        if scope.nodes.get(inst.step) != NodeState.RUNNING:
            raise ValueError(f"`{step.key}` isn't running in {iteration_key(inst.scope)!r}")
        return scope, step

    def _open_scope(
        self,
        key: ScopeKey,
        region: uuid.UUID | None,
        item: Any = None,
        index: int | None = None,
        *,
        reserved: bool = False,
    ) -> None:
        members = self._members[region]
        member_set = set(members)
        edges: dict[int, EdgeState] = {}
        for node_id in members:
            for e in self.program.steps[node_id].ins:
                source = self.program.edges[e].source
                # an edge from this region's own loop node is its body edge: live for every iteration
                edges[e] = EdgeState.LIVE if source not in member_set and source == region else EdgeState.PENDING
        scope = Scope(key, region, dict.fromkeys(members, NodeState.WAITING), edges, {}, item, index, reserved=reserved)
        if key:
            self._seq += 1
            scope.seq = self._seq
            self._n_open += 1
        self.scopes[key] = scope
        self._live += self._scope_bytes(scope)
        for node_id in members:
            self._check_ready(scope, node_id)
        self._after_settle(scope)

    def _prune(self, key: ScopeKey) -> None:
        """Forget a settled iteration's scope and every scope nested in it: its loop has what it needs."""
        self._drop_captures(key)
        for k in [k for k in self.scopes if k[: len(key)] == key]:
            if k and not self.scopes[k].frozen:
                self._n_open -= 1
                self._freed = True
            self._live -= self._scope_bytes(self.scopes[k])
            del self.scopes[k]

    def _resolve(self, scope: Scope, step: Step, live_ports: set[str]) -> None:
        """Resolve every outgoing edge of `step` in `scope` exactly once. Body edges belong to the iterations."""
        work = [(step, live_ports)]
        while work:
            source, live = work.pop()
            targets: list[uuid.UUID] = []
            for port, ids in source.out.items():
                if port == BODY and source.id in self.program.regions:
                    continue
                for e in ids:
                    if e in scope.edges:
                        scope.edges[e] = EdgeState.LIVE if port in live else EdgeState.DEAD
                        targets.append(self.program.edges[e].target)
            for target in sorted(set(targets), key=lambda n: self.program.steps[n].topo):
                dead = self._check_ready(scope, target)
                if dead is not None:
                    work.append((dead, set()))

    def _check_ready(self, scope: Scope, node_id: uuid.UUID) -> Step | None:
        """Queue the node when every incoming edge is resolved and one is live. Returns it when it died instead."""
        if scope.nodes[node_id] != NodeState.WAITING:
            return None
        step = self.program.steps[node_id]
        states = [scope.edges[e] for e in step.ins if e in scope.edges]
        if any(s == EdgeState.PENDING for s in states):
            return None
        if not states or any(s == EdgeState.LIVE for s in states):
            scope.nodes[node_id] = NodeState.RUNNING  # queued; take_ready() hands it over
            inst = Instance(scope.key, node_id)
            self._ready.append(inst)
            if self.batch_loop is None and self._iter_loop(inst):  # its variables, as of now (§5.3)
                self._captures[inst] = self.vars_version
                self._vrefs[self.vars_version] = self._vrefs.get(self.vars_version, 0) + 1
            return None
        scope.nodes[node_id] = NodeState.DEAD
        return step

    def _fail_scope(self, scope: Scope, failure: Failure, *, report: bool = True) -> None:
        """An unhandled failure ends its scope: waiting steps die, running ones are cancelled, and so is every scope
        nested inside it. `report`: tell the loop the iteration failed (not when the loop itself is stopping it)."""
        scope.failure = failure
        self._drop_captures(scope.key)
        queued = set(self._ready)
        for key in [k for k in self.scopes if k[: len(scope.key)] == scope.key]:
            inner = self.scopes[key]
            if key != scope.key and inner.failure is None:
                inner.failure = failure
            for node_id, state in inner.nodes.items():
                inst = Instance(key, node_id)
                if state == NodeState.RUNNING and inst not in queued and inst not in self._deferred:
                    self._cancels.append(inst)
                    self._handed.discard(inst)
                if state in (NodeState.RUNNING, NodeState.WAITING):
                    inner.nodes[node_id] = NodeState.DEAD
        self._ready = [r for r in self._ready if r.scope[: len(scope.key)] != scope.key]
        self._clear_deferred(scope.key)
        for inst in [i for i in self._starting if i.scope[: len(scope.key)] == scope.key]:
            del self._starting[inst]
            self._freed = True
        for inst in [i for i in self.loops if i.scope[: len(scope.key)] == scope.key]:
            self._drop_loop(self.loops[inst])
        if scope.key == ():
            self.end(RunEnd("failed", failure))
        elif report:
            self._iteration_settled(scope)

    def _drop_loop(self, loop: LoopRun) -> None:
        """The loop ends: nothing it waits for is still wanted."""
        del self.loops[loop.instance]
        self._live -= self._loop_bytes(loop)
        self._capped.discard(loop.instance)
        if self._starting.pop(loop.instance, None) is not None or self._held.pop(loop.instance, None) is not None:
            self._freed = True  # its slot is free
        for key in [k for k, inst in self._budget_waits.items() if inst == loop.instance]:
            del self._budget_waits[key]
            self.budget.waiting = [n for n in self.budget.waiting if not (n.requester == LOCAL and n.key == key)]
        self._batches = [b for b in self._batches if b.loop != loop.instance]

    def _after_settle(self, scope: Scope) -> None:
        if scope.frozen:
            return
        if scope.key != () and scope.settled:
            self._iteration_settled(scope)
        elif scope.key == () and scope.settled and self.ended is None:
            self.ended = RunEnd("succeeded")

    def _iteration_scope(self, loop: LoopRun, index: int) -> ScopeKey:
        return (*loop.instance.scope, (self.program.steps[loop.instance.step].key, index))

    def _iteration_settled(self, scope: Scope) -> None:
        *outer, (loop_key, index) = scope.key
        loop_inst = Instance(tuple(outer), self.program.by_key[loop_key])
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open or index in loop.collecting:
            return
        if scope.failure is not None:
            self._iteration_failed(loop, index, scope.failure)
        else:
            loop.collecting.add(index)
            self._collects.append(Collect(loop_inst, index, scope.key))

    def _iteration_failed(self, loop: LoopRun, index: int, failure: Failure) -> None:
        loop.open.remove(index)
        loop.collecting.discard(index)
        self._prune(self._iteration_scope(loop, index))
        if loop.stop_on_error:
            self._abort(loop, failure)
            return
        self._fail_entry(loop, {"index": index, "code": failure.code, "message": failure.message})
        self._advance(loop)

    def _abort(self, loop: LoopRun, failure: Failure) -> None:
        """The loop ends early (an iteration failed under `stop`, or the run reached its iteration cap): its open
        iterations end first, running steps cancelled and queued ones dropped, and then the loop step fails, so its
        own `on_error` applies. Nothing the loop opened outlives it. In a batch child, its slice stops instead."""
        self._drop_loop(loop)
        for other in loop.open:
            key = self._iteration_scope(loop, other)
            self._fail_scope(self.scopes[key], failure, report=False)
            self._prune(key)
        if loop.instance == self.batch_loop:
            self._batch_over(loop, failure)
            return
        parent = self.scopes[loop.instance.scope]
        if parent.failure is None and self.ended is None:
            self.fail(loop.instance, failure)

    def _batch_over(self, loop: LoopRun, stopped: Failure | None) -> None:
        if self.ended is None:
            self.outcome = BatchOutcome(list(loop.collected), list(loop.failures), stopped)
            self.ended = RunEnd("succeeded")

    def _open_next(self, loop: LoopRun, *, reserved: bool = False) -> None:
        index = loop.offset + loop.next
        item = item_at(loop.items, loop.next)
        loop.next += 1
        loop.open.append(index)
        key = self._iteration_scope(loop, index)
        self._open_scope(key, loop.instance.step, item=item, index=index, reserved=reserved)

    def _advance(self, loop: LoopRun) -> None:
        """Open iterations up to the concurrency (or hand out the next batch), or complete the loop when every item
        is done. A loop whose inline list is on its way to a claim waits for it."""
        if loop.items_sealing:
            return
        n = count(loop.items)
        if loop.batch:
            if loop.running_batch is None and loop.next < n:
                start = loop.next
                loop.next = min(start + loop.batch, n)
                loop.running_batch = start
                self._batches.append(Batch(loop.instance, start, sliced(loop.items, start, loop.next)))
                return
        else:
            while loop.next < n and len(loop.open) < loop.concurrency and not loop.waiting:
                room = self._room(loop)
                if room is None:  # the cap: it opens once scopes are freed (`_settle_wakes`)
                    self._capped.add(loop.instance)
                    return
                if not self.budget.take(1):
                    loop.waiting = True
                    key = f"loop:{iteration_key(loop.instance.scope)}:{self.program.steps[loop.instance.step].key}"
                    self._budget_waits[key] = loop.instance
                    self.budget.request(Need(LOCAL, key, 1, 1))
                    return
                self._capped.discard(loop.instance)
                self._open_next(loop, reserved=room)
                if loop.instance not in self.loops:  # the iteration failed at once and stopped the loop
                    return
        if not loop.open and loop.next >= n and loop.running_batch is None and not loop.waiting:
            self._drop_loop(loop)
            if loop.instance == self.batch_loop:
                self._batch_over(loop, None)
                return
            output = {"items": loop.collected, "failures": loop.failures, "count": n}
            scope = self.scopes.get(loop.instance.scope)
            if scope is not None and scope.failure is None and self.ended is None:
                self.succeed(loop.instance, output, (DONE,))

    # --- the live state (engine 2b spec §5.3, component 5) -----------------------------------------------------------

    @property
    def live(self) -> int:
        """The values the snapshot holds inline, the trigger aside, as JSON: kept as they enter and leave."""
        return self._live

    def recount(self) -> int:
        """The same sum, counted from scratch: what a restore starts from, and what `live` must equal."""
        total = size(self._vars) + self.vbox.bytes() + sum(u.bytes() for u in self.undo.values())
        total += sum(self._scope_bytes(sc) for sc in self.scopes.values())
        return total + sum(self._loop_bytes(loop) for loop in self.loops.values())

    @staticmethod
    def _scope_bytes(sc: Scope) -> int:
        item = size(sc.item) if sc.item is not None else 0
        return sum(size(r) for r in sc.results.values()) + item + sc.rbox.bytes()

    @staticmethod
    def _loop_bytes(loop: LoopRun) -> int:
        items = size(loop.items.to_json()) if isinstance(loop.items, ItemsRef) else size(loop.items)
        return items + size(loop.collected) + size(loop.failures)

    def _enforce_budget(self) -> None:
        """Past LIVE_BUDGET, the largest spillable container goes to a claim, until what's on its way out brings the
        live state back under: the relief is counted only past the budget, so a change costs nothing below it."""
        if self.ended is not None:
            return
        while self._live > LIVE_BUDGET and self._live - self._relief() > LIVE_BUDGET:
            candidates = self._containers()
            if not candidates:
                break
            _, _, which, target = min(candidates, key=lambda c: (-c[0], c[1], c[2]))
            self._spill_container(which, target)

    def _containers(self) -> list[tuple[int, tuple[Any, ...], str, Any]]:
        """The spillable containers (past HANDLE_MAX), with none of theirs on its way: (bytes, scheduling order, kind,
        target)."""
        out: list[tuple[int, tuple[Any, ...], str, Any]] = []
        for sc in self.scopes.values():
            order = self.order(Instance(sc.key, NIL))
            n = sum(size(r) for r in sc.results.values())
            if n > HANDLE_MAX and sc.rbox.sealing is None:
                out.append((n, order, "r", sc))
            if sc.item is not None and not sc.item_sealing and ClaimRef.of(sc.item) is None:
                n = size(sc.item)
                if n > HANDLE_MAX:
                    out.append((n, order, "t", sc))
        for lp in self.loops.values():
            if isinstance(lp.items, list) and not lp.items_sealing:
                n = size(lp.items)
                if n > HANDLE_MAX:
                    out.append((n, self.order(lp.instance), "i", lp))
        root = self.order(Instance((), NIL))
        n = size(self._vars)
        if n > HANDLE_MAX and self.vbox.sealing is None:
            out.append((n, root, "v", None))
        for k, rec in self.undo.items():
            if rec.vals is not None and not rec.sealing and rec.bytes() > HANDLE_MAX:
                out.append((rec.bytes(), root, f"u{k:08d}", k))
        return out

    def _relief(self) -> int:
        """What the claims on their way will take out of the live state."""
        out = self.vbox.sealing_size + sum(u.bytes() for u in self.undo.values() if u.sealing)
        out += sum(size(lp.items) for lp in self.loops.values() if lp.items_sealing)
        for sc in self.scopes.values():
            out += sc.rbox.sealing_size + (size(sc.item) if sc.item_sealing else 0)
        return out

    def _claim_id(self, owner: Instance, which: str, first: int) -> str:
        """A container's claim id, from where it was claimed: a retry, a replay or a restore derives the same."""
        sc = self.scopes.get(owner.scope)
        seq = sc.seq if sc is not None and which in ("r", "t") else 0
        topo = self.program.steps[owner.step].topo if owner.step != NIL else -1
        return str(uuid.uuid5(CLAIMS, f"{self.prefix}/{which}/{iteration_key(owner.scope)}/{seq}/{topo}/{first}"))

    def _spill_container(self, which: str, target: Any) -> None:
        root = Instance((), NIL)
        if which == "r":
            sc: Scope = target
            owner, first = Instance(sc.key, NIL), sc.rbox.claims
            before = self._scope_bytes(sc)
            sc.rbox.seal(sc.results)
            if sc.frozen:  # its results are in its claim from now on, as the scope reads them
                keys = self._keys(sc.region)
                codes = sc.claimed or "." * len(keys)
                claimed = {k for k, c in zip(keys, codes, strict=True) if c == "c"} | set(sc.results)
                sc.claimed = claimed_codes(self.program, sc.region, claimed)
            sc.results = {}
            self._live += self._scope_bytes(sc) - before
            prev = ClaimRef.of(sc.rbox.head)
            entry = {
                "id": self._claim_id(owner, "r", first),
                "value": sc.rbox.sealing,
                "prev": prev.id if prev else None,
            }
            self._spills.append(Spill(owner, "r", first, entry))
        elif which == "i":
            lp: LoopRun = target
            lp.items_sealing = True
            entry = {"id": self._claim_id(lp.instance, "i", 0), "value": lp.items}
            self._spills.append(Spill(lp.instance, "i", 0, entry))
        elif which == "t":
            sc = target
            owner = Instance(sc.key, NIL)
            sc.item_sealing = True
            self._spills.append(Spill(owner, "t", 0, {"id": self._claim_id(owner, "t", 0), "value": sc.item}))
        elif which == "v":
            first = self.vbox.claims
            before = size(self._vars) + self.vbox.bytes()
            self.vbox.seal(self._vars)
            self._vars = {}
            self._live += size(self._vars) + self.vbox.bytes() - before
            prev = ClaimRef.of(self.vbox.head)
            entry = {
                "id": self._claim_id(root, "v", first),
                "value": self.vbox.sealing,
                "prev": prev.id if prev else None,
            }
            self._spills.append(Spill(root, "v", first, entry))
        else:  # an undo record
            k = int(target)
            self.undo[k].sealing = True
            self._spills.append(Spill(root, "u", k, {"id": self._claim_id(root, "u", k), "value": self.undo[k].vals}))

    def _keys(self, region: uuid.UUID | None) -> list[str]:
        return [self.program.steps[m].key for m in self._members[region]]

    def result_of(self, sc: Scope, name: str) -> Any:
        """A step's result as its scope holds it: inline, on its way to a claim (still read inline), or a handle into
        the scope's claimed results; `{}` when it has none (it didn't settle, or it died)."""
        found = sc.results.get(name)
        if found is not None:
            return found
        if sc.rbox.sealing is not None and name in sc.rbox.sealing:
            return sc.rbox.sealing[name]
        head = ClaimRef.of(sc.rbox.head)
        if head is not None and name in self.program.by_key:
            if sc.frozen:
                keys = self._keys(sc.region)
                if name in keys and sc.claimed and sc.claimed[keys.index(name)] == "c":
                    return head.extend(name).to_json()
            elif sc.nodes.get(self.program.by_key[name]) in (NodeState.DONE, NodeState.FAILED):
                return head.extend(name).to_json()
        return {}

    def claimed_in(self, sc: Scope) -> str:
        """`claimed_codes` for a scope, as a batch child reads it: which of its results are in its claim."""
        if sc.frozen:
            return sc.claimed
        if sc.rbox.head is None:
            return ""
        inline = set(sc.results) | set(sc.rbox.sealing or {})
        done = (NodeState.DONE, NodeState.FAILED)
        keys = {self.program.steps[m].key for m, st in sc.nodes.items() if st in done} - inline
        return claimed_codes(self.program, sc.region, keys)

    def _fail_entry(self, loop: LoopRun, entry: dict[str, Any]) -> None:
        """A failed iteration, listed in the loop's failures: the list grows by the entry, and a comma after the
        first."""
        self._live += size(entry) + (1 if loop.failures else 0)
        loop.failures.append(entry)

    # --- the open-iteration cap (engine 2b spec §5.3) --------------------------------------------------------------

    @property
    def open_scopes(self) -> int:
        """Open iteration scopes, frozen ones aside: never past `cap + reserve`."""
        return self._n_open

    def _room(self, loop: LoopRun) -> bool | None:
        """Whether `loop` may open an iteration now: False under the cap, True from its level's reserved scope, None
        not at all. A reserved scope is only for a loop on the progress path, one per level."""
        if loop.instance in self._starting:  # the slot it took when it was released
            return self._starting.pop(loop.instance)
        taken = self._taken()
        if taken < self.cap:
            return False
        if taken >= self.cap + self.reserve:
            return None
        level = len(loop.instance.scope) + 1
        if self._reserved_at(level):
            return None
        return True if loop.instance.scope in self._path() else None

    def _taken(self) -> int:
        return self._n_open + len(self._starting) + len(self._held)

    def _root_key(self) -> ScopeKey:
        return self.batch_loop.scope if self.batch_loop is not None else ()

    def _iter_loop(self, inst: Instance) -> bool:
        """A loop step inside an iteration scope: the only step the cap defers."""
        return inst.step in self.program.regions and inst.scope != self._root_key()

    def _defer(self, inst: Instance) -> None:
        self._deferred.add(inst)
        bisect.insort(self._deferred_by_scope.setdefault(inst.scope, []), inst, key=self.order)
        heapq.heappush(self._deferred_heap, (self.order(inst), inst))

    def _undefer(self, inst: Instance) -> None:
        self._deferred.discard(inst)
        queue = self._deferred_by_scope[inst.scope]
        queue.remove(inst)
        if not queue:
            del self._deferred_by_scope[inst.scope]

    def _start_deferred(self) -> list[Instance]:
        """Queued loop steps that may start now, each taking a slot its loop's first iteration then uses: under the
        cap, in scheduling order; past it, one per level on the progress path, from that level's reserved scope. None
        while the iteration budget waits or asks: queued loop steps share its one request, and never add a need of
        their own (§5.3). Once it decides, they start: a refused one fails at its first iteration."""
        out: list[Instance] = []
        if not self._deferred or self.budget.waiting or self.budget.asking:
            return out
        while self._taken() < self.cap and self._deferred:
            _, inst = heapq.heappop(self._deferred_heap)
            if inst in self._deferred:  # else it left the queue meanwhile
                self._undefer(inst)
                self._release(inst, False)
                out.append(inst)
        if self._deferred and self._taken() >= self.cap:
            for key in sorted(self._path(), key=len):
                if self._taken() >= self.cap + self.reserve:
                    break
                queue = self._deferred_by_scope.get(key)
                if queue and not self._reserved_at(len(key) + 1):
                    inst = queue[0]
                    self._undefer(inst)
                    self._release(inst, True)
                    out.append(inst)
        return out

    def _release(self, inst: Instance, reserved: bool) -> None:
        self._starting[inst] = reserved
        if inst in self._captures:
            self._released[inst] = self._captures.pop(inst)

    def _reserved_at(self, level: int) -> bool:
        if any(s.reserved and len(s.key) == level for s in self.scopes.values()):
            return True
        held = list(self._starting.items()) + list(self._held.items())
        return any(r and len(i.scope) + 1 == level for i, r in held)

    def _clear_deferred(self, key: ScopeKey) -> None:
        for k in [k for k in self._deferred_by_scope if k[: len(key)] == key]:
            self._deferred -= set(self._deferred_by_scope.pop(k))

    def _path(self) -> set[ScopeKey]:
        """The progress path: from the execution's own root (a batch child's loop scope), the oldest open iteration
        at each level below, by opening order."""
        oldest: dict[ScopeKey, Scope] = {}
        for sc in self.scopes.values():
            if sc.key and not sc.frozen:
                best = oldest.get(sc.key[:-1])
                if best is None or sc.seq < best.seq:
                    oldest[sc.key[:-1]] = sc
        current = self._root_key()
        path = {current}
        while current in oldest:
            current = oldest[current].key
            path.add(current)
        return path

    def _settle_wakes(self) -> None:
        """Loops the cap held back open what they can once scopes are freed, in scheduling order."""
        if self._waking:
            return
        if self.ended is not None:
            self._capped.clear()
            return
        self._waking = True
        try:
            while self._freed:
                self._freed = False
                for inst in sorted(self._capped, key=self.order):
                    loop = self.loops.get(inst)
                    if loop is None:
                        self._capped.discard(inst)
                    elif not loop.waiting:
                        self._advance(loop)
        finally:
            self._waking = False

    # --- the variables, their versions and captures (engine 2b spec §5.3) -------------------------------------------

    def init_vars(self, values: dict[str, Any]) -> None:
        """Version 0: the defaults, or a batch's variables (which never change)."""
        self._live -= size(self._vars)
        self._vars = dict(values)
        self._live += size(self._vars)

    @property
    def vars(self) -> dict[str, Any]:
        """The current variables, what a step reads when it starts: inline, on their way to a claim, or handles into
        their claims."""
        out: dict[str, Any] = {}
        head = ClaimRef.of(self.vbox.head)
        if head is not None:
            out = {name: head.extend(name).to_json() for name in self._var_names}
        if self.vbox.sealing is not None:
            out.update(self.vbox.sealing)
        out.update(self._vars)
        return out

    def set_variables(self, values: Mapping[str, Any], step: Instance | None = None) -> None:
        """A root `set_variables` settled: the next version. While a queued loop step names an older one, this write
        keeps what it replaced."""
        if self._captures or self._released:
            current = self.vars
            topo = self.program.steps[step.step].topo if step is not None else -1
            rec = Undo(topo, {name: [current[name]] if name in current else [] for name in values})
            self.undo[self.vars_version] = rec
            self._live += rec.bytes()
        self._live -= size(self._vars)
        self._vars.update(values)
        self._live += size(self._vars)
        self.vars_version += 1

    def vars_at(self, version: int) -> dict[str, Any]:
        """The variables as they were at `version`: each written name from the oldest write after it."""
        out = self.vars
        for k in range(self.vars_version - 1, version - 1, -1):
            rec = self.undo[k]
            if rec.vals is not None:
                for name, old in rec.vals.items():
                    if old:
                        out[name] = old[0]
                    else:
                        out.pop(name, None)
                continue
            head = ClaimRef.of(rec.head)
            if head is None:  # a record holds its values or its claim
                raise ValueError("an undo record with neither its values nor its claim")
            for name in self.program.steps[self._by_topo[rec.step]].config.get("assignments", {}):
                out[name] = head.extend(name, 0).to_json()
        return out

    def consume_capture(self, inst: Instance) -> dict[str, Any] | None:
        """A released loop step's unit starts: the variables of the version it captured, read before that version
        may be dropped. None when it captured none: it reads the current ones."""
        if inst not in self._released:
            return None
        version = self._released.pop(inst)
        self._unref(version)
        variables = self.vars_at(version)
        self._gc_versions()
        return variables

    def _unref(self, version: int) -> None:
        n = self._vrefs[version] - 1
        if n:
            self._vrefs[version] = n
        else:
            del self._vrefs[version]

    def _drop_captures(self, key: ScopeKey) -> None:
        """The captures of the queued and released loop steps in scope `key` and inside it, found through the queues
        that hold them (not a scan of every capture)."""
        steps = [i for k, q in self._deferred_by_scope.items() if k[: len(key)] == key for i in q]
        steps += [i for i in self._ready if i.scope[: len(key)] == key]
        for inst in steps:
            version = self._captures.pop(inst, None)
            if version is not None:
                self._unref(version)
        for inst in [i for i in self._released if i.scope[: len(key)] == key]:
            self._unref(self._released.pop(inst))
        self._gc_versions()

    def _gc_versions(self) -> None:
        """Undo records no captured version needs any more are dropped."""
        if self.undo:
            oldest = min(self._vrefs) if self._vrefs else self.vars_version
            for k in [k for k in self.undo if k < oldest and not self.undo[k].sealing]:
                self._live -= self.undo.pop(k).bytes()

    # --- continue-as-new ---------------------------------------------------------------------------------------------

    def to_json(self, *, check: bool = False) -> dict[str, Any]:
        """The scheduler's state for a continue-as-new snapshot (`snapshot_format` 2, engine 2b spec §5.3): scopes,
        steps and loops by index, node and edge states as one code each in region order, and no queue: what's queued
        is rebuilt from the states on restore. Taken between units: nothing settled or cancelled is left to hand over.
        `check` (tests): restoring would rebuild exactly what's queued now."""
        if self._settled or self._cancels or self.ended is not None:
            raise ValueError("a snapshot is taken only between units, and never after the run ended")
        if self.budget.waiting or self.budget.reserved or self._budget_waits:  # the at-continue term (§5.3)
            raise ValueError("a snapshot is taken only when the iteration budget holds no waiting need or child grant")
        if self._live > LIVE_BUDGET:  # a container on its way to a claim still counts until it lands
            raise ValueError("a snapshot is taken only within the live-state budget, once its claims have landed")
        if check:
            self._check_queues()
        loops = set(self.loops)
        by_scope: dict[ScopeKey, dict[uuid.UUID, int]] = {}
        for inst, version in self._captures.items():
            by_scope.setdefault(inst.scope, {})[inst.step] = version
        return {
            "snapshot_format": SNAPSHOT_FORMAT,
            "scopes": [self._scope_json(sc, by_scope.get(sc.key, {})) for sc in self.scopes.values()],
            "loops": [self._loop_json(loop) for loop in self.loops.values()],
            "handed": [self._i(i) for i in sorted(self._handed_now(), key=self.order)],
            "collects_out": [
                [self._i(i), n]
                for i, n in sorted(self._collects_out, key=lambda c: (self.order(c[0]), c[1]))
                if i in loops
            ],
            "batches_out": [
                [self._i(i), n]
                for i, n in sorted(self._batches_out, key=lambda b: (self.order(b[0]), b[1]))
                if i in loops
            ],
            "budget": self.budget.to_json(),
            "budget_waits": [[k, self._i(i)] for k, i in self._budget_waits.items()],
            "batch_loop": self._i(self.batch_loop) if self.batch_loop else None,
            "starting": [
                [self._i(i), int(r)] for i, r in sorted(self._starting.items(), key=lambda c: self.order(c[0]))
            ],
            "held": [[self._i(i), int(r)] for i, r in sorted(self._held.items(), key=lambda c: self.order(c[0]))],
            "seq": self._seq,
            "vars": self._vars,
            "vbox": self.vbox.to_json(),
            "vars_version": self.vars_version,
            "undo": [[k, u.step, u.vals, u.head, int(u.sealing)] for k, u in sorted(self.undo.items())],
            "spills_out": [
                [self._i(i), w, n] for i, w, n in sorted(self._spills_out, key=lambda o: (self.order(o[0]), o[1], o[2]))
            ],
            "released": [[self._i(i), v] for i, v in sorted(self._released.items(), key=lambda c: self.order(c[0]))],
        }

    @classmethod
    def from_json(cls, program: Program, data: dict[str, Any], *, prefix: str = "") -> "Scheduler":
        if data.get("snapshot_format") != SNAPSHOT_FORMAT:
            raise ValueError(f"unknown snapshot format {data.get('snapshot_format')!r}")
        s = cls(program, budget=Budget.from_json(data["budget"]), prefix=prefix)
        for raw in data["scopes"]:
            scope = s._scope_from(raw)
            s.scopes[scope.key] = scope
        for raw in data["loops"]:
            loop = s._loop_from(raw)
            s.loops[loop.instance] = loop
        s._handed = {s._if(i) for i in data["handed"]} | set(s.loops)  # a loop step runs for as long as its loop
        s._collects_out = {(s._if(i), int(n)) for i, n in data["collects_out"]}
        s._batches_out = {(s._if(i), int(n)) for i, n in data["batches_out"]}
        s._budget_waits = {str(k): s._if(i) for k, i in data["budget_waits"]}
        s.batch_loop = s._if(data["batch_loop"]) if data["batch_loop"] else None
        s._starting = {s._if(i): bool(r) for i, r in data["starting"]}
        s._held = {s._if(i): bool(r) for i, r in data["held"]}
        s._seq = int(data["seq"])
        s._vars = dict(data["vars"])
        s.vbox = Box.from_json(data["vbox"])
        s.vars_version = int(data["vars_version"])
        s.undo = {int(k): Undo(int(t), v, h, bool(g)) for k, t, v, h, g in data["undo"]}
        s._spills_out = {(s._if(i), str(w), int(n)) for i, w, n in data["spills_out"]}
        s._released = {s._if(i): int(v) for i, v in data["released"]}
        for version in s._released.values():
            s._vrefs[version] = s._vrefs.get(version, 0) + 1
        s._n_open = sum(1 for sc in s.scopes.values() if sc.key and not sc.frozen)
        s._live = s.recount()
        s._spills = [sp for sp in s._pending() if (sp.owner, sp.which, sp.first) not in s._spills_out]
        ready, s._collects, s._batches = s._rebuilt()
        for inst in ready:  # queued loop steps inside iterations wait deferred, the rest ready
            if s._iter_loop(inst):
                s._defer(inst)
            else:
                s._ready.append(inst)
        s._capped = {  # a loop with items left and room for them may be one the cap held back: it tries again
            inst
            for inst, loop in s.loops.items()
            if not loop.batch
            and not loop.waiting
            and loop.next < count(loop.items)
            and len(loop.open) < loop.concurrency
        }
        return s

    def _pending(self) -> list[Spill]:
        """The containers' parts on their way to a claim, rebuilt from the state."""
        out: list[Spill] = []
        for sc in self.scopes.values():
            owner = Instance(sc.key, NIL)
            if sc.rbox.sealing is not None:
                prev = ClaimRef.of(sc.rbox.head)
                entry = {
                    "id": self._claim_id(owner, "r", sc.rbox.claims),
                    "value": sc.rbox.sealing,
                    "prev": prev.id if prev else None,
                }
                out.append(Spill(owner, "r", sc.rbox.claims, entry))
            if sc.item_sealing:
                out.append(Spill(owner, "t", 0, {"id": self._claim_id(owner, "t", 0), "value": sc.item}))
        root = Instance((), NIL)
        if self.vbox.sealing is not None:
            prev = ClaimRef.of(self.vbox.head)
            entry = {
                "id": self._claim_id(root, "v", self.vbox.claims),
                "value": self.vbox.sealing,
                "prev": prev.id if prev else None,
            }
            out.append(Spill(root, "v", self.vbox.claims, entry))
        for k, u in sorted(self.undo.items()):
            if u.sealing:
                out.append(Spill(root, "u", k, {"id": self._claim_id(root, "u", k), "value": u.vals}))
        for lp in self.loops.values():
            if lp.items_sealing:
                out.append(Spill(lp.instance, "i", 0, {"id": self._claim_id(lp.instance, "i", 0), "value": lp.items}))
        return out

    def _handed_now(self) -> set[Instance]:
        """Steps handed out and still running, loop steps aside (their loop says they run)."""
        out = set()
        for inst in self._handed:
            scope = self.scopes.get(inst.scope)
            if scope is not None and scope.nodes.get(inst.step) == NodeState.RUNNING and inst not in self.loops:
                out.add(inst)
        return out

    def _rebuilt(self) -> tuple[list[Instance], list[Collect], list[Batch]]:
        """What's queued, from the states: running steps not handed out, iterations whose `collect` waits, batches
        not handed out."""
        ready = sorted(
            (
                Instance(sc.key, n)
                for sc in self.scopes.values()
                for n, state in sc.nodes.items()
                if state == NodeState.RUNNING and Instance(sc.key, n) not in self._handed
            ),
            key=self.order,
        )
        collects = [
            Collect(loop.instance, i, self._iteration_scope(loop, i))
            for loop in self.loops.values()
            for i in sorted(loop.collecting)
            if (loop.instance, i) not in self._collects_out
        ]
        batches = [
            Batch(loop.instance, loop.running_batch, sliced(loop.items, loop.running_batch, loop.next))
            for loop in self.loops.values()
            if loop.running_batch is not None and (loop.instance, loop.running_batch) not in self._batches_out
        ]
        return ready, collects, batches

    def _check_queues(self) -> None:
        """Restoring rebuilds exactly what's queued now, and counts the live state the same."""
        if self._live != self.recount():
            raise AssertionError(f"the live state is counted {self._live}, but holds {self.recount()}")
        handed = self._handed | set(self.loops)
        saved, self._handed = self._handed, handed
        try:
            ready, collects, batches = self._rebuilt()
        finally:
            self._handed = saved
        if set(ready) != set(self._ready) | self._deferred:
            raise AssertionError(f"rebuilt {len(ready)} ready steps, but {len(self._ready) + len(self._deferred)} wait")
        if {(c.loop, c.index, c.scope) for c in collects} != {(c.loop, c.index, c.scope) for c in self._collects}:
            raise AssertionError("the rebuilt collects differ from those queued")
        if {(b.loop, b.start, count(b.items)) for b in batches} != {
            (b.loop, b.start, count(b.items)) for b in self._batches
        }:
            raise AssertionError("the rebuilt batches differ from those queued")
        pending = {(sp.owner, sp.which, sp.first) for sp in self._pending()} - self._spills_out
        if pending != {(sp.owner, sp.which, sp.first) for sp in self._spills}:
            raise AssertionError("the rebuilt claims differ from those queued")

    # indexes: a scope key as [loop topo, item index, ...], an instance as [key, step topo]
    def _k(self, key: ScopeKey) -> list[int]:
        return [x for loop, i in key for x in (self.program.steps[self.program.by_key[loop]].topo, i)]

    def _kf(self, raw: list[int]) -> ScopeKey:
        return tuple((self.program.steps[self._by_topo[raw[j]]].key, int(raw[j + 1])) for j in range(0, len(raw), 2))

    def _i(self, inst: Instance) -> list[Any]:
        return [self._k(inst.scope), self.program.steps[inst.step].topo if inst.step != NIL else -1]

    def _if(self, raw: list[Any]) -> Instance:
        return Instance(self._kf(raw[0]), self._by_topo[int(raw[1])] if int(raw[1]) >= 0 else NIL)

    def _edge_order(self, region: uuid.UUID | None) -> list[int]:
        """A region's edges in the order `_open_scope` lays them out."""
        order = self._edge_orders.get(region)
        if order is None:
            order = [e for node_id in self._members[region] for e in self.program.steps[node_id].ins]
            self._edge_orders[region] = order
        return order

    def _scope_json(self, sc: Scope, captures: Mapping[uuid.UUID, int]) -> list[Any]:
        """[key, region, node codes, edge codes, results, item, index, failure, frozen, seq, reserved, captures, box,
        item being claimed, claimed codes]:
        results by step index, as [index, 0, output], [index, 1, error] or [index, 2, output, error]; the captures,
        two characters per loop step of the region (none: ".."), or "" when there are none. A frozen scope has no
        codes."""
        nodes = edges = ""
        if not sc.frozen:
            nodes = "".join(_NODE_CODE[sc.nodes[m]] for m in self._members[sc.region])
            edges = "".join(_EDGE_CODE[sc.edges[e]] for e in self._edge_order(sc.region))
        results: list[list[Any]] = []
        for key, r in sc.results.items():
            t = self.program.steps[self.program.by_key[key]].topo
            if "output" in r and "error" in r:
                results.append([t, 2, r["output"], r["error"]])
            elif "error" in r:
                results.append([t, 1, r["error"]])
            else:
                results.append([t, 0, r["output"]])
        region = self.program.steps[sc.region].topo if sc.region is not None else -1
        failure = sc.failure.to_json() if sc.failure else None
        codes = ""
        if captures:
            codes = "".join(
                _capture_code(captures[m]) if m in captures else NO_CAPTURE for m in self._loop_members[sc.region]
            )
        box = sc.rbox.to_json() if sc.rbox.head is not None or sc.rbox.sealing is not None else None
        return [
            self._k(sc.key), region, nodes, edges, results, sc.item, sc.index, failure, int(sc.frozen), sc.seq,
            int(sc.reserved), codes, box, int(sc.item_sealing), sc.claimed,
        ]  # fmt: skip

    def _scope_from(self, raw: list[Any]) -> Scope:
        key, region = self._kf(raw[0]), (self._by_topo[raw[1]] if raw[1] >= 0 else None)
        frozen = bool(raw[8])
        nodes: dict[uuid.UUID, NodeState] = {}
        edges: dict[int, EdgeState] = {}
        if not frozen:
            nodes = {m: _NODE_FROM[c] for m, c in zip(self._members[region], raw[2], strict=True)}
            edges = {e: _EDGE_FROM[c] for e, c in zip(self._edge_order(region), raw[3], strict=True)}
        results: dict[str, dict[str, Any]] = {}
        for r in raw[4]:
            k = self.program.steps[self._by_topo[r[0]]].key
            results[k] = (
                {"output": r[2]} if r[1] == 0 else {"error": r[2]} if r[1] == 1 else {"output": r[2], "error": r[3]}
            )
        failure = Failure.from_json(raw[7]) if raw[7] else None
        for n, m in enumerate(self._loop_members[region] if raw[11] else ()):
            code = raw[11][2 * n : 2 * n + 2]
            if code != NO_CAPTURE:
                version = _capture_from(code)
                self._captures[Instance(key, m)] = version
                self._vrefs[version] = self._vrefs.get(version, 0) + 1
        scope = Scope(key, region, nodes, edges, results, raw[5], raw[6], failure, frozen, int(raw[9]), bool(raw[10]))
        scope.rbox, scope.item_sealing, scope.claimed = Box.from_json(raw[12]), bool(raw[13]), str(raw[14])
        return scope

    def _loop_json(self, loop: LoopRun) -> list[Any]:
        listed = loop.items.to_json() if isinstance(loop.items, ItemsRef) else None
        inline = loop.items if isinstance(loop.items, list) else None
        return [
            self._i(loop.instance), inline, loop.concurrency, int(loop.stop_on_error), loop.offset, loop.batch,
            loop.next, list(loop.open), sorted(loop.collecting), loop.collected, loop.failures, loop.running_batch,
            int(loop.waiting), listed, int(loop.items_sealing),
        ]  # fmt: skip

    def _loop_from(self, raw: list[Any]) -> LoopRun:
        items = ItemsRef.from_json(raw[13]) if raw[13] is not None else list(raw[1])
        return LoopRun(
            instance=self._if(raw[0]), items=items, concurrency=int(raw[2]), stop_on_error=bool(raw[3]),
            offset=int(raw[4]), batch=int(raw[5]), next=int(raw[6]), open=[int(i) for i in raw[7]],
            collecting={int(i) for i in raw[8]}, collected=list(raw[9]), failures=list(raw[10]),
            running_batch=raw[11], waiting=bool(raw[12]), items_sealing=bool(raw[14]),
        )  # fmt: skip


__all__ = [
    "Batch",
    "Box",
    "ItemsRef",
    "count",
    "item_at",
    "sliced",
    "INLINE_FLOOR",
    "LIVE_BUDGET",
    "NIL",
    "Spill",
    "Undo",
    "claimed_codes",
    "BatchOutcome",
    "CAP_MESSAGE",
    "Collect",
    "EdgeState",
    "Failure",
    "Instance",
    "ITERATION_CAP",
    "ITERATION_CAP_EXCEEDED",
    "LoopRun",
    "NodeState",
    "OuterScope",
    "RunEnd",
    "SNAPSHOT_FORMAT",
    "Scheduler",
    "Scope",
    "ScopeKey",
    "iteration_key",
]
