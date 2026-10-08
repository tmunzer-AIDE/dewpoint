# SPDX-License-Identifier: Apache-2.0
"""Guarded SMTP (plugins-3 D20), against a local server only: `smtplib` in a thread over a socket to the address the
guard vetted, the certificate checked against the configured name; STARTTLS required in its mode, implicit TLS in its
own, plaintext only to an allowlisted address and never with a password; PLAIN, else LOGIN, only once TLS is up.

Nothing can be delivered until the payload is written: a refusal before it is the server's, nothing sent. After it, a
250 is sent, a 4yz or 5yz the server's definite refusal (RFC 5321 §4.2.5), and a connection lost without an answer is
`MaybeSentError`. A message the runtime wouldn't put on the wire whole (a bare CR or LF, a NUL, a line past 1000
octets) is refused before connecting, as are recipients or a sender of another form."""

import asyncio
import concurrent.futures
import dataclasses
import socket
import time
from typing import Any

import pytest

from dewpoint.core.egress.guard import (
    EgressRefusedError,
    InvalidRequestError,
    MaybeSentError,
    NotSentError,
    TlsVerificationError,
)
from dewpoint.core.egress.smtp import (
    AuthUnavailableError,
    GuardedSmtp,
    SmtpLimits,
    SmtpRefusedError,
    SmtpTarget,
    TlsUnavailableError,
)
from tests.support.netfakes import TENANT, guard, tls
from tests.support.smtpfakes import Script, serve_smtp

NAMES = ("mail.test",)
MESSAGE = (b"From: alerts@example.com\r\nTo: ops@example.com\r\nSubject: Disk full\r\n\r\nDisk full on db-1\r\n"
           b".hidden dot line\r\n")  # fmt: skip


def target(port: int, security: str = "starttls", **changes: Any) -> SmtpTarget:
    values: dict[str, Any] = {"host": "mail.test", "port": port, "security": security,
                                 "sender": "alerts@example.com", "username": "ops", "password": "pa55-word",
                                 "ehlo_name": "example.com", **changes}  # fmt: skip
    return SmtpTarget(**values)


def smtp(answers: dict[str, list[str]] | None = None, limits: SmtpLimits | None = None) -> GuardedSmtp:
    return GuardedSmtp(guard(dict(answers or {"mail.test": ["127.0.0.1"]})), TENANT,  # type: ignore[arg-type]
                       ssl_context=tls(NAMES).client_context(), limits=limits or SmtpLimits())  # fmt: skip


async def test_starttls_then_plain_auth_then_the_message() -> None:
    async with serve_smtp() as server:
        refused = await smtp().send(target(server.port), ["ops@example.com", "dba@example.com"], MESSAGE)
    assert refused == []
    [got] = server.sessions
    assert got.ehlo == ["example.com", "example.com"]  # the sender's domain, again after TLS
    assert got.logins == [("PLAIN", "ops", "pa55-word")]
    tls_at = dict(got.commands)
    assert tls_at["STARTTLS"] is False and tls_at["AUTH"] is True and tls_at["MAIL"] is True
    assert got.mail == [f"FROM:<alerts@example.com> size={len(MESSAGE)}"]
    assert got.rcpt == ["ops@example.com", "dba@example.com"]
    assert got.payload == MESSAGE.replace(b"\r\n.hidden", b"\r\n..hidden")  # dot-stuffed
    assert got.quit


async def test_implicit_tls_speaks_tls_from_the_first_byte() -> None:
    async with serve_smtp(Script(extensions=("AUTH PLAIN",)), implicit_tls=True) as server:
        assert await smtp().send(target(server.port, "tls"), ["ops@example.com"], MESSAGE) == []
    [got] = server.sessions
    assert all(up for _, up in got.commands) and "STARTTLS" not in dict(got.commands)


async def test_plaintext_to_an_allowlisted_address_without_a_login() -> None:
    async with serve_smtp(Script(extensions=())) as server:
        assert await smtp().send(target(server.port, "none", username=None, password=None), ["ops@example.com"],
                                 MESSAGE) == []  # fmt: skip
    assert server.sessions[0].logins == [] and server.sessions[0].payload == MESSAGE.replace(b"\n.h", b"\n..h")


async def test_plaintext_needs_an_allowlist_entry() -> None:
    with pytest.raises(EgressRefusedError):
        await smtp({"mail.test": ["93.184.216.34"]}).send(target(25, "none", username=None, password=None),
                                                         ["ops@example.com"], MESSAGE)  # fmt: skip


