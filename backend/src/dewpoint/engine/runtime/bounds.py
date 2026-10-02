# SPDX-License-Identifier: Apache-2.0
"""The bound on a continued input (engine 2b spec §5.3), and the open-iteration cap a version gets from it:

    CODEC_OVERHEAD + ENVELOPE_MAX + TRIGGER_MAX + STRUCTURE_MAX_v(cap) + LIVE_BUDGET <= SNAPSHOT_MAX

Each maximum is the largest encoding its component can have, built with the encoders a snapshot uses: every id at
ID_MAX, every key at its longest, every number at its widest, every code present. Values (results, items, the parts of
collections, variables, handles in the state) are component 5's, counted by the live-state budget: here every value
slot is encoded empty (null, [], {}), and its framing counts. Learned sensitive values are none (component 3), and the
iteration budget's waiting needs and children's grants are none at a continue (the at-continue term): only its fixed
counters travel, in the envelope.

Publish computes a version's cap and its loop depth `D` (`pinned`) and stores them in the version: runs pin it, so a
later change of a constant can't change how a pinned run schedules. A version no cap fits fails to establish the bound
(`BoundError`): publish refuses it, never pinning a cap of 0 a run could read as none."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from temporalio.converter import DataConverter

from dewpoint.engine.graph.structure import MAX_LOOP_DEPTH
from dewpoint.engine.handles import HANDLE_MAX
from dewpoint.engine.registry.control import SET_VARIABLES
from dewpoint.engine.runtime import scheduler as S
from dewpoint.engine.runtime.activities import BatchInput, Parent, RunInput
from dewpoint.engine.runtime.execution import IN_FLIGHT_CAP
from dewpoint.engine.runtime.ids import ID_MAX, ITEM_CAP_MAX
from dewpoint.engine.runtime.program import Program
from dewpoint.engine.runtime.scheduler import (
    OPEN_SCOPES_CAP,
    SNAPSHOT_FORMAT,
    Box,
    Collection,
    EdgeState,
    Instance,
    LoopRun,
    NodeState,
    Scheduler,
    Scope,
)
from dewpoint.engine.runtime.size import CODEC_OVERHEAD, SNAPSHOT_BYTES
from dewpoint.engine.split import TRIGGER_INLINE

SNAPSHOT_MAX = SNAPSHOT_BYTES  # 1.5 MiB, encoded
U = str(uuid.UUID(int=(1 << 128) - 1))  # a UUID, as the grammar writes it
KEY = "k" * 63  # the longest step key
INDEX = ITEM_CAP_MAX - 1  # the largest item index
TOPO = 499  # the largest step index (MAX_NODES - 1)
SEQ = 999_999  # a scope's opening number, and a container's claim count: iterations are capped at 100,000 per run
VERSION = 62 * 62 - 1  # the largest variable version a capture encodes
ISO = "2026-09-30T23:59:59.999999+00:00"
IK_MAX = "/".join([f"{KEY}:{INDEX}"] * (MAX_LOOP_DEPTH - 1))  # the enclosing iterations of the deepest loop
TRIGGER_MAX = TRIGGER_INLINE + HANDLE_MAX
_CONVERTER = DataConverter.default.payload_converter


def size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def encoded(value: Any) -> int:
    """As Temporal holds it: the payload the default converter makes (the codec's share is counted apart)."""
    return len(_CONVERTER.to_payloads([value])[0].data)


# --- component 1: the envelope ---------------------------------------------------------------------------------------


def _parent() -> Parent:
    return Parent("w" * ID_MAX, U, U, IK_MAX, "failure_handler", ISO, 100_000, 5, U)


def _header() -> dict[str, Any]:
    """A snapshot with nothing in it but its header: every structural list empty, every value slot empty, every
    counter at its widest. The iteration budget holds no waiting need and no grant at a continue (§5.3)."""
    budget = {"total": 100_000, "root": False, "used": 100_000, "reserved": {}, "waiting": [], "asking": False,
              "refused": False}  # fmt: skip
    sched = {
        "snapshot_format": SNAPSHOT_FORMAT, "scopes": [], "loops": [], "handed": [], "collects_out": [],
        "batches_out": [], "budget": budget, "budget_waits": [],
        "batch_loop": [[TOPO, INDEX] * (MAX_LOOP_DEPTH - 1), TOPO],
        "starting": [], "held": [], "seq": SEQ, "vars": {}, "vbox": [None, None, SEQ], "vars_version": VERSION,
        "undo": [], "released": [], "spills_out": [],
    }  # fmt: skip
    kinds = ("activities", "cancelled", "children", "claims", "collect", "project", "timers", "values")
    drained = {
        "at": ISO,
        "events": [99_999_999] * 2,
        "bytes": [999_999_999_999] * 2,
        "units": dict.fromkeys(kinds, 100),
    }
    return {"snapshot_format": SNAPSHOT_FORMAT, "scheduler": sched, "run_started_at": ISO, "deadline": ISO,
            "drained": drained, "timers": []}  # fmt: skip


def envelope_max() -> int:
    """Every field at its widest, every id at ID_MAX, the trigger empty (component 2), the snapshot a bare header. A
    continued batch carries no items, outer scopes or variables (each value travels once)."""
    run = RunInput(U, U, U, {}, "simulate", 30 * 86_400.0, 600.0, _parent(), U, _header(), 1_000_000, 1_000_000,
                   100_000)  # fmt: skip
    batch = BatchInput(U, U, U, U, [], [], INDEX, 10_000, True, {}, {}, ISO, _parent(), "simulate", 600.0, _header(),
                       1_000_000, 1_000_000, 100_000, None, U)  # fmt: skip
    return max(encoded(run), encoded(batch))


# --- component 4: the structure ---------------------------------------------------------------------------------------


def _key(program: Program, loops: list[uuid.UUID | None]) -> tuple[tuple[str, int], ...]:
    """A scope's key through these loops: encoded, then widened (every loop's index at its largest)."""
    return tuple((program.steps[lp].key, INDEX) for lp in loops if lp is not None)


def scope_record(sched: Scheduler, key: tuple[tuple[str, int], ...], region: uuid.UUID | None, *, frozen: bool) -> int:
    """A scope's record at its widest, its values empty: every code, every capture, its box's framing."""
    members = sched._members[region]
    sc = Scope(key, region, dict.fromkeys(members, NodeState.WAITING), {}, {}, None, INDEX if key else None,
               None, frozen, SEQ, True)  # fmt: skip
    sc.item_sealing = True
    if not frozen:
        sc.edges = dict.fromkeys(sched._edge_order(region), EdgeState.PENDING)
    else:
        sc.claimed = "c" * len(members)
    captures = {m: VERSION for m in sched._loop_members[region]} if key and not frozen else {}
    raw = sched._scope_json(sc, captures)
    raw[0] = [TOPO, INDEX] * len(key)
    raw[1] = TOPO if region is not None else -1
    raw[12] = [None, None, SEQ]  # the box's framing: its handle and the part on its way are values
    return size(raw) + 1  # and the comma between records


def loop_record(sched: Scheduler, loop: uuid.UUID, enclosing: list[uuid.UUID | None]) -> int:
    """A started loop's record at its widest, its values empty: its counters, its two collections' framing, the
    slot a batch-mode loop holds."""
    depth = len(enclosing)
    inst = Instance(_key(sched.program, enclosing), loop)
    colls = [Collection(U + "/c", 10_000, INDEX, False, ibox=Box(None, None, SEQ), assembling=True),
             Collection(U + "/f", 10_000, INDEX, True, ibox=Box(None, None, SEQ), assembling=True)]  # fmt: skip
    lp = LoopRun(inst, [], 10_000, True, INDEX, 100, 10_000, [], set(), colls[0], colls[1], INDEX, True, True)
    raw = sched._loop_json(lp)
    raw[0] = [[TOPO, INDEX] * depth, TOPO]
    raw[1] = None  # an inline item list is a value
    for c in (9, 10):
        raw[c]["index"] = [None, None, SEQ]
    held = size([[[TOPO, INDEX] * depth, TOPO], 1]) + 1
    return size(raw) + 1 + held


def unit_max() -> int:
    """A unit handed out at a continue, a sleeping timer: its entry in the scheduler, and its wake time in the
    execution's snapshot."""
    key = [[TOPO, INDEX] * MAX_LOOP_DEPTH, TOPO]
    timer = [[[KEY, INDEX]] * MAX_LOOP_DEPTH, U, ISO, ISO, "activity"]
    return size(key) + size(timer) + 2


@dataclass(frozen=True)
class Maxima:
    envelope: int
    trigger: int
    live: int
    d: int
    root_loops: int
    root_setvars: int
    iter_scope: int  # ITER_SCOPE_MAX_v, with an open scope's entries in its loop's open and collecting lists
    root_scope: int  # ROOT_SCOPE_MAX_v, with the undo records' framing
    loop: int  # LOOP_MAX
    frozen: int  # FROZEN_MAX
    unit: int  # UNIT_MAX

    def structure(self, cap: int) -> int:
        return (
            (cap + self.d) * (self.iter_scope + self.loop)
            + self.root_scope
            + self.root_loops * self.loop
            + self.frozen
            + IN_FLIGHT_CAP * self.unit
        )

    def total(self, cap: int) -> int:
        return CODEC_OVERHEAD + self.envelope + self.trigger + self.structure(cap) + self.live

    def cap(self) -> int:
        """The largest cap, at most OPEN_SCOPES_CAP, whose total fits SNAPSHOT_MAX; 0 when none does."""
        return max((c for c in range(1, OPEN_SCOPES_CAP + 1) if self.total(c) <= SNAPSHOT_MAX), default=0)

    def live_min(self, cap: int) -> int:
        """Every container claimed: HANDLE_MAX each. Two per scope (open iterations, the root, a batch's frozen
        scopes), five per started loop (its item list, and each collection's segment list and whole list), one per
        kept undo record, and the variables."""
        scopes = cap + self.d + 1 + MAX_LOOP_DEPTH
        loops = cap + self.d + self.root_loops
        return HANDLE_MAX * (2 * scopes + 5 * loops + self.root_setvars + 1)


class BoundError(ValueError):
    """No open-iteration cap fits the continued-input bound: the bound can't be established for the version."""


_ENVELOPE: list[int] = []


def maxima(program: Program) -> Maxima:
    if not _ENVELOPE:
        _ENVELOPE.append(envelope_max())
    sched = Scheduler(program)
    loops = [sid for sid in program.regions if sid is not None]
    d = program.depth
    root_loops = sum(1 for sid in loops if program.steps[sid].region is None)
    setvars = sum(1 for st in program.steps.values() if st.ref == SET_VARIABLES and st.region is None)
    iter_scope = loop_rec = frozen = 0
    for lp in loops:
        enclosing = [r for r in reversed(program.chain(program.steps[lp].region)) if r is not None]  # outermost first
        key = _key(program, [*enclosing, lp])
        iter_scope = max(iter_scope, scope_record(sched, key, lp, frozen=False) + 2 * len(f",{INDEX}"))
        loop_rec = max(loop_rec, loop_record(sched, lp, list(enclosing)))
        chain: list[uuid.UUID | None] = [None, *enclosing]
        frozen = max(
            frozen,
            sum(scope_record(sched, _key(program, list(chain[1 : i + 1])), chain[i], frozen=True)
                for i in range(len(chain))),
        )  # fmt: skip
    root = scope_record(sched, (), None, frozen=False) + setvars * (size([99_999_999, TOPO, None, None, 1]) + 1)
    return Maxima(_ENVELOPE[0], TRIGGER_MAX, S.LIVE_BUDGET, d, root_loops, setvars, iter_scope, root, loop_rec, frozen,
                  unit_max())  # fmt: skip


def pinned(program: Program) -> tuple[int, int]:
    """What publish stores in a version: its open-iteration cap, and its loop depth `D`. Raises BoundError when no
    cap fits."""
    m = maxima(program)
    cap = m.cap()
    if cap < 1:
        raise BoundError(
            f"No open-iteration cap fits the continued-input bound: {m.total(1):,} bytes at a cap of 1, past "
            f"{SNAPSHOT_MAX:,}."
        )
    return cap, m.d


__all__ = ["SNAPSHOT_MAX", "TRIGGER_MAX", "BoundError", "Maxima", "maxima", "pinned"]
