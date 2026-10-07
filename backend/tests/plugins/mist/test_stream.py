# SPDX-License-Identifier: Apache-2.0
"""A device command's output from Mist's stream (plugins-3 D27), against a scripted stream: subscribe as a probe and
wait for the acknowledgement, POST, keep only the session's messages (those before the answer too, bounded), decode each
strictly, strip ANSI; end on terminal evidence, idle or the maximum duration; and fail every unmet condition: no
session, an overflow, no first message, a lost stream, an end without the declared evidence. Nothing before the POST
makes a retry unsafe. The stream is always closed."""

import asyncio
import json
from typing import Any

import pytest

from dewpoint.plugins.mist import stream
from dewpoint.plugins.mist.client import BadRequest, Forbidden, MistClient, Unauthorized
from dewpoint.sdk import FatalError, HandshakeRejected, RetryableError, StreamLost
from tests.plugins.mist.fakes import SITE, FakeConnection, FakeHttp, FakeStep, FakeStream, FakeWs, Reply, Sent

DEVICE = "00000000-0000-0000-1000-5c5b350e0060"
CHANNEL = f"/sites/{SITE}/devices/{DEVICE}/cmd"
PATH = f"/api/v1/sites/{SITE}/devices/{DEVICE}/ping"
SESSION = "9106e908-74dc-4a4f-9050-9c2adcaf44a5"
ACK = {"event": "channel_subscribed", "channel": CHANNEL}


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reader's timers, shrunk: acknowledgement, first message, idle, heartbeat."""
    monkeypatch.setattr(stream, "ACK_S", 0.3)
    monkeypatch.setattr(stream, "FIRST_S", 0.4)
    monkeypatch.setattr(stream, "IDLE_S", 0.2)
    monkeypatch.setattr(stream, "BEAT_S", 0.05)


def data(raw: str, session: str = SESSION, channel: str = CHANNEL) -> dict[str, Any]:
    return {"event": "data", "channel": channel, "data": {"session": session, "raw": raw}}


def acked(text: str) -> list[str]:
    return [json.dumps(ACK)] if json.loads(text) == {"subscribe": CHANNEL} else []


class Mist:
    """A connection to a scripted Mist: the POST answers `answer` and, as Mist does once it accepted the command, queues
    `output` on the stream."""

    def __init__(self, *output: Any, answer: Reply | None = None, on_send: Any = acked) -> None:
        self.stream = FakeStream(on_send)
        self.answer = answer or Reply(200, {"session": SESSION})
        self.output = output

        def script(sent: Sent) -> Reply:
            if sent.method == "POST":
                self.stream.queue(*self.output)
            return self.answer

        self.http = FakeHttp(script)
        self.connection = FakeConnection(self.http, ws=FakeWs(self.stream))
        self.step = FakeStep(self.connection)

    async def collect(self, *, terminal: bool = False, max_duration_s: float = 5.0) -> dict[str, Any]:
        return await stream.collect(
            self.step, self.connection, MistClient(self.connection), PATH, {"host": "8.8.8.8"},  # type: ignore[arg-type]
            channel=stream.channel(SITE, DEVICE), terminal=terminal, max_duration_s=max_duration_s,
        )  # fmt: skip

    @property
    def posts(self) -> list[Sent]:
        return [s for s in self.http.sent if s.method == "POST"]


async def test_a_bounded_collection_keeps_the_sessions_lines_until_idle() -> None:
    mist = Mist(data("64 bytes from 8.8.8.8: seq=1\n"), data("other\n", session="someone-else"),
                data("64 bytes from 8.8.8.8: seq=2\n"))  # fmt: skip
    out = await mist.collect()
    assert out == {
        "accepted": True, "session": SESSION, "lines": ["64 bytes from 8.8.8.8: seq=1", "64 bytes from 8.8.8.8: seq=2"],
        "received": 2, "ended_by": "idle", "completion_known": False, "truncated": False,
    }  # fmt: skip
    assert mist.stream.sent == [(json.dumps({"subscribe": CHANNEL}), True)]  # a probe: it changes nothing
    assert [(s.url, s.json, s.probe) for s in mist.posts] == [(PATH, {"host": "8.8.8.8"}, False)]
    assert mist.stream.closed


