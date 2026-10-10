# SPDX-License-Identifier: Apache-2.0
"""0053's expected state after its upgrade, derived from the reference snapshot (2b-4b M4 recovery, task 1's run 4) and
the statements gate A approved (`approved_0053.sql`). Nothing here reads a database: the tests compare the real
upgrade with what this derives, and a difference stops task 2 (back to gate A), never a change to either side.

Run as a script, it writes `migrations/expected_0053.json` from run 4's `expected-snapshot.json`:
`python -I tests/migrations/derive_0053.py <expected-snapshot.json>`.
"""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
APPROVED = Path(__file__).with_name("approved_0053.sql")
EXPECTED = BACKEND / "migrations" / "expected_0053.json"
MIGRATOR = "<migrator>"  # the role running the migration, as snapshot.sql writes it
SCHEMA_OWNER = "pg_database_owner"  # schema public's owner: a superuser's grant on it is recorded as the owner's
# run 4's expected-snapshot.json, by its digest's prefix (inventory.md, section 5)
REFERENCE_SHA256 = "2c1b6bf633210e48"

Object = tuple[str, str, str, str, str]  # kind, identity, owner, ACL state, detail
Grant = tuple[str, str, str, str, str, bool]  # kind, identity, privilege, grantee, grantor, grant option

_FUNCTION = re.compile(r"^(REVOKE|GRANT) EXECUTE ON FUNCTION (\S+?)\((.*)\) (FROM|TO) (\w+)$")
_TRAILING_COMMENT = re.compile(r";\s+--.*$")
TEMPORARY = "DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$"


def approved() -> tuple[list[str], list[str]]:
    """The approved upgrade and downgrade statements, in order, each without its final semicolon."""
    upgrade: list[str] = []
    downgrade: list[str] = []
    part: list[str] | None = None
    for line in APPROVED.read_text().splitlines():
        if "===== upgrade" in line:
            part = upgrade
            continue
        if "===== downgrade" in line:
            part = downgrade
            continue
        statement = line.strip()
        if part is None or not statement or statement.startswith("--"):
            continue
        statement = _TRAILING_COMMENT.sub(";", statement)
        if not statement.endswith(";"):
            raise ValueError(f"an approved statement spans lines: {statement!r}")
        part.append(statement[:-1])
    return upgrade, downgrade


def _identity(name: str, types: list[str], objects: set[Object]) -> str:
    """The snapshot identity of `name(types)`: identities carry argument names (pg_get_function_identity_arguments),
    the statements types only. Exactly one function must match, by name, argument count and each argument's type."""
    found = []
    for kind, identity, *_ in objects:
        if not kind.startswith("function:"):
            continue
        base, _, rest = identity.partition("(")
        if base != name:
            continue
        args = [a.strip() for a in rest[:-1].split(",")] if rest[:-1] else []
        args = [a for a in args if not a.startswith("OUT ")]  # identity arguments list OUT ones; a signature doesn't
        if len(args) == len(types) and all(a == t or a.endswith(" " + t) for a, t in zip(args, types, strict=True)):
            found.append(identity)
    if len(found) != 1:
        raise ValueError(f"{name}({', '.join(types)}) matches {len(found)} functions")
    return found[0]


