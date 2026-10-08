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

The message goes on the wire whole or not at all: a bare CR or LF (the way to smuggle a second message past a
server), a NUL or a line past 998 octets is refused before connecting, as is a sender, a recipient or a credential of
another form. Failures name no host, address or server text; nothing is logged."""

import asyncio
import re
import smtplib
import socket
import ssl
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

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
    password: str | None
    ehlo_name: str


@dataclass(frozen=True)
class SmtpLimits:
    connect_s: float = 5.0
    operation_s: float = 60.0  # each blocking read or write, the answer to the message's end included
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


class _Session:
    """One connection, start to QUIT, run in a worker thread; `abort` closes its socket from the event loop."""

    def __init__(self, target: SmtpTarget, context: ssl.SSLContext, limits: SmtpLimits) -> None:
        self.target, self.context, self.limits = target, context, limits
        self.sock: socket.socket | None = None

    def abort(self) -> None:
        sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _connect(self, addresses: Sequence[Address]) -> socket.socket:
        for address in addresses:
            try:
                raw = socket.create_connection((str(address), self.target.port), timeout=self.limits.connect_s)
            except OSError:
                continue
            raw.settimeout(self.limits.operation_s)
            self.sock = raw
            if self.target.security != "tls":
                return raw
            try:
                self.sock = self.context.wrap_socket(raw, server_hostname=self.target.host)
            except ssl.SSLCertVerificationError:
                raw.close()
                raise TlsVerificationError() from None
            except (ssl.SSLError, OSError):
                raw.close()
                continue
            return self.sock
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
            client.sock = self.sock = self.context.wrap_socket(client.sock, server_hostname=self.target.host)
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
        client = _Pinned(self._connect(addresses), self.target, self.limits)
        payload = False
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
            for recipient in recipients:
                code, _ = client.rcpt(recipient)
                if code == 421:
                    raise _refusal("rcpt", code)
                if code not in (250, 251):
                    refused[recipient] = code
            if len(refused) == len(recipients):  # nobody would get it: a transient refusal makes it worth a retry
                codes = list(refused.values())
                raise _refusal("rcpt", next((c for c in codes if 400 <= c < 500), codes[0]))
            code, _ = client.docmd("DATA")
            if code != 354:
                raise _refusal("data", code)
            payload = True  # from here, the server may have taken it
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
        except (OSError, ssl.SSLError, ValueError, UnicodeError):  # `smtplib`'s errors are OSErrors
            raise (MaybeSentError("smtp") if payload else NotSentError("smtp")) from None
        finally:
            try:
                client.quit()
            except (OSError, ssl.SSLError, ValueError):
                pass
            self.abort()


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

    async def send(self, target: SmtpTarget, recipients: Sequence[str], message: bytes) -> list[str]:
        """The recipients refused when the server took the message for the others."""
        _checked(target, recipients, message, self.limits)
        return await self._run(target, list(recipients), message)

    async def probe(self, target: SmtpTarget) -> None:
        _checked(target, None, None, self.limits)
        await self._run(target, None, None)

    async def _run(self, target: SmtpTarget, recipients: list[str] | None, message: bytes | None) -> list[str]:
        addresses = await self._guard.vet(target.host, target.port, self._tenant, plaintext=target.security == "none")
        session = _Session(target, self._context, self.limits)
        try:
            return await asyncio.to_thread(session.run, addresses, recipients, message)
        except asyncio.CancelledError:
            session.abort()  # the thread's blocked read ends now, not at its timeout
            raise
