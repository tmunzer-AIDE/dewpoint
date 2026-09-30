# SPDX-License-Identifier: Apache-2.0
"""What the engine sends Temporal, and what it gets back, measured before it goes (engine 2b spec §5.2). Temporal
refuses a payload over 2 MiB once the codec has encoded it, and its SDK then retries the workflow task forever; so
each payload is checked where it's produced — a step's result in its activity, a run's result in the run, a command
before the workflow sends it — against PAYLOAD_BYTES, measured as the payload converter's JSON plus CODEC_OVERHEAD,
a bound on what the tenant codec adds (a test of the codec proves it). Too large fails the step, the loop or the run
with `payload_too_large`: a result, never a retried workflow task. Nothing is spilled before 2b-1b's claims.

`fits` reads the limit from this module when it's called, so a test can lower it; workflow code imports names from
this module's full path, which the sandbox passes through (a submodule taken from its package would be a copy)."""

import json
from collections.abc import Sequence
from typing import Any

from temporalio.converter import PayloadConverter

CODEC_OVERHEAD = 256  # bytes the tenant codec adds to a payload, at most: its metadata, the nonce and the tag
PAYLOAD_BYTES = 1_835_008  # 1.75 MiB, encoded: a margin under Temporal's 2 MiB (2,097,152) payload limit
SNAPSHOT_BYTES = 1_572_864  # 1.5 MiB, encoded: a continued run's input (spec §5.3's SNAPSHOT_MAX)
# The sensitive values a run carries — in its result, its children's starts and its snapshot, so they're masked there
# too — as JSON: a bound on them keeps every result that has no outputs far under PAYLOAD_BYTES (engine 2b spec §5.2).
SECRETS_BYTES = 262_144
PAYLOAD_TOO_LARGE = "payload_too_large"
SNAPSHOT_TOO_LARGE = "snapshot_too_large"
RUN_INPUT_TOO_LARGE = "The run's input is too large to start (over 1.75 MiB)."
STEP_INPUT_TOO_LARGE = "The step's input is too large to send (over 1.75 MiB)."
SUBFLOW_INPUT_TOO_LARGE = "The sub-flow's input is too large to send (over 1.75 MiB)."
HANDLER_INPUT_TOO_LARGE = "The failure handler's input is too large to send (over 1.75 MiB)."
BATCH_ITEM_TOO_LARGE = "An item of this loop, with what its batch reads, is too large to send (over 1.75 MiB)."
RUN_SNAPSHOT_TOO_LARGE = "The run's state is too large to carry on (over 1.5 MiB)."
BATCH_SNAPSHOT_TOO_LARGE = "A batch of this loop has too much state to carry on (over 1.5 MiB)."
SECRETS_TOO_LARGE = "The sensitive values this run would have to carry are too many (over 256 KiB)."
RESULT_TOO_LARGE = "The result is too large to return (over 1.75 MiB): please report it."
STEP_OUTPUT_TOO_LARGE = "The step's output is too large to record (over 1.75 MiB)."
VERSION_TOO_LARGE = "The version is too large to load (over 1.75 MiB)."
OUTPUTS_TOO_LARGE = "The run's outputs are too large to return (over 1.75 MiB)."
BATCH_RESULTS_TOO_LARGE = "A batch of this loop collected too much to return (over 1.75 MiB)."


def encoded_bytes(value: Any, converter: PayloadConverter) -> int:
    """At most what `value`'s payload weighs once the codec has encoded it."""
    return len(converter.to_payloads([value])[0].data) + CODEC_OVERHEAD


def secret_bytes(value: str) -> int:
    """A sensitive value's JSON bytes, as the SDK's converter writes it (escaped as `json.dumps` does)."""
    return len(json.dumps(value))


def secrets_bytes(values: Sequence[str]) -> int:
    """The JSON bytes of a list of sensitive values: its brackets, each value, and a comma between two."""
    return 2 + sum(secret_bytes(v) for v in values) + max(len(values) - 1, 0)


def secrets_limit() -> int:
    """SECRETS_BYTES, read when it's called."""
    return SECRETS_BYTES


def payload_bytes() -> int:
    """PAYLOAD_BYTES, read when it's called."""
    return PAYLOAD_BYTES


def fits(value: Any, converter: PayloadConverter) -> bool:
    return encoded_bytes(value, converter) <= PAYLOAD_BYTES


def snapshot_fits(value: Any, converter: PayloadConverter) -> bool:
    """A continued run's input, snapshot and all, within SNAPSHOT_BYTES."""
    return encoded_bytes(value, converter) <= SNAPSHOT_BYTES
