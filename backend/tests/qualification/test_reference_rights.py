# SPDX-License-Identifier: Apache-2.0
"""The reference the `privileges` qualification compares a target's service roles against (2b-4b M4 recovery, task
18; the final review's finding 6): every right each service role holds on a fresh database at head, the migrations'
grants alone. A target holding more (a grant the migrations never made) or less is drift.

When a migration changes a grant, this test fails; regenerate the reference with
`DEWPOINT_WRITE_REFERENCE_RIGHTS=1 pytest tests/qualification/test_reference_rights.py`, and review its diff."""

import asyncio
import json
import os

import asyncpg  # type: ignore[import-untyped]  # it ships no type information
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.state_0053 import SERVICE_ROLES
from tests.migrations.support import upgrade
from tests.qualification.privileges import EFFECTIVE_SQL, REFERENCE


async def _rights(url: str) -> dict[str, list[list[str]]]:
    c = await asyncpg.connect(url)
    try:
        return {role: sorted([r[0], r[1], r[2]] for r in await c.fetch(EFFECTIVE_SQL, role))
                for role in SERVICE_ROLES}  # fmt: skip
    finally:
        await c.close()


async def test_the_reference_is_every_service_roles_rights_on_a_fresh_database_at_head() -> None:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:  # a cluster of its own: 0053's role is a cluster's
        url = pg.get_connection_url()
        await asyncio.to_thread(upgrade, url, "head")
        found = await _rights(url)
    if os.environ.get("DEWPOINT_WRITE_REFERENCE_RIGHTS") == "1":
        await asyncio.to_thread(REFERENCE.write_text, json.dumps(found, indent=1, sort_keys=True) + "\n")
    assert set(found) == set(SERVICE_ROLES)
    assert json.loads(await asyncio.to_thread(REFERENCE.read_text)) == found
