# SPDX-License-Identifier: Apache-2.0
"""A Mist connection whose HTTP answers from a script and records what was sent, and whose stream delivers what a test
queues, for the client's, the stream reader's and the nodes' tests: no network, no runtime."""

import asyncio
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
    delay_s: float = 0.0  # how long the answer takes


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
        if reply.delay_s:
            await asyncio.sleep(reply.delay_s)
        return FakeResponse(reply)


class FakeStream:
    """One open stream: what the node sends is recorded (and `on_send` may answer it); `inbox` is what it receives, in
    order: a text, an exception to raise, or None to close the stream."""

    def __init__(self, on_send: Callable[[str], list[str]] | None = None) -> None:
        self.inbox: asyncio.Queue[str | BaseException | None] = asyncio.Queue()
        self.sent: list[tuple[str, bool]] = []
        self.closed = False
        self._on_send = on_send

    def queue(self, *items: Any) -> None:
        for item in items:
            self.inbox.put_nowait(json.dumps(item) if isinstance(item, dict) else item)

    async def send(self, text: str, *, probe: bool = False) -> None:
        from dewpoint.sdk import StreamLost  # noqa: PLC0415

        if self.closed:
            raise StreamLost()
        self.sent.append((text, probe))
        for reply in self._on_send(text) if self._on_send is not None else []:
            self.inbox.put_nowait(reply)

    async def receive(self, timeout_s: float) -> str | None:
        from dewpoint.sdk import StreamLost  # noqa: PLC0415

        if self.closed:
            raise StreamLost()
        try:
            item = await asyncio.wait_for(self.inbox.get(), timeout_s)
        except TimeoutError:
            return None
        if item is None:
            self.closed = True
            raise StreamLost()
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class FakeWs:
    """A connection's `ws`: each `connect()` gives the stream, or raises `error`."""

    def __init__(self, stream: FakeStream | None = None, error: BaseException | None = None) -> None:
        self.stream, self.error, self.opened = stream or FakeStream(), error, 0

    async def connect(self) -> FakeStream:
        self.opened += 1
        if self.error is not None:
            raise self.error
        return self.stream


@dataclass
class FakeConnection:
    http: FakeHttp
    config: Mapping[str, Any] = field(default_factory=lambda: {"cloud": "global_01", "org_id": ORG})
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "mist"
    ws: FakeWs = field(default_factory=FakeWs)


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
    beats: int = 0

    def idempotency_key(self) -> str:
        return "k"

    async def connection(self, connection_id: uuid.UUID) -> FakeConnection:
        self.opened.append(connection_id)
        assert connection_id == self.connection_.id
        return self.connection_

    def heartbeat(self, *details: object) -> None:
        self.beats += 1
