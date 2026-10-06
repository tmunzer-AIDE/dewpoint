# SPDX-License-Identifier: Apache-2.0
"""Plugin code outside runs (plugins-3 D3): a node's `options()` and a connection type's `verify()`, which the worker
runs for the API. They only read, by construction: `http` and a connection's `http` send GET and HEAD and refuse any
other method (`ReadOnly`) before anything is sent; there is no `net`. Nothing they do is retried or resent."""

import uuid
from dataclasses import dataclass
from typing import Protocol

from dewpoint.sdk.context import StepLogger
from dewpoint.sdk.net import Connection, HttpClient, TransportError


class ReadOnly(TransportError):
    code, message = "read_only", "Code outside a run may only read: GET or HEAD."


@dataclass(frozen=True)
class Option:
    """One choice for an options field: the value written into the config, and what the person reads."""

    value: str
    label: str


@dataclass(frozen=True)
class OptionsQuery:
    """What the editor or start form asked: the text typed so far, and the connection the field's node names."""

    text: str
    connection_id: uuid.UUID | None


class CallContext(Protocol):
    """What `options()` and `verify()` see. It is an API, not a sandbox."""

    @property
    def tenant_id(self) -> uuid.UUID: ...

    @property
    def log(self) -> StepLogger: ...

    async def connection(self, connection_id: uuid.UUID) -> Connection:
        """The connection the call names, read-only. Raises `ConnectionUnavailable` for any other."""
        ...

    @property
    def http(self) -> HttpClient:
        """Guarded HTTP without credentials, read-only (plugins-3 D7)."""
        ...
