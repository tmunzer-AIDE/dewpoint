# SPDX-License-Identifier: Apache-2.0
"""`POST /hooks/<endpoint_id>` before an attempt is recorded (engine 2b spec §8.3; the owner's rulings 2, 5, 7 and 11
and the second review), in this order: at most so many requests in flight (503, before the body is read); an address
that has failed too often (429, before any database call); the global body cap (413) and the body's deadline (408),
both counted against the address; then the endpoint, the address against its allowlist and the authentication, every
failure one bodiless 401, counted against the address."""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from dewpoint.apps.ingress.main import create_app, declared_over
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.ingress.support import Clock, bearer, bearer_endpoint, client, hmac_endpoint, settings, signed

BODY = b'{"event": "ping"}'
pytestmark = pytest.mark.usefixtures("development_deployment")


@pytest.fixture
async def make_app(pg_url, _test_users):  # type: ignore[no-untyped-def]
    apps = []

    def make(**overrides):  # type: ignore[no-untyped-def]
        clock = Clock()
        app = create_app(settings(pg_url, **overrides), clock=clock)
        app.state.clock = clock
        apps.append(app)
        return app

    yield make
    for app in apps:
        await app.state.engine.dispose()


def _authenticated(response) -> bool:  # type: ignore[no-untyped-def]
    """Past every check, and recorded."""
    return response.status_code == 200 and response.json() == {"accepted": 1, "duplicates": 0}


async def test_health(make_app) -> None:
    async with client(make_app()) as c:
        assert (await c.get("/health/live")).json() == {"status": "ok"}
        assert (await c.get("/health/ready")).json() == {"status": "ready"}


async def test_a_signed_and_a_bearer_request_pass(make_app, owner_sessionmaker) -> None:
    _, signed_endpoint = await hmac_endpoint(owner_sessionmaker)
    _, bearer_endpoint_id = await bearer_endpoint(owner_sessionmaker)
    async with client(make_app()) as c:
        assert _authenticated(await c.post(f"/hooks/{signed_endpoint}", content=BODY, headers=signed(BODY)))
        assert _authenticated(await c.post(f"/hooks/{bearer_endpoint_id}", content=BODY, headers=bearer()))


async def test_every_refusal_before_recording_is_the_same_bodiless_401(make_app, owner_sessionmaker) -> None:
    _, endpoint_id = await hmac_endpoint(owner_sessionmaker)
    _, disabled = await hmac_endpoint(owner_sessionmaker, enabled=False)
    erasing, of_erasing = await hmac_endpoint(owner_sessionmaker)
    _, fenced = await hmac_endpoint(owner_sessionmaker, allowlist=["203.0.113.0/24"])
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": erasing})
    app = make_app()
    stale = signed(BODY, now=app.state.clock.now - 301)
    refusals = {
        "unknown endpoint": (f"/hooks/{uuid.uuid4()}", signed(BODY)),
        "not an id": ("/hooks/not-a-uuid", signed(BODY)),
        "disabled endpoint": (f"/hooks/{disabled}", signed(BODY)),
        "erasing tenant": (f"/hooks/{of_erasing}", signed(BODY)),
        "disallowed address": (f"/hooks/{fenced}", signed(BODY)),
        "wrong signature": (f"/hooks/{endpoint_id}", signed(BODY, secret=b"another")),
        "stale timestamp": (f"/hooks/{endpoint_id}", stale),
        "unsigned": (f"/hooks/{endpoint_id}", {}),
        "a token for a signed endpoint": (f"/hooks/{endpoint_id}", bearer()),
    }
    seen = set()
    async with client(app) as c:
        for name, (path, headers) in refusals.items():
            response = await c.post(path, content=BODY, headers=headers)
            assert (response.status_code, response.content) == (401, b""), name
            seen.add(tuple(sorted(response.headers.items())))
    assert len(seen) == 1  # the same headers too


async def test_a_spoofed_forwarded_address_never_passes_an_allowlist(make_app, owner_sessionmaker) -> None:
    _, fenced = await hmac_endpoint(owner_sessionmaker, allowlist=["203.0.113.0/24"])
    spoofed = signed(BODY) | {"x-forwarded-for": "203.0.113.5"}
    async with client(make_app()) as c:  # no proxy configured: the header is ignored
        assert (await c.post(f"/hooks/{fenced}", content=BODY, headers=spoofed)).status_code == 401
    behind = make_app(ingress_trusted_proxies="198.51.100.0/24")  # the client (198.51.100.7) is now a proxy
    async with client(behind) as c:
        assert _authenticated(await c.post(f"/hooks/{fenced}", content=BODY, headers=spoofed))
        prepended = signed(BODY) | {"x-forwarded-for": "203.0.113.5, 192.0.2.1"}  # its client wrote the first
        assert (await c.post(f"/hooks/{fenced}", content=BODY, headers=prepended)).status_code == 401
    async with client(make_app(), address=("203.0.113.5", 40000)) as c:
        assert _authenticated(await c.post(f"/hooks/{fenced}", content=BODY, headers=signed(BODY)))


