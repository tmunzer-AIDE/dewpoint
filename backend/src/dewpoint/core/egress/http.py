# SPDX-License-Identifier: Apache-2.0
"""The guarded HTTP client (plugins-3 D7).

Every new connection asks the guard to vet its host and dials the vetted address itself, so DNS can't change what
was checked (pinning); TLS is checked against the hostname. It reads no proxy, certificate or netrc setting from the
environment. Plain http goes only to allowlisted addresses (a pool of its own). Redirects are followed only when the
caller opts in, and only to the same origin; responses are capped. Every failure says what happened to the request:
not sent, maybe sent, refused or invalid, and no message names the host, an address or the URL."""

import asyncio
import json
import ssl
import uuid
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpcore
import httpx

from dewpoint.core.egress.guard import (
    EgressRefusedError,
    Guard,
    InvalidRequestError,
    MaybeSentError,
    NotSentError,
    TlsVerificationError,
)

MIB = 1024 * 1024
FORBIDDEN_IN_HEADERS = ("\r", "\n", "\0")
MAX_REDIRECTS = 3  # D7: a node may opt into at most 3 same-origin hops
# What frames, routes or encodes the request is the client's own: a plugin can't set it.
RESERVED_HEADERS = frozenset({
    "content-length", "transfer-encoding", "host", "connection", "upgrade", "te", "trailer", "keep-alive",
    "proxy-authorization", "proxy-connection", "accept-encoding",
})  # fmt: skip
INFLATABLE = {"gzip": 16 + zlib.MAX_WBITS, "x-gzip": 16 + zlib.MAX_WBITS, "deflate": zlib.MAX_WBITS}


@dataclass(frozen=True)
class HttpLimits:
    connect_s: float = 5.0
    read_s: float = 30.0
    total_s: float = 60.0
    max_response_bytes: int = 10 * MIB


class RedirectRefusedError(Exception):
    """A redirect the caller didn't allow (another origin, or too many hops). The request before it was sent."""

    def __init__(self, reason: str) -> None:
        super().__init__("A redirect was refused.")
        self.reason = reason


class ResponseTooLargeError(Exception):
    """The answer passed the cap. The request was sent and answered."""

    def __init__(self) -> None:
        super().__init__("The response is too large.")


class ResponseUnreadableError(Exception):
    """The answer came in an encoding the client can't decode within its cap. The request was sent and answered."""

    def __init__(self) -> None:
        super().__init__("The response can't be read.")


def _member(data: bytes, wbits: int, room: int) -> tuple[bytes, bytes]:
    """One complete compressed stream at the start of `data`, decoded within `room` bytes: (what it decodes to, the data
    after it). Raises ResponseTooLargeError past the room, ResponseUnreadableError for an incomplete or broken one."""
    inflater = zlib.decompressobj(wbits)
    out = bytearray()
    pending = data
    try:
        while pending and not inflater.eof:
            out += inflater.decompress(pending, room + 1 - len(out))
            if len(out) > room:
                raise ResponseTooLargeError()
            if inflater.unconsumed_tail == pending:  # no progress without the stream ending: broken
                break
            pending = inflater.unconsumed_tail
        if not inflater.eof:
            out += inflater.flush(room + 1 - len(out))
    except zlib.error:
        raise ResponseUnreadableError() from None
    if len(out) > room:
        raise ResponseTooLargeError()
    if not inflater.eof:  # truncated: never taken for the whole answer (the second review's finding 2)
        raise ResponseUnreadableError()
    return bytes(out), inflater.unused_data


def _inflate(raw: bytes, encoding: str, cap: int) -> bytes:
    """`raw` decoded, never holding more than the cap. Every gzip member is decoded, within the cap together; any data
    after a deflate stream is refused, as is a stream that doesn't end."""
    if encoding == "deflate":
        try:
            out, rest = _member(raw, zlib.MAX_WBITS, cap)  # zlib-wrapped, as the RFC says
        except ResponseUnreadableError:
            out, rest = _member(raw, -zlib.MAX_WBITS, cap)  # raw deflate, as some servers send
        if rest:
            raise ResponseUnreadableError()
        return out
    decoded = bytearray()
    pending = raw
    while pending:
        out, pending = _member(pending, INFLATABLE[encoding], cap - len(decoded))
        decoded += out
    return bytes(decoded)


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    content: bytes

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        return next((v for k, v in self.headers if k.lower() == wanted), None)

    def json(self) -> Any:
        return json.loads(self.content)


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """Connects only to an address the guard vetted for the tenant; the TLS layer above checks the hostname."""

    def __init__(self, guard: Guard, tenant_id: uuid.UUID, *, plaintext: bool) -> None:
        self._guard, self._tenant, self._plaintext = guard, tenant_id, plaintext
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await self._guard.vet(host, port, self._tenant, plaintext=self._plaintext)
        failure: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    str(address), port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as e:
                failure = e
        raise failure if failure is not None else NotSentError("connect")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise EgressRefusedError("unix_socket")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _transport(
    guard: Guard, tenant_id: uuid.UUID, context: ssl.SSLContext, *, plaintext: bool
) -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(verify=context, trust_env=False, retries=0)
    # httpx 0.28 takes no network backend: its pool is replaced by one dialling through the guard (pinned by a test).
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=context,
        max_connections=10,
        max_keepalive_connections=10,
        keepalive_expiry=5.0,
        http1=True,
        http2=False,
        retries=0,
        network_backend=_GuardedBackend(guard, tenant_id, plaintext=plaintext),
    )
    return transport


