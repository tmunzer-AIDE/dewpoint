# SPDX-License-Identifier: Apache-2.0
"""One execution's share of the run's iteration budget (spec §6, "One iteration counter per logical run").

The root execution holds the cap. A child (a loop batch, a sub-flow) holds what its parent granted it: an initial
grant when it starts, and more on demand. Needs are served in the order they arrive: this execution's own (an inline
iteration, a filter's items) and its children's requests.

A need the unreserved budget can't cover waits while another outstanding child may still release budget: a child
that isn't itself asking. Only then does a child execution ask its parent, for its shortfall (and up to a chunk of
1,000, so it asks rarely), reporting what it holds unused meanwhile. So a child asks only when its whole subtree is
short. A child that asks holds its unused budget until it's answered and ends: when what asking children hold would
cover a need, their asks are refused first, latest first, and the need waits for them to release it. A need is
refused only when nothing unused is left that could cover it: the cap is exact.

It is pure and deterministic, and its state is plain data, carried through continue-as-new."""

from dataclasses import dataclass, field
from typing import Any

CHUNK = 1_000  # a child asks for at least this much, so it rarely asks
LOCAL = ""  # the requester of this execution's own needs


@dataclass(frozen=True)
class Need:
    requester: str  # LOCAL, or the child's workflow id
    key: str  # the requester's own name for it: a child's request id, or the scheduler's unit
    need: int  # at least this much, or nothing
    want: int  # up to this much: a child's chunk; a local need wants exactly `need`
    held: int = 0  # what a child holds unused while it asks: it releases it if it's refused and ends


@dataclass(frozen=True)
class Answer:
    need: Need
    granted: int  # 0: refused


@dataclass(frozen=True)
class Ask:
    """What this execution asks its parent for: its shortfall, up to a chunk. `held` is what it holds unused meanwhile,
    which its parent can have if it refuses the ask."""

    need: int
    want: int
    held: int = 0


@dataclass
class Budget:
    total: int  # what this execution may spend: the cap at the root, its grants in a child
    root: bool
    used: int = 0  # its own needs served, and what its settled children used
    reserved: dict[str, int] = field(default_factory=dict)  # outstanding child -> what it was granted so far
    waiting: list[Need] = field(default_factory=list)
    asking: bool = False  # an Ask is out and unanswered
    refused: bool = False  # the parent refused: only this execution's own children can help now

    @property
    def unreserved(self) -> int:
        return self.total - self.used - sum(self.reserved.values())

    def take(self, n: int) -> bool:
        """This execution's own need, served now when nothing waits ahead of it and it fits."""
        if self.waiting or n > self.unreserved:
            return False
        self.used += n
        return True

    def request(self, need: Need) -> None:
        self.waiting.append(need)

    def start_child(self, child: str, initial: int) -> int:
        """A child starts: reserve its initial grant from the unreserved budget. Nothing is taken ahead of a waiting
        need, so a child may start with 0 and ask."""
        grant = 0 if self.waiting else max(0, min(initial, self.unreserved))
        self.reserved[child] = grant
        return grant

    def settle_child(self, child: str, used: int | None) -> None:
        """A child ended: debit what it used (all it was granted when it didn't say), and release the rest. Needs it
        left waiting are dropped: nothing will read their answers."""
        granted = self.reserved.pop(child, 0)
        self.used += granted if used is None else min(max(used, 0), granted)
        self.waiting = [n for n in self.waiting if n.requester != child]

    def answered(self, granted: int) -> None:
        """The parent answered this execution's Ask."""
        self.asking = False
        self.total += granted
        if granted == 0:
            self.refused = True

    def decide(self) -> tuple[list[Answer], Ask | None]:
        """Serve the waiting needs in order, as far as the budget goes. Returns the answers, and an Ask for the
        parent when this execution must ask (at most one at a time)."""
        answers: list[Answer] = []
        while self.waiting:
            head = self.waiting[0]
            free = self.unreserved
            if head.need <= free:
                granted = head.need if head.requester == LOCAL else min(head.want, free)
                if head.requester == LOCAL:
                    self.used += granted
                else:
                    self.reserved[head.requester] = self.reserved.get(head.requester, 0) + granted
                answers.append(Answer(head, granted))
                self.waiting.pop(0)
                continue
            if self._may_release(head):
                break  # another child may still release budget: wait for it
            if not self.root and not self.refused:
                if self.asking:
                    break
                self.asking = True
                shortfall = head.need - max(free, 0)
                return answers, Ask(shortfall, max(CHUNK, shortfall), max(free, 0))
            if self._refuse_asking(head, free, answers):
                break  # children that were asking hold enough: refused, they end and release it; wait for them
            answers.append(Answer(head, 0))
            self.waiting.pop(0)
        return answers, None

    def _refuse_asking(self, head: Need, free: int, answers: list[Answer]) -> bool:
        """Other children that are asking hold what they report (`held`) until they end, and they end only once
        answered. When what they hold would cover the head, refuse their needs, latest first, until it does: they
        release it when they end, and the head waits for them. Otherwise refuse none, and the head is refused."""
        chosen: list[str] = []
        held = 0
        for n in reversed(self.waiting):
            if free + held >= head.need:
                break
            if n.requester not in (LOCAL, head.requester) and n.requester not in chosen and n.held > 0:
                chosen.append(n.requester)
                held += n.held
        if free + held < head.need:
            return False
        answers.extend(Answer(n, 0) for n in self.waiting if n.requester in chosen)
        self.waiting = [n for n in self.waiting if n.requester not in chosen]
        return True

    def _may_release(self, head: Need) -> bool:
        """Whether an outstanding child other than the requester may still release budget: one that isn't asking."""
        asking = {n.requester for n in self.waiting}
        return any(child != head.requester and child not in asking for child in self.reserved)

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "root": self.root,
            "used": self.used,
            "reserved": dict(self.reserved),
            "waiting": [[n.requester, n.key, n.need, n.want, n.held] for n in self.waiting],
            "asking": self.asking,
            "refused": self.refused,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Budget":
        return cls(
            total=int(data["total"]),
            root=bool(data["root"]),
            used=int(data["used"]),
            reserved={str(k): int(v) for k, v in data["reserved"].items()},
            waiting=[Need(str(r), str(k), int(n), int(w), int(h)) for r, k, n, w, h in data["waiting"]],
            asking=bool(data["asking"]),
            refused=bool(data["refused"]),
        )


__all__ = ["CHUNK", "LOCAL", "Answer", "Ask", "Budget", "Need"]
