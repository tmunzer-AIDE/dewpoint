# SPDX-License-Identifier: Apache-2.0
"""Syslog (plugins-3 3c-2, D21): a `syslog` connection type (a host, a port, TLS, UDP or TCP, the facility and the
header's names; no secret) and `syslog.send_message`: the message as an RFC 5424 line (`<PRI>1 TIMESTAMP HOSTNAME
APP-NAME - - - BOM MSG`) or a CEF v27 payload, cut to its transport's size, framed for it (octet counting over TLS
and TCP, or LF for legacy TCP; one datagram over UDP) and sent through the guarded network to the connection's host
only. Every send is ambiguous: `sent` means handed over, never received."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.syslog import BOM, LIMITS, PLUGIN, SYSLOG, SendMessage, frame, render
from dewpoint.sdk import FatalError, SideEffect
from dewpoint.sdk.messages import Message
from tests.plugins.mist.fakes import FakeStep

NOW = datetime(2026, 10, 8, 9, 30, 0, 123456, tzinfo=UTC)
CONFIG = {"host": "logs.example.com", "port": 6514, "transport": "tls", "framing": "octet", "facility": 1,
          "app_name": "dewpoint", "hostname": None, "format": "rfc5424",
          "cef_event_class": "dewpoint.message"}  # fmt: skip
HEADER = re.compile(rb"<(\d{1,3})>1 (\S+) (\S+) (\S+) - - - ")


def config(**changes: Any) -> Any:
    return SYSLOG.Config.model_validate({**CONFIG, **changes})


def message(**changes: Any) -> Message:
    return Message.model_validate({"text": "Disk full on db-1", **changes})


def test_the_plugin_validates_its_type_has_no_secret_and_its_node_is_ambiguous() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert SendMessage.side_effect == SideEffect.AMBIGUOUS and SendMessage.credentials == ("syslog",)
    assert SYSLOG.Secret.model_fields == {} and SYSLOG.rate_scopes == () and SYSLOG.smtp is None


def test_an_rfc5424_line() -> None:
    line, cut = render(message(title="db-1", fields=[{"label": "Free", "value": "2%"}],
                               links=[{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                               severity="warning"), config(hostname="dewpoint-prod"), NOW)  # fmt: skip
    assert line == (b"<12>1 2026-10-08T09:30:00.123456Z dewpoint-prod dewpoint - - - " + BOM
                    + b"db-1 | Disk full on db-1 | Free: 2% | Runbook <https://wiki.example.com/disk>")  # fmt: skip
    assert cut == []


@pytest.mark.parametrize(("severity", "pri"), [("info", 14), ("success", 13), ("warning", 12), ("critical", 10)])
def test_the_priority_is_the_facility_times_8_plus_the_severity(severity: str, pri: int) -> None:
    line, _ = render(message(severity=severity), config(), NOW)
    assert HEADER.match(line).group(1) == str(pri).encode()  # type: ignore[union-attr]
    assert render(message(severity=severity), config(facility=16), NOW)[0].startswith(f"<{128 + pri - 8}>".encode())


def test_the_hostname_is_nil_unless_named_and_every_line_is_one_line() -> None:
    line, _ = render(message(text="a\r\nb\nc\rd"), config(), NOW)
    assert HEADER.match(line).group(3) == b"-" and b"\n" not in line and b"\r" not in line  # type: ignore[union-attr]
    assert line.endswith(BOM + b"a b c d")  # a CRLF is one break


@pytest.mark.parametrize(("transport", "limit"), [("udp", 2048), ("tcp", 8192), ("tls", 8192)])
def test_a_message_is_cut_to_its_transports_size(transport: str, limit: int) -> None:
    assert LIMITS[transport] == limit
    line, cut = render(message(text="é" * 40_000), config(transport=transport), NOW)
    assert len(line) <= limit and line.endswith("…".encode()) and cut == ["text"]
    line.decode("utf-8")  # cut between characters, never through one


def test_framing() -> None:
    line = b"<14>1 x - dewpoint - - - msg"
    assert frame(line, config(transport="tls")) == b"%d %s" % (len(line), line)  # RFC 5425
    assert frame(line, config(transport="tcp")) == b"%d %s" % (len(line), line)  # RFC 6587 octet counting
    assert frame(line, config(transport="tcp", framing="lf")) == line + b"\n"
    assert frame(line, config(transport="udp")) == line  # one datagram (RFC 5426)


def test_a_cef_payload_is_escaped_as_cef_v27_says() -> None:
    line, cut = render(message(title="disk | full \\ now", text="free=2% on a\\b\nnext", severity="critical"),
                       config(format="cef", cef_event_class="disk|full"), NOW)  # fmt: skip
    payload = line.split(b" - - - ", 1)[1]
    assert not payload.startswith(BOM)  # CEF readers expect "CEF:" first: MSG-ANY (RFC 5424 §6)
    assert payload.decode() == ("CEF:0|Dewpoint|Dewpoint|1.0.0|disk\\|full|disk \\| full \\\\ now|10|"
                                "msg=free\\=2% on a\\\\b next")  # fmt: skip
    assert cut == []


@pytest.mark.parametrize(("severity", "cef"), [("info", "3"), ("success", "1"), ("warning", "6"), ("critical", "10")])
def test_cef_severities(severity: str, cef: str) -> None:
    line, _ = render(message(severity=severity), config(format="cef"), NOW)
    assert line.split(b"|")[6] == cef.encode()


def test_cef_names_and_messages_are_cut_to_their_lengths() -> None:
    line, cut = render(message(title="n" * 600, text="m" * 2000), config(format="cef", transport="tcp"), NOW)
    fields = line.split(b" - - - ", 1)[1].decode().split("|")
    assert len(fields[5]) <= 512 and fields[5].endswith("…") and len(fields[7].removeprefix("msg=")) <= 1023
    assert cut == ["title", "text"]


@pytest.mark.parametrize(
    "changes",
    [{"host": "Logs.Example.com"}, {"host": "logs"}, {"port": 0}, {"transport": "quic"}, {"framing": "nul"},
     {"facility": 24}, {"facility": -1}, {"app_name": "dew point"}, {"app_name": "a" * 49}, {"hostname": "h\n"},
     {"hostname": "x" * 256}, {"format": "json"}, {"cef_event_class": "c\nx"}, {"extra": 1}],
)  # fmt: skip
def test_a_connection_of_another_form_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        config(**changes)


@dataclass
class FakeStream:
    sent: list[bytes] = field(default_factory=list)
    closed: bool = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive(self, max_bytes: int = 65_536) -> bytes:
        return b""

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeNet:
    opened: list[tuple[str, int, bool]] = field(default_factory=list)
    datagrams: list[tuple[str, int, bytes]] = field(default_factory=list)
    stream: FakeStream = field(default_factory=FakeStream)

    async def open_tcp(self, host: str, port: int, *, tls: bool) -> FakeStream:
        self.opened.append((host, port, tls))
        return self.stream

    async def send_udp(self, host: str, port: int, data: bytes) -> None:
        self.datagrams.append((host, port, data))


@dataclass
class FakeSyslogConnection:
    config: dict[str, Any]
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "syslog"


async def run(**changes: Any) -> tuple[Any, FakeNet]:
    conn = FakeSyslogConnection(config=config(**changes).model_dump(mode="json"))
    step = FakeStep(conn)  # type: ignore[arg-type]
    step.net = FakeNet()  # type: ignore[attr-defined]
    value = SendMessage.Config.model_validate({"connection": str(conn.id), "text": "hello"})
    out = await SendMessage().run(step, value)  # type: ignore[arg-type]
    return out.model_dump(), step.net  # type: ignore[attr-defined]


@pytest.mark.parametrize(("transport", "tls"), [("tls", True), ("tcp", False)])
async def test_a_stream_send_opens_the_connections_host_and_closes(transport: str, tls: bool) -> None:
    out, net = await run(transport=transport, port=6514 if tls else 601)
    assert out == {"sent": True, "truncated": []} and net.opened == [("logs.example.com", 6514 if tls else 601, tls)]
    [data] = net.stream.sent
    length, _, line = data.partition(b" ")
    assert int(length) == len(line) and line.endswith(BOM + b"hello") and net.stream.closed


async def test_a_datagram_send_is_one_datagram_to_the_connections_host() -> None:
    out, net = await run(transport="udp", port=514)
    [(host, port, data)] = net.datagrams
    assert (out, host, port) == ({"sent": True, "truncated": []}, "logs.example.com", 514) and data.endswith(b"hello")


async def test_simulating_renders_and_sends_nothing() -> None:
    conn = FakeSyslogConnection(config=config().model_dump(mode="json"))
    step = FakeStep(conn)  # type: ignore[arg-type]
    value = SendMessage.Config.model_validate({"connection": str(conn.id), "text": "y" * 40_000})
    out = await SendMessage().simulate(step, value)  # type: ignore[arg-type]
    assert out.model_dump() == {"sent": True, "truncated": ["text"]} and step.opened == []


@pytest.mark.parametrize("transport", ["udp", "tcp", "tls"])
@pytest.mark.parametrize("fill", ["\U0001f600", "|", "\\", "="])
def test_a_cef_line_never_exceeds_its_transports_size(transport: str, fill: str) -> None:
    """The review's L4: a 600-emoji title made a UDP CEF line 2155 octets."""
    line, cut = render(message(title=fill * 1000, text=fill * 40_000),
                       config(format="cef", transport=transport, cef_event_class="e" * 300), NOW)  # fmt: skip
    assert len(line) <= LIMITS[transport] and "title" in cut and "text" in cut
    head = line.split(b" - - - ", 1)[1].decode().split("|msg=", 1)[0] + "|"  # the extension's pipes need no escaping
    assert head.count("|") - head.count("\\|") == 7  # every header field's own pipe, none escaped away by a cut


def test_an_event_class_too_long_for_udp_is_refused_before_sending() -> None:
    with pytest.raises(FatalError) as raised:
        render(message(), config(format="cef", transport="udp", cef_event_class="|" * 1023), NOW)
    assert raised.value.code == "syslog.too_large"
