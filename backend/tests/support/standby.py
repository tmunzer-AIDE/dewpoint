# SPDX-License-Identifier: Apache-2.0
"""A synchronous standby that never answers, named on a test's Postgres for a block: a commit that writes waits for it
(under `synchronous_commit` on), with the locks its transaction holds, until the block ends and the helper names none
again.

The setting reaches commits only once the server has reloaded it (its checkpointer marks the standby defined), so the
block starts once a probe's commit is seen waiting for the standby: its session's wait event `SyncRep`, not merely a
slow commit (a WAL flush under load can take longer than any wait the helper would allow it). How soon the server
applies it isn't the helper's to choose: a checkpointer in a checkpoint behind schedule processes the reload once the
checkpoint ends (the logged suite run, 2026-10-13: 50 probes committed in 1.4 s, during a 28 s checkpoint). So probes go
on, each that committed closed at once, until one is seen waiting; none seen within READY_S, which bounds every wait (a
connect, the naming, a probe's statement or commit, the watcher), the block is refused. A probe that fails tells nothing
about the standby: it's reported, never taken for a commit.

Every exit, the block's failure and the helper's own included, attempts to reset the standby, letting go every commit
waiting for it, and ends every session of the helper's, a commit still under way cancelled and awaited first. A reset
that fails is reported, the standby then still named: on the failure already raised, or as the helper's own. For a
container of the test's own: the setting is the server's, every database's (tests in one worker run one at a time)."""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import AsyncIterator

import asyncpg

POLL_S = 0.05  # how often a probe's session is looked at while its commit runs
# How long the server may take to apply it: a timed checkpoint spreads its writes over most of `checkpoint_timeout`
# (5 min by default) and syncs after them; the logged runs saw one of 228 s (175 s writing, 50 s syncing)
READY_S = 360.0
NAME = "silent-standby"  # every session of the helper's, by its application_name
CANCEL_S = 5.0  # how long a cancelled commit of the helper's is awaited before its session is closed
# How long each of cleanup's own statements may take, the reset's and the server's ending of the helper's sessions:
# not READY_S, the readiness deadline (a test shortens it); letting commits go once reset is the server's, READY_S
CLEANUP_S = 30.0
# a probe's write: its commit writes (an xid alone writes nothing, and waits for no standby)
_PROBE = "SELECT pg_logical_emit_message(true, 'dewpoint', 'probe')"


_SYNC_REP = "SELECT EXISTS (SELECT FROM pg_stat_activity WHERE pid = $1 AND wait_event = 'SyncRep')"
_END = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid = ANY($1::int[]) AND application_name = $2"
_CHECKPOINTER = (
    "SELECT a.wait_event_type, a.wait_event, b.checkpoints_timed, b.checkpoints_req FROM pg_stat_activity a, "
    "pg_stat_bgwriter b WHERE a.backend_type = 'checkpointer'"
)


_LOG = logging.getLogger(__name__)


class StandbyError(RuntimeError):
    """The helper's own failure: a probe's, the watcher's, or its cleanup's."""


