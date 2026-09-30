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
once its loop has taken its result: only open scopes stay, which keeps a continue-as-new snapshot small."""

import bisect
import heapq
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dewpoint.engine.runtime import probe as P
from dewpoint.engine.runtime.budget import LOCAL, Answer, Ask, Budget, Need
from dewpoint.engine.runtime.program import BODY, DONE, ERROR_PORT, Program, Step

ScopeKey = tuple[tuple[str, int], ...]
ITERATION_CAP = 100_000  # loop iterations and filter items across the whole logical run (spec §4.2)
ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"
CAP_MESSAGE = "This run reached its limit of 100,000 loop iterations."
SNAPSHOT_FORMAT = 2  # proto (2b-1b go/no-go): indexes and state codes, no stored queues (2b spec §5.3)
OPEN_SCOPES_CAP = 100  # open iteration scopes per execution, besides the progress chain's reservation (§5.3)


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
NO_CAPTURE = ".."  # proto (§5.3): a scope's captures are two characters per loop step of its region, in region order


def _capture_code(version: int) -> str:
    if not 0 <= version < len(_B62) ** 2:
        raise ValueError(f"proto: variable version {version} past the capture encoding")
    return _B62[version // len(_B62)] + _B62[version % len(_B62)]


def _capture_from(code: str) -> int:
    return _B62.index(code[0]) * len(_B62) + _B62.index(code[1])


def _then_wake(fn: Any) -> Any:
    """Proto: after a change from outside, the loops the cap held back open what they can (`_settle_wakes`)."""

    def wrapper(self: "Scheduler", *args: Any, **kwargs: Any) -> Any:
        out = fn(self, *args, **kwargs)
        self._settle_wakes()
        self._enforce_budget()  # proto (§5.3): whatever changed, the live state goes back under its budget
        return out

    return wrapper


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
    seq: int = 0  # proto: its opening order; the oldest open iterations make the progress chain (§5.3)
    reserved: bool = False  # proto: opened from the progress chain's reservation

    @property
    def settled(self) -> bool:
        return self.failure is not None or all(s in SETTLED for s in self.nodes.values())


@dataclass
class Collection:
    """Proto (§5.3): a loop's collected values, as immutable segments and an inline tail, by absolute index. Positions
    with no value (a failed iteration, or one not yet collected) read as null."""

    base: str
    n: int
    offset: int
    segs: list[list[int]] = field(default_factory=list)  # [first, count, bytes], spilled
    tail: dict[int, Any] = field(default_factory=dict)
    sealing: dict[int, list[list[Any]]] = field(default_factory=dict)  # first -> pairs being spilled
    tail_bytes: int = 0  # the tail's values as the live state counts them (P.size + 8 each)
    sealing_bytes: int = 0

    def put(self, index: int, value: Any) -> int:
        self.tail[index] = value
        added = P.size(value) + 8
        self.tail_bytes += added
        return added

    def merge(self, other: dict[str, Any]) -> int:
        self.segs.extend([list(s) for s in other["segs"]])
        return sum(self.put(int(i), v) for i, v in other["tail"])

    def seal(self) -> tuple[int, list[list[Any]]] | None:
        if not self.tail:
            return None
        pairs = [[i, self.tail[i]] for i in sorted(self.tail)]
        self.tail = {}
        self.sealing[pairs[0][0]] = pairs
        self.sealing_bytes += self.tail_bytes
        self.tail_bytes = 0
        return pairs[0][0], pairs

    def sealed(self, first: int, size: int) -> int:
        pairs = self.sealing.pop(first)
        freed = sum(P.size(v) + 8 for _, v in pairs)
        self.sealing_bytes -= freed
        self.segs.append([first, len(pairs), size])
        return freed

    def output(self) -> Any:
        """The loop's `items`: a plain list while nothing was spilled, else the collection's handle."""
        if not self.segs and not self.sealing:
            return [self.tail.get(self.offset + p) for p in range(self.n)]
        return {P.KIND: P.COLL, **self.to_json()}

    def entries(self) -> Any:
        """The loop's `failures`: its entries in index order while nothing was spilled, else the handle."""
        if not self.segs and not self.sealing:
            return [{"index": i, **self.tail[i]} for i in sorted(self.tail)]
        return {P.KIND: P.COLL, **self.to_json()}

    def to_json(self) -> dict[str, Any]:
        return {
            "base": self.base, "n": self.n, "offset": self.offset, "segs": self.segs,
            "tail": [[i, self.tail[i]] for i in sorted(self.tail)],
            "sealing": [[f, pairs] for f, pairs in sorted(self.sealing.items())],
        }  # fmt: skip

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Collection":
        tail = {int(i): v for i, v in raw["tail"]}
        sealing = {int(f): pairs for f, pairs in raw.get("sealing", [])}
        return cls(
            str(raw["base"]), int(raw["n"]), int(raw["offset"]), [list(s) for s in raw["segs"]], tail, sealing,
            sum(P.size(v) + 8 for v in tail.values()),
            sum(P.size(v) + 8 for pairs in sealing.values() for _, v in pairs),
        )  # fmt: skip


