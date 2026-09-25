# SPDX-License-Identifier: Apache-2.0
"""When is a step guaranteed to have completed? (spec §4.3 path availability)

Each region (the root, or one loop body) is analysed separately. A step's liveness condition is a formula in
disjunctive normal form over branch decisions: which port a branching step took. A parallel fan-out adds no
literals, so a join after it is live exactly when its inputs are. Dominators would wrongly reject that case. For
exclusive branches the result matches dominance. `None` means "too complex to analyse", and callers treat it
conservatively."""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dewpoint.engine.graph.structure import Structure
from dewpoint.engine.registry import control as C

Lit = tuple[uuid.UUID, str]
Term = frozenset[Lit]
Cond = frozenset[Term] | None
TRUE: frozenset[Term] = frozenset({frozenset()})
FALSE: frozenset[Term] = frozenset()
ERR = "#err"
MAX_TERMS = 256


def _consistent(term: Term) -> bool:
    seen: dict[uuid.UUID, str] = {}
    return all(seen.setdefault(node, value) == value for node, value in term)


def simplify(terms: Iterable[Term], values: Mapping[uuid.UUID, tuple[str, ...]]) -> Cond:
    """Drop contradictions, absorb supersets, and merge terms that cover every value of one decision."""
    current = {t for t in terms if _consistent(t)}
    while True:
        if len(current) > MAX_TERMS:
            return None
        current = {t for t in current if not any(other < t for other in current)}
        additions: set[Term] = set()
        for term in current:
            for node, _ in term:
                options = values.get(node, ())
                base = frozenset(lit for lit in term if lit[0] != node)
                if base not in current and options and all(base | {(node, v)} in current for v in options):
                    additions.add(base)
        if not additions:
            return frozenset(current)
        current |= additions


def implies(consumer: Cond, producer: Cond) -> bool:
    """True when every situation in `consumer` guarantees `producer`. Sound; may say False when unsure."""
    if producer is None:
        return False
    if frozenset() in producer:
        return True
    if consumer is None:
        return False
    return all(any(p <= c for p in producer) for c in consumer)


def exclusive(a: Cond, b: Cond) -> bool:
    """True when the two conditions can never hold together."""
    if a is None or b is None:
        return False
    return all(not _consistent(x | y) for x in a for y in b)


def _add(cond: Cond, lit: Lit) -> Cond:
    return None if cond is None else frozenset(t | {lit} for t in cond)


def _union(conds: Iterable[Cond], values: Mapping[uuid.UUID, tuple[str, ...]]) -> Cond:
    terms: set[Term] = set()
    for cond in conds:
        if cond is None:
            return None
        terms |= cond
    return simplify(terms, values)


@dataclass(frozen=True)
class RegionLiveness:
    live: Mapping[uuid.UUID, Cond]  # the step runs
    ok: Mapping[uuid.UUID, Cond]  # the step ran and succeeded (its output exists)
    err: Mapping[uuid.UUID, Cond]  # the step ran and followed its error port
    exit: Cond  # the region finished normally (not through `fail`)


def normal_ports(s: Structure, node: uuid.UUID) -> tuple[str, ...]:
    ports = s.ports[node]
    return tuple(p for p in ports if p != "body") if s.specs[node].ref == C.LOOP else ports


def analyze_region(s: Structure, region: uuid.UUID | None) -> RegionLiveness:
    members = s.regions[region].members
    member_set = set(members)
    values: dict[uuid.UUID, tuple[str, ...]] = {
        n: normal_ports(s, n) + ((ERR,) if s.nodes[n].options.on_error == "port" else ()) for n in members
    }
    live: dict[uuid.UUID, Cond] = {}

    def edge(src: uuid.UUID, port: str) -> Cond:
        value = ERR if port == "error" else port
        return _add(live[src], (src, value)) if len(values[src]) > 1 else live[src]

    for n in members:
        incoming: list[Cond] = []
        for e in s.in_edges[n]:
            # An edge from outside the members can only be the loop's `body` port, which opens this region.
            incoming.append(TRUE if e.source.node not in member_set else edge(e.source.node, e.source.port))
        live[n] = TRUE if not incoming else _union(incoming, values)

    ok: dict[uuid.UUID, Cond] = {}
    err: dict[uuid.UUID, Cond] = {}
    for n in members:
        normal = normal_ports(s, n)
        if s.nodes[n].options.on_error == "port" and normal:
            ok[n] = _union((_add(live[n], (n, p)) for p in normal), values)
        else:
            ok[n] = live[n]
        err[n] = _add(live[n], (n, ERR)) if s.nodes[n].options.on_error == "port" else FALSE

    ends: list[Cond] = []
    for n in members:
        if s.specs[n].ref == C.FAIL:
            continue
        normal = normal_ports(s, n)
        if not normal:
            ends.append(live[n])  # `stop` ends the scope successfully
        for p in normal:
            if not any(e.source.port == p and e.to.node in member_set for e in s.out_edges[n]):
                ends.append(edge(n, p))
    return RegionLiveness(live=live, ok=ok, err=err, exit=_union(ends, values))
