# SPDX-License-Identifier: Apache-2.0
"""The tick cutover is never automatic (the owner's M3 rulings): no database state proves that a dispatcher from
before 0039 can't start later and seal a tick under a key made after the boundary, so even a fresh deployment's
migration records none. Only `keys tick-cutover --attest` does, on the operator's attestation; until then no tenant's
key retires (`legacy_ticks`). The suite's own database records one at its setup, as that attestation would."""

import asyncio
import os
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dewpoint.core.db import make_engine

BACKEND = Path(__file__).parents[3]


async def test_even_a_fresh_deployments_migration_records_no_tick_cutover(pg_url: str) -> None:
    fresh = f"fresh_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(pg_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{fresh}"'))
    url = pg_url.rsplit("/", 1)[0] + f"/{fresh}"
    try:
        env = {**os.environ, "DEWPOINT_DATABASE_URL": url}
        migrating = await asyncio.create_subprocess_exec("uv", "run", "alembic", "upgrade", "head", cwd=BACKEND,
                                                         env=env, stdout=asyncio.subprocess.DEVNULL,
                                                         stderr=asyncio.subprocess.DEVNULL)  # fmt: skip
        assert await migrating.wait() == 0
        migrated = make_engine(url)
        async with migrated.connect() as c:
            assert (await c.execute(text("select count(*) from tick_cutover"))).scalar_one() == 0
        await migrated.dispose()
    finally:
        async with admin.connect() as c:
            await c.execute(text(f'DROP DATABASE "{fresh}" WITH (FORCE)'))
        await admin.dispose()