async def test_the_post_waits_for_the_subscription() -> None:
    mist = Mist(data("x"), on_send=lambda text: [])  # never acknowledged
    with pytest.raises(RetryableError) as raised:
        await mist.collect()
    assert raised.value.code == "mist.stream_unavailable"
    assert mist.posts == [] and mist.stream.closed


@pytest.mark.parametrize(
    ("detail", "error", "code"),
    [
        ("Server error, please try again later", RetryableError, "mist.stream_unavailable"),  # the docs' sample
        ("forbidden", FatalError, "mist.subscribe_refused"),
        (None, FatalError, "mist.subscribe_refused"),
    ],
)
async def test_a_failed_subscription_sends_nothing(detail: str | None, error: type, code: str) -> None:
    failed = {"event": "subscribe_failed", "channel": CHANNEL, **({"detail": detail} if detail else {})}
    mist = Mist(on_send=lambda text: [json.dumps(failed)])
    with pytest.raises(error) as raised:
        await mist.collect()
    assert raised.value.code == code
    assert mist.posts == [] and mist.stream.closed


async def test_an_acknowledgement_of_another_channel_isnt_ours() -> None:
    other = {"event": "channel_subscribed", "channel": f"/sites/{SITE}/devices/someone-else/cmd"}
    mist = Mist(on_send=lambda text: [json.dumps(other)])
    with pytest.raises(RetryableError):
        await mist.collect()
    assert mist.posts == []


@pytest.mark.parametrize(
    ("error", "raised"),
    [(HandshakeRejected(401), Unauthorized), (HandshakeRejected(403), Forbidden)],
)
async def test_refused_credentials_fail_as_mists(error: Exception, raised: type) -> None:
    mist = Mist()
    mist.connection.ws = FakeWs(error=error)
    with pytest.raises(raised):
        await mist.collect()
    assert mist.posts == []


async def test_a_busy_or_failing_stream_host_is_left_to_the_runtime_to_retry() -> None:
    mist = Mist()
    mist.connection.ws = FakeWs(error=HandshakeRejected(429))
    with pytest.raises(HandshakeRejected):
        await mist.collect()
    assert mist.posts == []


async def test_a_stream_lost_before_the_post_is_retryable_and_posts_nothing() -> None:
    mist = Mist(on_send=lambda text: [None])  # closed instead of acknowledged
    mist.stream.inbox.put_nowait(None)
    with pytest.raises(RetryableError) as raised:
        await mist.collect()
    assert raised.value.code == "mist.stream_unavailable" and not isinstance(raised.value, StreamLost)
    assert mist.posts == []


async def test_messages_before_the_answer_are_kept_when_theyre_the_sessions() -> None:
    mist = Mist(answer=Reply(200, {"session": SESSION}, delay_s=0.15))
    early = [data("early\n"), data("not ours\n", session="other")]
    mist.stream._on_send = lambda text: [json.dumps(ACK), *(json.dumps(m) for m in early)]  # type: ignore[assignment]
    out = await mist.collect()
    assert out["lines"] == ["early"] and out["received"] == 1


async def test_too_many_messages_before_the_answer_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "PENDING_MESSAGES", 3)
    mist = Mist(answer=Reply(200, {"session": SESSION}, delay_s=0.15))
    mist.stream._on_send = lambda text: [json.dumps(ACK), *(json.dumps(data(f"{i}")) for i in range(4))]  # type: ignore[assignment]
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect()
    assert raised.value.code == "mist.output_overflow"
    assert len(mist.posts) == 1 and mist.stream.closed  # the POST was let finish: it's the command


async def test_an_answer_without_a_session_is_unmet() -> None:
    mist = Mist(data("x"), answer=Reply(200, {}))
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect()
    assert raised.value.code == "mist.no_session"


async def test_a_refused_post_fails_as_its_status_says() -> None:
    mist = Mist(answer=Reply(400, {"detail": "bad"}))
    with pytest.raises(BadRequest):
        await mist.collect()
    assert mist.stream.closed


