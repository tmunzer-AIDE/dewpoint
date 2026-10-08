# SPDX-License-Identifier: Apache-2.0
"""Guarded SMTP (plugins-3 D20): stdlib `smtplib` in a worker thread, over a socket connected to an address the guard
vetted; the session wraps it in TLS itself, the certificate checked against the configured name (`smtplib`'s own
STARTTLS would check `_host`, which it sets only in its constructor). `starttls` requires STARTTLS (RFC 3207 names a
missing one an attack), `tls` speaks TLS from the first byte (RFC 8314), `none` reaches only an allowlisted address
(D7) and never signs in; TLS is 1.2 or later, as the HTTP client's. Signing in uses PLAIN, else LOGIN, never CRAM-MD5
(`smtplib`'s first choice), and only once TLS is up (RFC 4954).

Nothing can be delivered until the payload is written (RFC 5321 §3.3: the end of data "tells the SMTP server to now
process the stored recipients"). A failure before it sent nothing: a 4yz or 5yz is the server's refusal, anything
else `NotSentError`. After it, a 250 is sent; a 4yz or 5yz is a definite refusal, after which the server "MUST NOT
make a subsequent attempt to deliver" (§4.2.5); any other answer, a connection lost or a timeout without one is
`MaybeSentError` (§4.5.3.2.6 warns of duplicates).

A server can't hold the worker: a reply is at most 100 lines and 64 KiB, a session at most `session_s` (aborted
past it), and sessions run on a pool of their own, never the event loop's default executor, which resolves names
for every guarded request. Cancelling a send, or closing the attempt, aborts its session wherever it is: before an
address is tried, after connecting, before each command.

The message goes on the wire whole or not at all: a bare CR or LF (the way to smuggle a second message past a
server), a NUL or a line past 998 octets is refused before connecting, as is a sender, a recipient or a credential of
another form. Failures name no host, address or server text; nothing is logged."""

import asyncio
import re
import smtplib
import socket
import ssl
import threading
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

from dewpoint.core.egress.addresses import Address
from dewpoint.core.egress.guard import (
    Guard,
    InvalidRequestError,
    MaybeSentError,
    NotSentError,
    TlsVerificationError,
)
from dewpoint.sdk.connections import HOST_RE, MAIL_ADDRESS, SMTP_SECURITY

MAX_RECIPIENTS = 50  # under RFC 5321's 100 a message (§4.5.3.1.8)
MAX_LINE = 998  # octets before the CRLF (RFC 5322 §2.1.1; RFC 5321 §4.5.3.1.6 counts 1000 with it)
CREDENTIAL = re.compile(r"[\x20-\x7e]{1,1024}")  # `smtplib` signs in with ASCII only
MECHANISMS = ("PLAIN", "LOGIN")
MAX_REPLY_LINE, MAX_REPLY_LINES, MAX_REPLY = 8192, 100, 64 * 1024  # a reply's line, lines and octets
POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dewpoint-smtp")  # the process's mail sessions
_STUFF = re.compile(rb"(?m)^\.")  # a line's leading dot doubled (RFC 5321 §4.5.2); lines end in CRLF only


@dataclass(frozen=True)
class SmtpTarget:
    """One server and sender, as a connection declares them; `ehlo_name` is what EHLO names (the sender's domain,
    never this worker's host name)."""

    host: str
    port: int
    security: str
    sender: str
    username: str | None
    password: str | None = field(repr=False)
    ehlo_name: str = ""


@dataclass(frozen=True)
class SmtpLimits:
    connect_s: float = 5.0
    operation_s: float = 60.0  # each blocking read or write, the answer to the message's end included
    session_s: float = 120.0  # a whole session, connect to QUIT
    max_message: int = 10 * 1024 * 1024


class SmtpRefusedError(Exception):
    """The server's definite refusal at `stage` with `reply` (4yz transient, 5yz permanent): nothing was delivered."""

    def __init__(self, stage: str, reply: int) -> None:
        super().__init__(stage, reply)
        self.stage, self.reply = stage, reply


class TlsUnavailableError(Exception):
    """STARTTLS is required and the server didn't offer it: nothing more was sent."""


class AuthUnavailableError(Exception):
    """The server offered no mechanism the runtime signs in with: nothing more was sent."""


class ReplyTooLargeError(OSError):
    """A reply past its bounds: the connection is closed, as on any broken exchange."""