@dataclass(frozen=True)
class Spill:
    """Proto: a collection's sealed values, for the `probe.spill` activity, as segment `base/first`."""

    loop: Instance
    base: str
    first: int
    pairs: list[list[Any]]
    which: str = "c"  # the loop's collected values (c) or its failures (f)


@dataclass
class LoopRun:
    """A loop node's iterations: opened in order, at most `concurrency` at a time. `offset` is the index of
    `items[0]` (a batch child runs a slice). With `batch`, the items run in children of that many, one at a time."""

    instance: Instance
    items: Any  # a list, or (proto) a handle-backed list
    concurrency: int
    stop_on_error: bool
    offset: int = 0
    batch: int = 0
    next: int = 0  # the next item to open, as a position in `items`
    open: list[int] = field(default_factory=list)  # open iterations, by absolute index
    collecting: set[int] = field(default_factory=set)  # settled iterations whose `collect` is being evaluated
    coll: Collection | None = None  # proto: what it collected, by absolute index
    fails: Collection | None = None  # proto: its failed iterations, by absolute index
    running_batch: int | None = None  # the start of the batch a child is running
    waiting: bool = False  # the next iteration waits for budget
    items_pending: list[int] = field(default_factory=list)  # proto: segments of `items` being spilled
    items_per: int = 0  # proto: items per segment, once they spill
    items_base: str = ""  # proto: their segments, `items_base/k`


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
    items: Any  # a list, or (proto) a handle-backed slice


@dataclass(frozen=True)
class BatchOutcome:
    """What a batch child's slice produced: the collected values, the failed iterations, and the failure that stopped
    it under `on_item_error: stop`."""

    collected: list[Any]
    failures: list[dict[str, Any]]
    stopped: Failure | None = None
    collection: dict[str, Any] | None = None  # proto: a batch child's collection (its parent's segments)
    failure_collection: dict[str, Any] | None = None  # proto: and its failures, the same way


