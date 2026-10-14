# SPDX-License-Identifier: Apache-2.0
"""The silent standby's own guarantee: its block starts once a commit is seen waiting for the standby, however late the
server applies it, and never without one. The server applies the setting to commits only when its checkpointer
processes the reload, which a checkpoint running behind schedule defers (the logged suite run, 2026-10-13: 50 probes
committed in 1.4 s, during a 28 s checkpoint, and the block was refused). A role whose commits wait for no standby
stands in for that delay here: its new sessions commit without waiting until it is reset."""

import asyncio
import gc
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager

import asyncpg
import pytest

from tests.support import standby

LATE_S = 3.0  # longer than the 50 probes the helper allowed take when nothing waits: a few hundred milliseconds
WATCHER_FAILING = (  # the watcher's query: division by zero, once the probe is seen waiting
    "SELECT 1 / (CASE WHEN EXISTS (SELECT FROM pg_stat_activity WHERE pid = $1 AND wait_event = 'SyncRep')"
    " THEN 0 ELSE 1 END) = 0"
)


def plain(pg_url: str) -> str:
    return pg_url.replace("postgresql+asyncpg://", "postgresql://")


_NAMED = standby._named  # the real one, before any test replaces it


@pytest.fixture(autouse=True)
def no_standby_left_named(pg_url: str) -> Iterator[None]:
    """Whatever a test or a regression leaves, its server names no standby after it: the database fixtures' own
    teardown writes would wait for good. Each test asserts the helper's reset itself; this only keeps the suite
    going."""
    yield
    asyncio.run(_NAMED(plain(pg_url), None))


async def _altered(c: asyncpg.Connection, statement: str) -> None:
    """A role change whose own commit waits for no standby: once the standby is named, it would wait for good."""
    async with c.transaction():
        await c.execute("SET LOCAL synchronous_commit = local")
        await c.execute(statement)


@asynccontextmanager
async def waiting_for_no_standby(url: str, *, until: float | None) -> AsyncIterator[None]:
    """New sessions of the url's role commit without waiting for any standby, until `until` seconds have passed
    (None: throughout); the role as it was afterwards."""
    c = await asyncpg.connect(url)
    role = await c.fetchval("SELECT current_user")
    await _altered(c, f'ALTER ROLE "{role}" SET synchronous_commit = local')

    async def reset_later() -> None:
        assert until is not None
        await asyncio.sleep(until)
        await _altered(c, f'ALTER ROLE "{role}" RESET synchronous_commit')

    resetting = asyncio.create_task(reset_later()) if until is not None else None
    try:
        yield
    finally:
        if resetting is not None:
            resetting.cancel()
            await asyncio.gather(resetting, return_exceptions=True)
        await _altered(c, f'ALTER ROLE "{role}" RESET synchronous_commit')
        await c.close()


def test_a_standby_applied_late_starts_the_block_once_a_commit_is_seen_waiting(pg_url: str, _test_users: None) -> None:
    url = plain(pg_url)

    async def run() -> tuple[float, bool]:
        started = time.monotonic()
        check = await asyncpg.connect(url)
        async with waiting_for_no_standby(url, until=LATE_S):
            async with standby.silent_standby(url):
                took = time.monotonic() - started
                tx = check.transaction()  # a session of the block's own, after it started: its commit writes
                await tx.start()
                await check.fetchval("SELECT pg_logical_emit_message(true, 'dewpoint', 'check')")
                committing = asyncio.create_task(tx.commit())
                await asyncio.wait({committing}, timeout=1.0)
                waited = not committing.done()
            await asyncio.wait_for(committing, 30)  # let go once the block ended
        await check.close()
        return took, waited

    took, waited = asyncio.run(run())
    assert took >= LATE_S and waited


