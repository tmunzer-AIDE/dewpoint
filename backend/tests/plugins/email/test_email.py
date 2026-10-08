# SPDX-License-Identifier: Apache-2.0
"""Email (plugins-3 3c-2, D20): an `email` connection type declaring its SMTP server (host, port, security, sender,
an optional sign-in), verified by a probe that never sends MAIL, and `email.send_message`, which renders the message
model as a plain-text email (From, To, Subject, Date, a Message-ID on the sender's domain, `Auto-Submitted:
auto-generated`; the body quoted-printable, so every line is ASCII and short) and sends it through the connection's
server to its recipients only; refused recipients are named, the rest got it."""

import email
import email.policy
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.email import EMAIL, PLUGIN, SendMessage, render, verify
from dewpoint.sdk import (
    AuthUnavailable,
    EgressRefused,
    FatalError,
    MailRefused,
    NotSent,
    SideEffect,
    TlsUnavailable,
    TlsVerificationFailed,
)
from dewpoint.sdk.messages import Message
from tests.plugins.mist.fakes import FakeStep

CONFIG = {"host": "smtp.example.com", "port": 587, "security": "starttls", "from_address": "alerts@example.com",
          "from_name": "Dewpoint alerts", "username": "alerts@example.com"}  # fmt: skip


@dataclass
class FakeSmtp:
    refused: list[str] = field(default_factory=list)
    error: Exception | None = None
    sent: list[tuple[list[str], bytes]] = field(default_factory=list)
    probes: int = 0

    async def send(self, recipients: list[str], message: bytes) -> list[str]:
        self.sent.append((list(recipients), message))
        if self.error is not None:
            raise self.error
        return self.refused

    async def probe(self) -> None:
        self.probes += 1
        if self.error is not None:
            raise self.error


@dataclass
class FakeMailConnection:
    smtp: FakeSmtp = field(default_factory=FakeSmtp)
    config: dict[str, Any] = field(default_factory=lambda: dict(CONFIG))
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "email"


def message(**changes: Any) -> Message:
    return Message.model_validate({"text": "Disk full on db-1", **changes})


def parsed(raw: bytes) -> email.message.EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.SMTP)  # type: ignore[return-value]


def test_the_plugin_validates_and_its_node_is_an_ambiguous_send() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert SendMessage.side_effect == SideEffect.AMBIGUOUS and SendMessage.credentials == ("email",)
    manifest = EMAIL.manifest()
    assert manifest["smtp"] == {"host": "host", "port": "port", "security": "security", "sender": "from_address",
                                "username": "username", "password": "password"}  # fmt: skip
    assert manifest["verify"] is True
    [scope] = EMAIL.rate_scopes
    assert (scope.kind, scope.config, scope.capacity, scope.refill_per_s) == ("email.server", ("host",), 5, 1.0)


@pytest.mark.parametrize(
    "changes",
    [{"host": "Smtp.Example.com"}, {"host": "smtp.example.com\n"}, {"host": "smtp"}, {"port": 0},
     {"security": "ssl"}, {"from_address": "alerts@example"}, {"from_address": "Alerts <alerts@example.com>"},
     {"from_name": "a\nBcc: x@example.com"}, {"username": "ops\r\n"}, {"username": "opé"}, {"extra": 1}],
)  # fmt: skip
def test_a_connection_of_another_form_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        EMAIL.Config.model_validate({**CONFIG, **changes})


