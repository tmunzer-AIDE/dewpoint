# SPDX-License-Identifier: Apache-2.0
"""Syslog (plugins-3 3c-2, D21): a message logged to a syslog receiver.

The connection names the receiver: a host name, a port, a transport - `tls` (RFC 5425: octet counting, TLS 1.2 or
later, the certificate checked; port 6514), `udp` (RFC 5426: one message a datagram; port 514) or `tcp` (RFC 6587:
octet counting, or LF framing for legacy receivers) - plain transports only to an allowlisted address (D7); the
facility (0 to 23, 1 by default), and the header's APP-NAME and HOSTNAME. It has no secret (no client certificates in
v1) and no quota scope (none is documented).

The message is one RFC 5424 line: `<PRI>1 TIMESTAMP HOSTNAME APP-NAME - - - MSG`, PRI the facility × 8 plus the
severity (info 6, success 5, warning 4, critical 2), TIMESTAMP UTC to the microsecond, PROCID, MSGID and
STRUCTURED-DATA nil, and MSG the title, the text, `label: value` fields and `label <url>` links joined by ` | `, CR and
LF as spaces, UTF-8 behind the BOM (§6.4). Or MSG is a CEF v27 payload, `CEF:0|Dewpoint|Dewpoint|<version>|<event
class>|<name>|<severity>|msg=…`, escaped as CEF says and sent without the BOM: CEF readers expect `CEF:` first. A
message is at most 2048 octets over UDP and 8192 over TCP and TLS (what receivers SHOULD accept); the MSG is cut to
fit, marked and reported.

Every send is ambiguous (D21): `sent` means the frame was handed over, never that it was received."""

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dewpoint.sdk import ConnectionType, FatalError, Node, Plugin, SideEffect, StepContext, connection_field
from dewpoint.sdk.messages import MARK, Message, Severity, cut

VERSION = "1.0.0"
BOM = b"\xef\xbb\xbf"
LIMITS = {"udp": 2048, "tcp": 8192, "tls": 8192}  # RFC 5424 §6.1, RFC 5426 §3.2; RFC 5425 §4.3.1
SEVERITIES = {Severity.INFO: 6, Severity.SUCCESS: 5, Severity.WARNING: 4, Severity.CRITICAL: 2}
CEF_SEVERITIES = {Severity.INFO: 3, Severity.SUCCESS: 1, Severity.WARNING: 6, Severity.CRITICAL: 10}
CEF_NAME_MAX, CEF_MSG_MAX = 512, 1023
NEWLINES = re.compile(r"\r\n|\r|\n")
# The config as the API checks it: the manifest's JSON Schema (pydantic's validators never run there), each pattern
# also pydantic's, whose regex has no lookaround. A schema pattern's `$` is Python's, which takes a final newline:
# `not` refuses any, in a string only (a null hostname passes).
NO_NEWLINE: dict[str, Any] = {"not": {"type": "string", "pattern": "\n"}}
HOST = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"  # HOST_RE; max_length its 253
PRINTUSASCII = r"^[\x21-\x7e]+$"  # RFC 5424 §6: what a header field holds
ONE_LINE = r"^[^\r\n]*$"  # no NEWLINES: a CEF header field is one line


class SyslogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(max_length=253, pattern=HOST, json_schema_extra=NO_NEWLINE, title="Receiver",
                      description="Its host name, e.g. logs.example.com.")  # fmt: skip
    port: int = Field(ge=1, le=65535, title="Port", description="6514 for TLS, 514 for UDP.")
    transport: Literal["tls", "udp", "tcp"] = Field("tls", title="Transport")
    framing: Literal["octet", "lf"] = Field("octet", title="TCP framing", description="lf for legacy receivers.")
    facility: int = Field(1, ge=0, le=23, title="Facility", description="0 to 23; 16 to 23 are local0 to local7.")
    app_name: str = Field("dewpoint", min_length=1, max_length=48, pattern=PRINTUSASCII, json_schema_extra=NO_NEWLINE,
                          title="App name")  # fmt: skip
    hostname: str | None = Field(None, max_length=255, pattern=PRINTUSASCII, json_schema_extra=NO_NEWLINE,
                                 title="Hostname", description="Nil (-) when empty.")  # fmt: skip
    format: Literal["rfc5424", "cef"] = Field("rfc5424", title="Format")
    cef_event_class: str = Field("dewpoint.message", min_length=1, max_length=1023, pattern=ONE_LINE,
                                 json_schema_extra=NO_NEWLINE, title="CEF event class")  # fmt: skip


class SyslogSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")


SYSLOG = ConnectionType(key="syslog", label="Syslog", Config=SyslogConfig, Secret=SyslogSecret)


def _flat(text: str) -> str:
    return NEWLINES.sub(" ", text)


def _cef_header(text: str) -> str:
    return _flat(text).replace("\\", "\\\\").replace("|", "\\|")


