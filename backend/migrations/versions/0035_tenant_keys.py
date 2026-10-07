# SPDX-License-Identifier: Apache-2.0
"""Every key between two tenant tables carries the tenant (issue #35; engine 2b spec §14). Row-level security checks
only a row's own `tenant_id`, and a foreign-key check doesn't apply the referenced table's policies, so a key on the
referenced id alone let a role scoped to one tenant record a row naming another tenant's workflow, version or run. Each
such key becomes a composite one that includes `tenant_id`; a key that names a version also names the row's workflow,
so a request, a mapping or a run names a version of its own workflow.

Rows that already break this stop the upgrade, which names each key and its count, never a row's contents: an operator
resolves them first (the application's reads are tenant-scoped, so none is expected).

Chained after 0042 (plugins-3a-2, after 0041), which merged first while 2b-4a held 0035-0040 (plugins-3 D25)."""

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from migrations.online import exists, index, online, plain, step

revision = "0035"
down_revision = "0042"
branch_labels = None
depends_on = None

WORKFLOW = ("workflows", ["id", "tenant_id"])
VERSION = ("workflow_versions", ["id", "workflow_id", "tenant_id"])
RUN = ("runs", ["id", "tenant_id"])

# (new name, table, columns, referenced table and columns, ON DELETE, the key it replaces with its definition)
KEYS = [
    ("run_requests_workflow", "run_requests", ["workflow_id", "tenant_id"], WORKFLOW, None,
     ("run_requests_workflow_id_fkey", ["workflow_id"], "workflows", ["id"])),
    ("run_requests_version", "run_requests", ["workflow_version_id", "workflow_id", "tenant_id"], VERSION, None,
     ("run_requests_workflow_version_id_fkey", ["workflow_version_id"], "workflow_versions", ["id"])),
    ("csv_uploads_workflow", "csv_uploads", ["workflow_id", "tenant_id"], WORKFLOW, None,
     ("csv_uploads_workflow_id_fkey", ["workflow_id"], "workflows", ["id"])),
    ("csv_mappings_workflow", "csv_mappings", ["workflow_id", "tenant_id"], WORKFLOW, None,
     ("csv_mappings_workflow_id_fkey", ["workflow_id"], "workflows", ["id"])),
    ("csv_mappings_version", "csv_mappings", ["saved_against", "workflow_id", "tenant_id"], VERSION, None,
     ("csv_mappings_saved_against_fkey", ["saved_against"], "workflow_versions", ["id"])),
    ("schedules_workflow", "schedules", ["workflow_id", "tenant_id"], WORKFLOW, None,
     ("schedules_workflow_id_fkey", ["workflow_id"], "workflows", ["id"])),
    ("workflow_versions_workflow", "workflow_versions", ["workflow_id", "tenant_id"], WORKFLOW, None,
     ("workflow_versions_workflow_id_fkey", ["workflow_id"], "workflows", ["id"])),
    ("workflows_active_version_fk", "workflows", ["active_version_id", "id", "tenant_id"], VERSION, None,
     ("workflows_active_version_fk", ["active_version_id", "id"], "workflow_versions", ["id", "workflow_id"])),
    ("runs_version_fk", "runs", ["workflow_version_id", "workflow_id", "tenant_id"], VERSION, None,
     ("runs_version_fk", ["workflow_version_id", "workflow_id"], "workflow_versions", ["id", "workflow_id"])),
    ("runs_parent_run", "runs", ["parent_run_id", "tenant_id"], RUN, None,
     ("runs_parent_run_id_fkey", ["parent_run_id"], "runs", ["id"])),
    ("run_steps_run", "run_steps", ["run_id", "tenant_id"], RUN, "CASCADE",
     ("run_steps_run_id_fkey", ["run_id"], "runs", ["id"])),
]  # fmt: skip

TARGETS = [("workflow_versions_tenant", *VERSION), ("runs_tenant", *RUN)]  # workflows_tenant exists (0032)


def check(conn: Connection) -> None:
    """Refuse rows that would break a new key: a row naming another tenant's object, or a version of another workflow.
    The error names each key with its count, never a row's contents. It must see every tenant's rows: `online()` turns
    row-level security off, so a role it applies to errors here, never counts none."""
    found = []
    for name, table, columns, (ref, ref_columns), _, _ in KEYS:
        on = f"r.{ref_columns[0]} = t.{columns[0]}"
        mismatch = " OR ".join(f"r.{rc} <> t.{c}" for c, rc in zip(columns[1:], ref_columns[1:], strict=True))
        count = conn.execute(text(f"SELECT count(*) FROM {table} t JOIN {ref} r ON {on} WHERE {mismatch}")).scalar_one()
        if count:
            found.append(f"{name} {count}")
    if found:
        raise RuntimeError(f"rows name another tenant's object or another workflow's version ({', '.join(found)}); "
                           "resolve them before this upgrade (migration 0035, issue #35)")  # fmt: skip


def _key(name: str, table: str, columns: list[str], ref: str, ref_columns: list[str], ondelete: str | None) -> str:
    cascade = f" ON DELETE {ondelete}" if ondelete else ""
    return (f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({', '.join(columns)}) "
            f"REFERENCES {ref} ({', '.join(ref_columns)}){cascade} NOT VALID")  # fmt: skip


def _replaced(name: str, table: str, columns: list[str]) -> str:
    """A `done` query: the key under its new name with its new columns (two keep their old names)."""
    return (f"SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.{table}'::regclass "
            f"AND conname = '{name}' AND cardinality(conkey) = {len(columns)})")  # fmt: skip


def upgrade() -> None:
    # Online (2b-4b, D15): the targets' unique indexes built concurrently, then attached; each key replaced in a step
    # of its own, its replacement added `NOT VALID` as the old one goes, so one of them always holds and every new row
    # is checked by the new one; the rows checked again once every replacement holds; then each key validated, which
    # blocks no reads or writes.
    with online() as conn:
        check(conn)
        for name, table, columns in TARGETS:
            index(conn, f"0035 {name}",
                  f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({', '.join(columns)})")  # fmt: skip
        for name, table, _ in TARGETS:
            step(conn, f"0035 {name} attached", f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE USING INDEX {name}",
                 done=exists("constraint", name))  # fmt: skip
        for name, table, columns, (ref, ref_columns), ondelete, (old, *_) in KEYS:
            step(conn, f"0035 {name}", f"ALTER TABLE {table} DROP CONSTRAINT {old}",
                 _key(name, table, columns, ref, ref_columns, ondelete), done=_replaced(name, table, columns))  # fmt: skip
        check(conn)
        for name, table, *_ in KEYS:
            plain(conn, f"0035 {name} validated", f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    for name, table, _, _, ondelete, (old, columns, ref, ref_columns) in reversed(KEYS):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(old, table, ref, columns, ref_columns, ondelete=ondelete)
    for name, table, _ in reversed(TARGETS):
        op.drop_constraint(name, table, type_="unique")
