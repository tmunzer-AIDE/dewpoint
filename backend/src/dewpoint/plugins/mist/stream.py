# SPDX-License-Identifier: Apache-2.0
"""A device command's output from Mist's stream (plugins-3 D27; docs `guides/websocket/`): subscribe to the device's
`cmd` channel (a probe: it changes nothing) and wait for `channel_subscribed`; POST the command; while the POST is under
way, buffer the channel's data messages (bounded), since the session they belong to is only known from its answer;
then keep the session's messages and discard the rest, a message without a session included. Each message is decoded
strictly: an envelope whose `data` is an object or a JSON string, itself at most once another envelope of the same
channel, holding a `session` and a `raw` text. ANSI sequences and control characters are stripped.

It ends on terminal evidence (a table's `"finished": true` with `"status": "SUCCESS"`), on idle once output came, or at
the node's maximum duration; it heartbeats on every message and at least every `BEAT_S`. Before the POST nothing was
sent, so every failure there is retryable or fatal; after it, an unmet condition is `Unmet`, which the node maps by
its review. The stream is closed whatever happens; no unsubscribe is sent (its message isn't documented)."""

import asyncio
import json
import re
from collections.abc import Awaitable, Mapping
from typing import Any

from dewpoint.plugins.mist.client import Answer, Forbidden, Unauthorized
from dewpoint.sdk import (
    Connection,
    FatalError,
    HandshakeRejected,
    ResponseTooLarge,
    ResponseUnreadable,
    RetryableError,
    StepContext,
    StreamLost,
    WebSocket,
)

ACK_S = 10.0  # the subscription's acknowledgement (docs `2_best_practices`: a 10 s watchdog)
FIRST_S = 30.0  # the session's first message after the POST's answer
IDLE_S = 10.0  # the quiet that ends a collection once output came
BEAT_S = 5.0  # the longest a receive waits: a heartbeat at least this often
PENDING_MESSAGES = 256  # the channel's messages buffered before the session is known
PENDING_BYTES = 1024 * 1024
KEPT_LINES = 5000  # the output a step keeps; past either, `truncated`
KEPT_BYTES = 512 * 1024
TRANSIENT = "Server error, please try again later"  # the docs' `subscribe_failed` sample: a retry may succeed
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # every control character but tab and newline
LOST = (StreamLost, ResponseTooLarge, ResponseUnreadable)
UNREADABLE = (ValueError, RecursionError)  # JSON nested past the decoder's limit raises the second (review L1)


class StreamUnavailable(RetryableError):
    def __init__(self) -> None:
        super().__init__("mist.stream_unavailable", "Mist's stream couldn't be opened or subscribed: nothing was sent.")