def _said(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


async def _connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(url, server_settings={"application_name": NAME})


async def _named(url: str, names: str | None) -> None:
    c = await _connect(url)
    try:
        if names is None:
            await c.execute("ALTER SYSTEM RESET synchronous_standby_names")
        else:
            await c.execute(f"ALTER SYSTEM SET synchronous_standby_names = '{names}'")
        await c.execute("SELECT pg_reload_conf()")
    finally:
        await c.close()


@dataclasses.dataclass
class _Held:
    """What the helper holds, for its cleanup: its sessions not yet closed, its commits a cancel hasn't settled yet, its
    probes so far, and the problems to report."""

    opened: list[asyncpg.Connection] = dataclasses.field(default_factory=list)
    pids: list[int] = dataclasses.field(
        default_factory=list
    )  # each session's, taken as it opened: a closed one has none
    unsettled: list[asyncio.Task[None]] = dataclasses.field(default_factory=list)
    problems: list[tuple[str, BaseException | None]] = dataclasses.field(default_factory=list)
    probes: int = 0


@contextlib.asynccontextmanager
async def silent_standby(url: str) -> AsyncIterator[None]:
    """`url`: a plain `postgresql://` one, a superuser's."""
    held = _Held()
    waiting: asyncio.Task[None] | None = None  # the probe's commit seen waiting for the standby, held through the block
    try:
        try:
            async with asyncio.timeout(READY_S):  # every wait: a connect, the naming, a probe, the watcher
                watcher = await _opened(url, held)
                await _named(url, "nobody")
                waiting = await _seen_waiting(url, watcher, held)
        except TimeoutError:
            raise AssertionError(
                f"the standby was never waited for: {held.probes} probes in {READY_S:.0f} s; the checkpointer "
                f"meanwhile: {await _checkpointer(url)}"
            ) from None
        yield
    except BaseException as e:
        await _ended(url, waiting, held, failing=e)  # that failure stays the one raised
        raise
    await _ended(url, waiting, held, failing=None)


async def _opened(url: str, held: _Held) -> asyncpg.Connection:
    c = await _connect(url)
    held.opened.append(c)
    held.pids.append(c.get_server_pid())
    return c


async def _seen_waiting(url: str, watcher: asyncpg.Connection, held: _Held) -> asyncio.Task[None]:
    """Probes until one's commit is seen waiting for the standby; each that committed is closed at once, and the
    helper holds it no more only once closed. A probe that fails, its write or its commit, tells nothing about the
    standby: it is reported, never taken for a commit; so is a probe whose session won't close (cleanup ends it)."""
    while True:
        probe = await _opened(url, held)
        held.probes += 1
        committing: asyncio.Task[None] | None = None
        try:
            tx = probe.transaction()
            await tx.start()
            await probe.execute(_PROBE)
            committing = asyncio.create_task(tx.commit())
            while not committing.done():
                if await _watched(watcher, probe, held.probes):
                    return committing
                await asyncio.wait({committing}, timeout=POLL_S)
            committing.result()
        except BaseException as e:  # the deadline, the watcher, or the probe: a commit under way is settled first
            await _settled(committing, held)
            if isinstance(e, Exception) and not isinstance(e, StandbyError):
                failure = f"probe {held.probes} failed ({_said(e)}): it tells nothing about the standby"
                raise StandbyError(failure) from e
            raise
        try:
            await probe.close()
        except Exception as e:
            raise StandbyError(f"probe {held.probes}'s session couldn't be closed ({_said(e)})") from e
        held.opened.remove(probe)


async def _watched(watcher: asyncpg.Connection, probe: asyncpg.Connection, n: int) -> bool:
    """The probe's session is waiting for the standby (its wait event `SyncRep`)."""
    try:
        return bool(await watcher.fetchval(_SYNC_REP, probe.get_server_pid()))
    except Exception as e:
        raise StandbyError(f"the watcher failed ({_said(e)}) while probe {n} committed") from e


async def _settled(commit: asyncio.Task[None] | None, held: _Held) -> None:
    """A commit of the helper's still under way is cancelled and awaited (within CANCEL_S) before its session is
    ended, its outcome retrieved. One its cancel hasn't settled by then is reported and kept: cleanup ends its session
    under it, then awaits it once more."""
    if commit is None:
        return
    if not commit.done():
        commit.cancel()
        await asyncio.wait({commit}, timeout=CANCEL_S)
    if not commit.done():
        held.unsettled.append(commit)
        held.problems.append((f"a probe's commit didn't settle within {CANCEL_S:g} s of its cancel", None))
    elif not commit.cancelled():
        commit.exception()


async def _ended(url: str, waiting: asyncio.Task[None] | None, held: _Held, *, failing: BaseException | None) -> None:
    """Every exit attempts: the standby reset, the held commit let go (so the reset has reached commits), and every
    session of the helper's ended: a commit still under way settled first, then the server asked to end each session
    still there (one waiting for a standby still named doesn't notice its client going), then each closed, then a commit
    a cancel hadn't settled awaited once more; one still pending then is left to `_observed_late`. Whatever fails is
    reported, the standby perhaps still named: noted on the failure already raised (`failing`), which stays the one
    raised, or raised as the helper's own."""
    try:
        try:
            await asyncio.wait_for(_named(url, None), CLEANUP_S)  # none named: every commit waiting for one is let go
        except Exception as e:
            unreset = f"the standby couldn't be reset ({_said(e)}): it is still named, commits wait for it"
            held.problems.append((unreset, e))
        else:
            if waiting is not None:
                try:
                    await asyncio.wait_for(waiting, READY_S)
                except Exception as e:
                    held.problems.append((f"the held probe's commit wasn't let go ({_said(e)})", e))
        await _settled(waiting, held)
        try:
            await asyncio.wait_for(_terminated(url, held.pids), CLEANUP_S)
        except Exception as e:
            held.problems.append((f"the helper's sessions couldn't be ended by the server ({_said(e)})", e))
    finally:
        for c in held.opened:
            try:
                c.terminate()  # one closed already, or aborted by asyncpg, is let go all the same
            except Exception as e:
                held.problems.append((f"a session of the helper's couldn't be closed ({_said(e)})", e))
    if held.unsettled:
        await asyncio.wait(held.unsettled, timeout=CANCEL_S)
        for commit in held.unsettled:
            if not commit.done():
                commit.add_done_callback(_observed_late)
                late = (
                    "a probe's commit was still pending after its session was ended: its outcome is logged as it ends"
                )
                held.problems.append((late, None))
            elif not commit.cancelled():
                commit.exception()
    if not held.problems:
        return
    if failing is not None:
        for problem, _ in held.problems:
            failing.add_note(problem)
        return
    cause = next((c for _, c in held.problems if c is not None), None)
    raise StandbyError("; ".join(problem for problem, _ in held.problems)) from cause


def _observed_late(commit: asyncio.Task[None]) -> None:
    """A commit of the helper's still pending when it returned, as it ends, however late: its outcome retrieved and
    logged (its type, no message, as every log line). Nothing waits for it."""
    if commit.cancelled():
        outcome = "cancelled"
    elif (e := commit.exception()) is not None:
        outcome = f"failed ({type(e).__name__})"
    else:
        outcome = "committed"
    _LOG.warning("a probe's commit the helper left pending ended: %s", outcome)


async def _terminated(url: str, pids: list[int]) -> None:
    """The server ends each of these sessions of the helper's still there, whatever it's doing."""
    c = await _connect(url)
    try:
        await c.execute(_END, pids, NAME)
    finally:
        await c.close()


async def _checkpointer(url: str) -> dict[str, object] | str:
    """What the checkpointer is doing, for a refusal's message (a reload reaches commits through it)."""
    try:
        c = await asyncio.wait_for(_connect(url), 5)
        try:
            row = await asyncio.wait_for(c.fetchrow(_CHECKPOINTER), 5)
        finally:
            c.terminate()
    except Exception as e:  # noqa: BLE001 -- a message's detail: the refusal stands either way
        return f"unknown ({type(e).__name__})"
    return dict(row) if row else "none found"
