# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §5.2: a payload is measured as the SDK's JSON converter writes it, plus a bound on what the codec
adds (test_codec.py proves the bound), against a margin under Temporal's 2 MiB."""

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


def test_every_final_result_fits_whatever_it_carries() -> None:
    """Engine 2b spec §5.2: without outputs or collected items, a result carries an error (a stored message, at most
    500 characters, each escaped to at most 6 bytes): a failure, a cancel, `snapshot_too_large`, a stopped batch.
    Each fits with room to spare. A run carries no sensitive values from 2b-1b: they're handles (§3.6)."""
    worst = {"code": "x" * 500, "message": "é" * 500, "attempt": 10}
    results = [
        RunResult("failed", None, worst, 100_000),
        BatchResult([], [], stopped=worst, iterations=100_000),
        BatchResult([], [], end={"status": "failed", "failure": worst, "stopped": False}, iterations=1),
    ]
    assert all(size.encoded_bytes(r, JSON) <= size.PAYLOAD_BYTES // 4 for r in results)
