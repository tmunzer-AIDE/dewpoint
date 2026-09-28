# SPDX-License-Identifier: Apache-2.0
"""The iteration budget's grants (spec §6, "One iteration counter per logical run"): exact, and never stuck."""

from dataclasses import dataclass, field

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.runtime.budget import CHUNK, LOCAL, Answer, Ask, Budget, Need


def local(key: str, n: int) -> Need:
    return Need(LOCAL, key, n, n)


def test_own_needs_are_served_in_order_while_the_budget_lasts() -> None:
    b = Budget(10, root=True)
    assert b.take(4) and b.take(6) and not b.take(1)
    assert (b.used, b.unreserved) == (10, 0)


def test_a_child_gets_its_initial_grant_and_releases_what_it_left() -> None:
    b = Budget(100, root=True)
    assert b.start_child("c", 30) == 30 and b.unreserved == 70
    b.settle_child("c", 12)
    assert (b.used, b.unreserved, b.reserved) == (12, 88, {})


def test_a_child_that_never_reports_is_debited_its_whole_grant() -> None:
    b = Budget(100, root=True)
    b.start_child("c", 30)
    b.settle_child("c", None)
    assert b.used == 30


def test_a_short_child_asks_its_parent_for_its_shortfall_up_to_a_chunk() -> None:
    b = Budget(5, root=False)
    assert b.take(5) and not b.take(3)
    b.request(local("loop", 3))
    answers, ask = b.decide()
    assert (answers, ask, b.asking) == ([], Ask(3, CHUNK), True)
    assert b.decide() == ([], None)  # one Ask at a time
    b.answered(CHUNK)
    answers, ask = b.decide()
    assert answers == [Answer(local("loop", 3), 3)] and ask is None and b.unreserved == CHUNK - 3


def test_the_parent_grants_up_to_the_chunk_from_what_it_has() -> None:
    root = Budget(50, root=True)
    root.start_child("c", 10)
    root.request(Need("c", "r1", 5, CHUNK))
    assert root.decide() == ([Answer(Need("c", "r1", 5, CHUNK), 40)], None)
    assert root.reserved == {"c": 50} and root.unreserved == 0


def test_a_need_waits_while_another_child_may_release_budget() -> None:
    root = Budget(20, root=True)
    root.start_child("busy", 10)
    root.start_child("idle", 10)
    root.request(Need("busy", "r1", 5, CHUNK))
    assert root.decide() == ([], None)  # `idle` holds 10 and isn't asking
    root.settle_child("idle", 2)
    assert root.decide() == ([Answer(Need("busy", "r1", 5, CHUNK), 8)], None)


def test_a_need_is_refused_only_when_no_other_child_can_release_anything() -> None:
    root = Budget(20, root=True)
    root.start_child("a", 10)
    root.start_child("b", 10)
    root.request(Need("a", "r1", 5, CHUNK))
    root.request(Need("b", "r1", 5, CHUNK))
    # both are asking, so neither can release anything, and nothing is left: `a` is refused. `b` then waits for
    # `a`, which is no longer asking and will settle, and is refused once `a` has released nothing.
    answers, ask = root.decide()
    assert [(a.need.requester, a.granted) for a in answers] == [("a", 0)] and ask is None
    root.settle_child("a", 10)
    answers, _ = root.decide()
    assert [(a.need.requester, a.granted) for a in answers] == [("b", 0)]


def test_a_refused_child_waits_for_its_own_children_and_never_asks_again() -> None:
    mid = Budget(10, root=False)
    mid.start_child("leaf", 10)
    mid.request(local("loop", 1))
    assert mid.decide() == ([], None)  # `leaf` may release
    mid.request(Need("leaf", "r1", 1, CHUNK))  # now the leaf is short too: the subtree is short
    assert mid.decide() == ([], Ask(1, CHUNK))
    mid.answered(0)
    answers, ask = mid.decide()
    assert [a.granted for a in answers] == [0, 0] and ask is None and mid.refused


