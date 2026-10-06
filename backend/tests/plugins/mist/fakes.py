# SPDX-License-Identifier: Apache-2.0
"""A Mist connection whose HTTP answers from a script and records what was sent, for the client's and the nodes'
tests: no network, no runtime."""

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ORG = "6a1d6e2f-3c4b-4a5d-9e8f-0123456789ab"
OTHER_ORG = "11111111-2222-4333-8444-555555555555"
SITE = "0f5e3c1a-9b8d-4e2f-a1b3-c5d7e9f1a3b5"


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    raw: bytes | None = None


@dataclass
class Sent:
    method: str
    url: str
    params: Mapping[str, Any] | None
    json: Any
    headers: Mapping[str, str] | None
    probe: bool = False


class FakeResponse:
    def __init__(self, reply: Reply) -> None:
        self.status_code = reply.status
        self._headers = {k.lower(): v for k, v in reply.headers.items()}
        if reply.raw is not None:
            self.content = reply.raw
        else:
            self.content = b"" if reply.body is None else json.dumps(reply.body).encode()

    @property
    def headers(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._headers.items())

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def json(self) -> Any:
        return json.loads(self.content)


Script = Callable[[Sent], Reply | BaseException]


class FakeHttp:
    def __init__(self, script: Script | Mapping[tuple[str, str], Reply | list[Reply]]) -> None:
        self.sent: list[Sent] = []
        self._script = script

    def _reply(self, sent: Sent) -> Reply | BaseException:
        if callable(self._script):
            return self._script(sent)
        found = self._script.get((sent.method, sent.url.split("?", 1)[0]))
        if found is None:
            return Reply(404, {"detail": "not scripted"})
        if isinstance(found, list):
            return found.pop(0)
        return found

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        json: Any = None,
        follow_same_origin: int = 0,
        probe: bool = False,
    ) -> FakeResponse:
        sent = Sent(method, url, dict(params) if params is not None else None, json, headers, probe)
        self.sent.append(sent)
        reply = self._reply(sent)
        if isinstance(reply, BaseException):
            raise reply
        return FakeResponse(reply)


@dataclass
class FakeConnection:
    http: FakeHttp
    config: Mapping[str, Any] = field(default_factory=lambda: {"cloud": "global_01", "org_id": ORG})
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "mist"


@dataclass
class FakeLog:
    def info(self, event: str, **fields: object) -> None:
        pass

    def warning(self, event: str, **fields: object) -> None:
        pass


@dataclass
class FakeStep:
    """A step's context with one Mist connection, for a node's run(): its id must be the one asked for."""

    connection_: FakeConnection
    attempt: int = 1
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    step_id: uuid.UUID = field(default_factory=uuid.uuid4)
    iteration_key: str = ""
    cancelled: bool = False
    log: FakeLog = field(default_factory=FakeLog)
    opened: list[uuid.UUID] = field(default_factory=list)

    def idempotency_key(self) -> str:
        return "k"

    async def connection(self, connection_id: uuid.UUID) -> FakeConnection:
        self.opened.append(connection_id)
        assert connection_id == self.connection_.id
        return self.connection_

    def heartbeat(self, *details: object) -> None:
        pass
