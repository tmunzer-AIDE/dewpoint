# SPDX-License-Identifier: Apache-2.0
"""What a node reaches the network with (plugins-3 D4, D7): HTTP and sockets through Dewpoint's guard, and connections
whose secret the runtime applies, so a node never holds one.

Their failures are `TransportError`s with fixed codes. The step's outcome follows from the class: nothing was sent
(`EgressRefused`, `TlsVerificationFailed`, `InvalidRequest`, `ConnectionUnavailable`, `SimulationSendsNothing` fail
the step; `NotSent` and `Cooldown` are retried), or the request may have arrived (`MaybeSent`, `RateLimited`,
`RedirectRefused`, `ResponseTooLarge`, `ResponseUnreadable`): an `ambiguous` node then ends `outcome_unknown`, any
other is retried after `MaybeSent` or `RateLimited` and fails after the others. Once any request of an attempt may
have arrived, an ambiguous node's failure is never retried. A node catches one only to do something else.

Mail (plugins-3 D20): `MailRefused` is a mail server's definite refusal, after which nothing was delivered: a
transient one (4yz) is retried, a permanent one (5yz) fails; `TlsUnavailable` and `AuthUnavailable` fail, having
sent nothing."""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Protocol


class TransportError(Exception):
    code: ClassVar[str] = "transport_failed"
    message: ClassVar[str] = "The network request failed."

    def __init__(self) -> None:
        super().__init__(self.message)


class EgressRefused(TransportError):
    code, message = "egress_refused", "The destination isn't allowed."


class TlsVerificationFailed(TransportError):
    code, message = "tls_verification_failed", "The destination's certificate didn't verify."


class InvalidRequest(TransportError):
    code, message = "invalid_request", "The request can't be sent as written."


class ConnectionUnavailable(TransportError):
    code, message = "connection_unavailable", "The connection isn't one this step may use."


class NotSent(TransportError):
    code, message = "not_sent", "The request wasn't sent."


class Cooldown(TransportError):
    code, message = "cooldown", "The connection is cooling down: nothing was sent."


class SimulationSendsNothing(TransportError):
    code, message = "simulation_sends_nothing", "A simulated step sends nothing."


class MaybeSent(TransportError):
    code, message = "maybe_sent", "The request may have been sent."


class RateLimited(TransportError):
    code, message = "rate_limited", "The provider answered that it's rate limiting."


class RedirectRefused(TransportError):
    code, message = "redirect_refused", "The answer redirected where this step may not follow."


class ResponseTooLarge(TransportError):
    code, message = "response_too_large", "The answer was larger than the step may read."


class ResponseUnreadable(TransportError):
    code, message = "response_unreadable", "The answer came in a form the step can't read."


class HandshakeRejected(TransportError):
    """A stream's opening handshake answered with `status` (not 101; a redirect is never followed). Only the handshake
    was sent; a 429's `Retry-After` has blocked the stream's quota scopes already."""

    code, message = "handshake_rejected", "The stream's handshake was refused."

    def __init__(self, status: int) -> None:
        super().__init__()
        self.status = status


class StreamLost(TransportError):
    code, message = "stream_lost", "The stream closed or broke."


class MailRefused(TransportError):
    """A mail server's definite refusal (plugins-3 D20) at `stage` (`connect`, `starttls`, `auth`, `mail`, `rcpt`,
    `data`, or `end`, its answer to the message's end) with reply `code`. The server delivers nothing it refused (RFC
    5321 §4.2.5): a 5yz is permanent, a 4yz transient."""

    code, message = "mail_refused", "The mail server refused the message."

    def __init__(self, stage: str, reply: int) -> None:
        super().__init__()
        self.stage, self.reply = stage, reply
        self.args = (f"The mail server refused at {stage} ({reply}).",)

    @property
    def permanent(self) -> bool:
        return 500 <= self.reply < 600


class TlsUnavailable(TransportError):
    code, message = "tls_unavailable", "The mail server offered no TLS where it's required."