class SubscribeRefused(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.subscribe_refused", "Mist refused the device's command channel: nothing was sent.")


class CommandFailed(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.command_failed", "The device answered that the command failed.")


class Unmet(Exception):
    """After an accepted POST, the node's success condition unmet (D27): the node maps it by its review, a repeatable
    diagnostic's to `RetryableError`, any other to `OutcomeUnknownError`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def no_session() -> Unmet:
    return Unmet("mist.no_session", "Mist accepted the command but named no session to read its output by.")


def overflow() -> Unmet:
    return Unmet("mist.output_overflow", "The command's output passed what a step may read.")


def no_output() -> Unmet:
    return Unmet("mist.no_output", "Mist accepted the command but no output came.")


def lost() -> Unmet:
    return Unmet("mist.stream_lost", "The stream was lost before the command's output was complete.")


def unreadable() -> Unmet:
    return Unmet("mist.output_unreadable", "The stream sent output the step can't read.")


def completion_unknown() -> Unmet:
    return Unmet("mist.completion_unknown", "The output ended without the evidence that the command finished.")


def channel(site_id: str, device_id: str) -> str:
    """The device's command channel, its ids in lower case as Mist writes them."""
    return f"/sites/{site_id.lower()}/devices/{device_id.lower()}/cmd"


def _lower(value: Any) -> str | None:
    return value.lower() if isinstance(value, str) else None


def _data(message: Any, channel_: str, depth: int = 0) -> tuple[str, str] | None:
    """A data envelope of `channel_`: its (session, raw), or None."""
    if not isinstance(message, Mapping) or message.get("event") != "data" or _lower(message.get("channel")) != channel_:
        return None
    value = message.get("data")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except UNREADABLE:
            return None
    if not isinstance(value, Mapping):
        return None
    if "event" in value:  # another envelope inside, once
        return _data(value, channel_, depth + 1) if depth == 0 else None
    session, raw = value.get("session"), value.get("raw")
    return (session, raw) if isinstance(session, str) and session and isinstance(raw, str) else None


def _parsed(text: str) -> Any:
    try:
        return json.loads(text)
    except UNREADABLE:
        return None


def _finished(raw: str) -> bool:
    """Whether `raw` is a table the device says is finished: a JSON object at its start (text after it is ignored, as
    the docs' show ARP sample has some) with `"finished": true` and `"status": "SUCCESS"`. Finished with another
    status is the device's refusal; finished without one is no evidence."""
    text = raw.lstrip()
    if not text.startswith("{"):
        return False
    try:
        table, _ = json.JSONDecoder().raw_decode(text)
    except UNREADABLE:
        return False
    if not isinstance(table, Mapping) or table.get("finished") is not True or not isinstance(table.get("status"), str):
        return False  # no evidence: a table without a status says nothing about the command
    if table["status"] != "SUCCESS":
        raise CommandFailed()
    return True


async def _open(connection: Connection) -> WebSocket:
    try:
        return await connection.ws.connect()
    except HandshakeRejected as e:
        if e.status == 401:
            raise Unauthorized() from None
        if e.status == 403:
            raise Forbidden() from None
        raise  # the runtime retries a 429 or a 5xx, and fails the rest


class _Reader:
    def __init__(self, ctx: StepContext, ws: WebSocket, channel_: str, terminal: bool) -> None:
        self.ctx, self.ws, self.channel, self.terminal = ctx, ws, channel_, terminal
        self.pending: list[tuple[str, str]] = []
        self.pending_bytes = 0
        self.overflowed = self.gone = self.garbled = False
        self.lines: list[str] = []
        self.kept_bytes, self.received, self.truncated = 0, 0, False

    def _beat(self) -> None:
        self.ctx.heartbeat()
        if self.ctx.cancelled:
            raise asyncio.CancelledError()

    async def subscribe(self) -> None:
        """Subscribed, or `StreamUnavailable` (lost, unacknowledged in `ACK_S`, refused for the documented transient
        reason) or `SubscribeRefused`: nothing was sent either way."""
        loop = asyncio.get_running_loop()
        try:
            await self.ws.send(json.dumps({"subscribe": self.channel}), probe=True)
            deadline = loop.time() + ACK_S
            while (remaining := deadline - loop.time()) > 0:
                text = await self.ws.receive(min(BEAT_S, remaining))
                self._beat()
                message = _parsed(text) if text is not None else None
                if not isinstance(message, Mapping):
                    continue
                event, named = message.get("event"), _lower(message.get("channel"))
                if event == "channel_subscribed" and named == self.channel:
                    return
                if event == "subscribe_failed" and named in (self.channel, None):
                    raise StreamUnavailable() if message.get("detail") == TRANSIENT else SubscribeRefused()
        except LOST:
            raise StreamUnavailable() from None
        raise StreamUnavailable()

    async def during(self, post: Awaitable[Answer]) -> Answer:
        """The POST's answer, the channel's data buffered while it was under way. A lost stream or an overflow lets the
        POST finish (it's the command) and fails after it."""
        task = asyncio.ensure_future(post)
        receive: asyncio.Future[str | None] | None = None
        try:
            while not task.done():
                if self.gone:
                    await asyncio.wait({task}, timeout=BEAT_S)
                    self.ctx.heartbeat()
                    continue
                receive = asyncio.ensure_future(self.ws.receive(BEAT_S))
                await asyncio.wait({task, receive}, return_when=asyncio.FIRST_COMPLETED)
                if not receive.done():
                    continue  # the POST answered: the receive is cancelled below (cancel-safe, nothing is lost)
                try:
                    text = receive.result()
                except LOST as e:
                    self.gone, self.garbled = True, isinstance(e, ResponseUnreadable)
                    self.overflowed = self.overflowed or isinstance(e, ResponseTooLarge)
                    continue
                finally:
                    receive = None
                self.ctx.heartbeat()
                if text is not None:
                    self._buffer(text)
            answer = task.result()
        finally:
            # Whatever ended the wait (the answer, a cancel, a bug), nothing is left running (review L1).
            pending = [f for f in (receive, task) if f is not None and not f.done()]
            for f in pending:
                f.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        if self.overflowed:
            raise overflow()
        if self.gone:
            raise unreadable() if self.garbled else lost()
        return answer

    def _buffer(self, text: str) -> None:
        found = _data(_parsed(text), self.channel)
        if found is None or self.overflowed:
            return
        self.pending_bytes += len(text.encode())
        if len(self.pending) >= PENDING_MESSAGES or self.pending_bytes > PENDING_BYTES:
            self.overflowed = True
            return
        self.pending.append(found)

    def _take(self, raw: str) -> bool:
        """The session's message kept: its lines, within the caps; whether it's the terminal evidence."""
        self.received += 1
        done = _finished(raw)
        for line in CONTROL.sub("", ANSI.sub("", raw)).splitlines():
            size = len(line.encode())
            if len(self.lines) >= KEPT_LINES or self.kept_bytes + size > KEPT_BYTES:
                self.truncated = True
                continue
            self.lines.append(line)
            self.kept_bytes += size
        return done

    async def collect(self, session: str, max_duration_s: float, until: float | None = None) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        start = loop.time()
        deadline = start + max_duration_s if until is None else min(start + max_duration_s, until)
        quiet_from = start
        ended: str | None = None
        for found_session, raw in self.pending:
            if found_session == session and self._take(raw):
                ended = "finished"
                break
        while ended is None:
            now = loop.time()
            quiet_until = quiet_from + (IDLE_S if self.received else FIRST_S)
            if now >= deadline:
                ended = "max_duration"
                break
            if now >= quiet_until:
                ended = "idle"
                break
            try:
                text = await self.ws.receive(min(BEAT_S, deadline - now, quiet_until - now))
            except StreamLost:
                raise lost() from None
            except ResponseTooLarge:
                raise overflow() from None
            except ResponseUnreadable:
                raise unreadable() from None
            self._beat()
            found = _data(_parsed(text), self.channel) if text is not None else None
            if found is None or found[0] != session:
                continue
            quiet_from = loop.time()
            if self._take(found[1]):
                ended = "finished"
        if not self.received:
            raise no_output()
        if self.terminal and ended != "finished":
            raise completion_unknown()
        return {
            "accepted": True,
            "session": session,
            "lines": self.lines,
            "received": self.received,
            "ended_by": ended,
            "completion_known": ended == "finished",
            "truncated": self.truncated,
        }


async def collect(
    ctx: StepContext,
    connection: Connection,
    client: Any,
    path: str,
    body: Any,
    *,
    channel: str,
    terminal: bool,
    max_duration_s: float,
    until: float | None = None,
) -> dict[str, Any]:
    """The command's output as D27's streaming contracts promise it: `terminal`, only with its terminal evidence; else
    a bounded collection, at least one message ended by idle, the maximum duration or that evidence. `until` (the event
    loop's time) ends the collection sooner, as its maximum duration would: the step's own timeout, less a margin."""
    ws = await _open(connection)
    try:
        reader = _Reader(ctx, ws, channel, terminal)
        await reader.subscribe()
        answer = await reader.during(client.call("POST", path, body=body))
        session = answer.body.get("session") if isinstance(answer.body, Mapping) else None
        if not isinstance(session, str) or not session:
            raise no_session()
        return await reader.collect(session, max_duration_s, until)
    finally:
        await ws.close()
