# SPDX-License-Identifier: Apache-2.0
"""Where an evaluation runs, and when the interpreter yields (spec §5.6, §5.9 rollout). Pure functions of recorded
facts, so a replay decides the same way."""

from dataclasses import dataclass
from typing import Literal

from dewpoint.engine.cel.bind import Measure
from dewpoint.engine.cel.record import ExpressionRecord

YIELD_ITERATIONS = 20_000
YIELD_BYTES = 8 * 1024 * 1024
YIELD_WORK = 4_000_000  # not in the spec's list: iterations don't bound CPU on their own (estimate.py)
YIELD_EVALUATIONS = 200
YIELD_NODES = 100_000  # the values the evaluations bind: converting them costs CPU their stored bounds don't count


def route(
    record: ExpressionRecord, measured: Measure, *, local_profile: str | None, version_profile: str
) -> Literal["local", "activity"]:
    """Local only when this build evaluates the version's profile in-process, publish classified the expression as
    local, and the recorded inputs are within the caps."""
    if local_profile is None or local_profile != version_profile or record.mode != "local":
        return "activity"
    return "local" if measured.within_caps else "activity"


@dataclass
class YieldBudget:
    """One workflow task's local evaluations: their stored bounds, and the values they bound (`Measure.nodes`)."""

    iterations: int = 0
    bytes: int = 0
    work: int = 0
    evaluations: int = 0
    nodes: int = 0

    def must_yield(self, record: ExpressionRecord | None = None) -> bool:
        """True when the interpreter must await a 1 ms durable timer before binding a view (`record` None), or before
        evaluating `record` locally. The first thing a workflow task does always runs."""
        if self.evaluations == 0 and self.nodes == 0:
            return False
        if self.evaluations >= YIELD_EVALUATIONS or self.nodes >= YIELD_NODES:
            return True
        return record is not None and (
            self.iterations + (record.iterations or 0) > YIELD_ITERATIONS
            or self.bytes + (record.bytes or 0) > YIELD_BYTES
            or self.work + (record.work or 0) > YIELD_WORK
        )

    def charge(self, record: ExpressionRecord | None = None, *, nodes: int = 0) -> None:
        """A view bound (`nodes`: the values it bound), or `record` evaluated locally."""
        self.nodes += nodes
        if record is not None:
            self.iterations += record.iterations or 0
            self.bytes += record.bytes or 0
            self.work += record.work or 0
            self.evaluations += 1

    def reset(self) -> None:
        """A new workflow task starts a fresh budget."""
        self.iterations = self.bytes = self.work = self.evaluations = self.nodes = 0