async def test_a_password_is_never_sent_without_tls() -> None:
    async with serve_smtp() as server:
        with pytest.raises(InvalidRequestError):
            await smtp().send(target(server.port, "none"), ["ops@example.com"], MESSAGE)
    assert server.sessions == []  # refused before connecting


async def test_starttls_not_offered_sends_nothing_more() -> None:
    async with serve_smtp(Script(extensions=("AUTH PLAIN",))) as server:
        with pytest.raises(TlsUnavailableError):
            await smtp().send(target(server.port), ["ops@example.com"], MESSAGE)
    [got] = server.sessions
    assert [verb for verb, _ in got.commands if verb not in ("EHLO", "QUIT")] == [] and got.logins == []


async def test_starttls_refused_is_the_servers_refusal() -> None:
    async with serve_smtp(Script(starttls=454)) as server:
        with pytest.raises(SmtpRefusedError) as raised:
            await smtp().send(target(server.port), ["ops@example.com"], MESSAGE)
    assert (raised.value.stage, raised.value.reply) == ("starttls", 454)
    assert server.sessions[0].logins == [] and server.sessions[0].mail == []


@pytest.mark.parametrize(("security", "implicit"), [("starttls", False), ("tls", True)])
async def test_a_certificate_for_another_name_is_refused(security: str, implicit: bool) -> None:
    async with serve_smtp(Script(names=("other.test",)), implicit_tls=implicit) as server:
        with pytest.raises(TlsVerificationError):
            await smtp().send(target(server.port, security), ["ops@example.com"], MESSAGE)
    assert all(got.logins == [] and got.mail == [] for got in server.sessions)


async def test_login_when_plain_isnt_offered() -> None:
    async with serve_smtp(Script(extensions=("STARTTLS", "AUTH LOGIN"))) as server:
        assert await smtp().send(target(server.port), ["ops@example.com"], MESSAGE) == []
    assert server.sessions[0].logins == [("LOGIN", "ops", "pa55-word")]


@pytest.mark.parametrize("extensions", [("STARTTLS", "AUTH CRAM-MD5"), ("STARTTLS",)])
async def test_no_usable_mechanism_signs_in_nowhere(extensions: tuple[str, ...]) -> None:
    async with serve_smtp(Script(extensions=extensions)) as server:
        with pytest.raises(AuthUnavailableError):
            await smtp().send(target(server.port), ["ops@example.com"], MESSAGE)
    assert server.sessions[0].mail == []


async def test_wrong_credentials_are_the_servers_refusal() -> None:
    async with serve_smtp(Script(credentials=("ops", "other"))) as server:
        with pytest.raises(SmtpRefusedError) as raised:
            await smtp().send(target(server.port), ["ops@example.com"], MESSAGE)
    assert (raised.value.stage, raised.value.reply) == ("auth", 535) and server.sessions[0].mail == []


@pytest.mark.parametrize(
    ("script", "stage", "reply"),
    [
        (Script(greeting=554), "connect", 554),
        (Script(greeting=421), "connect", 421),
        (Script(mail=550), "mail", 550),
        (Script(rcpt={"ops@example.com": 550, "dba@example.com": 553}), "rcpt", 550),
        (Script(rcpt={"ops@example.com": 550, "dba@example.com": 450}), "rcpt", 450),  # transient wins: retry
        (Script(rcpt={"ops@example.com": 421}), "rcpt", 421),
        (Script(data=554), "data", 554),
        (Script(end=451), "end", 451),
        (Script(end=554), "end", 554),
    ],
)
async def test_a_definite_refusal_names_its_stage_and_reply(script: Script, stage: str, reply: int) -> None:
    async with serve_smtp(script) as server:
        with pytest.raises(SmtpRefusedError) as raised:
            await smtp().send(target(server.port), ["ops@example.com", "dba@example.com"], MESSAGE)
    assert (raised.value.stage, raised.value.reply) == (stage, reply)
    if stage in ("connect", "mail", "rcpt", "data"):
        assert server.sessions[0].payload is None  # refused before the payload


async def test_some_recipients_refused_are_returned_and_the_rest_get_it() -> None:
    async with serve_smtp(Script(rcpt={"dba@example.com": 550})) as server:
        refused = await smtp().send(target(server.port), ["ops@example.com", "dba@example.com"], MESSAGE)
    assert refused == ["dba@example.com"] and server.sessions[0].payload is not None


async def test_a_connection_lost_after_the_payload_may_have_delivered() -> None:
    async with serve_smtp(Script(end=None)) as server:
        with pytest.raises(MaybeSentError):
            await smtp().send(target(server.port), ["ops@example.com"], MESSAGE)
    assert server.sessions[0].payload is not None


