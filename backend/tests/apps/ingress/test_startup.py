# SPDX-License-Identifier: Apache-2.0
"""Ingress stays a gated prototype until 2b-4 (the owner's rulings 8 and 13): it starts only when the recorded
environment is `development`, read through `ingress_environment()`, its only way to read it."""

import base64

import pytest

from dewpoint.apps.ingress.main import IngressRefusedError, create_app
from dewpoint.core.platform.service import DEVELOPMENT, PRODUCTION, record_environment
from tests.apps.ingress.support import bearer, bearer_endpoint, client, settings
from tests.core.ingress.support import events_of


async def _starts(pg_url: str) -> None:
    app = create_app(settings(pg_url))
    try:
        async with app.router.lifespan_context(app):
            pass
    finally:
        await app.state.engine.dispose()


async def test_without_a_recorded_environment_ingress_refuses_to_start(pg_url, _test_users) -> None:
    with pytest.raises(IngressRefusedError, match=r"development deployment .*\(recorded: none\)"):
        await _starts(pg_url)


async def test_in_production_ingress_refuses_to_start(pg_url, _test_users, owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    with pytest.raises(IngressRefusedError, match=r"\(recorded: production\)"):
        await _starts(pg_url)


async def test_in_development_ingress_starts(pg_url, _test_users, owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=DEVELOPMENT, namespace="default")
    await _starts(pg_url)


async def test_an_attempt_outside_development_is_503_and_records_nothing(
    pg_url, _test_users, owner_sessionmaker
) -> None:
    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
    app = create_app(settings(pg_url))  # a test transport skips the startup check: the function refuses anyway
    try:
        async with client(app) as c:
            response = await c.post(f"/hooks/{endpoint_id}", content=b'{"n": 1}', headers=bearer())
    finally:
        await app.state.engine.dispose()
    assert (response.status_code, response.json()) == (503, {"error": "unavailable"})
    assert await events_of(owner_sessionmaker, endpoint_id) == []


@pytest.mark.parametrize("name", ["DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"])
def test_a_key_encryption_key_in_its_environment_refuses_the_app_itself(pg_url, monkeypatch, name) -> None:
    """Not only `dewpoint ingress`: an app made directly (uvicorn's factory, an embedding) refuses too (the owner's M2
    review), before its lifespan, so a server run with its lifespan off can't skip the check."""
    value = base64.b64encode(b"k" * 32).decode()
    monkeypatch.setenv(name, value)
    with pytest.raises(IngressRefusedError, match=name) as refused:
        create_app(settings(pg_url))
    assert value not in str(refused.value)