def test_a_feasible_need_waits_for_an_asking_child_that_holds_enough_and_is_refused_first() -> None:
    """Checkpoint-1 review: the root's filter needs 8 and has 4. Child `a` holds 6 unused and asks for 5 more. The
    filter could have 8 once `a` releases its 6, which it does only once it's answered and ends. So `a` is refused,
    and the filter waits for it. Before, both were refused."""
    root = Budget(10, root=True)
    assert root.start_child("a", 6) == 6
    root.request(local("filter", 8))
    root.request(Need("a", "r1", 5, CHUNK, held=6))
    assert root.decide() == ([Answer(Need("a", "r1", 5, CHUNK, held=6), 0)], None)
    root.settle_child("a", 0)  # refused, `a` ends without using its grant
    assert root.decide() == ([Answer(local("filter", 8), 8)], None) and root.used == 8


def test_an_asking_child_that_holds_nothing_is_not_waited_for() -> None:
    root = Budget(10, root=True)
    root.start_child("a", 6)
    root.request(local("filter", 8))
    root.request(Need("a", "r1", 5, CHUNK, held=0))  # `a` used its 6
    answers, _ = root.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [(LOCAL, 0), ("a", 0)]  # nothing could cover either


def test_only_as_many_asking_children_are_refused_as_the_need_takes_latest_first() -> None:
    root = Budget(20, root=True)
    root.start_child("a", 6)
    root.start_child("b", 6)
    root.request(local("filter", 12))  # 8 free
    root.request(Need("a", "r1", 5, CHUNK, held=6))
    root.request(Need("b", "r1", 5, CHUNK, held=6))
    answers, _ = root.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [("b", 0)]  # `b`'s 6 is enough, and it asked last
    root.settle_child("b", 0)
    answers, _ = root.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [(LOCAL, 12), ("a", 0)]


def test_a_refused_child_refuses_its_own_asking_children_before_its_own_need() -> None:
    mid = Budget(10, root=False)
    mid.start_child("leaf", 6)
    mid.request(local("filter", 8))
    mid.request(Need("leaf", "r1", 5, CHUNK, held=6))
    assert mid.decide() == ([], Ask(4, CHUNK, 4))  # its subtree looks short: it asks its parent first
    mid.answered(0)
    answers, _ = mid.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [("leaf", 0)]  # the leaf's 6 can cover the filter
    mid.settle_child("leaf", 1)
    assert mid.decide() == ([Answer(local("filter", 8), 8)], None)


def test_no_premature_rejection_one_busy_child_among_ten_takes_nearly_everything() -> None:
    """Spec §10: with 10 child slots and one busy child, that child can use nearly the whole budget."""
    cap = 100_000
    root = Budget(cap, root=True)
    for i in range(10):
        root.start_child(f"c{i}", 100)
    busy = 100
    for request in range(1, 1_000):
        root.request(Need("c0", str(request), 1, CHUNK))
        answers, _ = root.decide()
        if not answers:
            break  # the others may still release what they hold: the request waits for them
        busy += answers[0].granted
    assert busy == cap - 900
    for i in range(1, 10):
        root.settle_child(f"c{i}", 1)  # the idle ones used 1 each and release the rest
    answers, _ = root.decide()
    busy += answers[0].granted
    assert busy == cap - 9


def test_the_state_round_trips_through_json() -> None:
    b = Budget(100, root=False, used=3, reserved={"c": 4}, waiting=[Need("c", "r", 1, CHUNK, held=2)], asking=True)
    assert Budget.from_json(b.to_json()) == b


# --- a simulated tree of executions ------------------------------------------------------------------------------


@dataclass
class Execution:
    name: str
    budget: Budget
    parent: "Execution | None" = None
    depth: int = 0
    children: list["Execution"] = field(default_factory=list)
    pending: dict[str, int] = field(default_factory=dict)  # own needs waiting for an answer
    served: int = 0  # own needs served
    done: bool = False
    counter: int = 0