@dataclass(frozen=True)
class OuterScope:
    """An enclosing scope, as a batch child reads it: the results its region can reference, and the loop item."""

    key: ScopeKey
    results: dict[str, dict[str, Any]]
    item: Any = None
    index: int | None = None


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
    def __init__(self, program: Program, *, budget: Budget | None = None) -> None:
        self.program = program
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
        self._loop_members = {
            region: tuple(m for m in members if m in program.regions) for region, members in self._members.items()
        }  # proto: the loop steps of each region, in region order, for the captures' codes
        # proto (2b-1b go/no-go): snapshot_format 2 and the open-scope cap
        self._by_topo = {s.topo: s.id for s in program.steps.values()}
        self._edge_orders: dict[uuid.UUID | None, list[int]] = {}
        computed = max(
            (len(program.chain(program.steps[r].region)) for r in program.regions if r is not None), default=0
        )
        self.reserve = program.loop_depth if program.loop_depth is not None else computed  # D, pinned in the version
        self.cap = program.open_scopes_cap or OPEN_SCOPES_CAP  # the version's cap, pinned in it
        # proto (§5.3): the variables, their versions, and the captures of queued loop steps inside iterations
        self.vars: dict[str, Any] = {}
        self.vars_version = 0
        self.var_deltas: dict[int, dict[str, Any]] = {}  # an older version: the values that differ from the current
        self._captures: dict[Instance, int] = {}  # queued loop step -> the version it became ready under
        self._released: dict[Instance, int] = {}  # handed out, its unit not yet started
        self._starting: dict[Instance, bool] = {}  # released loop step -> it took a reserved scope
        self._held: dict[Instance, bool] = {}  # a batch-mode loop inside an iteration: it holds its slot to the end
        # queued loop steps inside iterations, not started: by scope in scheduling order, and all in one heap
        self._deferred: set[Instance] = set()
        self._deferred_by_scope: dict[ScopeKey, list[Instance]] = {}
        self._deferred_heap: list[tuple[tuple[Any, ...], Instance]] = []
        self._seq = 0
        self._n_open = 0  # open iteration scopes, frozen ones aside
        self._capped: set[Instance] = set()  # loops the cap holds back
        self._freed = False
        self._waking = False
        self._handed: set[Instance] = set()  # steps handed over (take_ready) and not settled
        self._collects_out: set[tuple[Instance, int]] = set()
        self._batches_out: set[tuple[Instance, int]] = set()
        self.prefix = ""  # proto: the execution's own workflow id, for the collections it names
        self._live = P.size(self.vars)  # proto: see `live`; the variables count from the start
        self._spills: list[Spill] = []
        self._spills_out: set[tuple[Instance, str, int]] = set()
        self.probe = {"peak_open": 0, "peak_reserved": 0, "cap_waits": 0, "reserved_opens": 0}

    @property
    def iterations(self) -> int:
        """Iterations and filter items this execution used, its settled children's included."""
        return self.budget.used

    # --- the workflow's side ---------------------------------------------------------------------------------------

    def start(self) -> None:
        self._open_scope((), None)

    def start_batch(
        self,
        loop_step: uuid.UUID,
        outer: list[OuterScope],
        items: Any,
        *,
        offset: int,
        concurrency: int,
        stop_on_error: bool,
        base: str = "",
    ) -> None:
        """A batch child: rebuild the loop's enclosing scopes read-only, outermost first, and run items `offset` ..
        `offset + len(items)` of it. The loop's own scope is the last one."""
        chain = self.program.chain(self.program.steps[loop_step].region)  # innermost first
        for depth, o in enumerate(outer):
            region = chain[len(outer) - 1 - depth]
            self.scopes[o.key] = Scope(o.key, region, {}, {}, dict(o.results), o.item, o.index, frozen=True)
            self._live += self._scope_bytes(self.scopes[o.key])
        loop_inst = Instance(outer[-1].key, loop_step)
        self.batch_loop = loop_inst
        items = items if P.is_kind(items, P.LIST) else list(items)
        coll = Collection(base, P.count(items), offset)
        fails = Collection(base + "!f", P.count(items), offset)
        loop = LoopRun(loop_inst, items, concurrency, stop_on_error, offset=offset, coll=coll, fails=fails)
        self._live += P.size(items) if isinstance(items, list) else 0
        self.loops[loop_inst] = loop
        self._maybe_seal(loop)
        self._advance(loop)

    def take_ready(self) -> list[Instance]:
        """Ready steps, in (scope, topological) order. They are running from now on."""
        ready = []
        for inst in self._ready:
            if self._iter_loop(inst):  # proto (§5.3): it starts only when its loop can open an iteration at once
                self._defer(inst)
            else:
                ready.append(inst)
        self._ready = []
        ready += self._start_deferred()
        if self._deferred:  # proto: what stays queued after the take
            self.probe["deferred_peak"] = max(self.probe.get("deferred_peak", 0), len(self._deferred))
        ready.sort(key=self.order)
        for inst in ready:
            self.scopes[inst.scope].nodes[inst.step] = NodeState.RUNNING
        self._handed.update(ready)
        return ready

    def take_collects(self) -> list[Collect]:
        out, self._collects = self._collects, []
        self._collects_out.update((c.loop, c.index) for c in out)
        return out

    def take_spills(self) -> list[Spill]:
        out, self._spills = self._spills, []
        self._spills_out.update((s.loop, s.which, s.first) for s in out)
        return out

    @staticmethod
    def _colls(loop: LoopRun) -> list[tuple[str, Collection]]:
        return [(w, c) for w, c in (("c", loop.coll), ("f", loop.fails)) if c is not None]

    @_then_wake
    def spilled(self, loop_inst: Instance, which: str, first: int, size: int) -> None:
        """Proto: a sealed part of a collection is in its segment now."""
        self._spills_out.discard((loop_inst, which, first))
        loop = self.loops.get(loop_inst)
        if which == "i":
            if loop is None or first not in loop.items_pending:
                return
            loop.items_pending.remove(first)
            if not loop.items_pending:  # every segment is written: the loop carries on over them
                self._live -= P.size(loop.items)
                n = len(loop.items)
                loop.items = {P.KIND: P.LIST, "id": loop.items_base, "n": n, "per": loop.items_per}
            self._advance(loop)
            return
        coll = dict(self._colls(loop)).get(which) if loop is not None else None
        if loop is None or coll is None or first not in coll.sealing:
            return
        self._live -= coll.sealed(first, size)
        self._advance(loop)

    @property
    def live(self) -> int:
        """Proto (§5.3): the values the snapshot holds, as JSON: results and items of open scopes, loops' inline item
        lists, and collections' inline parts. Kept as they change; `_recount` is the same sum, from scratch."""
        return self._live

    def _recount(self) -> int:
        total = sum(self._scope_bytes(sc) for sc in self.scopes.values())
        total += P.size(self.vars) + sum(P.size(d) for d in self.var_deltas.values())
        for loop in self.loops.values():
            total += P.size(loop.items) if isinstance(loop.items, list) else 0
            total += sum(c.tail_bytes + c.sealing_bytes for _, c in self._colls(loop))
        return total

    @staticmethod
    def _scope_bytes(sc: Scope) -> int:
        return sum(P.size(r) for r in sc.results.values()) + (P.size(sc.item) if sc.item is not None else 0)

    def _seal(self, loop: LoopRun, which: str, coll: Collection) -> None:
        sealed = coll.seal()
        if sealed is not None:
            self.probe["spills"] = self.probe.get("spills", 0) + 1
            self._spills.append(Spill(loop.instance, coll.base, sealed[0], sealed[1], which))

    def _maybe_seal(self, loop: LoopRun) -> None:
        """A tail past a segment's size is spilled; so is the largest one while the live state is past its budget."""
        for which, coll in self._colls(loop):
            if coll.tail_bytes >= P.SEG_BYTES:
                self._seal(loop, which, coll)
        self._enforce_budget()

    def _enforce_budget(self) -> None:
        """Past the live-state budget, the largest spillable value goes out first (a collection's tail or an inline
        item list), until what's already on its way out brings it back under."""
        if self.ended is not None:
            return
        while self.live - self._relief() > P.LIVE_BUDGET:
            candidates: list[tuple[int, Any, str, LoopRun, Collection | None]] = [
                (c.tail_bytes, self.order(lp.instance), w, lp, c)
                for lp in self.loops.values()
                for w, c in self._colls(lp)
                if c.tail_bytes > P.FLOOR
            ]
            candidates += [
                (P.size(lp.items), self.order(lp.instance), "i", lp, None)
                for lp in self.loops.values()
                if isinstance(lp.items, list) and not lp.items_pending and P.size(lp.items) > P.FLOOR
            ]
            if not candidates:
                break
            _, _, w, lp, c = max(candidates, key=lambda t: (t[0], t[1], t[2]))
            if c is None:
                self._spill_items(lp)
            else:
                self._seal(lp, w, c)

    def _relief(self) -> int:
        """What the spills in flight will take out of the live state."""
        out = 0
        for lp in self.loops.values():
            out += sum(c.sealing_bytes for _, c in self._colls(lp))
            if lp.items_pending and isinstance(lp.items, list):
                out += P.size(lp.items)
        return out

    def _items_base(self, loop: LoopRun) -> str:
        return f"{self.prefix}/i/{iteration_key(loop.instance.scope)}/{self.program.steps[loop.instance.step].topo}"

    def _spill_items(self, loop: LoopRun) -> None:
        """Proto: an inline item list goes into segments of about SEG_BYTES; the loop waits for them, then carries on
        over the handle, so its next iterations hold item handles, not items."""
        items = loop.items
        per = max(1, len(items) * P.SEG_BYTES // max(1, P.size(items)))
        loop.items_per = per
        base = loop.items_base = self._items_base(loop)
        for k in range((len(items) + per - 1) // per):
            loop.items_pending.append(k)
            self._spills.append(Spill(loop.instance, base, k, items[k * per : (k + 1) * per], "i"))
        self.probe["item_spills"] = self.probe.get("item_spills", 0) + 1

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

    def give_back(
        self, steps: list[Instance], collects: list[Collect], batches: list[Batch], spills: list["Spill"] | None = None
    ) -> None:
        """Work handed over but never started (drain mode, the in-flight cap): it waits in the queues again, first,
        for the continued run."""
        self._ready = steps + self._ready
        self._collects = collects + self._collects
        self._batches = batches + self._batches
        self._handed -= set(steps)
        for inst in steps:  # proto: a loop step handed out and not started waits again, with its capture
            self._starting.pop(inst, None)
            if inst in self._released:
                self._captures[inst] = self._released.pop(inst)
        self._collects_out -= {(c.loop, c.index) for c in collects}
        self._batches_out -= {(b.loop, b.start) for b in batches}
        self._spills = list(spills or []) + self._spills
        self._spills_out -= {(sp.loop, sp.which, sp.first) for sp in spills or []}

    @_then_wake
    def succeed(self, inst: Instance, output: Any, ports: tuple[str, ...] | None = None) -> None:
        """The step succeeded. `ports`: the normal ports whose edges are live (if/switch pick one); all by default."""
        self._handed.discard(inst)
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.DONE
        scope.results[step.key] = {"output": output}
        self._live += P.size(scope.results[step.key])
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
        self._starting.pop(inst, None)
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.FAILED
        self._settled.append((inst, {"error": failure.to_json()}))
        if step.on_error == "port":
            scope.results[step.key] = {"error": failure.to_json()}
            self._live += P.size(scope.results[step.key])
            self._resolve(scope, step, {ERROR_PORT})
        elif step.on_error == "continue":
            scope.results[step.key] = {"error": failure.to_json()}
            self._live += P.size(scope.results[step.key])
            self._resolve(scope, step, set(step.ports) - {BODY})
        else:
            self._fail_scope(scope, failure)
            return
        self._after_settle(scope)

    @_then_wake
    def open_loop(
        self, inst: Instance, items: list[Any], *, concurrency: int, stop_on_error: bool, batch: int = 0
    ) -> None:
        """The loop node's `items` are known: open its first iterations, or hand out its first batch. An empty list
        completes it at once."""
        scope, step = self._running(inst)
        if scope is None:
            return
        items = items if P.is_kind(items, P.LIST) else list(items)
        base = f"{self.prefix}/c/{iteration_key(inst.scope)}/{step.topo}"
        coll, fails = Collection(base, P.count(items), 0), Collection(base + "!f", P.count(items), 0)
        loop = LoopRun(inst, items, concurrency, stop_on_error, batch=batch, coll=coll, fails=fails)
        self._live += P.size(items) if isinstance(items, list) else 0
        self.loops[inst] = loop
        if batch and self._iter_loop(inst):  # proto (§5.3): it opens no scope, so it holds its slot until it ends
            self._held[inst] = self._starting.pop(inst, False)
        self._maybe_seal(loop)
        self._advance(loop)

    @_then_wake
    def collected(self, loop_inst: Instance, index: int, value: Any) -> None:
        self._collects_out.discard((loop_inst, index))
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        loop.open.remove(index)
        loop.collecting.discard(index)
        self._live += loop.coll.put(index, value)  # type: ignore[union-attr]
        self._prune(self._iteration_scope(loop, index))
        self._maybe_seal(loop)
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
        if outcome.collection is not None:
            self._live += loop.coll.merge(outcome.collection)  # type: ignore[union-attr]
        else:
            for n, value in enumerate(outcome.collected):
                self._live += loop.coll.put(start + n, value)  # type: ignore[union-attr]
        if outcome.failure_collection is not None:
            self._live += loop.fails.merge(outcome.failure_collection)  # type: ignore[union-attr]
        else:
            for f in outcome.failures:
                self._live += loop.fails.put(int(f["index"]), {"code": f["code"], "message": f["message"]})  # type: ignore[union-attr]
        if outcome.stopped is not None:
            self._abort(loop, outcome.stopped)
            return
        self._maybe_seal(loop)
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
        self._live += P.size(scope.results[step.key])
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
        self._batches = []
        self._starting.clear()
        self._held.clear()
        self._captures.clear()
        self._released.clear()
        self._gc_versions()
        self.budget.drop_local()  # a loop waiting for its next iteration opens none now
        self._spills = []
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
        """The ready queue's order: scope (by its loops' topological index, then item index), then the step's."""
        return (tuple((self._topo_of_key[loop], i) for loop, i in inst.scope), self.program.steps[inst.step].topo)

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
        self._live += self._scope_bytes(scope)
        if key:
            self._seq += 1
            scope.seq = self._seq
            self._n_open += 1
            self.probe["peak_open"] = max(self.probe["peak_open"], self._n_open)
            if reserved:
                self.probe["reserved_opens"] += 1
                held = 1 + sum(1 for s in self.scopes.values() if s.reserved)
                self.probe["peak_reserved"] = max(self.probe["peak_reserved"], held)
            if self._n_open > self.cap + self.reserve:
                raise AssertionError(f"proto: {self._n_open} open scopes, past {self.cap} + {self.reserve}")
        self.scopes[key] = scope
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
            if self.batch_loop is None and self._iter_loop(inst):  # proto (§5.3): its variables, as of now
                self._captures[inst] = self.vars_version
            return None
        scope.nodes[node_id] = NodeState.DEAD
        return step

    def _fail_scope(self, scope: Scope, failure: Failure, *, report: bool = True) -> None:
        """An unhandled failure ends its scope: waiting steps die, running ones are cancelled, and so is every scope
        nested inside it. `report`: tell the loop the iteration failed (not when the loop itself is stopping it)."""
        scope.failure = failure
        queued = set(self._ready) | self._deferred
        for key in [k for k in self.scopes if k[: len(scope.key)] == scope.key]:
            inner = self.scopes[key]
            if key != scope.key and inner.failure is None:
                inner.failure = failure
            for node_id, state in inner.nodes.items():
                inst = Instance(key, node_id)
                if state == NodeState.RUNNING and inst not in queued:
                    self._cancels.append(inst)
                if state in (NodeState.RUNNING, NodeState.WAITING):
                    inner.nodes[node_id] = NodeState.DEAD
        self._ready = [r for r in self._ready if r.scope[: len(scope.key)] != scope.key]
        self._clear_deferred(scope.key)
        self._drop_captures(scope.key)
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
        self._capped.discard(loop.instance)
        if self._starting.pop(loop.instance, None) is not None or self._held.pop(loop.instance, None) is not None:
            self._freed = True  # its slot is free
        self._live -= P.size(loop.items) if isinstance(loop.items, list) else 0
        self._live -= sum(c.tail_bytes + c.sealing_bytes for _, c in self._colls(loop))
        for key in [k for k, inst in self._budget_waits.items() if inst == loop.instance]:
            del self._budget_waits[key]
            self.budget.waiting = [n for n in self.budget.waiting if not (n.requester == LOCAL and n.key == key)]
        self._batches = [b for b in self._batches if b.loop != loop.instance]
        self._spills = [sp for sp in self._spills if sp.loop != loop.instance]

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
        self._live += loop.fails.put(index, {"code": failure.code, "message": failure.message})  # type: ignore[union-attr]
        self._maybe_seal(loop)
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
            coll = loop.coll.to_json() if loop.coll is not None else None
            fails = loop.fails.to_json() if loop.fails is not None else None
            self.outcome = BatchOutcome([], [], stopped, collection=coll, failure_collection=fails)
            self.ended = RunEnd("succeeded")

    def _open_next(self, loop: LoopRun, *, reserved: bool = False) -> None:
        index = loop.offset + loop.next
        item = P.item_at(loop.items, loop.next)
        loop.next += 1
        loop.open.append(index)
        self._open_scope(
            self._iteration_scope(loop, index), loop.instance.step, item=item, index=index, reserved=reserved
        )

    def _advance(self, loop: LoopRun) -> None:
        """Open iterations up to the concurrency (or hand out the next batch), or complete the loop when every item
        is done."""
        if loop.items_pending:  # proto: its items are being spilled; it carries on once they are written
            return
        if loop.batch:
            if loop.running_batch is None and loop.next < P.count(loop.items):
                start = loop.next
                loop.next = min(start + loop.batch, P.count(loop.items))
                loop.running_batch = start
                self._batches.append(Batch(loop.instance, start, P.sliced(loop.items, start, loop.next)))
                return
        else:
            while loop.next < P.count(loop.items) and len(loop.open) < loop.concurrency and not loop.waiting:
                room = self._room(loop)
                if room is None:  # the cap: it opens once scopes are freed (_settle_wakes)
                    if loop.instance not in self._capped:
                        self.probe["cap_waits"] += 1
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
        done = not loop.open and loop.next >= P.count(loop.items) and loop.running_batch is None and not loop.waiting
        if done:
            for which, coll in self._colls(loop):  # proto (§5.1): past 64 KiB, or already spilled, it ends as a handle
                if (
                    not coll.sealing
                    and coll.tail_bytes > P.FLOOR
                    and (coll.segs or coll.tail_bytes > P.INLINE_LIMIT or self.live > P.LIVE_BUDGET)
                ):
                    self._seal(loop, which, coll)
        if done and not any(c.sealing for _, c in self._colls(loop)):
            self._drop_loop(loop)
            if loop.instance == self.batch_loop:
                self._batch_over(loop, None)
                return
            items = loop.coll.output() if loop.coll is not None else []
            failures = loop.fails.entries() if loop.fails is not None else []
            output = {"items": items, "failures": failures, "count": P.count(loop.items)}
            scope = self.scopes.get(loop.instance.scope)
            if scope is not None and scope.failure is None and self.ended is None:
                self.succeed(loop.instance, output, (DONE,))

    # --- proto: the open-scope cap (2b spec §5.3) --------------------------------------------------------------------

    def _room(self, loop: LoopRun) -> bool | None:
        """Whether `loop` may open an iteration now: False from the general cap, True from the reservation, None
        not at all. The reservation holds one scope per nesting level, for the progress chain only."""
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
        """A loop step inside an iteration scope: the only step the open-scope cap defers."""
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
        """Queued loop steps that may start now: their loop must be able to open an iteration at once, and the
        iteration budget must not be waiting (queued loop steps share its one request). Under the cap, in scheduling
        order; past it, one per level on the progress path, from that level's reserved scope."""
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

    def _drop_captures(self, key: ScopeKey) -> None:
        for inst in [i for i in self._captures if i.scope[: len(key)] == key]:
            del self._captures[inst]
        self._gc_versions()

    # --- proto (§5.3): variables, their versions and captures ---------------------------------------------------------

    def init_vars(self, values: dict[str, Any]) -> None:
        self._live -= P.size(self.vars)
        self.vars = dict(values)
        self._live += P.size(self.vars)

    def set_variables(self, values: Any) -> None:
        """A root `set_variables` settled: a new version. Each older version a queued loop step still names keeps the
        values this write replaces."""
        refs = set(self._captures.values()) | set(self._released.values())
        if self.vars_version in refs and self.vars_version not in self.var_deltas:
            self.var_deltas[self.vars_version] = {}
            self._live += P.size({})
        for delta in self.var_deltas.values():
            before = P.size(delta)
            for name in values:
                if name not in delta:
                    delta[name] = [self.vars[name]] if name in self.vars else []
            self._live += P.size(delta) - before
        before = P.size(self.vars)
        self.vars.update(values)
        self._live += P.size(self.vars) - before
        self.vars_version += 1
        self.probe["var_versions"] = max(self.probe.get("var_versions", 0), self.vars_version)

    def vars_at(self, version: int | None) -> dict[str, Any]:
        if version is None or version == self.vars_version:
            return dict(self.vars)
        out = dict(self.vars)
        for name, old in self.var_deltas.get(version, {}).items():
            if old:
                out[name] = old[0]
            else:
                out.pop(name, None)
        return out

    def consume_capture(self, inst: Instance) -> dict[str, Any] | None:
        """A released loop step's unit starts: the variables of the version it captured, read before that version
        may be dropped. None: it captured none, and reads the current ones."""
        if inst not in self._released:
            return None
        variables = self.vars_at(self._released.pop(inst))
        self._gc_versions()
        return variables

    def _gc_versions(self) -> None:
        refs = set(self._captures.values()) | set(self._released.values())
        for version in [v for v in self.var_deltas if v not in refs]:
            self._live -= P.size(self.var_deltas.pop(version))

    def _path(self) -> set[ScopeKey]:
        """The progress chain: from the execution's own root (a batch child's loop scope), the oldest open iteration
        at each level below."""
        oldest: dict[ScopeKey, Scope] = {}
        for sc in self.scopes.values():
            if sc.key and not sc.frozen:
                best = oldest.get(sc.key[:-1])
                if best is None or sc.seq < best.seq:
                    oldest[sc.key[:-1]] = sc
        current: ScopeKey = self.batch_loop.scope if self.batch_loop is not None else ()
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

    @property
    def open_scopes(self) -> int:
        return self._n_open

    # --- continue-as-new ---------------------------------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """The scheduler's state for a continue-as-new snapshot (proto `snapshot_format` 2): steps, edges and loops by
        index, node and edge states as one code each in region order, and no queue: what's queued is rebuilt from the
        states on restore. Taken between units: nothing settled or cancelled is left to hand over."""
        if self._settled or self._cancels or self.ended is not None:
            raise ValueError("a snapshot is taken only between units, and never after the run ended")
        self._check_queues()
        by_scope: dict[ScopeKey, dict[uuid.UUID, int]] = {}
        for inst, version in self._captures.items():
            by_scope.setdefault(inst.scope, {})[inst.step] = version
        return {
            "snapshot_format": SNAPSHOT_FORMAT,
            "scopes": [self._scope2(sc, by_scope.get(sc.key, {})) for sc in self.scopes.values()],
            "loops": [self._loop2(loop) for loop in self.loops.values()],
            "handed": [self._i(i) for i in sorted(self._handed_now(), key=self.order)],
            "collects_out": [
                [self._i(i), n] for i, n in sorted(self._collects_out, key=lambda c: (self.order(c[0]), c[1]))
            ],
            "batches_out": [
                [self._i(i), n] for i, n in sorted(self._batches_out, key=lambda b: (self.order(b[0]), b[1]))
            ],
            "spills_out": [
                [self._i(i), w, n] for i, w, n in sorted(self._spills_out, key=lambda b: (self.order(b[0]), b[1], b[2]))
            ],
            "budget": self.budget.to_json(),
            "budget_waits": [[k, self._i(i)] for k, i in self._budget_waits.items()],
            "batch_loop": self._i(self.batch_loop) if self.batch_loop else None,
            "vars": self.vars,
            "vars_version": self.vars_version,
            "var_deltas": [[v, d] for v, d in sorted(self.var_deltas.items())],
            "released": [[self._i(i), v] for i, v in sorted(self._released.items(), key=lambda c: self.order(c[0]))],
            "starting": [
                [self._i(i), int(r)] for i, r in sorted(self._starting.items(), key=lambda c: self.order(c[0]))
            ],
            "held": [[self._i(i), int(r)] for i, r in sorted(self._held.items(), key=lambda c: self.order(c[0]))],
            "seq": self._seq,
            "probe": dict(self.probe),
        }

    @classmethod
    def from_json(cls, program: Program, data: dict[str, Any]) -> "Scheduler":
        if data.get("snapshot_format") != SNAPSHOT_FORMAT:
            raise ValueError(f"unknown snapshot format {data.get('snapshot_format')!r}")
        s = cls(program, budget=Budget.from_json(data["budget"]))
        for raw in data["scopes"]:
            scope = s._scope2_from(raw)
            s.scopes[scope.key] = scope
        s._n_open = sum(1 for sc in s.scopes.values() if sc.key and not sc.frozen)
        for raw in data["loops"]:
            loop = s._loop2_from(raw)
            s.loops[loop.instance] = loop
        s._handed = {s._if(i) for i in data["handed"]} | set(s.loops)
        s._collects_out = {(s._if(i), int(n)) for i, n in data["collects_out"]}
        s._batches_out = {(s._if(i), int(n)) for i, n in data["batches_out"]}
        s._spills_out = {(s._if(i), str(w), int(n)) for i, w, n in data["spills_out"]}
        s._budget_waits = {str(k): s._if(i) for k, i in data["budget_waits"]}
        s.batch_loop = s._if(data["batch_loop"]) if data["batch_loop"] else None
        s.vars = dict(data["vars"])
        s.vars_version = int(data["vars_version"])
        s.var_deltas = {int(v): dict(d) for v, d in data["var_deltas"]}
        s._released = {s._if(i): int(v) for i, v in data["released"]}
        s._starting = {s._if(i): bool(r) for i, r in data["starting"]}
        s._held = {s._if(i): bool(r) for i, r in data["held"]}
        s._seq = int(data["seq"])
        s.probe = dict(data["probe"])
        s._ready, s._collects, s._batches = s._rebuilt()
        s._live = s._recount()
        s._spills = [
            Spill(loop.instance, coll.base, f, pairs, which)
            for loop in s.loops.values()
            for which, coll in s._colls(loop)
            for f, pairs in sorted(coll.sealing.items())
            if (loop.instance, which, f) not in s._spills_out
        ]
        s._spills += [
            Spill(loop.instance, loop.items_base, k, loop.items[k * loop.items_per : (k + 1) * loop.items_per], "i")
            for loop in s.loops.values()
            for k in loop.items_pending
            if (loop.instance, "i", k) not in s._spills_out
        ]
        s._capped = {
            inst
            for inst, loop in s.loops.items()
            if not loop.batch
            and not loop.waiting
            and loop.next < P.count(loop.items)
            and len(loop.open) < loop.concurrency
        }
        return s

    def _handed_now(self) -> set[Instance]:
        """Steps handed over and still running, loop steps aside (their loop says they run)."""
        out = set()
        for inst in self._handed:
            scope = self.scopes.get(inst.scope)
            if scope is not None and scope.nodes.get(inst.step) == NodeState.RUNNING and inst not in self.loops:
                out.add(inst)
        return out

    def _rebuilt(self) -> tuple[list[Instance], list[Collect], list[Batch]]:
        """What's queued, from the states: running steps not handed over, iterations whose `collect` waits, batches
        handed out and not taken."""
        ready = sorted(
            (
                Instance(sc.key, n)
                for sc in self.scopes.values()
                for n, st in sc.nodes.items()
                if st == NodeState.RUNNING and Instance(sc.key, n) not in self._handed
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
            Batch(loop.instance, loop.running_batch, P.sliced(loop.items, loop.running_batch, loop.next))
            for loop in self.loops.values()
            if loop.running_batch is not None and (loop.instance, loop.running_batch) not in self._batches_out
        ]
        return ready, collects, batches

    def _check_queues(self) -> None:
        """Proto: restoring rebuilds exactly what's queued now, and counts the live state the same."""
        if self._live != self._recount():
            raise AssertionError(f"proto: live {self._live} != recount {self._recount()}")
        self._handed |= set(self.loops)  # a loop step is handed over for as long as its loop runs
        ready, collects, batches = self._rebuilt()
        if set(ready) != set(self._ready) | self._deferred:
            raise AssertionError(
                f"proto: rebuilt ready {len(ready)} != queued {len(self._ready) + len(self._deferred)}"
            )
        if {(c.loop, c.index, c.scope) for c in collects} != {(c.loop, c.index, c.scope) for c in self._collects}:
            raise AssertionError("proto: rebuilt collects differ")
        if {(b.loop, b.start, P.count(b.items)) for b in batches} != {
            (b.loop, b.start, P.count(b.items)) for b in self._batches
        }:
            raise AssertionError("proto: rebuilt batches differ")

    # indexes: a scope key as [loop topo, item index, ...]; an instance as [key, step topo]
    def _k(self, key: ScopeKey) -> list[int]:
        return [x for loop, i in key for x in (self.program.steps[self.program.by_key[loop]].topo, i)]

    def _kf(self, raw: list[int]) -> ScopeKey:
        return tuple((self.program.steps[self._by_topo[raw[j]]].key, int(raw[j + 1])) for j in range(0, len(raw), 2))

    def _i(self, inst: Instance) -> list[Any]:
        return [self._k(inst.scope), self.program.steps[inst.step].topo]

    def _if(self, raw: list[Any]) -> Instance:
        return Instance(self._kf(raw[0]), self._by_topo[int(raw[1])])

    def _edge_order(self, region: uuid.UUID | None) -> list[int]:
        """A region's edges in the order `_open_scope` lays them out."""
        order = self._edge_orders.get(region)
        if order is None:
            order = [e for node_id in self._members[region] for e in self.program.steps[node_id].ins]
            self._edge_orders[region] = order
        return order

    def _scope2(self, sc: Scope, captures: dict[uuid.UUID, int]) -> list[Any]:
        if sc.frozen:
            nodes = edges = ""
        else:
            nodes = "".join(_NODE_CODE[sc.nodes[m]] for m in self._members[sc.region])
            edges = "".join(_EDGE_CODE[sc.edges[e]] for e in self._edge_order(sc.region))
        results = []
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
        return [
            self._k(sc.key),
            region,
            nodes,
            edges,
            results,
            sc.item,
            sc.index,
            failure,
            int(sc.frozen),
            sc.seq,
            int(sc.reserved),
            "".join(_capture_code(captures[m]) if m in captures else NO_CAPTURE for m in self._loop_members[sc.region])
            if captures
            else "",
        ]

    def _scope2_from(self, raw: list[Any]) -> Scope:
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
                self._captures[Instance(key, m)] = _capture_from(code)
        return Scope(key, region, nodes, edges, results, raw[5], raw[6], failure, frozen, int(raw[9]), bool(raw[10]))

    def _loop2(self, loop: LoopRun) -> list[Any]:
        return [
            self._i(loop.instance), loop.items, loop.concurrency, int(loop.stop_on_error), loop.offset, loop.batch,
            loop.next, list(loop.open), sorted(loop.collecting), loop.coll.to_json() if loop.coll else None,
            loop.fails.to_json() if loop.fails else None, loop.running_batch, int(loop.waiting),
            loop.items_pending, loop.items_per, loop.items_base,
        ]  # fmt: skip

    def _loop2_from(self, raw: list[Any]) -> LoopRun:
        return LoopRun(
            instance=self._if(raw[0]), items=raw[1] if P.is_kind(raw[1], P.LIST) else list(raw[1]),
            concurrency=int(raw[2]), stop_on_error=bool(raw[3]), offset=int(raw[4]), batch=int(raw[5]),
            next=int(raw[6]), open=[int(i) for i in raw[7]], collecting={int(i) for i in raw[8]},
            coll=Collection.from_json(raw[9]) if raw[9] else None,
            fails=Collection.from_json(raw[10]) if raw[10] else None,
            items_pending=[int(k) for k in raw[13]], items_per=int(raw[14]), items_base=str(raw[15]),
            running_batch=raw[11], waiting=bool(raw[12]),
        )  # fmt: skip


__all__ = [
    "Batch",
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
