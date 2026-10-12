# SPDX-License-Identifier: Apache-2.0
"""0053, read but not run (gate A's test 7, as the owner tightened it at the task-2 go): every statement it can run is
on the allowlist, and it can reach the database through one approved path only. A strict reading of its source rejects
any other SQL or DDL API, any mutating helper and any SQL built at run time; the approved statements are the reviewed
ones, as literal text, in order. Its run-time half, every statement sent during an upgrade and a downgrade, is in
test_0053.py."""

import ast
import hashlib
from pathlib import Path

import pytest

from tests.migrations.derive_0053 import approved
from tests.migrations.state_0053 import SNAPSHOT, sections

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0053_recovery_privileges.py"
SNAPSHOT_SHA256 = "17740e55dd20b208"  # gate A's snapshot.sql (run 4's frozen copy), by its digest's prefix

IMPORTS = {("json", None), ("pathlib", "Path"), ("alembic", "op"), ("sqlalchemy", "text")}
NAMES = {"text", "Path", "enumerate", "tuple", "set", "sorted", "len", "RuntimeError", "hook"}  # plus its own functions
METHODS = {"read_text", "resolve", "split", "strip", "rstrip", "get", "scalar_one", "one", "one_or_none", "loads"}
SETTINGS = {"SET LOCAL lock_timeout = '5s'", "SET LOCAL search_path = pg_catalog, pg_temp"}
WRITES = (
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "CREATE ",
    "ALTER ",
    "DROP ",
    "GRANT ",
    "REVOKE ",
    "COMMENT ",
    "TRUNCATE ",
    "SECURITY LABEL",
    "COPY ",
    "CALL ",
    "DO ",
    "EXECUTE ",
    "LOCK ",
    "VACUUM",
    "REINDEX",
    "CLUSTER",
    "REFRESH ",
)


def _loop_names(tree: ast.Module) -> set[str]:
    """The names bound by `for <i>, <name> in enumerate(UPGRADE|DOWNGRADE)`: the only arguments `op.execute` takes."""
    bound = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "enumerate" and len(node.iter.args) == 1
                and isinstance(node.iter.args[0], ast.Name) and node.iter.args[0].id in ("UPGRADE", "DOWNGRADE")
                and isinstance(node.target, ast.Tuple) and len(node.target.elts) == 2
                and isinstance(node.target.elts[1], ast.Name)):  # fmt: skip
            bound.add(node.target.elts[1].id)
    return bound


def _reads(tree: ast.Module) -> tuple[set[str], list[str]]:
    """The module's phase-0 constants (`text()`'s only arguments), and what's wrong with any of them."""
    names, problems = set(), []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        name, value = node.targets[0].id, node.value
        if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name) and value.value.id == "_SECTIONS":
            names.add(name)  # a section of the fixed snapshot file, checked byte for byte below
        elif isinstance(value, ast.Constant) and isinstance(value.value, str) and name.isupper() and name not in (
                "MARKER",):  # fmt: skip
            sql = value.value
            if sql in SETTINGS or (sql.lstrip().upper().startswith(("SELECT", "WITH")) and ";" not in sql
                                   and not any(w in sql.upper() for w in WRITES)):  # fmt: skip
                names.add(name)
            elif name not in ("revision", "down_revision"):
                problems.append(f"{name}: not a fixed read-only statement or an allowed setting")
    return names, problems


def violations(source: str) -> list[str]:
    """Everything in 0053's source outside the one approved path to the database."""
    tree = ast.parse(source)
    found: list[str] = []
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    loop_names = _loop_names(tree)
    reads, problems = _reads(tree)
    found += problems
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if (a.name, None) not in IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            found += [f"from {node.module} import {a.name}" for a in node.names if (node.module, a.name) not in IMPORTS]
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id not in NAMES | functions:
                    found.append(f"call to {func.id}()")
                elif func.id == "text" and not (len(node.args) == 1 and isinstance(node.args[0], ast.Name)
                                                 and node.args[0].id in reads):  # fmt: skip
                    found.append("text() of something other than a fixed read-only constant")
            elif isinstance(func, ast.Attribute):
                target = func.value
                if isinstance(target, ast.Name) and target.id == "op":
                    if func.attr not in ("execute", "get_bind", "get_context"):
                        found.append(f"op.{func.attr}()")
                    elif func.attr == "execute" and not (len(node.args) == 1 and not node.keywords
                                                         and isinstance(node.args[0], ast.Name)
                                                         and node.args[0].id in loop_names):  # fmt: skip
                        found.append("op.execute() of something other than an approved statement")
                elif func.attr == "execute":
                    first = node.args[0] if node.args else None
                    if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name)
                            and first.func.id == "text"):  # fmt: skip
                        found.append("a connection's execute() of something other than text(<a fixed read>)")
                    if len(node.args) > 2 or node.keywords:
                        found.append("execute() with more than its statement and its parameters")
                elif func.attr not in METHODS:
                    found.append(f".{func.attr}()")
                elif func.attr == "loads" and not (isinstance(target, ast.Name) and target.id == "json"):
                    found.append(".loads() on something other than json")
            else:
                found.append("a call of a computed function")
    return found