class AuthUnavailable(TransportError):
    code, message = "auth_unavailable", "The mail server offered no way to sign in the runtime uses (PLAIN, LOGIN)."


class HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> tuple[tuple[str, str], ...]: ...

    @property
    def content(self) -> bytes: ...

    def header(self, name: str) -> str | None: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
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
    ) -> HttpResponse:
        """`follow_same_origin`: how many redirects to the same origin to follow (GET and HEAD only); none by
        default, and never to another origin.

        `probe`: a read the node makes before its effect, to check it may act (a scope check): GET or HEAD without a
        body, else refused (`InvalidRequest`) before anything is sent. It doesn't count as a send, so an ambiguous
        node whose later request fails having sent nothing is still retried; it may be resent within the attempt
        after a short `Retry-After`. Its own failures are the node's to classify: one after which it may have arrived
        changes nothing, being a read."""
        ...


class NetStream(Protocol):
    async def send(self, data: bytes) -> None: ...

    async def receive(self, max_bytes: int = 65_536) -> bytes: ...

    async def close(self) -> None: ...


class Net(Protocol):
    async def open_tcp(self, host: str, port: int, *, tls: bool) -> NetStream: ...

    async def send_udp(self, host: str, port: int, data: bytes) -> None: ...


class WebSocket(Protocol):
    """One open stream (plugins-3 D26): text messages, each at most 1 MiB, at most 10 MiB received an attempt."""

    async def send(self, text: str, *, probe: bool = False) -> None:
        """A text message. It counts as a send, as an HTTP request does, unless `probe`: a message that changes nothing
        (a subscription), which leaves the attempt as it was. `StreamLost` once the stream is gone."""
        ...

    async def receive(self, timeout_s: float) -> str | None:
        """The next text message, or None when none came within `timeout_s` (nothing is lost: the next call reads it).
        `StreamLost` once the stream closed or broke; `ResponseTooLarge` past a cap; `ResponseUnreadable` for a
        binary message."""
        ...

    async def close(self) -> None: ...


class ConnectionWs(Protocol):
    async def connect(self) -> WebSocket:
        """The connection type's stream (its `StreamEndpoint`), opened with its credentials, once a token is taken from
        each of its stream quota scopes (`Cooldown` otherwise). Opening sends nothing a node answers for: failures are
        `HandshakeRejected` (the status), `NotSent`, `EgressRefused`, `TlsVerificationFailed`, `Cooldown`; a type
        without a stream, a simulated step and a plugin call are refused (`InvalidRequest`, `SimulationSendsNothing`,
        `ReadOnly`)."""
        ...


class ConnectionSmtp(Protocol):
    async def send(self, recipients: Sequence[str], message: bytes) -> list[str]:
        """Sends `message`, a whole RFC 5322 message with CRLF line ends, from the connection's sender to `recipients`
        (1 to 50, each a `MAIL_ADDRESS`), over the connection's server and security, signing in with its credentials:
        the node names neither. Returns the recipients the server refused when it took the message for the others.
        Failures: `MailRefused` (nothing delivered), `TlsUnavailable`, `AuthUnavailable`, `NotSent`, `EgressRefused`,
        `TlsVerificationFailed`, `Cooldown`, `InvalidRequest`; `MaybeSent` once the message's end may have reached the
        server without its answer. Refused in a simulated step and a plugin call."""
        ...

    async def probe(self) -> None:
        """Connects, greets, secures and signs in, then quits, never sending MAIL (plugins-3 D3's read-only adapter):
        how a connection type's `verify` checks the server and credentials. The same failures as `send`, before it."""
        ...


class Connection(Protocol):
    """One of the tenant's connections, opened for this step. Its `http` applies the connection's credentials and
    resolves relative URLs against the connection's base; the secret itself is never exposed."""

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def type(self) -> str: ...

    @property
    def config(self) -> Mapping[str, Any]: ...

    @property
    def http(self) -> HttpClient: ...

    @property
    def ws(self) -> ConnectionWs: ...

    @property
    def smtp(self) -> ConnectionSmtp: ...