def derive(
    objects_before: set[Object], grants_before: set[Grant]
) -> tuple[set[Object], set[Grant], set[tuple[str, str]]]:
    """The objects and grants after the approved upgrade, and the existing objects it touches."""
    objects, grants = set(objects_before), set(grants_before)
    touched: set[tuple[str, str]] = set()

    def remove(grant: Grant) -> None:
        if grant not in grants:
            raise ValueError(f"the reference lacks {grant}")
        grants.remove(grant)

    upgrade, _ = approved()
    for statement in upgrade:
        if match := _FUNCTION.match(statement):
            verb, name, args, _, role = match.groups()
            identity = _identity(name, [a.strip() for a in args.split(",")] if args else [], objects)
            touched.add(("function:f", identity))
            if verb == "REVOKE":
                if role != "PUBLIC":
                    raise ValueError(statement)
                remove(("function:f", identity, "EXECUTE", "PUBLIC", MIGRATOR, False))
            else:
                grants.add(("function:f", identity, "EXECUTE", role, MIGRATOR, False))
        elif statement.startswith(("CREATE ROLE dewpoint_recovery ", "COMMENT ON ROLE dewpoint_recovery ")):
            continue  # roles aren't objects of this database; the role's own tests check it
        elif statement == "CREATE SCHEMA recovery":
            objects.add(("schema", "recovery", MIGRATOR, "default", ""))
            grants |= {("schema", "recovery", p, MIGRATOR, MIGRATOR, False) for p in ("CREATE", "USAGE")}
        elif statement == "REVOKE ALL ON SCHEMA recovery FROM PUBLIC":  # no PUBLIC entry to remove; the ACL is stored
            objects = {(*o[:3], "explicit", o[4]) if o[:2] == ("schema", "recovery") else o for o in objects}
        elif statement == "GRANT USAGE ON SCHEMA recovery TO dewpoint_recovery":
            grants.add(("schema", "recovery", "USAGE", "dewpoint_recovery", MIGRATOR, False))
        elif statement == "REVOKE USAGE ON SCHEMA public FROM PUBLIC":
            touched.add(("schema", "public"))
            remove(("schema", "public", "USAGE", "PUBLIC", SCHEMA_OWNER, False))
        elif match := re.fullmatch(r"GRANT USAGE ON SCHEMA public TO (\w+)", statement):
            grants.add(("schema", "public", "USAGE", match.group(1), SCHEMA_OWNER, False))
        elif statement == TEMPORARY:
            touched.add(("database", "<current>"))
            remove(("database", "<current>", "TEMPORARY", "PUBLIC", MIGRATOR, False))
        elif match := re.fullmatch(r"REVOKE USAGE ON LANGUAGE (plpgsql|sql) FROM PUBLIC", statement):
            touched.add(("language", match.group(1)))  # the trusted ones only: PostgreSQL refuses c and internal
            remove(("language", match.group(1), "USAGE", "PUBLIC", MIGRATOR, False))
        elif statement == "ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC":
            objects.add(("default_acl", f"{MIGRATOR}:*:f", MIGRATOR, "explicit", ""))
            grants.add(("default_acl", f"{MIGRATOR}:*:f", "EXECUTE", MIGRATOR, MIGRATOR, False))
        else:
            raise ValueError(f"no derivation for an approved statement: {statement!r}")
    objects = {(*o[:3], "explicit", o[4]) if o[:2] in touched else o for o in objects}
    return objects, grants, touched


def reference(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not hashlib.sha256(raw).hexdigest().startswith(REFERENCE_SHA256):
        raise ValueError("not run 4's expected-snapshot.json")
    return json.loads(raw)


def write(path: Path) -> None:
    ref = reference(path)
    before_objects = {tuple(o) for o in ref["EXPECTED_OBJECTS"]}
    before_grants = {tuple(g) for g in ref["EXPECTED_GRANTS"]}
    after_objects, after_grants, touched = derive(before_objects, before_grants)  # type: ignore[arg-type]
    document = {
        "source": {"run4_expected_snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "EXPECTED_OBJECTS": ref["EXPECTED_OBJECTS"],
        "EXPECTED_GRANTS": ref["EXPECTED_GRANTS"],
        "recovery_presence": ref["recovery_presence"],
        "AFTER_CHANGES": {
            "objects_removed": sorted(before_objects - after_objects),
            "objects_added": sorted(after_objects - before_objects),
            "grants_removed": sorted(before_grants - after_grants),
            "grants_added": sorted(after_grants - before_grants),
        },
        "TOUCHED": sorted(touched),
    }
    EXPECTED.write_text(json.dumps(document, indent=1) + "\n")


if __name__ == "__main__":
    write(Path(sys.argv[1]))