def test_0053_takes_only_the_approved_path_to_the_database() -> None:
    assert violations(MIGRATION.read_text()) == []


def listed(source: str) -> dict[str, list[str]]:
    """0053's UPGRADE and DOWNGRADE tuples: literal strings only, or the test fails."""
    lists = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
                "UPGRADE", "DOWNGRADE"):  # fmt: skip
            assert isinstance(node.value, ast.Tuple)
            assert all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts)
            lists[node.targets[0].id] = [e.value for e in node.value.elts]  # type: ignore[attr-defined]
    return lists


def test_its_statements_are_the_approved_ones_as_literal_text_in_order() -> None:
    upgrade, downgrade = approved()
    assert listed(MIGRATION.read_text()) == {"UPGRADE": upgrade, "DOWNGRADE": downgrade}


def test_the_snapshot_it_reads_is_gate_as_and_reads_only() -> None:
    assert hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest().startswith(SNAPSHOT_SHA256)
    for name, sql in sections().items():
        assert sql.lstrip().upper().startswith(("SELECT", "WITH")), name
        assert ";" not in sql, name


GRANT = "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_ingress"
CHECKED = '    _checked("upgrade")\n'
READ = "    bind.execute(text(PINNED))\n"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param(
            CHECKED, f'{CHECKED}    op.get_bind().exec_driver_sql("{GRANT}")\n', id="another path: exec_driver_sql"
        ),
        pytest.param(CHECKED, f'{CHECKED}    op.create_table("extra")\n', id="another path: an Alembic operation"),
        pytest.param(
            "from alembic import op\n",
            "from alembic import op\nfrom sqlalchemy.schema import DDL\n",
            id="another path: SQLAlchemy's DDL",
        ),
        pytest.param(
            CHECKED,
            f"{CHECKED}    for row in op.get_bind().execute(text(OBJECTS)):\n"
            '        op.execute(f"GRANT EXECUTE ON FUNCTION {row[1]} TO dewpoint_ingress")\n',
            id="a catalog-built GRANT",
        ),
        pytest.param(CHECKED, f'{CHECKED}    op.execute("CREATE SCHEMA extra")\n', id="an unlisted CREATE SCHEMA"),
        pytest.param("PINNED = ", 'WIDE = "SET search_path = public"\nPINNED = ', id="a SET that isn't LOCAL"),
        pytest.param(READ, f'{READ}    bind.execute(text("SELECT 1"))\n', id="a statement built in place"),
        pytest.param(CHECKED, f'{CHECKED}    getattr(op, "execute")("SELECT 1")\n', id="a dynamic call"),
    ],
)
def test_a_mutation_is_caught(before: str, after: str) -> None:
    source = MIGRATION.read_text()
    assert before in source, f"the mutation's anchor isn't in 0053: {before!r}"
    assert violations(source.replace(before, after, 1)) != []


@pytest.mark.parametrize("change", ["a stray COMMENT", "two statements swapped"])
def test_a_changed_statement_list_is_caught(change: str) -> None:
    lines = MIGRATION.read_text().splitlines(keepends=True)
    start = lines.index("UPGRADE = (\n") + 1  # one approved statement per line, as 0053 writes them
    if change == "a stray COMMENT":
        lines.insert(start + 3, "    \"COMMENT ON SCHEMA public IS 'x'\",\n")
    else:
        lines[start + 5], lines[start + 6] = lines[start + 6], lines[start + 5]
    upgrade, downgrade = approved()
    assert listed("".join(lines)) != {"UPGRADE": upgrade, "DOWNGRADE": downgrade}
