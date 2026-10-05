# SPDX-License-Identifier: Apache-2.0
"""The guarded HTTP client (plugins-3 D7) against local servers only: it connects to the address it vetted, checks TLS
against the hostname, never uses a proxy, follows only opted-in same-origin redirects, caps responses, refuses CR/LF in
headers, and says whether a failed request may have been sent."""

import asyncio
import socket

import pytest

from dewpoint.core.egress.guard import (
    EgressRefusedError,
    InvalidRequestError,
    MaybeSentError,
    NotSentError,
    TlsVerificationError,
)
from dewpoint.core.egress.http import (
    GuardedHttp,
    HttpLimits,
    RedirectRefusedError,
    ResponseTooLargeError,
    ResponseUnreadableError,
)
from tests.support.netfakes import TENANT, Request, guard, respond, serve, tls

NAMES = ("dewpoint.test",)


def client(answers, limits: HttpLimits | None = None) -> GuardedHttp:  # type: ignore[no-untyped-def]
    return GuardedHttp(guard(answers), TENANT, ssl_context=tls(NAMES).client_context(), limits=limits or HttpLimits())


async def test_tls_is_checked_against_the_hostname_while_the_vetted_address_is_dialled() -> None:
    async with serve(respond(200, b"hello"), tls_names=NAMES) as server:
        http = client({"dewpoint.test": ["127.0.0.1"]})
        try:
            answer = await http.request("GET", f"https://dewpoint.test:{server.port}/path?q=1")
        finally:
            await http.aclose()
    assert (answer.status_code, answer.content) == (200, b"hello")
    assert server.requests[0].headers["host"] == f"dewpoint.test:{server.port}"
    assert server.requests[0].target == "/path?q=1"


async def test_a_certificate_for_another_name_is_refused_as_tls_not_retried() -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        http = client({"other.test": ["127.0.0.1"]})
        try:
            with pytest.raises(TlsVerificationError):
                await http.request("GET", f"https://other.test:{server.port}/")
        finally:
            await http.aclose()
    assert server.requests == []


async def test_each_connection_is_vetted_and_pinned_so_rebinding_is_refused() -> None:
    answers = {"dewpoint.test": [["127.0.0.1"], ["10.0.0.9"]]}
    async with serve(respond(), tls_names=NAMES) as server:
        first = client(answers)
        try:
            assert (await first.request("GET", f"https://dewpoint.test:{server.port}/")).status_code == 200
            assert (await first.request("GET", f"https://dewpoint.test:{server.port}/")).status_code == 200  # reused
        finally:
            await first.aclose()
        second = client(answers)  # a new attempt connects again: the name now answers a private address
        try:
            with pytest.raises(EgressRefusedError):
                await second.request("GET", f"https://dewpoint.test:{server.port}/")
        finally:
            await second.aclose()
    assert len(server.requests) == 2


async def test_one_disallowed_answer_refuses_the_name() -> None:
    http = client({"dewpoint.test": ["127.0.0.1", "10.0.0.9"]})
    try:
        with pytest.raises(EgressRefusedError):
            await http.request("GET", "https://dewpoint.test:4443/")
    finally:
        await http.aclose()


async def test_plain_http_needs_an_allowlist_entry_even_for_a_global_address() -> None:
    http = client({"public.test": ["93.184.216.34"]})
    try:
        with pytest.raises(EgressRefusedError):  # refused before any connection: nothing leaves this host
            await http.request("GET", "http://public.test/")
    finally:
        await http.aclose()


async def test_plain_http_to_an_allowlisted_address_works() -> None:
    async with serve(respond(204, b"")) as server:
        http = client({"local.test": ["127.0.0.1"]})
        try:
            assert (await http.request("GET", f"http://local.test:{server.port}/")).status_code == 204
        finally:
            await http.aclose()


def _redirect(location_of) -> object:  # type: ignore[no-untyped-def]
    async def handler(request: Request, writer: asyncio.StreamWriter) -> None:
        if request.target == "/start":
            await respond(302, b"", [("location", location_of(request))])(request, writer)
        else:
            await respond(200, b"landed")(request, writer)

    return handler


async def test_redirects_are_not_followed_unless_the_node_opts_in() -> None:
    async with serve(_redirect(lambda r: "/end")) as server:  # type: ignore[arg-type]
        http = client({"local.test": ["127.0.0.1"]})
        try:
            url = f"http://local.test:{server.port}/start"
            assert (await http.request("GET", url)).status_code == 302
            followed = await http.request("GET", url, follow_same_origin=3)
        finally:
            await http.aclose()
    assert (followed.status_code, followed.content) == (200, b"landed")


async def test_a_cross_origin_redirect_is_refused() -> None:
    async with serve(_redirect(lambda r: "http://elsewhere.test/end")) as server:  # type: ignore[arg-type]
        http = client({"local.test": ["127.0.0.1"], "elsewhere.test": ["127.0.0.1"]})
        try:
            with pytest.raises(RedirectRefusedError):
                await http.request("GET", f"http://local.test:{server.port}/start", follow_same_origin=3)
        finally:
            await http.aclose()


async def test_too_many_hops_are_refused() -> None:
    async def loop(request: Request, writer: asyncio.StreamWriter) -> None:
        await respond(302, b"", [("location", "/again")])(request, writer)

    async with serve(loop) as server:
        http = client({"local.test": ["127.0.0.1"]})
        try:
            with pytest.raises(RedirectRefusedError):
                await http.request("GET", f"http://local.test:{server.port}/", follow_same_origin=2)
        finally:
            await http.aclose()
    assert len(server.requests) == 3


