# SPDX-License-Identifier: Apache-2.0
"""Online migrations (the 2b-4b plan's M1a; the owner's D15, option B). A migration that runs against a deployment in
use commits in short steps instead of holding its locks to its end, so normal readers and writers never wait long
behind it, and a writer's lock order can't deadlock it into rolling everything back.

- `step`: what a migration changes in the catalogue together (its tables, policies, grants, triggers, functions), in
  one transaction, its statements in their original order, so every committed state keeps each boundary whole: a
  table never exists without its row-level security, a privilege never without the restrictive policy that bounds
  it, a key never dropped before its replacement exists. A step's transaction lasts at most its budget, `SHARE` of the
  server's `deadlock_timeout`: each statement's lock and statement timeouts are what's left of it. So a normal
  operation queued behind it waits less than that, and a writer whose lock the step waits for never waits long enough
  for the server's deadlock check: the step gives way first. A lock not taken in time, a deadlock, or the budget spent
  rolls the step back whole; it's tried again after a growing, jittered pause, at most `ATTEMPTS` times, each
  giving-way logged, then the upgrade stops, naming it (`StepFailedError`). A step whose `done` query says it
  committed already is skipped: an interrupted migration runs again from its start (Alembic records it only at its
  end).
- `batches`: a backfill in committed batches of `BATCH` rows, each a step, each taking rows not done yet.
- `plain`: one statement outside any transaction, whose locks block no normal read or write (`CREATE INDEX
  CONCURRENTLY`, `VALIDATE CONSTRAINT`), each lock waiting at most `LOCK_PLAIN`, retried the same way.
- `index`: an index built concurrently, an invalid one an interrupted build left behind dropped first.

`AFTER` holds hooks called with each committed step's (or statement's) name: the tests check each boundary there.
Logs name a step, its attempt and why it gave way, never a value."""

import logging
import random
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

SHARE = 0.6  # a step's budget: this share of the server's deadlock_timeout
MARGIN_MS = 50  # a statement's timeout past its lock timeout
LOCK_PLAIN = "5s"  # what a statement outside a step waits for each of its locks
ATTEMPTS = 60  # a step's tries before the upgrade stops, naming it
PAUSE_S = (0.05, 2.0)  # the pause between tries: doubling from the first, at most the second, jittered
BATCH = 1_000  # rows a backfill's batch
GIVE_WAY = {"55P03": "lock", "40P01": "deadlock", "57014": "budget"}  # lock_not_available, deadlock, canceled
INVALID = (
    "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
    "WHERE c.relname = :n AND c.relnamespace = 'public'::regnamespace"
)

AFTER: list[Callable[[Connection, str], None]] = []
log = logging.getLogger("alembic.online")


class StepFailedError(RuntimeError):
    """A step that gave way `ATTEMPTS` times: the upgrade stops, naming it."""


class _Budget(Exception):
    pass


@contextmanager
def online() -> Iterator[Connection]:
    """The migration's statements from here run in the steps below, each committing on its own (Alembic's autocommit
    block). Row-level security is off for the session: a migrating role it would apply to errors rather than read or
    write only some tenants' rows."""
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        conn.execute(text("SET row_security = off"))
        conn.execute(text(f"SET lock_timeout = '{LOCK_PLAIN}'"))
        try:
            yield conn
        finally:
            conn.execute(text("RESET lock_timeout"))
            conn.execute(text("RESET row_security"))


def _budget(conn: Connection) -> float:
    if "online_budget" not in conn.info:
        ms = conn.execute(text("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")).scalar_one()
        conn.info["online_budget"] = SHARE * ms / 1000
    budget: float = conn.info["online_budget"]
    return budget


def _why(e: BaseException) -> str | None:
    if isinstance(e, _Budget):
        return "budget"
    return GIVE_WAY.get(getattr(getattr(e, "orig", None), "sqlstate", None) or "")


