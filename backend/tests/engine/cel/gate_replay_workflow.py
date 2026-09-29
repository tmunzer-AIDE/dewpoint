# SPDX-License-Identifier: Apache-2.0
"""Gate 4's workflow (spec §5.9): it evaluates a CEL corpus in-process, inside Temporal's sandbox, the way RunGraph
evaluates local CEL. The digest of the outcomes names the activity it then schedules, so a replay that computes any
other outcome fails as nondeterministic."""

import hashlib
import json
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():  # as RunGraph: the runtime is a C++ extension, loaded once
    from dewpoint.engine.cel import evaluate


@activity.defn(name="gate4.outcomes")
async def outcomes(digest: str) -> None:
    """Nothing to do: the digest is the activity's id."""


@workflow.defn(name="CelCorpus")
class CelCorpus:
    @workflow.run
    async def run(self, corpus: list[list[Any]]) -> str:
        out = [evaluate.run(evaluate.compiled(expr, decls), bindings).to_json() for expr, decls, bindings in corpus]
        digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:32]
        await workflow.execute_activity(
            outcomes, digest, activity_id=digest, start_to_close_timeout=timedelta(seconds=30)
        )
        return digest