async def test_a_response_past_the_cap_is_refused() -> None:
    async with serve(respond(200, b"x" * 2048)) as server:
        http = client({"local.test": ["127.0.0.1"]}, HttpLimits(max_response_bytes=1024))
        try:
            with pytest.raises(ResponseTooLargeError):
                await http.request("GET", f"http://local.test:{server.port}/")
        finally:
            await http.aclose()


async def test_proxy_settings_in_the_environment_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    async with serve(respond(200, b"direct"), tls_names=NAMES) as server:
        http = client({"dewpoint.test": ["127.0.0.1"]})
        try:
            assert (await http.request("GET", f"https://dewpoint.test:{server.port}/")).content == b"direct"
        finally:
            await http.aclose()


@pytest.mark.parametrize(
    ("url", "headers"),
    [
        ("http://local.test:{port}/", {"x-a": "1\r\nx-injected: 2"}),
        ("http://local.test:{port}/", {"x-a\r\nx-b": "1"}),
        ("http://user:pw@local.test:{port}/", {}),
        ("ftp://local.test:{port}/", {}),
    ],
)
async def test_invalid_requests_are_refused_before_anything_is_sent(url: str, headers: dict[str, str]) -> None:
    async with serve(respond()) as server:
        http = client({"local.test": ["127.0.0.1"]})
        try:
            with pytest.raises(InvalidRequestError):
                await http.request("GET", url.format(port=server.port), headers=headers)
        finally:
            await http.aclose()
    assert server.requests == []


async def test_a_refused_connection_means_nothing_was_sent() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    http = client({"local.test": ["127.0.0.1"]})
    try:
        with pytest.raises(NotSentError):
            await http.request("POST", f"http://local.test:{port}/", content=b"payload")
    finally:
        await http.aclose()


async def test_a_server_that_closes_without_answering_may_have_got_the_request() -> None:
    async def hang_up(_: Request, writer: asyncio.StreamWriter) -> None:
        writer.close()

    async with serve(hang_up) as server:
        http = client({"local.test": ["127.0.0.1"]})
        try:
            with pytest.raises(MaybeSentError):
                await http.request("POST", f"http://local.test:{server.port}/", content=b"payload")
        finally:
            await http.aclose()
    assert len(server.requests) == 1


async def test_a_slow_answer_times_out_as_maybe_sent() -> None:
    async def slow(request: Request, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(2)
        await respond()(request, writer)

    async with serve(slow) as server:
        http = client({"local.test": ["127.0.0.1"]}, HttpLimits(read_s=0.2))
        try:
            with pytest.raises(MaybeSentError):
                await http.request("GET", f"http://local.test:{server.port}/")
        finally:
            await http.aclose()


async def test_errors_never_name_the_host() -> None:
    http = client({"secret-name.test": ["10.0.0.9"]})
    try:
        with pytest.raises(EgressRefusedError) as raised:
            await http.request("GET", "https://secret-name.test/")
    finally:
        await http.aclose()
    assert "secret-name" not in str(raised.value)


def _gzipped(size: int) -> bytes:
    import gzip

    return gzip.compress(b"\0" * size)


async def test_answers_are_asked_uncompressed_and_a_compressed_one_is_inflated_within_the_cap() -> None:
    """The review's finding 6: decoding never holds more than the cap."""
    small, huge = _gzipped(500), _gzipped(64 * 1024 * 1024)
    async with serve(respond(200, small, [("content-encoding", "gzip")])) as server:
        http = client({"local.test": ["127.0.0.1"]}, HttpLimits(max_response_bytes=1024))
        try:
            assert (await http.request("GET", f"http://local.test:{server.port}/")).content == b"\0" * 500
        finally:
            await http.aclose()
    assert server.requests[0].headers["accept-encoding"] == "identity"
    async with serve(respond(200, huge, [("content-encoding", "gzip")])) as server:
        http = client({"local.test": ["127.0.0.1"]}, HttpLimits(max_response_bytes=1024 * 1024))
        try:
            with pytest.raises(ResponseTooLargeError):
                await http.request("GET", f"http://local.test:{server.port}/")
        finally:
            await http.aclose()


async def test_an_encoding_it_cant_bound_is_refused() -> None:
    async with serve(respond(200, b"\x0b\x02\x80", [("content-encoding", "br")])) as server:
        http = client({"local.test": ["127.0.0.1"]})
        try:
            with pytest.raises(ResponseUnreadableError):
                await http.request("GET", f"http://local.test:{server.port}/")
        finally:
            await http.aclose()


@pytest.mark.parametrize("name", ["Content-Length", "transfer-encoding", "Host", "Connection", "Upgrade", "TE"])
async def test_framing_headers_are_the_clients_own(name: str) -> None:
    """The review's finding 8: a plugin can't set what frames or routes the request."""
    async with serve(respond()) as server:
        http = client({"local.test": ["127.0.0.1"]})
        try:
            with pytest.raises(InvalidRequestError):
                await http.request("POST", f"http://local.test:{server.port}/", headers={name: "5"}, content=b"x")
        finally:
            await http.aclose()
    assert server.requests == []


async def test_at_most_three_redirect_hops_can_be_asked_for() -> None:
    http = client({"local.test": ["127.0.0.1"]})
    try:
        with pytest.raises(InvalidRequestError):
            await http.request("GET", "http://local.test:1/", follow_same_origin=4)
    finally:
        await http.aclose()