async def test_no_answer_to_the_end_within_the_limit_may_have_delivered() -> None:
    async with serve_smtp(Script(end_delay_s=2.0)) as server:
        with pytest.raises(MaybeSentError):
            await smtp(limits=SmtpLimits(operation_s=0.5)).send(target(server.port), ["ops@example.com"], MESSAGE)


async def test_no_server_means_nothing_was_sent() -> None:
    async with serve_smtp() as server:
        port = server.port
    with pytest.raises(NotSentError):
        await smtp().send(target(port), ["ops@example.com"], MESSAGE)


@pytest.mark.parametrize(
    ("recipients", "message", "changes"),
    [
        (["ops@example.com"], MESSAGE.replace(b"\r\n", b"\n"), {}),  # bare LF
        (["ops@example.com"], MESSAGE + b"x\rBcc: y\r\n", {}),  # bare CR
        (["ops@example.com"], MESSAGE + b"\0\r\n", {}),
        (["ops@example.com"], MESSAGE + b"x" * 999 + b"\r\n", {}),  # 1001 octets with CRLF
        (["ops@example.com"], b"x" * 11 * 1024 * 1024, {}),
        (["ops@example.com"], b"", {}),
        ([], MESSAGE, {}),
        ([f"u{i}@example.com" for i in range(51)], MESSAGE, {}),
        (["ops@example.com\r\nRCPT TO:<x@evil.example.com>"], MESSAGE, {}),
        (["<ops@example.com>"], MESSAGE, {}),
        (["ops@example.com", "ops@example.com"], MESSAGE, {}),  # a duplicate would muddle what was refused
        (["ops@example.com"], MESSAGE, {"sender": "alerts@example.com>\r\nRCPT TO:<x@evil.example.com"}),
        (["ops@example.com"], MESSAGE, {"host": "Mail.Test"}),
        (["ops@example.com"], MESSAGE, {"port": 0}),
        (["ops@example.com"], MESSAGE, {"security": "maybe"}),
        (["ops@example.com"], MESSAGE, {"password": "pässword"}),  # smtplib signs in with ASCII only
        (["ops@example.com"], MESSAGE, {"username": "ops\r\n"}),
        (["ops@example.com"], MESSAGE, {"password": None}),  # a username needs its password
    ],
)
async def test_what_the_runtime_wouldnt_send_whole_is_refused_before_connecting(
    recipients: list[str], message: bytes, changes: dict[str, Any]
) -> None:
    async with serve_smtp() as server:
        with pytest.raises(InvalidRequestError):
            await smtp().send(dataclasses.replace(target(server.port), **changes), recipients, message)
    assert server.sessions == []


async def test_a_probe_signs_in_and_quits_without_mail() -> None:
    async with serve_smtp() as server:
        await smtp().probe(target(server.port))
    [got] = server.sessions
    assert got.logins == [("PLAIN", "ops", "pa55-word")] and got.mail == [] and got.payload is None and got.quit


async def test_a_probe_with_wrong_credentials_is_refused() -> None:
    async with serve_smtp(Script(credentials=("ops", "other"))) as server:
        with pytest.raises(SmtpRefusedError) as raised:
            await smtp().probe(target(server.port))
    assert (raised.value.stage, raised.value.reply) == ("auth", 535)


async def test_a_cancelled_send_closes_its_socket() -> None:
    async with serve_smtp(Script(end_delay_s=30.0)) as server:
        task = asyncio.create_task(smtp().send(target(server.port), ["ops@example.com"], MESSAGE))
        for _ in range(1000):  # until the payload reached the server
            if server.sessions and server.sessions[0].payload is not None:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        for _ in range(300):  # the server sees the connection closed, not left to its 30 s
            if server.sessions[0].client_closed:
                break
            await asyncio.sleep(0.01)
    assert server.sessions[0].client_closed


@pytest.mark.parametrize(
    "script",
    [
        Script(greeting_flood=100_000),  # past 100 lines
        Script(greeting_flood=20, flood_width=8000),  # under 100 lines, past 64 KiB
        Script(extensions=("STARTTLS", *(f"X{i}" for i in range(150)))),
    ],
)
async def test_a_reply_past_its_bounds_is_refused_having_sent_nothing(script: Script) -> None:
    """A reply is at most 100 lines and 64 KiB (the review's H1: a server flooding continuation lines grew the worker
    without bound)."""
    async with serve_smtp(script) as server:
        with pytest.raises(NotSentError):
            await asyncio.wait_for(smtp().send(target(server.port), ["ops@example.com"], MESSAGE), 10)
    assert all(got.mail == [] for got in server.sessions)


