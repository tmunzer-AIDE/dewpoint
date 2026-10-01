"""Throwaway (2b-1b §5.3 follow-up): the maxima of §5.3's five components, computed by building the largest encoding
each can have with the prototype's own encoders, and the open-scope cap a version gets from them:

  CODEC_OVERHEAD + ENVELOPE_MAX + TRIGGER_MAX + STRUCTURE_MAX_v(cap) + LIVE_BUDGET <= SNAPSHOT_MAX

`publish(program)` is what the prototype's publish stores in the version (OPEN_SCOPES_CAP_v, D_v); `report(program)`
gives every term. Values (results, items, collections' parts, variables, handles in the state) are component 5's,
counted by the live-state budget: here each value slot is encoded empty (null, [], {}), and its framing is counted."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from temporalio.converter import DataConverter

from dewpoint.engine.graph.structure import MAX_LOOP_DEPTH
from dewpoint.engine.registry.control import LOOP, SET_VARIABLES
from dewpoint.engine.runtime import probe as P
from dewpoint.engine.runtime.activities import BatchInput, Parent, RunInput
from dewpoint.engine.runtime.budget import Budget, Need
from dewpoint.engine.runtime.execution import IN_FLIGHT_CAP
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

SNAPSHOT_MAX = 1_572_864  # 1.5 MiB
CODEC_OVERHEAD = 256  # §5.2: what TenantCodec adds, at most (2b-1a's proven bound)
U = "f" * 8 + "-" + "f" * 4 + "-" + "f" * 4 + "-" + "f" * 4 + "-" + "f" * 12  # a UUID, as the grammar writes it
KEY = "k" * 63  # the longest step key
INDEX = 9_999  # the largest item index (item_cap 10,000)
SEQ = 999_999  # a scope's opening number: iterations are capped at 100,000 per logical run
IK_MAX = "/".join([f"{KEY}:{INDEX}"] * (MAX_LOOP_DEPTH - 1))  # the enclosing iterations of the deepest loop
ID_MAX = len(f"t:{U}:run:{U}/{U}/{IK_MAX}/batch:{INDEX}")  # §6.1: a batch's id, the longest server-built id
ISO = "2026-09-30T23:59:59.999999+00:00"
_CONVERTER = DataConverter.default.payload_converter


def size(v: Any) -> int:
    return len(json.dumps(v, separators=(",", ":")))


def encoded(v: Any) -> int:
    """As Temporal holds it: the payload the default converter makes (the codec's overhead is counted apart)."""
    [payload] = _CONVERTER.to_payloads([v])
    return payload.ByteSize()


# --- component 1: the envelope ---------------------------------------------------------------------------------------


def _parent() -> Parent:
    wid = "w" * ID_MAX
    return Parent(wid, U, U, IK_MAX, "failure_handler", ISO, 100_000, 5, [])


def _header() -> dict[str, Any]:
    """A snapshot with nothing in it but its header: every structural list empty, every value slot empty."""
    sched = {
        "snapshot_format": SNAPSHOT_FORMAT, "scopes": [], "loops": [], "handed": [], "collects_out": [],
        "batches_out": [], "spills_out": [],
        "budget": {"total": 100_000, "root": False, "used": 100_000, "reserved": {}, "waiting": [], "asking": False,
                   "refused": False},
        "budget_waits": [], "batch_loop": [[499, INDEX] * (MAX_LOOP_DEPTH - 1), 499], "vars": {},
        "vbox": [None, None, SEQ], "vars_version": 499, "undo": [], "released": [], "starting": [], "held": [],
        "seq": SEQ, "probe": {},
    }  # fmt: skip
    return {"snapshot_format": SNAPSHOT_FORMAT, "scheduler": sched, "secrets": [], "run_started_at": ISO,
            "deadline": ISO, "drained": 1_000_000, "timers": []}  # fmt: skip


def budget_fixed() -> int:
    """The budget's fixed counters at their widest, as the snapshot's header holds them (inside ENVELOPE_MAX)."""
    return size(_header()["scheduler"]["budget"])


def envelope_max() -> int:
    """Every field at its widest, every id at ID_MAX, the trigger empty (component 2), the snapshot a bare header."""
    run = RunInput(U, U, U, {}, "simulate", 30 * 86_400.0, 600.0, _parent(), U, _header(), 1_000_000, 1_000_000,
                   100_000)  # fmt: skip
    batch = BatchInput(U, U, U, U, [], [], INDEX, 10_000, True, {}, {}, ISO, _parent(), "simulate", 600.0, _header(),
                       1_000_000, 1_000_000, 100_000, None, "c" * P.CLAIM_ID_MAX)  # fmt: skip
    return max(encoded(run), encoded(batch))


# --- component 2: the trigger ----------------------------------------------------------------------------------------

TRIGGER_MAX = P.TRIGGER_INLINE + P.HANDLE_MAX


# --- component 4: the structure ---------------------------------------------------------------------------------------


def _key(program: Program, loops: list[uuid.UUID]) -> tuple[tuple[str, int], ...]:
    return tuple((program.steps[lp].key, INDEX) for lp in loops)


def _scope_record(sched: Scheduler, key: tuple[tuple[str, int], ...], region: uuid.UUID | None, *, frozen: bool) -> int:
    members = sched._members[region]
    sc = Scope(key, region, dict.fromkeys(members, NodeState.WAITING), {}, {}, None, INDEX if key else None,
               None, frozen, SEQ, True, Box(), True)  # fmt: skip
    if not frozen:
        sc.edges = dict.fromkeys(sched._edge_order(region), EdgeState.PENDING)
    captures = {m: 62 * 62 - 1 for m in sched._loop_members[region]} if key and not frozen else {}
    raw = sched._scope2(sc, captures)
    raw[12] = [None, None, SEQ]  # the box's framing: its handle and its part being claimed are values
    return size(raw) + 1  # and the comma between records


def _loop_record(sched: Scheduler, inst: Instance) -> int:
    lst = {P.KIND: P.LIST, "id": "c" * P.CLAIM_ID_MAX, "n": 10_000, "per": 10_000, "from": 10_000}
    base = "c" * P.CLAIM_ID_MAX
    coll = Collection(base, 10_000, INDEX, ibox=Box(None, None, SEQ))
    fails = Collection(base + "!f", 10_000, INDEX, ibox=Box(None, None, SEQ))
    lp = LoopRun(inst, lst, 10_000, True, INDEX, 100, 10_000, [], [], coll, fails, INDEX, True,
                 list(range(7)), 10_000, base)  # fmt: skip
    held = size([sched._i(inst), 1]) + 1  # a batch-mode loop's slot
    return size(sched._loop2(lp)) + 1 + held


@dataclass
class Maxima:
    envelope: int
    trigger: int
    live: int
    d: int
    root_loops: int
    root_setvars: int
    iter_scope: int  # ITER_SCOPE_MAX_v, with an open scope's entries in its loop's open and collecting lists
    root_scope: int  # ROOT_SCOPE_MAX_v, with the undo records' framing
    loop: int  # LOOP_MAX_v
    frozen: int  # FROZEN_MAX
    unit: int  # UNIT_MAX
    need: int  # NEED_MAX
    grant: int  # GRANT_MAX

    def budget(self, cap: int, at_continue: bool = False) -> int:
        """BUDGET_MAX_v(cap) as rev 5 states it; `at_continue`: an execution continues only once its budget holds no
        waiting need and no child's grant (enforced: the quiescence check and the snapshot), so only its fixed
        counters travel, and they're in ENVELOPE_MAX (`budget_fixed`), as `Parent.grant` is."""
        if at_continue:
            return 0
        return (cap + self.d + self.root_loops + 2 * IN_FLIGHT_CAP) * self.need + IN_FLIGHT_CAP * self.grant

    def structure(self, cap: int, at_continue: bool = False) -> int:
        return (
            (cap + self.d) * (self.iter_scope + self.loop)
            + self.root_scope
            + self.root_loops * self.loop
            + self.frozen
            + IN_FLIGHT_CAP * self.unit
            + self.budget(cap, at_continue)
        )

    def total(self, cap: int, at_continue: bool = False) -> int:
        return CODEC_OVERHEAD + self.envelope + self.trigger + self.structure(cap, at_continue) + self.live

    def cap(self, at_continue: bool = False) -> int:
        """The largest cap, at most OPEN_SCOPES_CAP, whose total fits SNAPSHOT_MAX; 0 when none does."""
        best = 0
        for cap in range(1, OPEN_SCOPES_CAP + 1):
            if self.total(cap, at_continue) <= SNAPSHOT_MAX:
                best = cap
        return best

    def live_min(self, cap: int) -> int:
        """Every container claimed: HANDLE_MAX each. Two per scope (open iterations, the root, a batch's frozen
        scopes), five per started loop, one per kept undo record, and the variables."""
        scopes = cap + self.d + 1 + MAX_LOOP_DEPTH
        loops = cap + self.d + self.root_loops
        return P.HANDLE_MAX * (2 * scopes + 5 * loops + self.root_setvars + 1)


_ENVELOPE: int | None = None


def maxima(program: Program) -> Maxima:
    global _ENVELOPE
    if _ENVELOPE is None:
        _ENVELOPE = envelope_max()
    sched = Scheduler(program)
    loops = [sid for sid in program.regions if sid is not None]
    d = max((len(program.chain(program.steps[lp].region)) for lp in loops), default=0)
    root_loops = sum(1 for sid in loops if program.steps[sid].region is None)
    setvars = sum(1 for st in program.steps.values() if st.ref == SET_VARIABLES and st.region is None)
    iter_scope = 0
    loop_rec = 0
    for lp in loops:
        enclosing = list(reversed(program.chain(program.steps[lp].region)))  # outermost first
        enclosing = [r for r in enclosing if r is not None]
        key = _key(program, [*enclosing, lp])
        iter_scope = max(iter_scope, _scope_record(sched, key, lp, frozen=False) + 2 * len(f",{INDEX}"))
        loop_rec = max(loop_rec, _loop_record(sched, Instance(_key(program, enclosing), lp)))
    root = _scope_record(sched, (), None, frozen=False) + setvars * (size([99_999_999, 499, None, None, 1]) + 1)
    frozen = 0
    for lp in loops:
        enclosing = [r for r in reversed(program.chain(program.steps[lp].region)) if r is not None]
        chain = [None, *enclosing]
        frozen = max(
            frozen,
            sum(_scope_record(sched, _key(program, enclosing[:i]), chain[i], frozen=True) for i in range(len(chain))),
        )
    timer_key = [[KEY, INDEX]] * MAX_LOOP_DEPTH
    unit = size([[[499, INDEX] * MAX_LOOP_DEPTH, 499]]) + size([timer_key, U, ISO, ISO, "activity"]) + 2
    local = size(["", f"loop:{IK_MAX}/{KEY}:{INDEX}:{KEY}", 1, 1, 0]) + size(
        [f"loop:{IK_MAX}/{KEY}:{INDEX}:{KEY}", [[499, INDEX] * MAX_LOOP_DEPTH, 499]]
    )
    filt = size(["", f"filter:{IK_MAX}/{KEY}:{INDEX}:{KEY}", 10_000, 10_000, 0])
    child = size(["w" * ID_MAX, "9" * 12, 100_000, 100_000, 100_000])
    need = max(local, filt, child) + 2
    grant = size({"w" * ID_MAX: 100_000}) - 1
    return Maxima(_ENVELOPE, TRIGGER_MAX, P.LIVE_BUDGET, d, root_loops, setvars, iter_scope, root, loop_rec, frozen,
                  unit, need, grant)  # fmt: skip


def publish(program: Program) -> tuple[int, int]:
    """What publish stores in the version: OPEN_SCOPES_CAP_v and D_v."""
    m = maxima(program)
    return m.cap(), m.d


def report(program: Program) -> dict[str, Any]:
    m = maxima(program)
    cap = m.cap()
    return {
        "ID_MAX": ID_MAX, "HANDLE_MAX": P.HANDLE_MAX, "POINTER_MAX": P.POINTER_MAX, "ENVELOPE_MAX": m.envelope,
        "BUDGET_FIXED (in ENVELOPE_MAX)": budget_fixed(), "Parent.grant (in ENVELOPE_MAX)": len("100000"),
        "TRIGGER_MAX": m.trigger, "LIVE_BUDGET": m.live, "D": m.d, "ROOT_LOOPS": m.root_loops,
        "ROOT_SETVARS": m.root_setvars, "ITER_SCOPE_MAX": m.iter_scope, "ROOT_SCOPE_MAX": m.root_scope,
        "LOOP_MAX": m.loop, "FROZEN_MAX": m.frozen, "UNIT_MAX": m.unit, "NEED_MAX": m.need, "GRANT_MAX": m.grant,
        "cap": cap, "STRUCTURE_MAX(cap)": m.structure(cap) if cap else None,
        "BUDGET_MAX(cap)": m.budget(cap) if cap else None, "total(cap)": m.total(cap) if cap else None,
        "STRUCTURE_MAX(1)": m.structure(1), "total(1)": m.total(1), "SNAPSHOT_MAX": SNAPSHOT_MAX,
        "headroom(1)": SNAPSHOT_MAX - m.total(1),
        "cap_at_continue": m.cap(True), "total_at_continue(1)": m.total(1, True),
        "headroom_at_continue(1)": SNAPSHOT_MAX - m.total(1, True),
        "LIVE_MIN(cap)": m.live_min(max(cap, m.cap(True))),
    }  # fmt: skip


__all__ = ["LOOP", "Maxima", "maxima", "publish", "report", "Need", "Budget"]
