# SPDX-License-Identifier: Apache-2.0
"""Online migrations (the 2b-4b plan's M1a; the owner's D15, option B). A migration that runs against a deployment in
use commits in short steps instead of holding its locks to its end, so normal readers and writers never wait long
behind it, and a writer's lock order can't deadlock it into rolling everything back.

- `step`: what a migration changes in the catalogue together (its tables, policies, triggers, functions), in one
  transaction, its statements in their original order, so every committed state keeps each boundary whole: a table
  never exists without its row-level security, a key never dropped before its replacement exists. A migration grants
  last, in its last step (`grants`, `ungranted`), once everything that bounds what it grants is committed: its
  restrictive policies, its triggers. A step locks at most one table in use (a grant locks none), but for 0035's keys,
  which take both their table and the one they reference, and a new table's keys, which share what they reference.
- A step's transaction lasts at most its budget, `SHARE` of the shortest `deadlock_timeout` any role or the database
  has: each statement's lock timeout is what's left of it (its statement timeout, `MARGIN` of that `deadlock_timeout`
  more). So a normal operation queued behind it waits less than that, and a writer whose lock the step waits for never
  waits long enough for its own deadlock check: the step gives way first. A lock not taken in time, a deadlock, or the
  budget spent rolls the step back whole; it's tried again after a growing, jittered pause, at most `ATTEMPTS` times,
  each giving-way logged, then the upgrade stops, naming it (`StepFailedError`); a statement cancelled on purpose
  stops it at once. A role that may sets each step's own `deadlock_timeout` to a third of its budget: the server,
  checking the lock a step waits for, then cancels the autovacuum blocking it, and only that one (it otherwise would
  only once the request had waited `deadlock_timeout`, which a step never does). A step whose `done` query says it
  committed already is skipped: an interrupted migration runs again from its start (Alembic records it only at its
  end).
- `batches`: a backfill in committed batches of `BATCH` rows, each taking rows not done yet: finding them outside any
  step (it waits for no normal operation), applying them in one.
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
MARGIN = 0.05  # a statement's timeout past its lock timeout: this share of deadlock_timeout (50 ms at its default)
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


# Every `deadlock_timeout` a session of this database may run with: this one's, each role's and the database's own
# (`ALTER ROLE`, `ALTER DATABASE`), and the server's files' (when this role may read them). A role can't set its own in
# a session without the privilege to (a superuser parameter).
TIMEOUTS = """SELECT setting || 'ms' FROM pg_settings WHERE name = 'deadlock_timeout'
UNION ALL
SELECT substr(c, length('deadlock_timeout=') + 1) FROM pg_db_role_setting s, unnest(s.setconfig) c
WHERE s.setdatabase IN (0, (SELECT oid FROM pg_database WHERE datname = current_database()))
  AND starts_with(c, 'deadlock_timeout=')"""
FILES = "SELECT setting FROM pg_file_settings WHERE name = 'deadlock_timeout' AND applied"
UNITS = {"us": 0.001, "ms": 1, "s": 1_000, "min": 60_000, "h": 3_600_000, "d": 86_400_000}


def _ms(value: str) -> float:
    """A `deadlock_timeout` as configured ('200ms', '1s', '1000': milliseconds), in milliseconds."""
    found = re.fullmatch(r"([0-9.]+)\s*([a-z]*)", value.strip().strip("'\""))
    if found is None or found[2] not in ("", *UNITS):
        raise ValueError(f"a deadlock_timeout this module can't read: {value!r}")
    return float(found[1]) * UNITS.get(found[2], 1)


def _budget(conn: Connection) -> float:
    """A step's budget, in seconds: `SHARE` of the shortest `deadlock_timeout` any session of this database may have,
    so no writer's deadlock check comes before the step gives way, whatever its role."""
    if "online_budget" not in conn.info:
        values = list(conn.execute(text(TIMEOUTS)).scalars())
        try:
            values += list(conn.execute(text(FILES)).scalars())
        except DBAPIError:  # only a role that may read the server's files: its session's setting stands in for them
            pass
        conn.info["online_budget"] = SHARE * min(_ms(v) for v in values) / 1000
    budget: float = conn.info["online_budget"]
    return budget