@dataclass
class Tree:
    cap: int
    root: Execution
    everyone: list[Execution]
    mail: list[tuple[str, Execution, object]] = field(default_factory=list)  # (kind, to, payload)
    refusals: list[tuple[int, int]] = field(default_factory=list)  # (need, unused anywhere at that moment)

    def served(self) -> int:
        return sum(e.served for e in self.everyone)

    def settle(self, e: Execution) -> None:
        answers, ask = e.budget.decide()
        for a in answers:
            if a.need.requester == LOCAL:
                n = e.pending.pop(a.need.key)
                if a.granted:
                    e.served += n
                else:
                    self.refusals.append((n, self.cap - self.served()))
            else:
                child = next(c for c in e.children if c.name == a.need.requester)
                self.mail.append(("answer", child, a.granted))
        if ask is not None and e.parent is not None:
            e.counter += 1
            self.mail.append(("ask", e.parent, Need(e.name, str(e.counter), ask.need, ask.want, ask.held)))

    def deliver(self, i: int) -> None:
        kind, to, payload = self.mail.pop(i)
        if kind == "ask":
            assert isinstance(payload, Need)
            to.budget.request(payload)
        elif kind == "answer":
            assert isinstance(payload, int)
            to.budget.answered(payload)
        else:  # a child ended
            assert isinstance(payload, tuple)
            name, used = payload
            to.budget.settle_child(name, used)
        self.settle(to)


def run(data: st.DataObject, cap: int, unit: bool) -> Tree:
    root = Execution("root", Budget(cap, root=True))
    tree = Tree(cap, root, [root])
    for _ in range(data.draw(st.integers(10, 120))):
        live = [e for e in tree.everyone if not e.done]
        moves = ["need", "child", "finish"] + (["mail"] if tree.mail else [])
        move = data.draw(st.sampled_from(moves))
        if move == "mail":
            tree.deliver(data.draw(st.integers(0, len(tree.mail) - 1)))
            continue
        e = data.draw(st.sampled_from(live))
        if move == "need" and not e.pending:
            n = 1 if unit else data.draw(st.integers(1, 30))
            if e.budget.take(n):
                e.served += n
            else:
                e.counter += 1
                key = f"own{e.counter}"
                e.pending[key] = n
                e.budget.request(Need(LOCAL, key, n, n))
                tree.settle(e)
        elif move == "child" and e.depth < 2 and len(e.children) < 3 and not e.pending:
            name = f"{e.name}.{len(e.children)}"
            grant = e.budget.start_child(name, data.draw(st.integers(0, 40)))
            child = Execution(name, Budget(grant, root=False), e, e.depth + 1)
            e.children.append(child)
            tree.everyone.append(child)
        elif move == "finish" and e is not root and not e.pending and all(c.done for c in e.children):
            if not any(m[1] is e for m in tree.mail) and not e.budget.asking:
                e.done = True
                assert e.parent is not None
                tree.mail.append(("ended", e.parent, (e.name, e.budget.used)))
        assert tree.served() <= cap, "the cap was exceeded"
    return tree


def finish(tree: Tree) -> None:
    """Let everything settle: deliver the mail, and end each execution that's no longer waiting."""
    for _ in range(10_000):
        if tree.mail:
            tree.deliver(0)
            continue
        idle = [
            e
            for e in tree.everyone
            if not e.done
            and e is not tree.root
            and not e.pending
            and not e.budget.asking
            and all(c.done for c in e.children)
        ]
        if not idle:
            break
        e = idle[-1]
        e.done = True
        assert e.parent is not None
        tree.mail.append(("ended", e.parent, (e.name, e.budget.used)))
    stuck = [e.name for e in tree.everyone if e.pending]
    assert not stuck, f"needs never answered: {stuck}"
    assert tree.served() <= tree.cap


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_one_at_a_time_needs_are_refused_only_when_nothing_is_left(data: st.DataObject) -> None:
    """With loop iterations (needs of 1), the cap is exact: a need is refused only when nothing unused is left in the
    whole tree, and no need waits forever."""
    tree = run(data, cap=data.draw(st.integers(5, 60)), unit=True)
    finish(tree)
    for need, unused in tree.refusals:
        assert unused < need, f"a need of {need} was refused with {unused} unused"


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_larger_needs_never_pass_the_cap_and_never_wait_forever(data: st.DataObject) -> None:
    tree = run(data, cap=data.draw(st.integers(5, 200)), unit=False)
    finish(tree)
