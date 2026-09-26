# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Protocol


class StepLogger(Protocol):
    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...


class StepContext(Protocol):
    """What a node sees while it runs. Sub-project 3 adds connection() and http. It is an API, not a sandbox."""

    @property
    def tenant_id(self) -> uuid.UUID: ...

    @property
    def run_id(self) -> uuid.UUID: ...

    @property
    def step_id(self) -> uuid.UUID: ...

    @property
    def iteration_key(self) -> str: ...

    @property
    def attempt(self) -> int: ...

    @property
    def log(self) -> StepLogger: ...

    @property
    def cancelled(self) -> bool: ...

    def idempotency_key(self) -> str: ...

    def heartbeat(self, *details: object) -> None: ...
