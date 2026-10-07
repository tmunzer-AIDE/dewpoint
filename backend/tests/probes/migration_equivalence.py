# SPDX-License-Identifier: Apache-2.0
"""The online migrations' equivalence probe (the 2b-4b plan's M1a; the owner's D15): the original migrations, at a git
ref, and the working tree's, each run revision by revision from an empty database, compared at every revision on the
whole schema (`tests/migrations/support.schema`: constraints, indexes, columns, functions, triggers, policies, row-level
security, every grant, roles). Run by hand, never in CI; a disposable Postgres 16 container (testcontainers). From
`backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.migration_equivalence <ref> --workdir DIR [--write]

Prints each revision's differing parts with their rows, original first. `--write` records the original's fingerprints
as the suite's fixture (`tests/migrations/revisions.json`), which `test_each_revision_ends_as_the_original_left_it`
compares the working tree's migrations against."""

import argparse
import asyncio
import io
import json
import subprocess
import tarfile
from pathlib import Path

import asyncpg
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.support import BACKEND, alembic_config, autocommitted, fingerprint, schema, upgrade

ORDER = ["0034", "0041", "0042", "0035", "0036", "0037", "0038", "0039", "0040", "0043", "0044"]
FIXTURE = BACKEND / "tests/migrations/revisions.json"


def extract(ref: str, workdir: Path) -> Path:
    """`backend/migrations` as it is at `ref`, under `workdir`."""
    archive = subprocess.run(["git", "archive", ref, "migrations"], cwd=BACKEND, capture_output=True,  # noqa: S603,S607
                             check=True).stdout  # fmt: skip
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(workdir, filter="data")
    return workdir / "migrations"


async def _create(base: str, *names: str) -> None:
    c = await asyncpg.connect(f"{base}/postgres")
    try:
        for name in names:
            await c.execute(f'CREATE DATABASE "{name}"')
    finally:
        await c.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ref")
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    original = alembic_config(extract(args.ref, args.workdir))
    fingerprints, differ = {}, {}
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        base = pg.get_connection_url().rsplit("/", 1)[0]
        asyncio.run(_create(base, "original", "online"))
        for revision in ORDER:
            upgrade(f"{base}/original", revision, original)
            upgrade(f"{base}/online", revision)
            before, after = autocommitted(f"{base}/original", schema), autocommitted(f"{base}/online", schema)
            fingerprints[revision] = autocommitted(f"{base}/original", fingerprint)
            for part, rows in before.items():
                if rows != after[part]:
                    a = set(rows.items()) if isinstance(rows, dict) else rows
                    b = set(after[part].items()) if isinstance(after[part], dict) else after[part]
                    differ.setdefault(revision, {})[part] = {"original": sorted(map(repr, a - b)),
                                                             "online": sorted(map(repr, b - a))}  # fmt: skip
            print(revision, "identical" if revision not in differ else f"differs: {sorted(differ[revision])}")
    if differ:
        print(json.dumps(differ, indent=1))
    if args.write:
        FIXTURE.write_text(json.dumps(fingerprints, indent=1) + "\n")
        print(f"wrote {FIXTURE.relative_to(BACKEND)} from {args.ref}")


if __name__ == "__main__":
    main()
