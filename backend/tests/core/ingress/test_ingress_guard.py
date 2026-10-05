# SPDX-License-Identifier: Apache-2.0
"""Ingress stays a development-only prototype until 2b-4 (the owner's rulings 8 and 13): the recording function records
nothing unless the recorded environment is `development`, absent included, whatever the process checked."""

from sqlalchemy import text

from dewpoint.core.platform.service import PRODUCTION, record_environment
from tests.core.ingress.support import digest, endpoint, events_of, key, record


async def test_without_a_recorded_environment_nothing_is_recorded(owner_sessionmaker, ingress_sessionmaker) -> None:
    _, endpoint_id = await endpoint(owner_sessionmaker)
    assert await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]) == {"outcome": "environment"}
    assert await events_of(owner_sessionmaker, endpoint_id) == []


async def test_in_production_nothing_is_recorded(owner_sessionmaker, ingress_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    _, endpoint_id = await endpoint(owner_sessionmaker)
    assert await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]) == {"outcome": "environment"}
    async with ingress_sessionmaker() as s:
        assert (await s.execute(text("select ingress_environment()"))).scalar_one() == "production"