def test_a_standby_never_seen_waited_for_refuses_the_block_within_its_bound(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    monkeypatch.setattr(standby, "READY_S", 2.0)
    url = plain(pg_url)

    async def run() -> tuple[float, tuple[int, str]]:
        started = time.monotonic()
        async with waiting_for_no_standby(url, until=None):
            with pytest.raises(AssertionError, match="never waited for"):
                async with standby.silent_standby(url):
                    pass
        return time.monotonic() - started, await helpers_left(url)

    took, left = asyncio.run(run())
    assert 2.0 <= took < 10 and left == (0, "")


async def helpers_left(url: str) -> tuple[int, str]:
    """The helper's sessions still open (after up to 5 s for a closed one to end), and the standby named, as a new
    session sees it."""
    c = await asyncpg.connect(url)
    try:
        for _ in range(50):
            left = await c.fetchval("SELECT count(*) FROM pg_stat_activity WHERE application_name = $1", standby.NAME)
            if left == 0:
                break
            await asyncio.sleep(0.1)
        return left, await c.fetchval("SHOW synchronous_standby_names")
    finally:
        await c.close()


def test_a_probe_whose_commit_fails_is_reported_not_counted_as_a_commit(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """A probe that commits with an error tells nothing about the standby: the block is refused naming the error."""
    failing = (  # a unique key checked at commit, broken
        "CREATE TEMP TABLE probe_once (i int UNIQUE DEFERRABLE INITIALLY DEFERRED);"
        " INSERT INTO probe_once VALUES (1), (1);"
    )
    monkeypatch.setattr(standby, "_PROBE", f"{failing} {standby._PROBE}")
    url = plain(pg_url)

    async def run() -> tuple[int, str]:
        with pytest.raises(RuntimeError, match="UniqueViolation") as e:
            async with standby.silent_standby(url):
                pass
        assert "committed" not in str(e.value)
        return await helpers_left(url)

    assert asyncio.run(run()) == (0, "")


def test_a_stalled_probe_meets_the_deadline_while_it_waits(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    monkeypatch.setattr(standby, "READY_S", 1.0)
    monkeypatch.setattr(standby, "_PROBE", "SELECT pg_sleep(60)")  # neither commits nor waits for the standby
    url = plain(pg_url)

    async def run() -> tuple[float, tuple[int, str]]:
        started = time.monotonic()
        with pytest.raises(AssertionError, match="never waited for"):
            async with standby.silent_standby(url):
                pass
        return time.monotonic() - started, await helpers_left(url)

    took, left = asyncio.run(run())
    assert took < 10 and left == (0, "")


def test_the_block_raising_closes_the_helpers_sessions_and_names_no_standby(pg_url: str, _test_users: None) -> None:
    url = plain(pg_url)

    async def run() -> tuple[int, str]:
        with pytest.raises(KeyError):
            async with standby.silent_standby(url):
                raise KeyError("the block's own failure")
        return await helpers_left(url)

    assert asyncio.run(run()) == (0, "")


def test_a_failure_naming_the_standby_still_resets_it_and_closes_the_helpers_sessions(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The setting written, then the naming fails (its reload, say): the helper resets it and leaves no session."""
    named = standby._named

    async def failing(url: str, names: str | None) -> None:
        await named(url, names)
        if names is not None:
            raise ConnectionResetError("lost after naming the standby")

    monkeypatch.setattr(standby, "_named", failing)
    url = plain(pg_url)

    async def run() -> tuple[int, str]:
        try:
            with pytest.raises(ConnectionResetError):
                async with standby.silent_standby(url):
                    pass
            return await helpers_left(url)
        finally:
            await named(url, None)  # whatever the helper left: the suite's later writes would wait for good

    assert asyncio.run(run()) == (0, "")


def running_at(monkeypatch: pytest.MonkeyPatch, step: str) -> list[list[asyncio.Task[object]]]:
    """Each time the helper's `step` begins: its probes' commits then still running (one must be settled before its
    session is ended)."""
    found: list[list[asyncio.Task[object]]] = []
    real = getattr(standby, step)

    async def spied(*args: object, **kwargs: object) -> None:
        found.append([t for t in asyncio.all_tasks() if not t.done() and _committing(t)])
        await real(*args, **kwargs)

    monkeypatch.setattr(standby, step, spied)
    return found


def _committing(task: asyncio.Task[object]) -> bool:
    return getattr(task.get_coro(), "__qualname__", "") == "Transaction.commit"


def refused_resets(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str | None], Awaitable[None]]:
    """Every reset of the standby refused; the real naming, for the test's own reset."""
    named = standby._named

    async def refusing(url: str, names: str | None) -> None:
        if names is None:
            raise ConnectionRefusedError("the reset refused")
        await named(url, names)

    monkeypatch.setattr(standby, "_named", refusing)
    return named


def test_a_reset_failing_while_the_block_fails_is_noted_on_the_blocks_failure(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The block's failure stays the one raised; the reset's is noted on it, saying the standby is still named. The
    held commit, still waiting, is settled before the server ends the helper's sessions, which end all the same."""
    named, url = refused_resets(monkeypatch), plain(pg_url)
    ending = running_at(monkeypatch, "_terminated")

    async def run() -> tuple[list[str], tuple[int, str]]:
        try:
            with pytest.raises(KeyError) as e:
                async with standby.silent_standby(url):
                    raise KeyError("the block's own failure")
            return getattr(e.value, "__notes__", []), await helpers_left(url)
        finally:
            await named(url, None)  # the reset the helper couldn't make

    notes, left = asyncio.run(run())
    assert any("couldn't be reset" in n and "still named" in n for n in notes), notes
    assert left == (0, "nobody") and ending == [[]]


def test_a_reset_failing_after_the_block_is_reported_as_such(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    named, url = refused_resets(monkeypatch), plain(pg_url)

    async def run() -> tuple[int, str]:
        try:
            with pytest.raises(RuntimeError, match="couldn't be reset.*still named") as e:
                async with standby.silent_standby(url):
                    pass
            assert isinstance(e.value.__cause__, ConnectionRefusedError)
            return await helpers_left(url)
        finally:
            await named(url, None)

    assert asyncio.run(run()) == (0, "nobody")


def test_a_watcher_failing_while_a_probe_commits_cancels_and_awaits_that_commit(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The watcher fails once the probe's commit waits for the standby: that's what is reported, and the commit is
    cancelled and awaited before the helper's cleanup begins (no task of the helper's running then, nor after)."""
    monkeypatch.setattr(standby, "_SYNC_REP", WATCHER_FAILING)
    url = plain(pg_url)
    cleanup = running_at(monkeypatch, "_ended")

    async def run() -> tuple[list[asyncio.Task[object]], tuple[int, str]]:
        with pytest.raises(RuntimeError, match="the watcher failed"):
            async with standby.silent_standby(url):
                pass
        running = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        return running, await helpers_left(url)

    assert asyncio.run(run()) == ([], (0, "")) and cleanup == [[]]


def closing_probes(
    monkeypatch: pytest.MonkeyPatch, close_probe: Callable[..., Awaitable[None]]
) -> list[asyncpg.Connection]:
    """A probe's close is `close_probe(real close, connection, its timeout)`; every other session of the helper's
    closes as usual. The probes are the sessions it opens after its watcher, kept here: only the helper's cleanup ends
    one, never the collector."""
    opened, close, probes = standby._opened, asyncpg.Connection.close, []

    async def tracking(url: str, held: standby._Held) -> asyncpg.Connection:
        c = await opened(url, held)
        if len(held.opened) > 1:
            probes.append(c)
        return c

    async def closing(self: asyncpg.Connection, *, timeout: float | None = None) -> None:  # noqa: ASYNC109 -- close's own
        if any(self is probe for probe in probes):
            return await close_probe(close, self, timeout)
        await close(self, timeout=timeout)

    monkeypatch.setattr(standby, "_opened", tracking)
    monkeypatch.setattr(asyncpg.Connection, "close", closing)
    return probes


def failing_probe_closes(monkeypatch: pytest.MonkeyPatch) -> list[asyncpg.Connection]:
    """A probe's close fails in asyncpg's own close: it can't finish in a microsecond, so asyncpg aborts the connection
    (its protocol gone, as when the deadline cancels a close: seen in the parallel suite, where cleanup then crashed
    asking that connection its server pid, reset nothing, and the suite hung on the standby left named)."""

    async def failing(close: Callable[..., Awaitable[None]], c: asyncpg.Connection, within: float | None) -> None:
        await close(c, timeout=1e-6)

    return closing_probes(monkeypatch, failing)


def test_a_probe_whose_session_fails_to_close_is_reported_and_its_session_ended(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """A probe commits without waiting (its role's commits wait for no standby), then its close fails: that's what is
    reported, and its session, still the helper's, is ended by cleanup."""
    probes, url = failing_probe_closes(monkeypatch), plain(pg_url)

    async def run() -> tuple[int, str]:
        try:
            async with waiting_for_no_standby(url, until=None):
                with pytest.raises(standby.StandbyError, match="couldn't be closed"):
                    async with standby.silent_standby(url):
                        pass
            return await helpers_left(url)
        finally:
            for probe in probes:  # the test's own references, let go
                probe.terminate()

    assert asyncio.run(run()) == (0, "")


def stubborn_commits(
    monkeypatch: pytest.MonkeyPatch, *, after_cancel_s: float, then: BaseException | None = None
) -> None:
    """A probe's commit, once cancelled, still runs `after_cancel_s` before it ends (cancelled, or failing with `then`);
    the helper waits half a second for a cancelled commit (CANCEL_S), so it finds one still pending."""
    commit = asyncpg.transaction.Transaction.commit

    async def stubborn(self: asyncpg.transaction.Transaction) -> None:
        try:
            await commit(self)
        except asyncio.CancelledError:
            await asyncio.sleep(after_cancel_s)
            if then is not None:
                raise then from None
            raise

    monkeypatch.setattr(asyncpg.transaction.Transaction, "commit", stubborn)
    monkeypatch.setattr(standby, "CANCEL_S", 0.5)


def test_a_probes_commit_still_pending_after_its_cancel_is_reported_and_its_session_ended(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The watcher fails while the probe's commit waits; cancelled, the commit is still pending past the helper's
    wait for it, and past cleanup's after its session is ended: both noted on the watcher's failure; the session ended
    all the same."""
    stubborn_commits(monkeypatch, after_cancel_s=3.0)
    monkeypatch.setattr(standby, "_SYNC_REP", WATCHER_FAILING)
    url = plain(pg_url)

    async def run() -> tuple[list[str], tuple[int, str]]:
        with pytest.raises(standby.StandbyError, match="the watcher failed") as e:
            async with standby.silent_standby(url):
                pass
        return getattr(e.value, "__notes__", []), await helpers_left(url)

    notes, left = asyncio.run(run())
    assert any("didn't settle" in n for n in notes), notes
    assert any("still pending after its session was ended" in n for n in notes), notes  # 3 s: past cleanup's wait too
    assert left == (0, "")


def test_a_held_commit_still_pending_after_its_cancel_is_reported_on_the_failure(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The reset refused while the block fails, so the held commit is cancelled; still pending past the helper's wait
    for it, it's noted on the block's failure beside the reset's, and its session ended all the same."""
    named, url = refused_resets(monkeypatch), plain(pg_url)
    stubborn_commits(monkeypatch, after_cancel_s=3.0)

    async def run() -> tuple[list[str], tuple[int, str]]:
        try:
            with pytest.raises(KeyError) as e:
                async with standby.silent_standby(url):
                    raise KeyError("the block's own failure")
            return getattr(e.value, "__notes__", []), await helpers_left(url)
        finally:
            await named(url, None)

    notes, left = asyncio.run(run())
    assert any("couldn't be reset" in n for n in notes) and any("didn't settle" in n for n in notes), notes
    assert left == (0, "nobody")


def test_a_reset_slower_than_the_readiness_deadline_still_completes(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """Cleanup's reset has a bound of its own: refused within a 2 s deadline, the helper resets the standby though the
    reset takes 3 s (bounded by the deadline, it was cut off half done, the standby left named)."""

    async def slow(url: str, names: str | None) -> None:
        if names is None:
            await asyncio.sleep(3)
        await _NAMED(url, names)

    monkeypatch.setattr(standby, "READY_S", 2.0)
    monkeypatch.setattr(standby, "_named", slow)
    url = plain(pg_url)

    async def run() -> tuple[int, str]:
        async with waiting_for_no_standby(url, until=None):
            with pytest.raises(AssertionError, match="never waited for") as e:
                async with standby.silent_standby(url):
                    pass
        assert not getattr(e.value, "__notes__", []), e.value.__notes__
        return await helpers_left(url)

    assert asyncio.run(run()) == (0, "")


class LateFailure(Exception):
    """A pending commit's own failure, once the helper has returned."""


def test_a_commit_failing_after_the_helper_returned_has_its_failure_observed_and_logged(
    pg_url: str, _test_users: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # fmt: skip
    """The watcher fails while the probe's commit waits; cancelled, the commit is still pending after cleanup's last
    wait, and fails 4 s after its cancel, the helper long returned. Nothing here awaits it: the helper's own observer
    logs the late failure (its type: no message, as every log line), so asyncio finds no exception left unretrieved."""
    stubborn_commits(monkeypatch, after_cancel_s=4.0, then=LateFailure("the commit's late failure"))
    monkeypatch.setattr(standby, "_SYNC_REP", WATCHER_FAILING)
    url = plain(pg_url)
    unretrieved: list[dict[str, object]] = []

    async def run() -> tuple[list[str], tuple[int, str]]:
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: unretrieved.append(context))
        with pytest.raises(standby.StandbyError, match="the watcher failed") as e:
            async with standby.silent_standby(url):
                pass
        notes = getattr(e.value, "__notes__", [])
        del e
        await asyncio.sleep(6)  # the late failure lands while this loop still runs; nothing awaits the commit
        gc.collect()  # a failed task no one retrieved reports itself as it's collected
        return notes, await helpers_left(url)

    with caplog.at_level(logging.WARNING, logger=standby.__name__):
        notes, left = asyncio.run(run())
    assert any("still pending after its session was ended" in n for n in notes), notes
    late = [r.getMessage() for r in caplog.records if r.name == standby.__name__]
    assert late == ["a probe's commit the helper left pending ended: failed (LateFailure)"], late
    assert unretrieved == [] and left == (0, "")
