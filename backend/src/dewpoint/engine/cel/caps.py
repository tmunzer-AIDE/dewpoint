# SPDX-License-Identifier: Apache-2.0
"""Runtime input caps for local evaluation (spec §5.6) and the size model the bound estimator uses (§5.5).

The caps are initial limits to measure, not guarantees (spec §11.2). Changing one changes classification or routing,
so it needs a new classifier version in the CEL profile."""

import datetime
from typing import Any

VALUE_JSON = 65_536  # canonical JSON bytes, per referenced value
TOTAL_JSON = 65_536  # canonical JSON bytes, all referenced values together
LIST_LENGTH = 200  # elements per list: map/filter memory is quadratic in it (ACCUMULATOR_SLOT)
MAP_ENTRIES = 200  # entries per map (the estimator needs a count bound for sortedKeys ranges)
STRING_BYTES = 16_384  # UTF-8 bytes per string

SCALAR = 16  # model bytes of null, bool, numbers, timestamps and durations; also every container's own overhead
INPUT_MODEL_BYTES = 8 * TOTAL_JSON + 8  # model_size(v) <= 8 * len(canonical_json(v)) + 8 (proved in the tests)
# Bytes the runtime keeps per accumulator slot. cel-expr-python 0.1.3 builds a map or filter result by copying the
# accumulator every iteration and keeps every copy until the evaluation ends: n(n + 1) / 2 slots for a range of n,
# summed over a chain. Measured 41-45 bytes per slot at n >= 200 (gate 6 re-measures it on Linux).
ACCUMULATOR_SLOT = 48


def model_size(value: Any) -> int:
    """The estimator's size model: close to the runtime's memory use, and bounded by the JSON size."""
    if isinstance(value, str):
        return SCALAR + len(value.encode())
    if isinstance(value, bytes | bytearray):
        return SCALAR + len(value)
    if isinstance(value, list):
        return SCALAR + sum(model_size(v) for v in value)
    if isinstance(value, dict):
        return SCALAR + sum(model_size(k) + model_size(v) for k, v in value.items())
    if value is None or isinstance(value, bool | int | float | datetime.datetime | datetime.timedelta):
        return SCALAR
    raise TypeError(f"no size model for {type(value).__name__}")