def _cef_value(text: str) -> str:
    return _flat(text).replace("\\", "\\\\").replace("=", "\\=")


def _fitted(raw: str, max_chars: int, max_bytes: int, escape: Callable[[str], str]) -> tuple[str, bool]:
    """`raw` escaped, within `max_chars` characters of it and `max_bytes` octets escaped: cut before an escape rather
    than through one (a lone `\\` would escape the next field's pipe), and marked."""
    flat = _flat(raw)
    whole = escape(flat)
    if len(flat) <= max_chars and len(whole.encode()) <= max_bytes:
        return whole, False
    kept: list[str] = []
    size, budget = 0, max_bytes - len(MARK.encode())
    for char in flat[: max(max_chars - 1, 0)]:
        part = escape(char)
        if size + len(part.encode()) > budget:
            break
        kept.append(part)
        size += len(part.encode())
    return "".join(kept) + MARK, True


def _parts(message: Message, *, title: bool) -> str:
    parts = ([message.title] if title and message.title else []) + [message.text]
    parts += [f"{f.label}: {f.value}" for f in message.fields]
    parts += [f"{link.label} <{link.url}>" for link in message.links]
    return _flat(" | ".join(parts))


def render(message: Message, config: SyslogConfig, now: datetime) -> tuple[bytes, list[str]]:
    """The message as one syslog line (RFC 5424, or its CEF payload), within the transport's size, and the names of the
    values it cut."""
    pri = config.facility * 8 + SEVERITIES[message.severity]
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    header = f"<{pri}>1 {stamp} {config.hostname or '-'} {config.app_name} - - - ".encode()
    budget = LIMITS[config.transport] - len(header)
    truncated: list[str] = []
    if config.format == "cef":
        start = f"CEF:0|Dewpoint|Dewpoint|{VERSION}|{_cef_header(config.cef_event_class)}|"
        end = f"|{CEF_SEVERITIES[message.severity]}|msg="
        room = budget - len((start + end).encode())  # for the name and the message (the review's L4)
        named = message.title or message.text
        text = _parts(message, title=False)
        wanted = len(_cef_value(_flat(text)[:CEF_MSG_MAX]).encode())
        name, name_cut = _fitted(named, CEF_NAME_MAX, max(room - wanted, room // 2), _cef_header)
        body, body_cut = _fitted(text, CEF_MSG_MAX, room - len(name.encode()), _cef_value)
        truncated += [n for n, was in (("title" if message.title else "text", name_cut), ("text", body_cut))
                      if was and n not in truncated]  # fmt: skip
        if room < 2 * len(MARK.encode()):  # within it, the name and the message always fit: each cut to what's left
            raise FatalError("syslog.too_large", "The CEF event class leaves no room in the transport's size.")
        return header + (start + name + end + body).encode(), truncated
    body, text_cut = cut(_parts(message, title=True), budget - len(BOM), unit="bytes")
    if text_cut:
        truncated.append("text")
    return header + BOM + body.encode(), truncated


def frame(line: bytes, config: SyslogConfig) -> bytes:
    """The line as its transport carries it: octet counting over TLS (RFC 5425) and TCP (RFC 6587, unless LF framing
    is asked for), the datagram itself over UDP (RFC 5426)."""
    if config.transport == "udp":
        return line
    if config.transport == "tcp" and config.framing == "lf":
        return line + b"\n"  # the line holds no LF
    return b"%d %s" % (len(line), line)


class SendConfig(Message):
    connection: uuid.UUID = connection_field("syslog")


class SendOutput(BaseModel):
    sent: bool
    truncated: list[str]


SIMULATED = {"host": "simulated.invalid", "port": 6514}  # the connection isn't opened: the default transport's sizes


class SendMessage(Node):
    """Logs a message to the connection's syslog receiver."""

    type = "syslog.send_message"
    version = 1
    title = "Send a syslog message"
    description = (
        "Logs a message to a syslog receiver over TLS, UDP or TCP, as RFC 5424 or CEF. Sent means handed over: syslog "
        "doesn't acknowledge; a send is never retried once a byte may have left."
    )
    Config = SendConfig
    Output = SendOutput
    credentials = ("syslog",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        _, truncated = render(config, SyslogConfig.model_validate(SIMULATED), datetime.now(UTC))
        return SendOutput(sent=True, truncated=truncated)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        connection = await ctx.connection(config.connection)
        target = SyslogConfig.model_validate(dict(connection.config))
        line, truncated = render(config, target, datetime.now(UTC))
        data = frame(line, target)
        net: Any = ctx.net
        if target.transport == "udp":
            await net.send_udp(target.host, target.port, data)
        else:
            stream = await net.open_tcp(target.host, target.port, tls=target.transport == "tls")
            try:
                await stream.send(data)
            finally:
                await stream.close()
        return SendOutput(sent=True, truncated=truncated)


PLUGIN = Plugin(name="syslog", version=VERSION, nodes=(SendMessage,), connection_types=(SYSLOG,))
