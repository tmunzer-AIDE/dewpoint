# SPDX-License-Identifier: Apache-2.0
"""A single-step run's seeds (S2; the simulation design §5.3): the values its one step reads, given by pointer
(`{"values": {pointer: value}, "absent": [pointer]}`, the run's trigger), and the scope view built from them in place
of the scheduler's. The run binds `run` itself. A loop-contained step's innermost frame is `/item` and `/index`, which
its `loops.<key>` reads too. Nothing else is in scope: a read the seeds don't cover is a guard's failure
(`seed_missing`), which admission's check makes unreachable."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dewpoint.engine.cel.bind import ScopeView
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph.values import RefPath

SEED_MISSING = "seed_missing"
SEEDED_LIVE_REFUSED = "seeded_live_refused"
TARGET_INVALID = "target_invalid"


def segments(pointer: str) -> tuple[str, ...]:
    """A JSON pointer's segments (RFC 6901), unescaped."""
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError(f"not a JSON pointer: {pointer!r}")
    return tuple(s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/"))


def well_formed(trigger: Any) -> bool:
    """Seeds as `Seeds.of` reads them: `{"values": {pointer: value}, "absent": [pointer]}`, each pointer below the root.
    A root pointer (`""`) would cover every read."""
    if not isinstance(trigger, Mapping) or not set(trigger) <= {"values", "absent"}:
        return False
    values, absent = trigger.get("values", {}), trigger.get("absent", [])
    if not isinstance(values, Mapping) or not isinstance(absent, list | tuple):
        return False
    return all(isinstance(p, str) and p.startswith("/") for p in (*values, *absent))


def _put(tree: dict[str, Any], path: Sequence[str], value: Any) -> None:
    for seg in path[:-1]:
        nxt = tree.get(seg)
        if not isinstance(nxt, dict):
            nxt = tree[seg] = {}
        tree = nxt
    tree[path[-1]] = value


def _hollow(tree: dict[str, Any], path: Sequence[str]) -> None:
    """The containers above an absent value: it's absent from them, they're there (`has()` is false, not an error)."""
    for seg in path:
        nxt = tree.setdefault(seg, {})
        if not isinstance(nxt, dict):
            return
        tree = nxt


@dataclass(frozen=True)
class Seeds:
    values: Mapping[str, Any]
    absent: tuple[str, ...]
    innermost: str | None = None  # the key of the loop around the step, if any: its frame is `/item`, `/index`
    tree: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def of(cls, trigger: Mapping[str, Any], innermost: str | None) -> "Seeds":
        values = dict(trigger.get("values") or {})
        tree: dict[str, Any] = {}
        for pointer in sorted(values, key=lambda p: len(segments(p))):  # an outer value first, an inner one on it
            path = segments(pointer)
            if path:
                _put(tree, path, values[pointer])
        absent = tuple(trigger.get("absent") or ())
        for pointer in absent:
            _hollow(tree, segments(pointer)[:-1])
        return cls(values, absent, innermost, tree)

    @property
    def trigger(self) -> dict[str, Any]:
        found = self.tree.get("trigger", {})
        return found if isinstance(found, dict) else {}

    def view(self, run: Mapping[str, str], item: tuple[Any, int] | None = None) -> ScopeView:
        """The step's scope: its seeds, the run's own `run`, and a filter's element when `item` is given."""
        loops = {k: dict(v) for k, v in (self.tree.get("loops") or {}).items() if isinstance(v, dict)}
        if self.innermost is not None:  # its frame, with what's given of it: empty when `/item` is absent
            loops[self.innermost] = {k: self.tree[k] for k in ("item", "index") if k in self.tree}
        value: Any = self.tree.get("item")
        index: Any = self.tree.get("index")
        if item is not None:
            value, index = item
        steps = self.tree.get("steps") or {}
        variables = self.tree.get("vars") or {}
        return ScopeView(trigger=self.trigger, steps=steps, vars=variables, loops=loops, run=run, item=value,
                         index=index, framed=self.innermost is not None or item is not None)  # fmt: skip

    def covers(self, path: Sequence[str | int]) -> bool:
        """Whether a read of `path` (root first) is within a given or an absent value."""
        path = tuple(str(p) for p in path)
        if self.innermost is not None and path[:2] == ("loops", self.innermost) and len(path) >= 3:
            path = path[2:]  # the innermost frame's alias
        for pointer in (*self.values, *self.absent):
            seg = segments(pointer)
            if path[: len(seg)] == seg:
                return True
        return False


def read_paths(p: RefPath) -> tuple[str | int, ...]:
    """A reference's path, root first, as `covers` reads it."""
    if p.root in ("steps", "loops"):
        return (p.root, str(p.name), str(p.section), *p.rest)
    if p.root == "vars":
        return ("vars", *([str(p.name)] if p.name is not None else []), *p.rest)
    return (p.root, *p.rest)


def cel_paths(record: ExpressionRecord) -> list[tuple[str, ...]]:
    """What a CEL value reads that must be there: its typed paths, and its projections but presence tests."""
    out = [tuple(i.split(".")) for i in record.idents if "." in i]
    roots = {i for i in record.idents if "." not in i}
    out += [tuple(pr.path) for pr in record.projections if not pr.presence and pr.path and pr.path[0] in roots]
    covered = {pr.path[0] for pr in record.projections if pr.path}
    out += [(r,) for r in roots if r not in covered]
    return out
