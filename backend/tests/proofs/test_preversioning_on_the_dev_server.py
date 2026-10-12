# SPDX-License-Identifier: Apache-2.0
"""The pre-versioning query's scenario (preversioning.py) on a CLI dev server of its own: a rehearsal in the normal
suite, so the proof's own mistakes show here and not in an authorized run. The dev server's visibility is SQLite, not
D12's PostgreSQL: this proves nothing about the target (d12/test_preversioning.py would, once the owner authorizes
its run)."""

from tests.proofs import preversioning
from tests.support.temporal import start_local


async def test_the_query_finds_the_open_unversioned_run_and_neither_the_versioned_nor_the_closed_one() -> None:
    async with await start_local() as environment:
        evidence = await preversioning.observe(environment.client)
    preversioning.check(evidence)
