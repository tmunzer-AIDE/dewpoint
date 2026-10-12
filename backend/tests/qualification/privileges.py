# SPDX-License-Identifier: Apache-2.0
"""The recovery login's effective privileges on the target (design revision 10 §2, revision 11 §1): the suite's own
enumerator (`tests.migrations.state_0053.EFFECTIVE`: every object outside the system schemas, every privilege that
applies, through the `has_*_privilege` functions) run against the target's `dewpoint`, since a target may carry grants
the migrations never made. A test recovery login holds gate A's allow-list exactly, and is a member of
`dewpoint_recovery` alone; each service role holds exactly the rights it holds on a fresh database at head
(`reference_rights.json`, kept current by `test_reference_rights.py`): a table grant to the API that would let it
write a confirmation itself is drift, as any other is.

    DEWPOINT_QUALIFICATION_APPROVED=<id> DEWPOINT_QUALIFICATION_ADMIN_PASSWORD=... \\
    python -m tests.qualification.privileges --dsn '<the administrator's verify-full DSN>' --login rcv_qualify_1 \\
      --inventory logins.json --out privileges.jsonl

`logins.json` is the target's own inventory of its services' logins: `{"dewpoint_api_login": "dewpoint_api", ...,
"<the start check's login>": "dewpoint_start_check"}`. Each is checked whatever it's a member of now (one that lost its
membership, or doesn't exist, fails), and a login of a service role it doesn't name fails too."""

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from dewpoint.apps.cli import recovery
from tests.core.test_recovery_privileges import RECOVERY_FUNCTIONS
from tests.migrations.state_0053 import EFFECTIVE, GRANTED, SERVICE_ROLES, UNTRUSTED, holders
from tests.qualification.approval import Record, approved, secret

DESCRIPTION = "The recovery login's effective privileges on the target, exactly gate A's allow-list."
ALLOWED: frozenset[tuple[str, str, str]] = frozenset({
    ("database", "<current>", "CONNECT"), ("schema", "recovery", "USAGE"),
    *(("function:f", f, "EXECUTE") for f in RECOVERY_FUNCTIONS), *UNTRUSTED,
})  # fmt: skip
REFERENCE = Path(__file__).with_name("reference_rights.json")  # head's, refreshed by test_reference_rights.py
EFFECTIVE_SQL = re.sub(r"(?<![:\w]):r\b", "$1", EFFECTIVE)  # its one parameter, asyncpg's way


def drift(found: dict[str, set[tuple[str, str, str]]],
          reference: dict[str, list[list[str]]]) -> dict[str, dict[str, list[tuple[str, str, str]]]]:  # fmt: skip
    """Each service role whose rights differ from the reference taken at head: those it holds beyond it (a grant the
    migrations never made), and those it lacks."""
    drifted = {}
    for role, held in found.items():
        expected = {(r[0], r[1], r[2]) for r in reference.get(role, [])}
        extra, lacking = sorted(held - expected), sorted(expected - held)
        if extra or lacking:
            drifted[role] = {"extra": extra, "missing": lacking}
    return drifted