def test_the_email_is_plain_text_with_the_documented_headers() -> None:
    raw, cut = render(message(title="db-1", fields=[{"label": "Free", "value": "2%"}],
                              links=[{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                              severity="warning"), "alerts@example.com", "Dewpoint alerts",
                      ["ops@example.com", "dba@example.com"])  # fmt: skip
    got = parsed(raw)
    assert got["From"] == "Dewpoint alerts <alerts@example.com>" and got["To"] == "ops@example.com, dba@example.com"
    assert got["Subject"] == "db-1" and got["Auto-Submitted"] == "auto-generated" and got["Date"]
    assert got["Message-ID"].endswith("@example.com>")  # the sender's domain, never this worker's host name
    assert got.get_content_type() == "text/plain" and got["Content-Transfer-Encoding"] == "quoted-printable"
    body = got.get_content().replace("\r\n", "\n")
    assert body == "Disk full on db-1\n\nFree: 2%\n\nRunbook: https://wiki.example.com/disk\n\nSeverity: warning\n"
    assert cut == [] and raw.isascii() and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert max(len(line) for line in raw.split(b"\r\n")) <= 998 and "Bcc" not in got


def test_without_a_title_the_subject_is_the_texts_first_line() -> None:
    got = parsed(render(message(text="Disk full\non db-1"), "alerts@example.com", None, ["ops@example.com"])[0])
    assert got["Subject"] == "Disk full" and got["From"] == "alerts@example.com"


@pytest.mark.parametrize("title", ["a\r\nBcc: evil@example.com", "a\nb", "tab\there", "nul\0here"])
def test_run_data_never_adds_a_header(title: str) -> None:
    raw, _ = render(message(title=title), "alerts@example.com", None, ["ops@example.com"])
    got = parsed(raw)
    assert "Bcc" not in got and "\0" not in str(got["Subject"]) and b"\0" not in raw
    assert [h for h, _ in got.items()].count("Subject") == 1


def test_a_long_title_is_cut_and_marked_and_non_ascii_text_stays_ascii_on_the_wire() -> None:
    raw, cut = render(message(title="é" * 1000, text="日本語 " * 5000), "alerts@example.com", None, ["ops@example.com"])
    got = parsed(raw)
    assert len(got["Subject"]) <= 200 and got["Subject"].endswith("…") and cut == ["title"]
    assert raw.isascii() and got.get_content().startswith("日本語")
    assert max(len(line) for line in raw.split(b"\r\n")) <= 998


async def test_a_send_goes_through_the_connection_to_its_recipients() -> None:
    conn = FakeMailConnection(smtp=FakeSmtp(refused=["dba@example.com"]))
    config = SendMessage.Config.model_validate({"connection": str(conn.id), "text": "hello",
                                                "to": ["ops@example.com", "dba@example.com"]})  # fmt: skip
    out = await SendMessage().run(FakeStep(conn), config)  # type: ignore[arg-type]
    assert out.model_dump() == {"sent": True, "refused": ["dba@example.com"], "truncated": []}
    [(recipients, raw)] = conn.smtp.sent
    assert recipients == ["ops@example.com", "dba@example.com"]
    assert parsed(raw)["From"] == "Dewpoint alerts <alerts@example.com>"  # the connection's sender, never the node's


@pytest.mark.parametrize(
    "to",
    [[], ["ops@example"], ["Ops <ops@example.com>"], ["ops@example.com\r\nRCPT TO:<x@example.com>"],
     [f"u{i}@example.com" for i in range(51)], ["ops@example.com", "ops@example.com"],
     ["=?utf-8?b?Q0VPIDxjZW9AY29ycC5leGFtcGxlPiw=?=@x.example.com"]],
)  # fmt: skip
def test_recipients_of_another_form_are_refused(to: list[str]) -> None:
    with pytest.raises(ValueError):
        SendMessage.Config.model_validate({"connection": str(uuid.uuid4()), "text": "x", "to": to})


async def test_a_refusal_is_the_runtimes_to_classify() -> None:
    conn = FakeMailConnection(smtp=FakeSmtp(error=MailRefused("rcpt", 550)))
    config = SendMessage.Config.model_validate({"connection": str(conn.id), "text": "x", "to": ["ops@example.com"]})
    with pytest.raises(MailRefused):
        await SendMessage().run(FakeStep(conn), config)  # type: ignore[arg-type]


async def test_simulating_renders_and_sends_nothing() -> None:
    conn = FakeMailConnection()
    step = FakeStep(conn)  # type: ignore[arg-type]
    config = SendMessage.Config.model_validate({"connection": str(conn.id), "text": "x", "title": "t" * 300,
                                                "to": ["ops@example.com"]})  # fmt: skip
    out = await SendMessage().simulate(step, config)  # type: ignore[arg-type]
    assert out.model_dump() == {"sent": True, "refused": [], "truncated": ["title"]}
    assert conn.smtp.sent == [] and step.opened == []


@pytest.mark.parametrize(
    ("error", "detail"),
    [(None, "ok"), (MailRefused("auth", 535), "auth_failed"), (MailRefused("connect", 554), "refused"),
     (TlsUnavailable(), "tls_unavailable"), (AuthUnavailable(), "auth_unavailable"),
     (TlsVerificationFailed(), "tls_verification_failed"), (EgressRefused(), "egress_refused"),
     (NotSent(), "unreachable")],
)  # fmt: skip
async def test_verify_probes_and_names_what_failed(error: Exception | None, detail: str) -> None:
    conn = FakeMailConnection(smtp=FakeSmtp(error=error))
    result = await verify(None, conn)  # type: ignore[arg-type]
    assert (result.ok, result.detail) == (error is None, detail) and conn.smtp.probes == 1 and conn.smtp.sent == []


def test_the_to_header_names_exactly_the_envelopes_recipients() -> None:
    to = ["ops@example.com", "first.last+tag@mail.example.co.uk", "o'brien@example.com"]
    got = parsed(render(message(), "alerts@example.com", None, to)[0])
    assert [a.addr_spec for a in got["To"].addresses] == to


def test_an_encoded_word_recipient_never_reaches_the_header_even_past_the_check() -> None:
    """The To header is built from addresses, never parsed from a string a header would decode (the review's L3)."""
    with pytest.raises(ValueError):
        render(message(), "alerts@example.com", None, ["=?utf-8?b?Q0VPIDxjZW9AY29ycC5leGFtcGxlPiw=?=@x.example.com"])


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"])
def test_every_line_break_in_a_title_becomes_a_space(separator: str) -> None:
    for changes, subject in (({"title": f"a{separator}b"}, "a b"), ({"text": f"a{separator}b"}, "a")):  # first line
        got = parsed(render(message(**changes), "alerts@example.com", f"n{separator}m", ["ops@example.com"])[0])
        assert got["Subject"] == subject and got["From"].addresses[0].display_name == "n m"


async def test_a_message_that_wont_render_fails_having_sent_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any rendering failure is the node's own, before the connection sends anything: fatal, never unknown."""
    import dewpoint.plugins.email as plugin

    def broken(*args: Any) -> Any:
        raise ValueError("header")

    monkeypatch.setattr(plugin, "render", broken)
    conn = FakeMailConnection()
    config = SendMessage.Config.model_validate({"connection": str(conn.id), "text": "x", "to": ["ops@example.com"]})
    with pytest.raises(FatalError) as raised:
        await SendMessage().run(FakeStep(conn), config)  # type: ignore[arg-type]
    assert raised.value.code == "email.invalid_message" and conn.smtp.sent == []