async def test_an_end_reply_past_its_bounds_may_have_delivered() -> None:
    async with serve_smtp(Script(end_flood=100_000)) as server:
        with pytest.raises(MaybeSentError):
            await asyncio.wait_for(smtp().send(target(server.port), ["ops@example.com"], MESSAGE), 10)


async def test_a_session_has_a_deadline_however_slowly_the_server_drips() -> None:
    """Each read within `operation_s` doesn't keep a session past `session_s` (the review's H1)."""
    async with serve_smtp(Script(drip_s=0.05)) as server:
        started = asyncio.get_running_loop().time()
        with pytest.raises(NotSentError):
            await smtp(limits=SmtpLimits(operation_s=1.0, session_s=0.5)).send(target(server.port),
                                                                              ["ops@example.com"], MESSAGE)  # fmt: skip
        assert asyncio.get_running_loop().time() - started < 3
    assert server.sessions[0].mail == []


async def test_a_deadline_after_the_payload_may_have_delivered() -> None:
    async with serve_smtp(Script(end_delay_s=5.0)) as server:
        with pytest.raises(MaybeSentError):
            await smtp(limits=SmtpLimits(session_s=0.5)).send(target(server.port), ["ops@example.com"], MESSAGE)


async def test_sessions_never_take_the_loops_default_executor() -> None:
    """The guard resolves names on the default executor: a slow server's session must not hold it (the review's H1)."""
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1))
    async with serve_smtp(Script(drip_s=0.05)) as server:
        tasks = [asyncio.create_task(smtp(limits=SmtpLimits(session_s=3.0)).send(target(server.port),
                                                                                 ["ops@example.com"], MESSAGE))
                 for _ in range(2)]  # fmt: skip
        await asyncio.sleep(0.3)
        assert await asyncio.wait_for(loop.run_in_executor(None, lambda: 7), 1.0) == 7
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("fails", [False, True])  # the first address connects slowly, or fails slowly
async def test_a_send_cancelled_while_connecting_never_reaches_the_server(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    """The review's M1: a cancel during `create_connection` closed nothing, and the session went on to deliver, or to
    the next address."""
    real, calls = socket.create_connection, []

    def slow(*args: Any, **kwargs: Any) -> socket.socket:
        calls.append(args)
        time.sleep(0.6)
        if fails and len(calls) == 1:
            raise ConnectionRefusedError()
        return real(*args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", slow)
    async with serve_smtp() as server:
        task = asyncio.create_task(smtp({"mail.test": ["127.0.0.1", "127.0.0.1"]}).send(
            target(server.port), ["ops@example.com"], MESSAGE))  # fmt: skip
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(1.0)  # the thread's connect ends meanwhile
    assert len(calls) == 1  # the next address is never tried
    assert all(got.mail == [] and got.commands == [] for got in server.sessions)


async def test_closing_aborts_a_send_left_running() -> None:
    """A send the node didn't await ends with its attempt (the review's M1)."""
    async with serve_smtp(Script(end_delay_s=30.0)) as server:
        mail = smtp()
        task = asyncio.create_task(mail.send(target(server.port), ["ops@example.com"], MESSAGE))
        for _ in range(1000):
            if server.sessions and server.sessions[0].payload is not None:
                break
            await asyncio.sleep(0.01)
        await mail.aclose()
        with pytest.raises(MaybeSentError):
            await asyncio.wait_for(task, 5)
    assert server.sessions[0].client_closed


async def test_a_session_stuck_connecting_past_its_deadline_sent_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """An abort can't interrupt a connect: past the deadline the send fails having sent nothing, without waiting."""
    real = socket.create_connection

    def stuck(*args: Any, **kwargs: Any) -> socket.socket:
        time.sleep(2.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", stuck)
    async with serve_smtp() as server:
        started = asyncio.get_running_loop().time()
        with pytest.raises(NotSentError):
            await smtp(limits=SmtpLimits(session_s=0.3, connect_s=0.3)).send(target(server.port), ["ops@example.com"],
                                                                            MESSAGE)  # fmt: skip
        assert asyncio.get_running_loop().time() - started < 1.5
        await asyncio.sleep(2.0)  # the thread ends, aborted
    assert all(got.commands == [] for got in server.sessions)


def test_a_targets_repr_never_shows_its_password() -> None:
    assert "pa55-word" not in repr(target(25)) and "pa55-word" not in str(target(25))
