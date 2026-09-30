# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §5.2: a payload is measured as the SDK's JSON converter writes it, plus a bound on what the codec
adds (test_codec.py proves the bound), against a margin under Temporal's 2 MiB."""

import json

from temporalio.converter import DataConverter

from dewpoint.engine.runtime import size
from dewpoint.engine.runtime.activities import BatchResult, RunResult
from dewpoint.engine.runtime.execution import CEL_REQUEST_BYTES

TEMPORAL_PAYLOAD_LIMIT = 2 * 1024 * 1024
JSON = DataConverter.default.payload_converter


def test_a_payload_weighs_its_json_and_the_codecs_share() -> None:
    value = {"s": "é" * 10}  # escaped as the converter writes it: 6 bytes each, not UTF-8's 2
    assert size.encoded_bytes(value, JSON) == len(JSON.to_payloads([value])[0].data) + size.CODEC_OVERHEAD
    assert size.encoded_bytes(value, JSON) == len('{"s":"' + "\\u00e9" * 10 + '"}') + size.CODEC_OVERHEAD


def test_the_limits_leave_a_margin_under_temporals() -> None:
    """Every payload the guard lets through, and #15's largest cel.evaluate request once encoded (spec §5.2: its guard
    verified again after the codec)."""
    assert size.PAYLOAD_BYTES < TEMPORAL_PAYLOAD_LIMIT
    assert CEL_REQUEST_BYTES + size.CODEC_OVERHEAD < TEMPORAL_PAYLOAD_LIMIT


def test_fits_reads_the_limit_when_its_called(monkeypatch) -> None:
    assert size.fits("x" * 1_000, JSON)
    monkeypatch.setattr(size, "PAYLOAD_BYTES", 1_000)
    assert not size.fits("x" * 1_000, JSON)


def secrets_at_the_bound() -> list[str]:
    """Sensitive values whose JSON is SECRETS_BYTES exactly: 1,000-character strings, then one to fill up."""
    values, used = [], 2  # the list's brackets
    while used + 1_003 <= size.SECRETS_BYTES:
        values.append(f"{len(values):06d}" + "s" * 994)
        used += len(json.dumps(values[-1])) + (1 if len(values) > 1 else 0)
    values.append("t" * (size.SECRETS_BYTES - used - 3))
    assert size.secrets_bytes(values) == size.SECRETS_BYTES
    return values


def test_the_carried_sensitive_values_are_measured_as_the_converter_writes_them() -> None:
    values = ["é" * 10, "plain-token", '"quoted"']
    assert size.secrets_bytes(values) == len(JSON.to_payloads([values])[0].data)
    assert size.secrets_bytes([]) == 2


def test_every_final_result_fits_whatever_it_carries() -> None:
    """Engine 2b spec §5.2: without outputs or collected items, a result carries an error (a stored message, at most
    500 characters, each escaped to at most 6 bytes) and the sensitive values (at most SECRETS_BYTES): a failure, a
    cancel, `snapshot_too_large`, a stopped batch. Each fits with room to spare."""
    worst = {"code": "x" * 500, "message": "é" * 500, "attempt": 10}
    secrets = secrets_at_the_bound()
    results = [
        RunResult("failed", None, worst, 100_000, secrets),
        BatchResult([], [], stopped=worst, iterations=100_000, secrets=secrets),
        BatchResult(
            [], [], end={"status": "failed", "failure": worst, "stopped": False}, iterations=1, secrets=secrets
        ),
    ]
    assert all(size.encoded_bytes(r, JSON) <= size.PAYLOAD_BYTES // 4 for r in results)
