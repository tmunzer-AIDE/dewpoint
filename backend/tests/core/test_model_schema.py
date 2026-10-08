# SPDX-License-Identifier: Apache-2.0
"""Alembic autogenerates from the models' metadata (`migrations/env.py`), so the models declare the schema's tables,
foreign keys and unique constraints as the migrations made them: the tenant-composite keys (#35, engine 2b spec §14)
included. A model that drifted would have autogenerate propose dropping a table or a key, or adding back a
single-column key that lets a row name another tenant's object (the owner's M2 review)."""

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from dewpoint.core.models import Base

KEYS = ("add_table", "remove_table", "add_fk", "remove_fk", "add_constraint", "remove_constraint")


def _described(diff: Any) -> str:
    kind, thing = diff[0], diff[1]
    if kind.endswith("table"):
        return f"{kind} {thing.name}"
    if kind.endswith("fk"):
        columns = [c.name for c in thing.columns]
        return f"{kind} {thing.parent.name}{columns} -> {thing.referred_table.name} ({thing.name})"
    return f"{kind} {thing.table.name}.{thing.name}"


async def test_the_models_declare_every_table_and_key_the_migrations_made(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        connection = await s.connection()
        diffs = await connection.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    assert sorted(_described(d) for d in diffs if isinstance(d, tuple) and d[0] in KEYS) == []