def excess(held: set[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    """Every right held beyond the allow-list."""
    return set(held) - ALLOWED


def missing(held: set[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    """Every right of the allow-list not held."""
    return set(ALLOWED) - set(held)


ATTRIBUTES = ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls")


async def service_logins(c: Any) -> dict[str, set[str]]:
    """Every login that is a member of a service role, with the service roles it's a member of."""
    rows = await c.fetch("SELECT m.rolname AS login, r.rolname AS role FROM pg_auth_members a "
                         "JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
                         "WHERE m.rolcanlogin AND r.rolname = ANY($1::text[])", list(SERVICE_ROLES))  # fmt: skip
    found: dict[str, set[str]] = {}
    for row in rows:
        found.setdefault(row["login"], set()).add(row["role"])
    return found


def inventory_problems(inventory: dict[str, str], discovered: dict[str, set[str]]) -> list[str]:
    """What's wrong with the target's inventory of its services' logins (login: its intended service role) before any
    login is checked: a role that isn't a service role; a service role with no login named (the start check's
    included); a login of a service role that it doesn't name."""
    problems = [f"{login}: {role} is not a service role" for login, role in sorted(inventory.items())
                if role not in SERVICE_ROLES]  # fmt: skip
    problems += [f"no login named for {role}" for role in SERVICE_ROLES if role not in set(inventory.values())]
    problems += [f"{login}: a login of {', '.join(sorted(roles))} the inventory doesn't name"
                 for login, roles in sorted(discovered.items()) if login not in inventory]  # fmt: skip
    return problems


async def check_logins(c: Any, inventory: dict[str, str]) -> dict[str, list[str]]:
    """Each login the inventory names, checked against its intended role, whatever it's a member of now: one that lost
    its membership, or doesn't exist, is found, never passed over."""
    found: dict[str, list[str]] = {}
    for login, role in sorted(inventory.items()):
        if not await c.fetchval("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1 AND rolcanlogin)", login):
            found[login] = [f"{login}: no such login"]
            continue
        found[login] = await login_problems(c, login, role)
    return found


async def login_problems(c: Any, login: str, role: str) -> list[str]:
    """What a service's login holds beyond its intended role: another membership, an attribute beyond LOGIN, a right
    granted to it directly (or one of the role's it doesn't hold, NOINHERIT say)."""
    problems = []
    attributes = await c.fetchrow(f"SELECT {', '.join(ATTRIBUTES)}, rolinherit FROM pg_roles WHERE rolname = $1", login)
    problems += [f"{login}: {name[3:].upper()}" for name in ATTRIBUTES if attributes[name]]
    if not attributes["rolinherit"]:
        problems.append(f"{login}: NOINHERIT")
    memberships = {r[0] for r in await c.fetch(
        "SELECT r.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid "
        "JOIN pg_roles m ON m.oid = a.member WHERE m.rolname = $1", login)}  # fmt: skip
    problems += [f"{login}: also a member of {other}" for other in sorted(memberships - {role})]
    if role not in memberships:
        problems.append(f"{login}: not a member of {role}")
    held, intended = await _rights(c, login), await _rights(c, role)
    problems += [f"{login}: {right[2]} on {right[0]} {right[1]}, granted to the login itself"
                 for right in sorted(held - intended)]  # fmt: skip
    problems += [f"{login}: lacks {right[2]} on {right[0]} {right[1]}" for right in sorted(intended - held)]
    return problems


async def _rights(c: Any, role: str) -> set[tuple[str, str, str]]:
    return {(r[0], r[1], r[2]) for r in await c.fetch(EFFECTIVE_SQL, role)}


async def _checked(args: argparse.Namespace, record: Record) -> None:
    target = recovery.server(args.dsn, user=recovery.ADMINISTRATOR)
    c = await recovery.connect(target, secret("DEWPOINT_QUALIFICATION_ADMIN_PASSWORD"))
    try:
        held = await _rights(c, args.login)
        record.check(not excess(held), "the recovery login holds nothing beyond the allow-list",
                     excess=sorted(excess(held)))  # fmt: skip
        record.check(not missing(held), "the recovery login holds the whole allow-list", missing=sorted(missing(held)))
        memberships = {r[0] for r in await c.fetch(
            "SELECT r.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid "
            "JOIN pg_roles m ON m.oid = a.member WHERE m.rolname = $1", args.login)}  # fmt: skip
        record.check(memberships == {"dewpoint_recovery"}, "a member of dewpoint_recovery alone",
                     memberships=sorted(memberships))  # fmt: skip
        rights = {role: await _rights(c, role) for role in SERVICE_ROLES}
        drifted = drift(rights, json.loads(REFERENCE.read_text()))
        record.check(not drifted, "every service role holds exactly head's rights (the migrations' grants alone)",
                     drift=drifted)  # fmt: skip
        inventory = json.loads(args.inventory.read_text())
        shaped = isinstance(inventory, dict) and all(isinstance(k, str) and isinstance(v, str)
                                                     for k, v in inventory.items())  # fmt: skip
        record.check(shaped, "the inventory: {login: its intended service role}")
        if shaped:
            problems = inventory_problems(inventory, await service_logins(c))
            record.check(not problems, "the inventory names every service role's login, and every login found",
                         problems=problems)  # fmt: skip
            for login, wrong in (await check_logins(c, inventory)).items():
                record.check(not wrong, f"{login}: exactly {inventory[login]}'s membership and rights", problems=wrong)
        for function, roles in GRANTED.items():
            found = holders(rights, function)
            record.check(found == roles, f"{function}: executed by exactly its grantees", holders=sorted(found))
        for role, held_by in rights.items():
            reach = sorted(r for r in held_by if r[1].startswith("recovery.") or r[1] == "recovery")
            record.check(not reach, f"{role} reaches nothing of schema recovery", reach=reach)
    finally:
        await c.close()


def main() -> int:
    approval = approved()
    parser = argparse.ArgumentParser(prog="python -m tests.qualification.privileges", description=DESCRIPTION)
    parser.add_argument("--dsn", required=True, help="the administrator's, verify-full")
    parser.add_argument("--login", required=True, help="the test recovery login (rcv_...)")
    parser.add_argument("--inventory", type=Path, required=True,
                        help="the target's service logins, as JSON {login: its service role}, the start check's "
                             "included")  # fmt: skip
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = Record(args.out, "privileges", approval)
    record.write(login=args.login)
    asyncio.run(_checked(args, record))
    return record.finished()


if __name__ == "__main__":
    raise SystemExit(main())
