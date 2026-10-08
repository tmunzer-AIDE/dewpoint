# SPDX-License-Identifier: Apache-2.0
"""Email (plugins-3 3c-2, D20): a message sent through an SMTP server, which the runtime speaks.

The connection declares its server (`SmtpServer`): a host name, a port, its security (`starttls`, the submission
port's, RFC 6409; `tls`, implicit on 465, RFC 8314; or `none`, only to an allowlisted address), the sender's address
and name, and optionally a username and password, with which the runtime signs in once TLS is up; the plugin never
holds the password. Verify probes the server (connect, greet, secure, sign in, QUIT), never sending MAIL. One quota
scope a server host, bursts of 5, then 1 a second: no quota is documented.

The message is plain text, UTF-8 and quoted-printable, so every line on the wire is ASCII and short; its headers are
From (the connection's sender, never the node's), To, Subject (the title, else the text's first line, at most 200
characters, control characters as spaces), Date, a Message-ID on the sender's domain, and `Auto-Submitted:
auto-generated` (RFC 3834: automatic responders don't answer it). The body is the text, the fields as `label: value`,
the links as `label: url` and the severity. Recipients are `to` only, 1 to 50 addresses, every recipient seeing the
others.

A send is ambiguous (D20): the runtime decides its outcome from the server's answers; the recipients a server refused
while taking the message for the others are named in `refused`."""

import email.policy
import email.utils
import re
import uuid
from datetime import UTC, datetime
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from dewpoint.sdk import (
    MAIL_ADDRESS,
    AuthUnavailable,
    CallContext,
    Connection,
    ConnectionType,
    EgressRefused,
    FatalError,
    MailRefused,
    Node,
    Plugin,
    RateScope,
    SideEffect,
    SmtpServer,
    StepContext,
    TlsUnavailable,
    TlsVerificationFailed,
    TransportError,
    VerifyResult,
    connection_field,
)
from dewpoint.sdk.connections import HOST_RE
from dewpoint.sdk.messages import Message, cut

SUBJECT_MAX = 200
CONTROL = re.compile(r"[\x00-\x1f\x7f]")  # CR and LF among them: a header is one line, NUL never on the wire
USERNAME = re.compile(r"[\x20-\x7e]{1,256}")  # the runtime signs in with ASCII only


class EmailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(max_length=253, title="SMTP server", description="Its host name, e.g. smtp.example.com.")
    port: int = Field(ge=1, le=65535, title="Port", description="587 for STARTTLS, 465 for TLS.")
    security: Literal["starttls", "tls", "none"] = Field(
        title="Security", description="starttls (port 587), tls (port 465), or none: only to an allowlisted server."
    )
    from_address: str = Field(max_length=254, title="Sender address")
    from_name: str | None = Field(None, max_length=100, title="Sender name")
    username: str | None = Field(None, max_length=256, title="Username")

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        if not HOST_RE.fullmatch(value):
            raise ValueError("a lowercase host name of two or more labels")
        return value

    @field_validator("from_address")
    @classmethod
    def _address(cls, value: str) -> str:
        if not MAIL_ADDRESS.fullmatch(value):
            raise ValueError("a plain address, such as alerts@example.com")
        return value

    @field_validator("from_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and CONTROL.search(value):
            raise ValueError("one line of text")
        return value

    @field_validator("username")
    @classmethod
    def _username(cls, value: str | None) -> str | None:
        if value is not None and not USERNAME.fullmatch(value):
            raise ValueError("printable ASCII")
        return value


class EmailSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(SecretStr(""), max_length=1024, title="Password")


async def verify(ctx: CallContext, connection: Connection) -> VerifyResult:
    """The server and the credentials, probed: connect, greet, secure, sign in, QUIT; never MAIL."""
    try:
        await connection.smtp.probe()
    except MailRefused as e:
        return VerifyResult(False, "auth_failed" if e.stage == "auth" else "refused")
    except TlsUnavailable:
        return VerifyResult(False, "tls_unavailable")
    except AuthUnavailable:
        return VerifyResult(False, "auth_unavailable")
    except TlsVerificationFailed:
        return VerifyResult(False, "tls_verification_failed")
    except EgressRefused:
        return VerifyResult(False, "egress_refused")
    except TransportError:
        return VerifyResult(False, "unreachable")
    return VerifyResult(True, "ok")


EMAIL = ConnectionType(
    key="email",
    label="Email (SMTP)",
    Config=EmailConfig,
    Secret=EmailSecret,
    smtp=SmtpServer(
        host="host",
        port="port",
        security="security",
        sender="from_address",
        username="username",
        password="password",  # noqa: S106 - a field's name
    ),
    rate_scopes=(RateScope("email.server", config=("host",), capacity=5, refill_per_s=1.0),),
    verify=verify,
)


def _line(text: str) -> str:
    """One header line: every break `str.splitlines()` knows (U+2028 among them), then any control, as a space; a
    header value holding one would be refused (the 3c-2 review's L6)."""
    return CONTROL.sub(" ", " ".join(text.splitlines())).strip()


def render(message: Message, sender: str, sender_name: str | None, to: list[str]) -> tuple[bytes, list[str]]:
    """The message as an email on the wire (CRLF, ASCII), and the names of the values it cut."""
    truncated: list[str] = []
    if message.title:
        subject, was_cut = cut(_line(message.title), SUBJECT_MAX)
        if was_cut:
            truncated.append("title")
    else:  # the whole text is in the body: its first line, however cut, loses nothing
        subject = cut(_line(message.text.splitlines()[0] if message.text.strip() else message.text), SUBJECT_MAX)[0]
    parts = [message.text]
    if message.fields:
        parts.append("\n".join(f"{f.label}: {f.value}" for f in message.fields))
    if message.links:
        parts.append("\n".join(f"{link.label}: {link.url}" for link in message.links))
    parts.append(f"Severity: {message.severity.value}")
    mail = EmailMessage(policy=email.policy.SMTP)
    mail["From"] = Address(display_name=_line(sender_name or ""), addr_spec=sender)
    mail["To"] = [Address(addr_spec=r) for r in to]  # the envelope's recipients exactly, never a parsed string
    mail["Subject"] = subject
    mail["Date"] = email.utils.format_datetime(datetime.now(UTC))
    mail["Message-ID"] = email.utils.make_msgid(domain=sender.rsplit("@", 1)[1].lower())  # never this host's name
    mail["Auto-Submitted"] = "auto-generated"
    mail.set_content("\n\n".join(parts) + "\n", charset="utf-8", cte="quoted-printable")
    return mail.as_bytes(), truncated


class SendConfig(Message):
    connection: uuid.UUID = connection_field("email")
    to: list[str] = Field(min_length=1, max_length=50, title="To", description="1 to 50 addresses.")

    @field_validator("to")
    @classmethod
    def _recipients(cls, value: list[str]) -> list[str]:
        if not all(MAIL_ADDRESS.fullmatch(address) for address in value):
            raise ValueError("plain addresses, such as ops@example.com")
        if len({address.lower() for address in value}) != len(value):
            raise ValueError("each address once")
        return value


def _rendered(config: "SendConfig", sender: str, name: str | None) -> tuple[bytes, list[str]]:
    """The email, or the node's own failure before anything is sent: never an unknown outcome (the review's L6)."""
    try:
        return render(config, sender, name, config.to)
    except (ValueError, TypeError):
        raise FatalError("email.invalid_message", "The message can't be written as an email.") from None


class SendOutput(BaseModel):
    sent: bool
    refused: list[str]
    truncated: list[str]


class SendMessage(Node):
    """Emails a message through the connection's SMTP server."""

    type = "email.send_message"
    version = 1
    title = "Send an email"
    description = (
        "Emails a message as plain text through an SMTP server, from the connection's sender. A send that fails after "
        "the server may have taken it is never retried."
    )
    Config = SendConfig
    Output = SendOutput
    credentials = ("email",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        _, truncated = _rendered(config, "alerts@example.invalid", None)  # the connection isn't opened
        return SendOutput(sent=True, refused=[], truncated=truncated)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        connection = await ctx.connection(config.connection)
        sender, name = connection.config["from_address"], connection.config.get("from_name")
        raw, truncated = _rendered(config, sender, name)
        refused = await connection.smtp.send(config.to, raw)
        return SendOutput(sent=True, refused=refused, truncated=truncated)


PLUGIN = Plugin(name="email", version="1.0.0", nodes=(SendMessage,), connection_types=(EMAIL,))
