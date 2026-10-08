# SPDX-License-Identifier: Apache-2.0
"""Starting a CLI dev server of a test's own."""

from typing import Any

from temporalio.testing import WorkflowEnvironment

TRIES = 3


async def start_local(**kwargs: Any) -> WorkflowEnvironment:
    """`WorkflowEnvironment.start_local`, tried again when the dev server misses the SDK's startup deadline, which its
    core fixes and a busy machine can exceed (many dev servers starting at once under `-n auto`: M4's full-suite
    failures, accounted for). Any other failure is raised at once."""
    for attempt in range(1, TRIES + 1):
        try:
            return await WorkflowEnvironment.start_local(**kwargs)
        except RuntimeError as e:
            if "did not start within" not in str(e) or attempt == TRIES:
                raise
    raise AssertionError("unreachable")