def _tried(conn: Connection, name: str, once: Callable[[], Any], done: str | None) -> None:
    """`once` until it doesn't give way, at most `ATTEMPTS` times; then the hooks."""
    if done is not None and conn.execute(text(done)).scalar():
        log.info("online step %s: done already", name)
        return
    for attempt in range(1, ATTEMPTS + 1):
        started = time.monotonic()
        try:
            once()
        except (DBAPIError, _Budget) as e:
            why = _why(e)
            if why is None:
                raise
            if attempt == ATTEMPTS:
                raise StepFailedError(f"online step {name} gave way {ATTEMPTS} times ({why})") from e
            log.warning("online step %s: attempt %d gave way (%s)", name, attempt, why)
            pause = min(PAUSE_S[1], PAUSE_S[0] * 2 ** (attempt - 1))
            time.sleep(pause * random.uniform(0.5, 1.0))  # noqa: S311  # jitter, no security meaning
            continue
        log.info("online step %s: committed (attempt %d, %.3f s)", name, attempt, time.monotonic() - started)
        for hook in AFTER:
            hook(conn, name)
        return


def step(conn: Connection, name: str, *actions: str | Callable[[], object], done: str | None = None) -> None:
    """`actions` (statements, or callables issuing them: Alembic's operations) in one transaction, as above."""
    budget = _budget(conn)

    def once() -> None:
        started = time.monotonic()
        conn.execute(text("BEGIN"))
        try:
            for action in actions:
                left = budget - (time.monotonic() - started)
                if left <= 0:
                    raise _Budget
                ms = max(1, int(left * 1000))  # a lock not taken gives way as such, just before the statement does
                conn.execute(text("SELECT set_config('lock_timeout', :l, true), set_config('statement_timeout', :s, "
                                  "true)"), {"l": f"{ms}ms", "s": f"{ms + MARGIN_MS}ms"})  # fmt: skip
                if isinstance(action, str):
                    conn.execute(text(action))
                else:
                    action()
        except BaseException:
            conn.execute(text("ROLLBACK"))
            raise
        conn.execute(text("COMMIT"))

    _tried(conn, name, once, done)


def plain(conn: Connection, name: str, statement: str, *, done: str | None = None) -> None:
    """One statement outside any transaction, retried as a step is."""
    _tried(conn, name, lambda: conn.execute(text(statement)), done)


def index(conn: Connection, name: str, create: str, *, done: str | None = None) -> None:
    """`create`, a `CREATE [UNIQUE] INDEX CONCURRENTLY IF NOT EXISTS <index> …`, which blocks no reads or writes. An
    invalid index of that name, which an interrupted or failed build leaves behind, is dropped first."""
    built = re.search(r"INDEX CONCURRENTLY IF NOT EXISTS (\w+)", create)
    if built is None:
        raise ValueError(f"online step {name}: not a concurrent build")

    def once() -> None:
        if conn.execute(text(INVALID), {"n": built[1]}).scalar():
            conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {built[1]}"))
        conn.execute(text(create))

    _tried(conn, name, once, done)


def batches(conn: Connection, name: str, bounds: str, apply: str, *, first: Any, size: int | None = None) -> int:
    """A backfill, batch by batch, each its own step: `bounds` (`:after`, `:n`) gives the last key and the count of
    the next `:n` rows not done yet past `:after`, from `first`; `apply` (`:after`, `:hi`) does those. It ends after a
    batch of fewer than `size` rows, and returns how many it took. Resumable: an interrupted backfill's committed batches
    stay done, and `bounds` doesn't take them again."""
    size = size or BATCH
    after, total, k = first, 0, 0
    while True:
        k += 1
        taken: dict[str, Any] = {}

        def once(after: Any = after, taken: dict[str, Any] = taken) -> None:
            hi, n = conn.execute(text(bounds), {"after": after, "n": size}).one()
            if n:
                conn.execute(text(apply), {"after": after, "hi": hi})
            taken.update(hi=hi, n=n)

        step(conn, f"{name} (batch {k})", once)
        total += taken["n"]
        if taken["n"] < size:
            return total
        after = taken["hi"]


def exists(kind: str, name: str, table: str = "") -> str:
    """A `done` query: whether the table or index, the constraint, the column of `table` or the policy on `table`, the
    trigger on `table`, or the function (its signature) is there."""
    return {
        "relation": f"SELECT to_regclass('public.{name}') IS NOT NULL",
        "constraint": f"SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}' "
        "AND connamespace = 'public'::regnamespace)",
        "column": f"SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('public.{table}') "
        f"AND attname = '{name}' AND NOT attisdropped)",
        "policy": f"SELECT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = '{table}' "
        f"AND policyname = '{name}')",
        "trigger": f"SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass('public.{table}') "
        f"AND tgname = '{name}')",
        "function": f"SELECT to_regprocedure('public.{name}') IS NOT NULL",
    }[kind]