async def test_no_first_message_is_no_output() -> None:
    mist = Mist()
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect()
    assert raised.value.code == "mist.no_output"


async def test_a_stream_lost_after_the_post_is_unmet_even_with_output() -> None:
    mist = Mist(data("partial\n"), None)
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect()
    assert raised.value.code == "mist.stream_lost"


async def test_the_maximum_duration_ends_a_collection_that_has_output() -> None:
    mist = Mist(*(data(f"line {i}\n") for i in range(3)))

    async def chatty() -> None:
        for i in range(40):
            await asyncio.sleep(0.03)
            mist.stream.queue(data(f"more {i}\n"))

    task = asyncio.create_task(chatty())
    out = await mist.collect(max_duration_s=0.4)
    task.cancel()
    assert out["ended_by"] == "max_duration" and out["completion_known"] is False and out["received"] >= 3


async def test_the_maximum_duration_without_any_output_is_no_output() -> None:
    mist = Mist()
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect(max_duration_s=0.1)
    assert raised.value.code == "mist.no_output"


TABLE = {"status": "SUCCESS", "finished": True, "message": "Arp Table", "rows": [{"ip_address": "192.168.1.1"}]}


async def test_terminal_evidence_ends_a_table_with_its_completion_known() -> None:
    mist = Mist(data(json.dumps(TABLE) + "\n"))
    out = await mist.collect(terminal=True)
    assert (out["ended_by"], out["completion_known"], out["lines"]) == ("finished", True, [json.dumps(TABLE)])


async def test_a_bounded_collection_that_sees_the_evidence_ends_early_too() -> None:
    mist = Mist(data("Retrieving...\n"), data(json.dumps(TABLE)))
    out = await mist.collect(terminal=False, max_duration_s=30)
    assert (out["ended_by"], out["completion_known"], out["received"]) == ("finished", True, 2)


async def test_a_table_whose_raw_has_trailing_text_after_its_object_still_finishes() -> None:
    """The docs' show ARP sample ends its table with `\\n"}}`: the object is the device's word, what follows isn't."""
    mist = Mist(data(json.dumps(TABLE) + '\n"}}'))
    out = await mist.collect(terminal=True)
    assert out["ended_by"] == "finished"


@pytest.mark.parametrize(
    "table",
    [
        {"status": "SUCCESS", "finished": False, "rows": []},
        {"status": "SUCCESS", "finished": "true", "rows": []},
        {"finished": True},  # no status
    ],
)
async def test_without_the_evidence_a_terminal_contract_is_unmet(table: dict[str, Any]) -> None:
    mist = Mist(data(json.dumps(table)))
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect(terminal=True)
    assert raised.value.code == "mist.completion_unknown"


async def test_a_finished_table_that_failed_is_the_devices_refusal() -> None:
    mist = Mist(data(json.dumps({**TABLE, "status": "FAILED"})))
    with pytest.raises(FatalError) as raised:
        await mist.collect(terminal=True)
    assert raised.value.code == "mist.command_failed"


@pytest.mark.parametrize(
    "message",
    [
        {"event": "data", "channel": CHANNEL, "data": json.dumps({"session": SESSION, "raw": "as a string\n"})},
        {"event": "data", "channel": CHANNEL, "data": json.dumps(
            {"event": "data", "channel": CHANNEL, "data": {"session": SESSION, "raw": "nested\n"}})},
    ],
)  # fmt: skip
async def test_data_as_a_json_string_or_a_nested_envelope_is_read(message: dict[str, Any]) -> None:
    mist = Mist(message)
    out = await mist.collect()
    assert out["received"] == 1 and len(out["lines"]) == 1


