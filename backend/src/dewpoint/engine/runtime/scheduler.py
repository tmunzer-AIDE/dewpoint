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

A snapshot (`snapshot_format` 2, engine 2b spec §5.3) holds states, not queues: one code per node and per edge in
region order, steps and loops by their topological index. Restoring rebuilds what's queued from those states, minus
what was handed out before the snapshot and is still running."""

import bisect
import heapq
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dewpoint.engine.runtime.budget import LOCAL, Answer, Ask, Budget, Need
from dewpoint.engine.runtime.program import BODY, DONE, ERROR_PORT, Program, Step

ScopeKey = tuple[tuple[str, int], ...]
ITERATION_CAP = 100_000  # loop iterations and filter items across the whole logical run (spec §4.2)
ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"
CAP_MESSAGE = "This run reached its limit of 100,000 loop iterations."
SNAPSHOT_FORMAT = 2
OPEN_SCOPES_CAP = 100  # open iteration scopes per execution, besides the progress path's reservation (§5.3)


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
    seq: int = 0  # its opening order: the oldest open iterations make the progress path (§5.3)
    reserved: bool = False  # opened from its level's reserved scope

    @property
    def settled(self) -> bool:
        return self.failure is not None or all(s in SETTLED for s in self.nodes.values())


@dataclass
class LoopRun:
    """A loop node's iterations: opened in order, at most `concurrency` at a time. `offset` is the index of
    `items[0]` (a batch child runs a slice). With `batch`, the items run in children of that many, one at a time."""

    instance: Instance
    items: list[Any]
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
    items: list[Any]


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
        self.undo: dict[int, dict[str, list[Any]]] = {}  # write k (version k -> k + 1): {name: [old] or [] if none}
        self._captures: dict[Instance, int] = {}  # a queued loop step -> the version it became ready under
        self._released: dict[Instance, int] = {}  # handed out, its unit not yet started
        self._vrefs: dict[int, int] = {}  # a captured version -> the queued or released loop steps that name it

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
        items: list[Any],
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
            self.scopes[o.key] = Scope(o.key, region, {}, {}, dict(o.results), o.item, o.index, frozen=True)
        loop_inst = Instance(outer[-1].key, loop_step)
        self.batch_loop = loop_inst
        loop = LoopRun(loop_inst, list(items), concurrency, stop_on_error, offset=offset, collected=[None] * len(items))
        self.loops[loop_inst] = loop
        self._advance(loop)

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

    def give_back(self, steps: list[Instance], collects: list[Collect], batches: list[Batch]) -> None:
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

    @_then_wake
    def succeed(self, inst: Instance, output: Any, ports: tuple[str, ...] | None = None) -> None:
        """The step succeeded. `ports`: the normal ports whose edges are live (if/switch pick one); all by default."""
        self._handed.discard(inst)
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.DONE
        scope.results[step.key] = {"output": output}
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
            self._resolve(scope, step, {ERROR_PORT})
        elif step.on_error == "continue":
            scope.results[step.key] = {"error": failure.to_json()}
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
        loop = LoopRun(inst, list(items), concurrency, stop_on_error, batch=batch, collected=[None] * len(items))
        self.loops[inst] = loop
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
        loop.collected[start : start + len(outcome.collected)] = outcome.collected
        loop.failures.extend(outcome.failures)
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
        if key:
            self._seq += 1
            scope.seq = self._seq
            self._n_open += 1
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
        loop.failures.append({"index": index, "code": failure.code, "message": failure.message})
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
        item = loop.items[loop.next]
        loop.next += 1
        loop.open.append(index)
        key = self._iteration_scope(loop, index)
        self._open_scope(key, loop.instance.step, item=item, index=index, reserved=reserved)

    def _advance(self, loop: LoopRun) -> None:
        """Open iterations up to the concurrency (or hand out the next batch), or complete the loop when every item
        is done."""
        if loop.batch:
            if loop.running_batch is None and loop.next < len(loop.items):
                start = loop.next
                loop.next = min(start + loop.batch, len(loop.items))
                loop.running_batch = start
                self._batches.append(Batch(loop.instance, start, loop.items[start : loop.next]))
                return
        else:
            while loop.next < len(loop.items) and len(loop.open) < loop.concurrency and not loop.waiting:
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
        if not loop.open and loop.next >= len(loop.items) and loop.running_batch is None and not loop.waiting:
            self._drop_loop(loop)
            if loop.instance == self.batch_loop:
                self._batch_over(loop, None)
                return
            output = {"items": loop.collected, "failures": loop.failures, "count": len(loop.items)}
            scope = self.scopes.get(loop.instance.scope)
            if scope is not None and scope.failure is None and self.ended is None:
                self.succeed(loop.instance, output, (DONE,))

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
        self._vars = dict(values)

    @property
    def vars(self) -> dict[str, Any]:
        """The current variables: what a step reads when it starts."""
        return dict(self._vars)

    def set_variables(self, values: Mapping[str, Any], step: Instance | None = None) -> None:
        """A root `set_variables` settled: the next version. While a queued loop step names an older one, this write
        keeps what it replaced."""
        if self._captures or self._released:
            self.undo[self.vars_version] = {name: [self._vars[name]] if name in self._vars else [] for name in values}
        self._vars.update(values)
        self.vars_version += 1

    def vars_at(self, version: int) -> dict[str, Any]:
        """The variables as they were at `version`: each written name from the oldest write after it."""
        out = self.vars
        for k in range(self.vars_version - 1, version - 1, -1):
            for name, old in self.undo[k].items():
                if old:
                    out[name] = old[0]
                else:
                    out.pop(name, None)
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
            for k in [k for k in self.undo if k < oldest]:
                del self.undo[k]

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
            "vars_version": self.vars_version,
            "undo": [[k, u] for k, u in sorted(self.undo.items())],
            "released": [[self._i(i), v] for i, v in sorted(self._released.items(), key=lambda c: self.order(c[0]))],
        }

    @classmethod
    def from_json(cls, program: Program, data: dict[str, Any]) -> "Scheduler":
        if data.get("snapshot_format") != SNAPSHOT_FORMAT:
            raise ValueError(f"unknown snapshot format {data.get('snapshot_format')!r}")
        s = cls(program, budget=Budget.from_json(data["budget"]))
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
        s.vars_version = int(data["vars_version"])
        s.undo = {int(k): dict(u) for k, u in data["undo"]}
        s._released = {s._if(i): int(v) for i, v in data["released"]}
        for version in s._released.values():
            s._vrefs[version] = s._vrefs.get(version, 0) + 1
        s._n_open = sum(1 for sc in s.scopes.values() if sc.key and not sc.frozen)
        ready, s._collects, s._batches = s._rebuilt()
        for inst in ready:  # queued loop steps inside iterations wait deferred, the rest ready
            if s._iter_loop(inst):
                s._defer(inst)
            else:
                s._ready.append(inst)
        s._capped = {  # a loop with items left and room for them may be one the cap held back: it tries again
            inst
            for inst, loop in s.loops.items()
            if not loop.batch and not loop.waiting and loop.next < len(loop.items) and len(loop.open) < loop.concurrency
        }
        return s

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
            Batch(loop.instance, loop.running_batch, loop.items[loop.running_batch : loop.next])
            for loop in self.loops.values()
            if loop.running_batch is not None and (loop.instance, loop.running_batch) not in self._batches_out
        ]
        return ready, collects, batches

    def _check_queues(self) -> None:
        """Restoring rebuilds exactly what's queued now."""
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
        if {(b.loop, b.start, len(b.items)) for b in batches} != {
            (b.loop, b.start, len(b.items)) for b in self._batches
        }:
            raise AssertionError("the rebuilt batches differ from those queued")

    # indexes: a scope key as [loop topo, item index, ...], an instance as [key, step topo]
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

    def _scope_json(self, sc: Scope, captures: Mapping[uuid.UUID, int]) -> list[Any]:
        """[key, region, node codes, edge codes, results, item, index, failure, frozen, seq, reserved, captures]:
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
        return [
            self._k(sc.key), region, nodes, edges, results, sc.item, sc.index, failure, int(sc.frozen), sc.seq,
            int(sc.reserved), codes,
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
        return Scope(key, region, nodes, edges, results, raw[5], raw[6], failure, frozen, int(raw[9]), bool(raw[10]))

    def _loop_json(self, loop: LoopRun) -> list[Any]:
        return [
            self._i(loop.instance), loop.items, loop.concurrency, int(loop.stop_on_error), loop.offset, loop.batch,
            loop.next, list(loop.open), sorted(loop.collecting), loop.collected, loop.failures, loop.running_batch,
            int(loop.waiting),
        ]  # fmt: skip

    def _loop_from(self, raw: list[Any]) -> LoopRun:
        return LoopRun(
            instance=self._if(raw[0]), items=list(raw[1]), concurrency=int(raw[2]), stop_on_error=bool(raw[3]),
            offset=int(raw[4]), batch=int(raw[5]), next=int(raw[6]), open=[int(i) for i in raw[7]],
            collecting={int(i) for i in raw[8]}, collected=list(raw[9]), failures=list(raw[10]),
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