def _tls_failure(error: BaseException) -> bool:
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, ssl.SSLError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


class GuardedHttp:
    """One attempt's HTTP client for one tenant: its connections are never shared with another attempt or tenant."""

    def __init__(
        self,
        guard: Guard,
        tenant_id: uuid.UUID,
        *,
        ssl_context: ssl.SSLContext | None = None,
        limits: HttpLimits | None = None,
    ) -> None:
        self.limits = limits or HttpLimits()
        context = ssl_context or httpx.create_ssl_context(trust_env=False)
        self._client = httpx.AsyncClient(
            mounts={
                "https://": _transport(guard, tenant_id, context, plaintext=False),
                "http://": _transport(guard, tenant_id, context, plaintext=True),
            },
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=self.limits.connect_s,
                read=self.limits.read_s,
                write=self.limits.read_s,
                pool=self.limits.connect_s,
            ),  # fmt: skip
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _url(url: str) -> httpx.URL:
        try:
            parsed = httpx.URL(url)
        except (httpx.InvalidURL, TypeError, ValueError):
            raise InvalidRequestError("url") from None
        if parsed.scheme not in ("http", "https") or not parsed.host:
            raise InvalidRequestError("scheme")
        if parsed.userinfo:
            raise InvalidRequestError("userinfo")
        return parsed

    @staticmethod
    def _headers(headers: Mapping[str, str] | None) -> dict[str, str]:
        for name, value in (headers or {}).items():
            if any(c in name or c in value for c in FORBIDDEN_IN_HEADERS):
                raise InvalidRequestError("header")
            if name.lower() in RESERVED_HEADERS:
                raise InvalidRequestError("reserved_header")
        return {**(headers or {}), "Accept-Encoding": "identity"}

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
    ) -> HttpResponse:
        target = self._url(url)
        sent_headers = self._headers(headers)
        if not 0 <= follow_same_origin <= MAX_REDIRECTS:
            raise InvalidRequestError("redirects")
        hops = 0
        try:
            async with asyncio.timeout(self.limits.total_s):
                while True:
                    try:
                        request = self._client.build_request(
                            method, target, headers=sent_headers, params=params, content=content, json=json
                        )
                    except (httpx.InvalidURL, TypeError, ValueError):
                        raise InvalidRequestError("request") from None
                    answer = await self._send(request)
                    location = answer.header("location")
                    if not follow_same_origin or method not in ("GET", "HEAD") or location is None:
                        return answer
                    if answer.status_code not in (301, 302, 303, 307, 308):
                        return answer
                    if hops >= follow_same_origin:
                        raise RedirectRefusedError("too_many")
                    try:
                        following = target.join(location)
                    except (httpx.InvalidURL, ValueError):
                        raise RedirectRefusedError("location") from None
                    if (following.scheme, following.host, following.port) != (target.scheme, target.host, target.port):
                        raise RedirectRefusedError("cross_origin")
                    target, params, hops = following, None, hops + 1
        except TimeoutError:
            raise MaybeSentError("deadline") from None

    async def _send(self, request: httpx.Request) -> HttpResponse:
        try:
            response = await self._client.send(request, stream=True)
        except httpx.ConnectError as e:
            if _tls_failure(e):
                raise TlsVerificationError() from None
            raise NotSentError("connect") from None
        except (httpx.ConnectTimeout, httpx.PoolTimeout):
            raise NotSentError("connect_timeout") from None
        except (httpx.UnsupportedProtocol, httpx.LocalProtocolError):
            raise InvalidRequestError("protocol") from None
        except (httpx.ReadTimeout, httpx.WriteTimeout):
            raise MaybeSentError("timeout") from None
        except httpx.TransportError:
            raise MaybeSentError("transport") from None
        try:
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.limits.max_response_bytes:
                raise ResponseTooLargeError()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_raw():  # the bytes on the wire: decoded below, within the cap
                total += len(chunk)
                if total > self.limits.max_response_bytes:
                    raise ResponseTooLargeError()
                chunks.append(chunk)
        except httpx.TimeoutException:
            raise MaybeSentError("timeout") from None
        except (httpx.TransportError, httpx.DecodingError):
            raise MaybeSentError("transport") from None
        finally:
            await response.aclose()
        raw = b"".join(chunks)
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("", "identity"):
            if encoding not in INFLATABLE:
                raise ResponseUnreadableError()
            raw = _inflate(raw, encoding, self.limits.max_response_bytes)
        return HttpResponse(response.status_code, tuple(response.headers.multi_items()), raw)