class AbortedError(OSError):
    """The session was aborted: cancelled, closed with its attempt, or past its deadline."""


def _refusal(stage: str, reply: int) -> Exception:
    """A reply that isn't the one expected: the server's refusal when it's a 4yz or 5yz, else a broken exchange."""
    return SmtpRefusedError(stage, reply) if 400 <= reply < 600 else NotSentError("smtp")


def _checked(target: SmtpTarget, recipients: Sequence[str] | None, message: bytes | None, limits: SmtpLimits) -> None:
    host_ok = isinstance(target.host, str) and HOST_RE.fullmatch(target.host) is not None
    port_ok = type(target.port) is int and 1 <= target.port <= 65535
    ehlo_ok = isinstance(target.ehlo_name, str) and HOST_RE.fullmatch(target.ehlo_name) is not None
    sender_ok = isinstance(target.sender, str) and MAIL_ADDRESS.fullmatch(target.sender) is not None
    if not (host_ok and port_ok and ehlo_ok and sender_ok and target.security in SMTP_SECURITY):
        raise InvalidRequestError("smtp")
    login = (target.username, target.password)
    if login != (None, None):
        if not all(isinstance(v, str) and CREDENTIAL.fullmatch(v) for v in login):
            raise InvalidRequestError("smtp")
        if target.security == "none":  # a password never crosses the network unencrypted (RFC 4954 §4)
            raise InvalidRequestError("smtp")
    if recipients is not None:
        if not 1 <= len(recipients) <= MAX_RECIPIENTS:
            raise InvalidRequestError("smtp")
        if not all(isinstance(r, str) and MAIL_ADDRESS.fullmatch(r) for r in recipients):
            raise InvalidRequestError("smtp")
        if len({r.lower() for r in recipients}) != len(recipients):  # the review's L5: what was refused is by address
            raise InvalidRequestError("smtp")
    if message is not None:
        if not isinstance(message, bytes) or not 0 < len(message) <= limits.max_message or b"\0" in message:
            raise InvalidRequestError("smtp")
        lines = message.split(b"\r\n")
        if any(b"\r" in line or b"\n" in line or len(line) > MAX_LINE for line in lines):
            raise InvalidRequestError("smtp")


class _Pinned(smtplib.SMTP):
    """`smtplib` on a socket already connected to a vetted address."""

    def __init__(self, sock: socket.socket, target: SmtpTarget, limits: SmtpLimits) -> None:
        super().__init__(local_hostname=target.ehlo_name, timeout=limits.operation_s)  # never `socket.getfqdn()`
        self._pinned = sock

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return self._pinned

    def getreply(self) -> tuple[int, bytes]:
        """A reply, as `smtplib`'s, but bounded: `smtplib` reads continuation lines without end (the review's H1)."""
        if self.file is None:
            if self.sock is None:
                raise smtplib.SMTPServerDisconnected("closed")
            self.file = self.sock.makefile("rb")
        lines: list[bytes] = []
        total = 0
        while True:
            line = self.file.readline(MAX_REPLY_LINE + 1)
            if not line:
                self.close()
                raise smtplib.SMTPServerDisconnected("closed")
            total += len(line)
            if len(line) > MAX_REPLY_LINE or total > MAX_REPLY or len(lines) >= MAX_REPLY_LINES:
                self.close()
                raise ReplyTooLargeError()
            lines.append(line[4:].strip(b" \t\r\n"))
            try:
                code = int(line[:3])
            except ValueError:
                return -1, b"\n".join(lines)
            if line[3:4] != b"-":
                return code, b"\n".join(lines)


