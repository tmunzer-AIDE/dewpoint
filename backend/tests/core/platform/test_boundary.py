# SPDX-License-Identifier: Apache-2.0
"""What a namespace boundary (D3g) is recorded on (2b-4b M4, the owner's ruling on the M4 design): D12's proof record
(`DEWPOINT_PROOF_OUT`'s JSON lines), whole and passed. Both configurations' inventories name the same server build,
every D12 case of each passed or was a case for the other configuration (skipped), and none failed. The record's own
SHA-256 and that build go with the boundary, so the row names the proof and the server it holds for."""

import hashlib
import json
import re

import pytest

from dewpoint.core.platform.boundary import (
    D6_CASES,
    D12_CASES,
    D12_ELSEWHERE,
    ONE_CONFIGURATION,
    ProofRefusedError,
    proof_evidence,
)

BUILD = "sha256:" + "ab" * 32


def inventory(config: str, build: str = BUILD, start_check: str | None = "on") -> dict[str, object]:
    found: dict[str, object] = {"binary": build, "server_version": "1.32.0", "rpcs": [], "endpoints": []}
    if start_check is not None:
        found["start_check"] = start_check
    return {"environment": f"d12-{config}", "inventory": found}


def case(name: str, outcome: str = "passed", config: str | None = "mtls", proof: str = "d12") -> dict[str, object]:
    suffix = f"[{config}]" if config else ""
    return {"case": f"tests/proofs/{proof}/test_{proof}.py::{name}{suffix}", "phase": "call", "outcome": outcome,
            "seconds": 1.0}  # fmt: skip


def every_case() -> list[dict[str, object]]:
    """A whole run's cases: each D6 case, each D12 case on both configurations (skipped where it's the other's), and
    the D12 cases outside them."""
    found = [case(name, proof="d6", config=None) for name in D6_CASES]
    for name in D12_CASES:
        for config in ("mtls", "jwt"):
            only = ONE_CONFIGURATION.get(name)
            found.append(case(name, "skipped" if only and only != config else "passed", config))
    return found + [case(name, config=None) for name in D12_ELSEWHERE]


def lines(*entries: dict[str, object]) -> bytes:
    return "".join(json.dumps(e) + "\n" for e in entries).encode()


CASES = tuple(every_case())
PASSED = (inventory("mtls"), inventory("jwt"), *CASES)


def test_a_passed_record_gives_its_digest_and_the_server_build() -> None:
    record = lines(*PASSED)
    evidence = proof_evidence(record)
    assert evidence.server_build == BUILD
    assert evidence.digest == "sha256:" + hashlib.sha256(record).hexdigest()
    d12_passed = sum(1 for c in CASES if "/d12/" in str(c["case"]) and c["outcome"] == "passed")
    assert evidence.passed == d12_passed and evidence.configurations == ("jwt", "mtls")


@pytest.mark.parametrize(("entries", "why"), [
    ((*PASSED, case("test_d12_4_an_unreachable_bucket_refuses_every_change", "failed")), "failed"),
    ((*PASSED, {**case("test_d12_3_x"), "phase": "setup", "outcome": "failed"}), "failed"),
    ((inventory("mtls"), inventory("jwt", "sha256:" + "cd" * 32), *CASES), "two server builds"),
    ((inventory("mtls"), *CASES), "configuration B (jwt)"),
    ((*CASES,), "no inventory"),
    ((inventory("mtls"), inventory("jwt")), "didn't pass"),
    ((*PASSED, {**case("test_d12_5_the_servers_certificate_is_verified"), "phase": "teardown", "outcome": "failed"}),
     "failed"),
])  # fmt: skip
def test_a_record_that_isnt_a_whole_pass_is_refused(entries: tuple[dict[str, object], ...], why: str) -> None:
    with pytest.raises(ProofRefusedError, match=re.escape(why)):
        proof_evidence(lines(*entries))


@pytest.mark.parametrize("mode", ["off", "unset", "invalid", None])
def test_a_server_whose_start_check_isnt_on_is_refused(mode: str | None) -> None:
    """The start-check slice: an inventory must show the check on, in every configuration, before a boundary is
    recorded from its run; one off by omission or explicitly is never enough."""
    with pytest.raises(ProofRefusedError, match="start check"):
        proof_evidence(lines(inventory("mtls"), inventory("jwt", start_check=mode), *CASES))


def test_the_start_check_on_is_a_prerequisite_never_the_proof() -> None:
    """On is required, and proves nothing by itself: a run whose cases didn't all pass is refused all the same."""
    with pytest.raises(ProofRefusedError, match="didn't pass"):
        proof_evidence(lines(inventory("mtls"), inventory("jwt")))


def test_a_record_that_isnt_json_lines_is_refused() -> None:
    with pytest.raises(ProofRefusedError, match="line 2"):
        proof_evidence(lines(inventory("mtls")) + b"not json\n")


def without(name: str, config: str | None) -> tuple[dict[str, object], ...]:
    suffix = f"[{config}]" if config else ""
    return tuple(c for c in PASSED if not str(c.get("case", "")).endswith(f"::{name}{suffix}"))


@pytest.mark.parametrize(("entries", "why"), [
    # the review's I3: a partial run (`-k`, an interrupted one) isn't a whole pass
    (without("test_d12_4_a_bucket_refusing_writes_refuses_every_change", "jwt"),
     "test_d12_4_a_bucket_refusing_writes_refuses_every_change [jwt] didn't pass"),
    (without("test_d6_2_deleting_the_version_is_refused_to_the_writer_and_to_root", None),
     "test_d6_2_deleting_the_version_is_refused_to_the_writer_and_to_root didn't pass"),
    (without("test_dw_4_the_check_fails_on_a_wide_namespace_elsewhere", None), "didn't pass"),
    # a configuration's own case skipped is a gap, not the other configuration's skip
    ((*without("test_d12_6_mutual_tls_only", "mtls"), case("test_d12_6_mutual_tls_only", "skipped", "mtls")),
     "test_d12_6_mutual_tls_only [mtls] didn't pass"),
])  # fmt: skip
def test_a_run_missing_any_required_case_is_refused(entries: tuple[dict[str, object], ...], why: str) -> None:
    with pytest.raises(ProofRefusedError, match=re.escape(why)):
        proof_evidence(lines(*entries))


def test_the_required_cases_are_the_suites_own() -> None:
    """The lists the record is checked against name exactly the proof suites' cases: a case added to a suite, or
    renamed, changes what a whole pass is here too."""
    from tests.proofs.d6 import test_d6
    from tests.proofs.d12 import test_d12

    def cases(module: object) -> set[str]:
        return {name for name in vars(module) if name.startswith("test_")}

    assert set(D6_CASES) == cases(test_d6)
    assert set(D12_CASES) | set(D12_ELSEWHERE) == cases(test_d12)
    assert set(ONE_CONFIGURATION) <= set(D12_CASES)
