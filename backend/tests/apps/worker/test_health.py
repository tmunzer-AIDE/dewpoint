# SPDX-License-Identifier: Apache-2.0
"""A worker instance proves what it records (engine 2b spec §2.7): its KEK wraps and unwraps, and its role may read
data keys. A failed check stops it polling, at startup or later; a database that doesn't answer (an outage, which
the worker keeps running through) proves nothing either way, and neither does a record it can't write."""

import pytest

from dewpoint.apps.worker.health import CAPABILITIES, WorkerUnhealthyError, self_check, start_healthy, watch
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.conftest import _url_for


class Log:
    def __init__(self, checks: list[bool | None], fail_reports: int = 0) -> None:
        self.checks, self.fail_reports = checks, fail_reports
        self.events: list[str] = []

    async def check(self) -> bool | None:
        healthy = self.checks.pop(0)
        self.events.append(f"check {healthy}")
        return healthy

    async def report(self, healthy: bool) -> None:
        if self.fail_reports:
            self.fail_reports -= 1
            self.events.append("report failed")
            raise ConnectionError("the database is down")
        self.events.append(f"report {healthy}")

    async def stop(self) -> None:
        self.events.append("stop")


@pytest.mark.parametrize("answer", [False, None])
async def test_an_instance_that_cant_prove_itself_at_startup_records_it_and_never_polls(answer: bool | None) -> None:
    log = Log([answer])
    with pytest.raises(WorkerUnhealthyError):
        await start_healthy(log.check, log.report)
    assert log.events == [f"check {answer}", "report False"]


async def test_a_healthy_start_is_recorded() -> None:
    log = Log([True])
    await start_healthy(log.check, log.report)
    assert log.events == ["check True", "report True"]


async def test_a_failed_check_stops_the_workers_then_ends_the_process() -> None:
    log = Log([True, False])
    with pytest.raises(WorkerUnhealthyError):
        await watch(log.check, log.report, log.stop, interval_s=0)
    assert log.events == ["check True", "report True", "check False", "report False", "stop"]


async def test_an_outage_proves_nothing_and_keeps_the_instance_polling() -> None:
    """Nothing is recorded while the database doesn't answer: the row goes stale, and a stale row isn't live."""
    log = Log([True, None, None, False])
    with pytest.raises(WorkerUnhealthyError):
        await watch(log.check, log.report, log.stop, interval_s=0)
    assert log.events == [
        "check True",
        "report True",
        "check None",
        "check None",
        "check False",
        "report False",
        "stop",
    ]


async def test_a_record_it_cant_write_keeps_a_healthy_instance_polling() -> None:
    log = Log([True, True, False], fail_reports=2)
    with pytest.raises(WorkerUnhealthyError):
        await watch(log.check, log.report, log.stop, interval_s=0)
    events = ["check True", "report failed", "check True", "report failed", "check False", "report False", "stop"]
    assert log.events == events


async def test_the_check_proves_the_kek_and_the_roles_access_to_data_keys(
    pg_url, _test_users, worker_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A role without `SELECT` on `data_keys` fails the check; a database that doesn't answer is no answer."""
    keyring = Keyring(KekSet(Kek("k1", b"k" * 32)))
    assert await self_check(keyring, worker_sessionmaker) is True
    ingress, unreachable = (
        make_engine(_url_for(pg_url, "dewpoint_ingress")),
        make_engine("postgresql+asyncpg://nobody@127.0.0.1:9/none"),
    )
    try:
        assert await self_check(keyring, make_sessionmaker(ingress)) is False  # no grant: a definite answer
        assert await self_check(keyring, make_sessionmaker(unreachable)) is None
    finally:
        await ingress.dispose()
        await unreachable.dispose()
    monkeypatch.setattr(Kek, "unwrap", lambda self, blob, aad: b"not the key")
    assert await self_check(keyring, worker_sessionmaker) is False


async def test_the_check_proves_the_claim_store_answers(pg_url, _test_users, worker_sessionmaker) -> None:
    """Engine 2b spec §2.7, `claim_check`: from 2b-1b the instance's role must read and write claims, grants and the
    secret index. The dispatcher's role reads data keys, but writes no step's claims: a definite failure."""
    keyring = Keyring(KekSet(Kek("k1", b"k" * 32)))
    assert "claim_check" in CAPABILITIES
    assert await self_check(keyring, worker_sessionmaker) is True
    dispatch = make_engine(_url_for(pg_url, "dewpoint_dispatch"))
    try:
        assert await self_check(keyring, make_sessionmaker(dispatch)) is False
    finally:
        await dispatch.dispose()
