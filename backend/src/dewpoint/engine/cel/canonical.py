# SPDX-License-Identifier: Apache-2.0
"""Output canonicalization (spec §5.8): every CEL result becomes canonical JSON before it enters workflow state.
Map keys are sorted, timestamps become RFC 3339 UTC, durations `"<seconds>s"`; bytes, type values, non-text map keys
and non-finite numbers are refused."""

import datetime
import math
from decimal import Decimal
from typing import Any

from dewpoint.engine.canonical import canonical_json

OUTPUT_LIMIT = 262_144  # canonical JSON bytes of one result


class NonJsonValue(ValueError):
    pass


class OutputTooLarge(ValueError):
    pass


def rfc3339(value: datetime.datetime) -> str:
    utc = value.astimezone(datetime.UTC) if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}".rstrip("0")
    return text + "Z"


def seconds(value: datetime.timedelta) -> str:
    total = Decimal(value.days * 86_400 + value.seconds) + Decimal(value.microseconds) / Decimal(1_000_000)
    text = format(total.normalize(), "f")
    return ("0" if text in ("-0", "") else text) + "s"


def canonical(value: Any) -> Any:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NonJsonValue("a number that isn't finite")
        return value
    if isinstance(value, datetime.datetime):
        return rfc3339(value)
    if isinstance(value, datetime.timedelta):
        return seconds(value)
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise NonJsonValue("a map key that isn't text")
        return {k: canonical(value[k]) for k in sorted(value)}
    raise NonJsonValue(f"a {type(value).__name__} value")


def to_output(value: Any) -> Any:
    out = canonical(value)
    if len(canonical_json(out)) > OUTPUT_LIMIT:
        raise OutputTooLarge(f"the result is larger than {OUTPUT_LIMIT // 1024} KiB")
    return out