async def test_an_address_over_its_failures_is_refused_before_any_database_call(make_app, owner_sessionmaker) -> None:
    _, endpoint_id = await hmac_endpoint(owner_sessionmaker)
    app = make_app(ingress_address_failures=3)
    async with client(app) as c:
        for _ in range(3):
            assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY, headers=signed(BODY))).status_code == 401
        sessions, app.state.sessionmaker = app.state.sessionmaker, None  # any database call now fails the request
        refused = await c.post(f"/hooks/{endpoint_id}", content=BODY, headers=signed(BODY))
        assert (refused.status_code, refused.json(), refused.headers["retry-after"]) == (
            429, {"error": "rate_limited"}, "60",
        )  # fmt: skip
        app.state.sessionmaker = sessions
    async with client(app, address=("192.0.2.44", 40000)) as c:  # another address isn't
        assert _authenticated(await c.post(f"/hooks/{endpoint_id}", content=BODY, headers=signed(BODY)))
    app.state.clock.now += 60  # its minute is over
    async with client(app) as c:
        assert _authenticated(await c.post(f"/hooks/{endpoint_id}", content=BODY, headers=signed(BODY)))


async def test_the_limit_counts_an_ipv6_client_by_its_64(make_app) -> None:
    app = make_app(ingress_address_failures=2)
    async with client(app, address=("2001:db8:1:2::1", 40000)) as c:
        await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)
    async with client(app, address=("2001:db8:1:2::ffff", 40000)) as c:
        await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)
        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429


async def test_a_body_past_the_global_cap_is_413_and_counts_against_its_address(make_app) -> None:
    app = make_app(ingress_body_cap=1000, ingress_address_failures=2)

    async def chunked():  # no Content-Length: refused one byte past the cap as it arrives
        for _ in range(11):
            yield b"x" * 100

    async with client(app) as c:
        declared = await c.post(f"/hooks/{uuid.uuid4()}", content=b"x" * 1001)
        assert (declared.status_code, declared.json()) == (413, {"error": "too_large"})
        streamed = await c.post(f"/hooks/{uuid.uuid4()}", content=chunked())
        assert (streamed.status_code, streamed.json()) == (413, {"error": "too_large"})
        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429


async def test_a_body_slower_than_its_deadline_is_408_and_closed_and_counts(make_app) -> None:
    app = make_app(ingress_body_deadline_s=0.2, ingress_address_failures=1)

    async def slow():
        yield b'{"event":'
        await asyncio.sleep(5)
        yield b' "ping"}'

    async with client(app) as c:
        timed_out = await c.post(f"/hooks/{uuid.uuid4()}", content=slow())
        assert (timed_out.status_code, timed_out.headers["connection"]) == (408, "close")
        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429


async def test_past_the_in_flight_limit_a_request_is_503_before_its_body_is_read(make_app) -> None:
    app = make_app(ingress_max_in_flight=1)
    release, read = asyncio.Event(), []

    async def held():
        await release.wait()
        yield BODY

    async def counted():
        read.append(True)
        yield BODY

    async with client(app) as c:
        first = asyncio.create_task(c.post(f"/hooks/{uuid.uuid4()}", content=held()))
        await asyncio.sleep(0.05)
        busy = await c.post(f"/hooks/{uuid.uuid4()}", content=counted())
        assert (busy.status_code, busy.json(), busy.headers["retry-after"]) == (503, {"error": "busy"}, "1")
        assert read == []
        release.set()
        assert (await first).status_code == 401
        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 401  # the slot came back


async def test_an_unavailable_database_is_503_and_not_the_clients_failure(make_app) -> None:
    app = make_app(ingress_address_failures=1)
    down = make_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")
    app.state.sessionmaker = make_sessionmaker(down)
    async with client(app) as c:
        for _ in range(2):
            response = await c.post(f"/hooks/{uuid.uuid4()}", content=BODY, headers=signed(BODY))
            assert (response.status_code, response.json(), response.headers["retry-after"]) == (
                503, {"error": "unavailable"}, "5",
            )  # fmt: skip
    await down.dispose()


async def test_a_declared_length_past_any_integer_limit_is_the_counted_413(make_app) -> None:
    """A digit string too long for `int()` (the owner's M2 review) is still a length past the cap."""
    app = make_app(ingress_address_failures=1)
    async with client(app) as c:
        huge = await c.post(f"/hooks/{uuid.uuid4()}", content=b"x", headers={"content-length": "9" * 5000})
        assert (huge.status_code, huge.json()) == (413, {"error": "too_large"})
        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429


def test_a_declared_length_is_compared_without_converting_an_unbounded_string() -> None:
    cap = 5 * 1024 * 1024
    assert declared_over("9" * 5000, cap) and declared_over(str(cap + 1), cap) and declared_over("1" + "0" * 8, cap)
    assert (
        not declared_over(str(cap), cap) and not declared_over("0" * 5000 + "12", cap) and not declared_over("0", cap)
    )
    for odd in ("", "1²", "-1", "+5", " 5", "1e9", "١٢"):  # not a length: the bytes are counted as they arrive
        assert not declared_over(odd, cap), odd
