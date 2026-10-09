# SPDX-License-Identifier: Apache-2.0
"""What a namespace boundary (D3g, `namespace_boundaries`) is recorded on (2b-4b M4, the owner's ruling on the M4
design): D12's proof record, the JSON lines its suites write to `DEWPOINT_PROOF_OUT` (tests/proofs/conftest.py), whole
and passed. Both configurations' inventories (A, mutual TLS; B, a JWT bearer token) name the same server build; no
case anywhere in the record failed, D6's included (D12's audit trail is D6's bucket); and at least one D12 case
passed. The record's own SHA-256 and that build go with the boundary row, which so names the proof and the server it
holds for. A local deployment's boundary only: production's waits for real-target qualification."""

import hashlib
import json
from dataclasses import dataclass

CONFIGURATIONS = {"mtls": "configuration A (mtls)", "jwt": "configuration B (jwt)"}


class ProofRefusedError(ValueError):
    """The record isn't a whole, passed D12 proof."""


@dataclass(frozen=True)
class Evidence:
    digest: str  # sha256:<hex> of the record as given
    server_build: str  # sha256:<hex> of the server binary both inventories name
    configurations: tuple[str, ...]
    passed: int  # D12 cases passed


def proof_evidence(record: bytes) -> Evidence:
    builds: dict[str, str] = {}
    failed: list[str] = []
    passed = 0
    for number, line in enumerate(record.decode().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            raise ProofRefusedError(f"line {number} isn't JSON") from None
        environment = str(entry.get("environment", ""))
        if environment.startswith("d12-") and isinstance(entry.get("inventory"), dict):
            builds[environment.removeprefix("d12-")] = str(entry["inventory"].get("binary", ""))
        if "case" in entry:
            if entry.get("outcome") == "failed":
                failed.append(str(entry["case"]))
            elif entry.get("outcome") == "passed" and "/proofs/d12/" in str(entry["case"]):
                passed += 1
    if failed:
        raise ProofRefusedError(f"{len(failed)} case(s) failed, the first {failed[0]}")
    if not builds:
        raise ProofRefusedError("no inventory: D12.1 didn't run")
    for configuration, name in CONFIGURATIONS.items():
        if configuration not in builds:
            raise ProofRefusedError(f"no inventory for {name}")
    if len(set(builds.values())) != 1:
        raise ProofRefusedError("the inventories name two server builds")
    if passed == 0:
        raise ProofRefusedError("no D12 case passed")
    [build] = set(builds.values())
    return Evidence(digest="sha256:" + hashlib.sha256(record).hexdigest(), server_build=build,
                    configurations=tuple(sorted(builds)), passed=passed)  # fmt: skip
