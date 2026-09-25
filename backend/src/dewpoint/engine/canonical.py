# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8, no NaN/Infinity: equal values always give equal bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
