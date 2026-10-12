# SPDX-License-Identifier: Apache-2.0
"""Temporal as an erasure's step 60 sees it (`apps.erasure.temporal`), in memory: each workflow id's chain of runs, in
order, each open or closed; describing an id alone shows its chain's latest run still there; a deleted run answers
NOT_FOUND. For the provenance and identity rules (2b-4b M4 recovery, phase D), whose cases a dev server can't stage
(a history already gone, a run never shown). Whether a real server behaves so is the stage tests' (`test_stages.py`)."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from dewpoint.apps.erasure import temporal


@dataclass
class Run:
    run_id: str
    open: bool = False
    request_id: str | None = None  # its started event's request id (a first run's)
    children: list[tuple[str, str | None]] = field(default_factory=list)


class FakeTemporal:
    def __init__(self) -> None:
        self.chains: dict[str, list[Run]] = {}
        self.deleted: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, str, str | None]] = []
        self.unanswered: Exception | None = None  # what an identity read raises, if set
        self.sticky: set[tuple[str, str]] = set()  # runs a delete leaves there (Temporal deletes asynchronously)
        self.visible: list[tuple[str, str]] = []  # what visibility lists under the tenant's prefix

    def add(self, workflow_id: str, run_id: str, **fields: Any) -> Run:
        run = Run(run_id, **fields)
        self.chains.setdefault(workflow_id, []).append(run)
        return run

    def _there(self, workflow_id: str) -> list[Run]:
        return [r for r in self.chains.get(workflow_id, []) if (workflow_id, r.run_id) not in self.deleted]

    async def execution(self, _client: Any, workflow_id: str, run_id: str | None) -> temporal.ExecutionShown | None:
        self.calls.append(("describe", workflow_id, run_id))
        there = self._there(workflow_id)
        if run_id is not None:
            there = [r for r in there if r.run_id == run_id]
        return temporal.ExecutionShown(run_id=there[-1].run_id, open=there[-1].open) if there else None

    async def terminate(self, _client: Any, workflow_id: str, run_id: str) -> None:
        self.calls.append(("terminate", workflow_id, run_id))
        for run in self.chains.get(workflow_id, []):
            if run.run_id == run_id:
                run.open = False

    async def delete_execution(self, _client: Any, workflow_id: str, run_id: str) -> None:
        self.calls.append(("delete", workflow_id, run_id))
        if (workflow_id, run_id) not in self.sticky:
            self.deleted.add((workflow_id, run_id))

    async def read_run(self, _client: Any, workflow_id: str, run_id: str) -> temporal.RunRead:
        self.calls.append(("read", workflow_id, run_id))
        chain = self.chains[workflow_id]
        at = next(i for i, r in enumerate(chain) if r.run_id == run_id)
        return temporal.RunRead(previous=chain[at - 1].run_id if at > 0 else None,
                                next=chain[at + 1].run_id if at + 1 < len(chain) else None,
                                children=list(chain[at].children))  # fmt: skip

    async def first_run_request_id(self, _client: Any, workflow_id: str, run_id: str) -> "temporal.FirstRun | None":
        """The chain's first run, whichever run is named, and its started event's request id; None: it's gone, or has
        none."""
        self.calls.append(("identity", workflow_id, run_id))
        if self.unanswered is not None:
            raise self.unanswered
        chain = self.chains.get(workflow_id, [])
        if not chain or (workflow_id, chain[0].run_id) in self.deleted or chain[0].request_id is None:
            return None
        return temporal.FirstRun(chain[0].run_id, chain[0].request_id)

    async def listed(self, _client: Any, _prefix: str) -> list[tuple[str, str]]:
        return [(w, r) for w, r in self.visible if (w, r) not in self.deleted]

    def install(self, monkeypatch: pytest.MonkeyPatch) -> "FakeTemporal":
        for name in ("execution", "terminate", "delete_execution", "read_run", "first_run_request_id", "listed"):
            monkeypatch.setattr(temporal, name, getattr(self, name))
        return self
