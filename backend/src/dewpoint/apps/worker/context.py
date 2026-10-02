# SPDX-License-Identifier: Apache-2.0
"""The `StepContext` a plugin step receives (spec §3)."""

import hashlib
import uuid
from dataclasses import dataclass

from temporalio import activity

from dewpoint.apps.worker.logs import Literals, StepLog
from dewpoint.sdk import StepContext, StepLogger


def idempotency_key(run_id: str, step_id: str, iteration_key: str) -> str:
    """Derived from (run_id, step_id, iteration_key): the same for every attempt of a step in one iteration."""
    return hashlib.sha256(f"{run_id}\x1f{step_id}\x1f{iteration_key}".encode()).hexdigest()


@dataclass(frozen=True)
class Context:
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    step_id: uuid.UUID
    iteration_key: str
    attempt: int
    log: StepLogger

    @property
    def cancelled(self) -> bool:
        return activity.is_cancelled()

    def idempotency_key(self) -> str:
        return idempotency_key(str(self.run_id), str(self.step_id), self.iteration_key)

    def heartbeat(self, *details: object) -> None:
        activity.heartbeat(*details)


def context(
    tenant_id: str, run_id: str, step_id: str, iteration_key: str, attempt: int, known: Literals = frozenset()
) -> StepContext:
    """`known`: the constants of the node's plugin, all its log may hold (engine 2b spec §6.7)."""
    log = StepLog(known, run_id=run_id, step_id=step_id, iteration_key=iteration_key)
    return Context(uuid.UUID(tenant_id), uuid.UUID(run_id), uuid.UUID(step_id), iteration_key, attempt, log)