class _Session:
    """One connection, start to QUIT, run in a worker thread; `abort` closes its socket from the event loop."""

    def __init__(self, target: SmtpTarget, context: ssl.SSLContext, limits: SmtpLimits) -> None:
        self.target, self.context, self.limits = target, context, limits
        self.sock: socket.socket | None = None
        self.aborted = threading.Event()
        self.payload = False  # once the payload's first byte may have left

    def _go_on(self) -> None:
        """While connecting, where no socket is open yet for `abort` to close (the review's M1); once one is, closing
        it ends the session at its next read or write."""
        if self.aborted.is_set():
            raise AbortedError()

    def abort(self) -> None:
        """From any thread: the session stops at its next step. Its socket is shut down at the descriptor, which wakes
        a read or write blocked on it (a TLS handshake's included) and fails every later one; never closed here: a
        descriptor closed under another thread's blocked call may not wake it, and its number may be reused by
        another socket meanwhile. The session's own thread closes it."""
        self.aborted.set()
        sock = self.sock
        if sock is not None:
            try:
                socket.socket.shutdown(sock, socket.SHUT_RDWR)  # the descriptor's, not `SSLSocket.shutdown`, which
            except OSError:  # drops the TLS object another thread may be using
                pass

    def _close(self) -> None:
        """In the session's own thread only."""
        sock = self.sock
        if sock is not None:
            try:
                socket.socket.shutdown(sock, socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _tls(self, raw: socket.socket) -> ssl.SSLSocket:
        """TLS on `raw`, abort-safe: `wrap_socket` detaches `raw`, so the TLS socket is the session's before its
        handshake, for an abort to shut the live one down; a session aborted meanwhile goes no further (the owner's
        review of c092eb9, M1)."""
        tls = self.context.wrap_socket(raw, server_hostname=self.target.host, do_handshake_on_connect=False)
        self.sock = tls
        self._fence(tls)  # an abort before this socket was the session's closed the detached `raw`, to no effect
        tls.do_handshake()  # an abort from here shuts this socket down, the handshake with it
        return tls

    def _fence(self, sock: socket.socket) -> None:
        if self.aborted.is_set():
            sock.close()
            raise AbortedError()

    def _connect(self, addresses: Sequence[Address]) -> socket.socket:
        for address in addresses:
            self._go_on()
            try:
                raw = socket.create_connection((str(address), self.target.port), timeout=self.limits.connect_s)
            except OSError:
                continue
            raw.settimeout(self.limits.operation_s)
            self.sock = raw
            if self.aborted.is_set():  # aborted while connecting: `abort` found no socket to close
                raw.close()
                raise AbortedError()
            if self.target.security != "tls":
                return raw
            try:
                return self._tls(raw)
            except ssl.SSLCertVerificationError:
                self._close()
                raise TlsVerificationError() from None
            except (ssl.SSLError, OSError):
                if self.sock is not None:
                    self.sock.close()
                self._go_on()  # a handshake the abort broke tries no other address
                continue
        raise NotSentError("connect")

    def _greet(self, client: _Pinned) -> None:
        code, _ = client.ehlo()
        if code != 250:
            raise _refusal("connect", code)

    def _secure(self, client: _Pinned) -> None:
        if not client.has_extn("starttls"):
            raise TlsUnavailableError()
        code, _ = client.docmd("STARTTLS")
        if code != 220:
            raise _refusal("starttls", code)
        if client.sock is None:  # the server closed the connection
            raise NotSentError("smtp")
        try:
            client.sock = self._tls(client.sock)
        except ssl.SSLCertVerificationError:
            raise TlsVerificationError() from None
        client.file = None  # RFC 3207 §4.2: what the server said before TLS is forgotten
        client.helo_resp = client.ehlo_resp = None
        client.esmtp_features = {}
        client.does_esmtp = False
        self._greet(client)

    def _login(self, client: _Pinned) -> None:
        if not client.has_extn("auth"):
            raise AuthUnavailableError()
        offered = client.esmtp_features["auth"].upper().split()
        client.user, client.password = self.target.username or "", self.target.password or ""  # both set, checked
        for mechanism in MECHANISMS:
            if mechanism in offered:
                try:
                    client.auth(mechanism, getattr(client, f"auth_{mechanism.lower()}"))
                except smtplib.SMTPAuthenticationError as e:
                    raise _refusal("auth", e.smtp_code) from None
                return
        raise AuthUnavailableError()

    def run(self, addresses: Sequence[Address], recipients: Sequence[str] | None, message: bytes | None) -> list[str]:
        """Probes when `message` is None: connect, greet, secure, sign in, QUIT."""
        try:
            client = _Pinned(self._connect(addresses), self.target, self.limits)
        except AbortedError:
            raise NotSentError("smtp") from None
        try:
            code, _ = client.connect(self.target.host, self.target.port)
            if code != 220:
                raise _refusal("connect", code)
            self._greet(client)
            if self.target.security == "starttls":
                self._secure(client)
            if self.target.username is not None:
                self._login(client)
            if recipients is None or message is None:
                return []
            options = [f"size={len(message)}"] if client.has_extn("size") else []
            code, _ = client.mail(self.target.sender, options)
            if code != 250:
                raise _refusal("mail", code)
            refused: dict[str, int] = {}
            accepted = 0
            for recipient in recipients:
                code, _ = client.rcpt(recipient)
                if code == 421:
                    raise _refusal("rcpt", code)
                if code in (250, 251):
                    accepted += 1
                else:
                    refused[recipient] = code
            if not accepted:  # nobody would get it: a transient refusal makes it worth a retry
                codes = list(refused.values())
                raise _refusal("rcpt", next((c for c in codes if 400 <= c < 500), codes[0]))
            code, _ = client.docmd("DATA")
            if code != 354:
                raise _refusal("data", code)
            self.payload = True  # from here, the server may have taken it
            stuffed = _STUFF.sub(b"..", message)
            client.send(stuffed + (b"" if stuffed.endswith(b"\r\n") else b"\r\n") + b".\r\n")
            code, _ = client.getreply()
            if code == 250:
                return [r for r in recipients if r in refused]
            if 400 <= code < 600:
                raise SmtpRefusedError("end", code)
            raise MaybeSentError("smtp")
        except (SmtpRefusedError, TlsUnavailableError, AuthUnavailableError, TlsVerificationError, NotSentError,
                MaybeSentError):  # fmt: skip
            raise
        except (OSError, ssl.SSLError, ValueError, UnicodeError):  # `smtplib`'s errors are OSErrors; an abort's too
            raise (MaybeSentError("smtp") if self.payload else NotSentError("smtp")) from None
        finally:
            try:
                client.quit()
            except (OSError, ssl.SSLError, ValueError):
                pass
            self._close()


class GuardedSmtp:
    """One attempt's mail for one tenant."""

    def __init__(
        self,
        guard: Guard,
        tenant_id: uuid.UUID,
        *,
        ssl_context: ssl.SSLContext | None = None,
        limits: SmtpLimits | None = None,
    ) -> None:
        self._guard, self._tenant = guard, tenant_id
        # the same trust as the HTTP client's: the bundled CAs, never SSL_CERT_FILE or SSL_CERT_DIR; TLS 1.2 or later
        self._context = ssl_context or httpx.create_ssl_context(trust_env=False)
        self.limits = limits or SmtpLimits()
        self._sessions: set[_Session] = set()  # under way, vetting included: aborted when the attempt closes
        self._closed = False

    async def send(self, target: SmtpTarget, recipients: Sequence[str], message: bytes) -> list[str]:
        """The recipients refused when the server took the message for the others."""
        _checked(target, recipients, message, self.limits)
        return await self._run(target, list(recipients), message)

    async def probe(self, target: SmtpTarget) -> None:
        _checked(target, None, None, self.limits)
        await self._run(target, None, None)

    async def _run(self, target: SmtpTarget, recipients: list[str] | None, message: bytes | None) -> list[str]:
        if self._closed:  # the attempt ended: nothing more starts (as the guarded websocket's fence)
            raise InvalidRequestError("closed")
        addresses = await self._guard.vet(target.host, target.port, self._tenant, plaintext=target.security == "none")
        if self._closed:  # the attempt ended while this vetted (the owner's review of c092eb9, L1)
            raise InvalidRequestError("closed")
        session = _Session(target, self._context, self.limits)
        self._sessions.add(session)
        try:
            work = asyncio.get_running_loop().run_in_executor(POOL, session.run, addresses, recipients, message)
            try:
                return await asyncio.wait_for(asyncio.shield(work), self.limits.session_s)
            except TimeoutError:
                session.abort()  # past its deadline: the thread ends on its closed socket, naming what may have left
                try:
                    return await asyncio.wait_for(asyncio.shield(work), self.limits.connect_s)
                except TimeoutError:
                    raise (MaybeSentError("smtp") if session.payload else NotSentError("smtp")) from None
        except asyncio.CancelledError:
            session.abort()  # the thread's blocked read ends now, not at its timeout
            raise
        finally:
            self._sessions.discard(session)

    async def aclose(self) -> None:
        """Aborts every session still under way (a send the node didn't await ends with its attempt), and refuses any
        later one."""
        self._closed = True
        for session in list(self._sessions):
            session.abort()
