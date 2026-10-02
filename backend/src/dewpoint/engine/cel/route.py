# SPDX-License-Identifier: Apache-2.0
"""Where an evaluation runs, and when the interpreter yields (spec §5.6, §5.9 rollout). Pure functions of recorded
facts, so a replay decides the same way."""

from dataclasses import dataclass
from typing import Literal

from dewpoint.engine.cel.bind import Measure
from dewpoint.engine.cel.record import ExpressionRecord

# A third below the first values (20,000, 8 MiB, 4,000,000, 200, 100,000), which took three of gate 7b's loads past
# 1 s per workflow task on Linux.
YIELD_ITERATIONS = 13_000
YIELD_BYTES = 11 * 512 * 1024  # 5.5 MiB
YIELD_WORK = (
    2_700_000  # iterations don't bound CPU on their own (estimate.py); one local evaluation does at most 2,000,000
)
YIELD_EVALUATIONS = 130
YIELD_NODES = 65_000  # the values the evaluations bind: converting them costs CPU their stored bounds don't count
STARTUP_SHARE = 10  # an execution's first workflow task gets this fraction of each threshold: it also starts it
YIELD_STRUCTURE = (
    200_000  # a workflow task's structural units (engine 2b spec §5.3): a snapshot's or a restore's parts,
)
# steps started and taken, weighted by their measured cost; about 90 ms of CPU, a tenth of that for a restore in an
# execution's first task
YIELD_SEND_BYTES = 3 * 1024 * 1024  # the payload bytes one workflow task sends, every command's (#15, engine 2b spec
# §5.2): under Temporal's 4 MiB gRPC message limit, which terminates the workflow when a task's completion passes it


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
    """One workflow task's local evaluations, the values they bound (`Measure.nodes`), and the payloads it sends."""

    iterations: int = 0
    bytes: int = 0
    work: int = 0
    evaluations: int = 0
    nodes: int = 0
    sent: int = 0
    structure: int = 0  # structural units: a snapshot's or a restore's parts, steps started and taken (§5.3)
    share: int = 1  # each threshold is divided by it: STARTUP_SHARE in an execution's first workflow task

    def must_yield(
        self, record: ExpressionRecord | None = None, *, send: int = 0, structure: int = 0, whole: bool = False
    ) -> bool:
        """True when the interpreter must await a 1 ms durable timer before binding a view (`record` None), before
        evaluating `record` locally, or before sending a payload of `send` bytes. The first thing a workflow task does
        always runs; a view is always bound first, so an evaluation whose bounds pass an execution's first task's share
        waits for the next task. Sending has its own limit, Temporal's, with no startup share. Structural work has its
        own too (engine 2b spec §5.3): the first part always runs; `whole`, a step's, gets the whole share, not the
        startup tenth a restore has."""
        if send:
            return self.sent > 0 and self.sent + send > YIELD_SEND_BYTES
        if structure:
            limit = YIELD_STRUCTURE if whole else YIELD_STRUCTURE // self.share
            return self.structure > 0 and self.structure + structure > limit
        if self.evaluations == 0 and self.nodes == 0:
            return False
        if self.evaluations >= YIELD_EVALUATIONS // self.share or self.nodes >= YIELD_NODES // self.share:
            return True
        return record is not None and (
            self.iterations + (record.iterations or 0) > YIELD_ITERATIONS // self.share
            or self.bytes + (record.bytes or 0) > YIELD_BYTES // self.share
            or self.work + (record.work or 0) > YIELD_WORK // self.share
        )

    def charge(
        self, record: ExpressionRecord | None = None, *, nodes: int = 0, sent: int = 0, structure: int = 0
    ) -> None:
        """A view bound (`nodes`: the values it bound), `record` evaluated locally, a payload of `sent` bytes, or
        `structure` units."""
        self.nodes += nodes
        self.sent += sent
        self.structure += structure
        if record is not None:
            self.iterations += record.iterations or 0
            self.bytes += record.bytes or 0
            self.work += record.work or 0
            self.evaluations += 1

    def reset(self, *, startup: bool = False) -> None:
        """A new workflow task starts a fresh budget: a tenth of it (`STARTUP_SHARE`) in an execution's first task,
        which also loads and compiles the version, or restores a snapshot."""
        self.iterations = self.bytes = self.work = self.evaluations = self.nodes = self.sent = self.structure = 0
        self.share = STARTUP_SHARE if startup else 1
