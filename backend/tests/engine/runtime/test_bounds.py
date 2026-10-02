# SPDX-License-Identifier: Apache-2.0
"""The bound on a continued input (engine 2b spec §5.3), computed: each maximum is the largest encoding its component
can have, built with the snapshot's own encoders, and a version's open-iteration cap is the largest (at most 100) for
which the sum fits SNAPSHOT_MAX. Nothing is refused on an assumption: the largest graphs the limits allow (500 nodes,
2,000 edges, loops 3 deep, 63-character keys) get a cap of at least 1, and LIVE_BUDGET is above what the live state
needs with every container claimed, for every cap the formula allows."""

from collections.abc import Callable

import pytest

from dewpoint.engine.graph.structure import MAX_LOOP_DEPTH
from dewpoint.engine.handles import HANDLE_MAX
from dewpoint.engine.runtime import bounds
from dewpoint.engine.runtime import scheduler as S
from dewpoint.engine.runtime.ids import ID_MAX
from tests.engine.runtime.support import program
from tests.support.graphs import G

ECHO, LOOP, SET = "testkit.echo@1", "flow.loop@1", "flow.set_variables@1"


def k(n: int) -> str:
    """The n-th step's key, 63 characters, the longest a key may be."""
    return f"s{n:04d}".ljust(63, "k")


def chained(g: G, keys: list[str], edges: int) -> None:
    """Edges along `keys` in order, then more from each to later ones, until there are `edges`."""
    made = 0
    for a, b in zip(keys, keys[1:], strict=False):
        g.edge(a, b)
        made += 1
    for i, a in enumerate(keys):
        for b in keys[i + 2 :]:
            if made >= edges:
                return
            g.edge(a, b)
            made += 1


def one_loop() -> G:
    """One loop, a 499-step body, 1,999 edges."""
    g = G().node(k(0), LOOP, {"items": [1]})
    body = [k(n) for n in range(1, 500)]
    for key in body:
        g.node(key, ECHO)
    g.edge(k(0), body[0], "body")
    chained(g, body, 1_998)
    return g


def three_deep() -> G:
    """Loops 3 deep, a 497-step body, 2,000 edges."""
    g = G().node(k(0), LOOP, {"items": [1]}).node(k(1), LOOP, {"items": [1]}).node(k(2), LOOP, {"items": [1]})
    g.edge(k(0), k(1), "body").edge(k(1), k(2), "body")
    body = [k(n) for n in range(3, 500)]
    for key in body:
        g.node(key, ECHO)
    g.edge(k(2), body[0], "body")
    chained(g, body, 1_997)
    return g


def sibling_loops() -> G:
    """249 loop steps in one body (each with a body step of its own)."""
    g = G().node(k(0), LOOP, {"items": [1]})
    for n in range(249):
        loop, step = k(1 + 2 * n), k(2 + 2 * n)
        g.node(loop, LOOP, {"items": [1]}).node(step, ECHO).edge(k(0), loop, "body").edge(loop, step, "body")
    return g


def root_loops() -> G:
    """250 root loops: a loop needs a body."""
    g = G()
    for n in range(250):
        g.node(k(2 * n), LOOP, {"items": [1]}).node(k(2 * n + 1), ECHO).edge(k(2 * n), k(2 * n + 1), "body")
    return g


def root_writes() -> G:
    """494 root `set_variables` steps, one after another, and a loop."""
    g = G().node(k(0), LOOP, {"items": [1]}).node(k(1), ECHO).edge(k(0), k(1), "body")
    g.settings["vars_schema"] = {"type": "object", "properties": {"x": {"type": "integer", "default": 0}}}
    for n in range(494):
        g.node(k(2 + n), SET, {"assignments": {"x": n}})
        if n:
            g.edge(k(1 + n), k(2 + n))
    return g


LARGEST: list[Callable[[], G]] = [one_loop, three_deep, sibling_loops, root_loops, root_writes]


@pytest.mark.parametrize("build", LARGEST, ids=lambda b: b.__name__)
def test_the_largest_graphs_get_a_cap_of_at_least_one_and_the_live_budget_holds_every_container(
    build: Callable[[], G],
) -> None:
    m = bounds.maxima(program(build()))
    cap = m.cap()
    assert cap >= 1, f"no cap fits: {m}"
    assert m.total(cap) <= bounds.SNAPSHOT_MAX
    assert cap == S.OPEN_SCOPES_CAP or m.total(cap + 1) > bounds.SNAPSHOT_MAX  # the largest that fits
    for c in range(1, cap + 1):
        assert m.live_min(c) < S.LIVE_BUDGET, f"cap {c}: every container claimed needs {m.live_min(c)} bytes"


def test_each_fixed_maximum_is_built_from_the_largest_encoding() -> None:
    """The envelope holds every id at ID_MAX, and the trigger is its inline bound and a handle."""
    assert bounds.envelope_max() > 2 * ID_MAX  # the parent's workflow id, and the batch's own id field are widest
    assert bounds.TRIGGER_MAX == 65_536 + HANDLE_MAX
    assert bounds.unit_max() > 0


def test_the_cap_and_the_depth_are_what_publish_pins() -> None:
    g = three_deep()
    cap, d = bounds.pinned(program(g))
    assert d == MAX_LOOP_DEPTH and 1 <= cap <= S.OPEN_SCOPES_CAP


def test_a_cap_that_wouldnt_fit_is_none() -> None:
    """The formula's own edge: with SNAPSHOT_MAX below what one iteration needs, no cap fits (0); tests show the
    largest graphs never get there."""
    m = bounds.maxima(program(one_loop()))
    tight = bounds.Maxima(**{**m.__dict__, "live": bounds.SNAPSHOT_MAX})
    assert tight.cap() == 0
