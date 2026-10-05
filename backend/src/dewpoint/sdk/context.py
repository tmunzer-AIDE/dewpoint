# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Protocol

from dewpoint.sdk.net import Connection, HttpClient, Net


class StepLogger(Protocol):
    """Logs only what the plugin's own code wrote (engine 2b spec §6.7): an event, a field's name and a field's value
    are kept when each is a constant of the plugin's source (a string or number literal), a boolean or null. A
    computed event is withheld, a computed field name dropped, and any other value redacted, so log
    `"token_refreshed"`, not `f"refreshed {token}"`. A field whose name looks secret (`password`, `token`, …) is
    redacted even then. Only this logger is bound by it: a plugin's own `logging` or `print`, or a library's logging,
    isn't, so a plugin logs through `ctx.log`."""

    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...


class StepContext(Protocol):
    """What a node sees while it runs. It is an API, not a sandbox."""

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

    async def connection(self, connection_id: uuid.UUID) -> Connection:
        """A connection this step's config names (plugins-3 D4). Raises `ConnectionUnavailable` for any other, and in a
        simulated run, which never sends."""
        ...

    @property
    def http(self) -> HttpClient:
        """Guarded HTTP without credentials (plugins-3 D7). Refused in a simulated run."""
        ...

    @property
    def net(self) -> Net:
        """Guarded TCP, TLS and UDP (plugins-3 D7). Refused in a simulated run."""
        ...

    def heartbeat(self, *details: object) -> None:
        """Tells Temporal the attempt is alive. `details` aren't sent: Temporal keeps an attempt's last ones, and a
        timeout writes them into the run's history (engine 2b spec §12)."""
        ...