def _why(e: BaseException) -> str | None:
    """Why a step gave way, or None: an error that stops the upgrade (a cancel on purpose among them)."""
    if isinstance(e, _Budget):
        return "budget"
    orig = getattr(e, "orig", None)
    if "user request" in str(orig):  # 57014 by `pg_cancel_backend`, not a timeout
        return None
    return GIVE_WAY.get(getattr(orig, "sqlstate", None) or "")


def _detects(conn: Connection) -> bool:
    """Whether this role may set its own `deadlock_timeout` (a superuser's parameter, unless granted `SET` on it):
    then each step sets it shorter than its budget, and the server, checking the lock a step waits for, cancels the
    autovacuum that blocks it (never one against wraparound) and no other; a cycle makes the step its victim. Else a
    step behind an autovacuum gives way and tries again, said once."""
    if "online_detects" not in conn.info:
        conn.info["online_detects"] = bool(conn.execute(text(
            "SELECT has_parameter_privilege('deadlock_timeout', 'SET')")).scalar())  # fmt: skip
        if not conn.info["online_detects"]:
            log.warning("online steps: this role may not set deadlock_timeout, so an autovacuum a step waits for is "
                        "waited out (the step gives way and tries again)")  # fmt: skip
    detects: bool = conn.info["online_detects"]
    return detects


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
    detects = _detects(conn)

    def once() -> None:
        started = time.monotonic()
        conn.execute(text("BEGIN"))
        try:
            if detects:
                conn.execute(text("SELECT set_config('deadlock_timeout', :d, true)"),
                             {"d": f"{max(1, int(budget * 1000 / 3))}ms"})  # fmt: skip
            for action in actions:
                left = budget - (time.monotonic() - started)
                if left <= 0:
                    raise _Budget
                ms = max(1, int(left * 1000))  # a lock not taken gives way as such, just before the statement does
                margin = max(1, int(budget / SHARE * MARGIN * 1000))
                conn.execute(text("SELECT set_config('lock_timeout', :l, true), set_config('statement_timeout', :s, "
                                  "true)"), {"l": f"{ms}ms", "s": f"{ms + margin}ms"})  # fmt: skip
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
    """A backfill, batch by batch: `bounds` (`:after`, `:n`) gives the last key and the count of the next `:n` rows not
    done yet past `:after`, from `first`; `apply` (`:after`, `:hi`) does those, in a step of its own. Finding them takes
    no lock a normal operation waits for, so it runs outside the step and its budget (a resumed backfill's first
    search reads past every row done already). It ends after a batch of fewer than `size` rows, and returns how many it
    took. Resumable: an interrupted backfill's committed batches stay done, and `bounds` doesn't take them again."""
    size = size or BATCH
    after, total, k = first, 0, 0
    while True:
        k += 1
        hi, n = conn.execute(text(bounds), {"after": after, "n": size}).one()
        if n:

            def once(after: Any = after, hi: Any = hi) -> None:
                conn.execute(text(apply), {"after": after, "hi": hi})

            step(conn, f"{name} (batch {k})", once)
        total += int(n)
        if n < size:
            return total
        after = hi


def _granting(action: str | Callable[[], object]) -> bool:
    return isinstance(action, str) and action.lstrip().upper().startswith("GRANT ")


def grants(*actions: str | Callable[[], object]) -> list[str]:
    """The `GRANT` statements among `actions`: a migration grants last, in its last step, once everything that bounds
    what it grants is committed (its restrictive policies, its triggers: the erasure's insert fence, say)."""
    return [action for action in actions if isinstance(action, str) and _granting(action)]


def ungranted(*actions: str | Callable[[], object]) -> list[str | Callable[[], object]]:
    """`actions` but their `GRANT` statements (a `REVOKE` stays where it is: a function's from `PUBLIC` with it)."""
    return [action for action in actions if not _granting(action)]


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
