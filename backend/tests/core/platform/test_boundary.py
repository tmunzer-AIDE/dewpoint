# SPDX-License-Identifier: Apache-2.0
"""What a namespace boundary (D3g) is recorded on (2b-4b M4, the owner's ruling on the M4 design): D12's proof record
(`DEWPOINT_PROOF_OUT`'s JSON lines), whole and passed. Both configurations' inventories name the same server build,
every D12 case of each passed or was a case for the other configuration (skipped), and none failed. The record's own
SHA-256 and that build go with the boundary, so the row names the proof and the server it holds for."""

import hashlib
import json
import re

import pytest

from dewpoint.core.platform.boundary import ProofRefusedError, proof_evidence

BUILD = "sha256:" + "ab" * 32


def inventory(config: str, build: str = BUILD) -> dict[str, object]:
    return {"environment": f"d12-{config}", "inventory": {"binary": build, "server_version": "1.32.0", "rpcs": [],
                                                          "endpoints": []}}  # fmt: skip


def case(name: str, outcome: str = "passed", config: str = "mtls") -> dict[str, object]:
    return {"case": f"tests/proofs/d12/test_d12.py::{name}[{config}]", "phase": "call", "outcome": outcome,
            "seconds": 1.0}  # fmt: skip


def lines(*entries: dict[str, object]) -> bytes:
    return "".join(json.dumps(e) + "\n" for e in entries).encode()


PASSED = (
    inventory("mtls"),
    inventory("jwt"),
    case("test_d12_2_through_the_sdk"),
    case("test_d12_2_through_the_sdk", config="jwt"),
    case("test_d12_6_mutual_tls_only", "skipped", "jwt"),
)


def test_a_passed_record_gives_its_digest_and_the_server_build() -> None:
    record = lines(*PASSED)
    evidence = proof_evidence(record)
    assert evidence.server_build == BUILD
    assert evidence.digest == "sha256:" + hashlib.sha256(record).hexdigest()
    assert evidence.passed == 2 and evidence.configurations == ("jwt", "mtls")


@pytest.mark.parametrize(("entries", "why"), [
    ((*PASSED, case("test_d12_4_an_unreachable_bucket_refuses_every_change", "failed")), "failed"),
    ((*PASSED, {**case("test_d12_3_x"), "phase": "setup", "outcome": "failed"}), "failed"),
    ((inventory("mtls"), inventory("jwt", "sha256:" + "cd" * 32), *PASSED[2:]), "two server builds"),
    ((inventory("mtls"), *PASSED[2:]), "configuration B (jwt)"),
    ((*PASSED[2:],), "no inventory"),
    ((inventory("mtls"), inventory("jwt")), "no D12 case passed"),
])  # fmt: skip
def test_a_record_that_isnt_a_whole_pass_is_refused(entries: tuple[dict[str, object], ...], why: str) -> None:
    with pytest.raises(ProofRefusedError, match=re.escape(why)):
        proof_evidence(lines(*entries))


def test_a_record_that_isnt_json_lines_is_refused() -> None:
    with pytest.raises(ProofRefusedError, match="line 2"):
        proof_evidence(lines(inventory("mtls")) + b"not json\n")
