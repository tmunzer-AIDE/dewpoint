# SPDX-License-Identifier: Apache-2.0
"""The `StepContext` a plugin step receives (spec §3)."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity

from dewpoint.sdk import StepContext, StepLogger

_SECRET = re.compile(r"password|secret|token|credential|authorization|api_?key", re.IGNORECASE)


def idempotency_key(run_id: str, step_id: str, iteration_key: str) -> str:
    """Derived from (run_id, step_id, iteration_key): the same for every attempt of a step in one iteration."""
    return hashlib.sha256(f"{run_id}\x1f{step_id}\x1f{iteration_key}".encode()).hexdigest()


class _Logger:
    """Logs with the step's ids; a field whose name looks secret is redacted."""

    def __init__(self, **ids: str) -> None:
        self._log = structlog.get_logger("dewpoint.step").bind(**ids)

    @staticmethod
    def _clean(fields: dict[str, Any]) -> dict[str, Any]:
        return {k: "[redacted]" if _SECRET.search(k) else v for k, v in fields.items()}

    def info(self, event: str, **fields: Any) -> None:
        self._log.info(event, **self._clean(fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._log.warning(event, **self._clean(fields))


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


def context(tenant_id: str, run_id: str, step_id: str, iteration_key: str, attempt: int) -> StepContext:
    log = _Logger(run_id=run_id, step_id=step_id, iteration_key=iteration_key)
    return Context(uuid.UUID(tenant_id), uuid.UUID(run_id), uuid.UUID(step_id), iteration_key, attempt, log)