@pytest.mark.parametrize(
    "message",
    [
        "not json",
        json.dumps([1, 2]),
        json.dumps({"event": "data", "channel": f"/sites/{SITE}/devices/other/cmd",
                    "data": {"session": SESSION, "raw": "another device"}}),
        json.dumps({"event": "data", "channel": CHANNEL, "data": json.dumps(
            {"event": "data", "channel": f"/sites/{SITE}/devices/other/cmd",
             "data": {"session": SESSION, "raw": "nested elsewhere"}})}),
        json.dumps({"event": "data", "channel": CHANNEL, "data": json.dumps(json.dumps(
            {"session": SESSION, "raw": "twice encoded"}))}),
        json.dumps({"event": "data", "channel": CHANNEL, "data": {"raw": "no session"}}),
        json.dumps({"event": "data", "channel": CHANNEL, "data": {"session": SESSION, "raw": 5}}),
        json.dumps({"event": "data", "channel": CHANNEL, "data": {"session": 5, "raw": "x"}}),
        json.dumps({"event": "other", "channel": CHANNEL, "data": {"session": SESSION, "raw": "x"}}),
    ],
)  # fmt: skip
async def test_a_message_that_isnt_the_sessions_data_is_discarded_never_accepted(message: str) -> None:
    mist = Mist(message)
    with pytest.raises(stream.Unmet) as raised:
        await mist.collect()
    assert raised.value.code == "mist.no_output"


async def test_ansi_and_control_characters_are_stripped() -> None:
    mist = Mist(data("\x1b[1;32mOK\x1b[0m\tdone\r\n\x1b]0;title\x07bell\x07\x00\n"))
    out = await mist.collect()
    assert out["lines"] == ["OK\tdone", "bell"]


async def test_the_output_is_capped_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "KEPT_LINES", 3)
    mist = Mist(data("a\nb\n"), data("c\nd\n"), data("e\n"))
    out = await mist.collect()
    assert (out["lines"], out["received"], out["truncated"]) == (["a", "b", "c"], 3, True)
    monkeypatch.setattr(stream, "KEPT_LINES", 100)
    monkeypatch.setattr(stream, "KEPT_BYTES", 5)
    mist = Mist(data("abc\ndef\n"))
    out = await mist.collect()
    assert (out["lines"], out["truncated"]) == (["abc"], True)


async def test_it_heartbeats_on_messages_and_while_waiting() -> None:
    mist = Mist(data("one\n"))
    await mist.collect()
    assert mist.step.beats >= 4  # the idle wait (0.2 s) in beats of 0.05 s, and the message


async def test_a_cancelled_step_stops_and_closes_its_stream() -> None:
    mist = Mist(data("one\n"))

    async def cancel() -> None:
        await asyncio.sleep(0.05)
        mist.step.cancelled = True

    task = asyncio.create_task(cancel())
    with pytest.raises(asyncio.CancelledError):
        await mist.collect(max_duration_s=5)
    await task
    assert mist.stream.closed


def test_the_channel_is_the_devices_command_channel_in_lower_case() -> None:
    assert stream.channel(SITE.upper(), DEVICE.upper()) == CHANNEL


DEEP = "[" * 200_000  # past the JSON decoder's recursion limit


async def test_deeply_nested_json_is_unreadable_and_discarded_in_every_phase() -> None:
    """Review L1: `RecursionError` isn't a `ValueError`; each phase discards such a message instead of raising it."""
    deep_raw = '{"a":' * 50_000
    mist = Mist(data(deep_raw), data("after\n"), answer=Reply(200, {"session": SESSION}, delay_s=0.1))
    mist.stream._on_send = lambda text: [DEEP, json.dumps(ACK), DEEP]  # type: ignore[assignment]
    out = await mist.collect()
    assert out["received"] == 2 and out["lines"][-1] == "after"
    terminal = Mist(data(deep_raw))
    with pytest.raises(stream.Unmet) as raised:
        await terminal.collect(terminal=True)
    assert raised.value.code == "mist.completion_unknown"


async def test_a_cancelled_collection_leaves_no_task_behind() -> None:
    """Review L1: the POST under way and the pending receive are both cancelled and awaited."""
    mist = Mist(answer=Reply(200, {"session": SESSION}, delay_s=5))
    before = asyncio.all_tasks()
    collecting = asyncio.ensure_future(mist.collect())
    await asyncio.sleep(0.2)  # subscribed, the POST under way
    collecting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await collecting
    await asyncio.sleep(0)
    assert {t for t in asyncio.all_tasks() - before if not t.done()} == set()
    assert mist.stream.closed
