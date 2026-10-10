# SPDX-License-Identifier: Apache-2.0
"""What a namespace boundary (D3g, `namespace_boundaries`) is recorded on (2b-4b M4, the owner's ruling on the M4
design): D12's proof record, the JSON lines its suites write to `DEWPOINT_PROOF_OUT` (tests/proofs/conftest.py), whole
and passed. Both configurations' inventories (A, mutual TLS; B, a JWT bearer token) name the same server build; no
case anywhere in the record failed, in any phase; and every required case passed: each of D6's (D12's audit trail is
D6's bucket), each of D12's on both configurations (skipped only where it's the other configuration's case), and
D12's cases outside them. A partial run (a `-k`, an interruption) isn't a whole pass (the review's I3). The lists
below are the proof suites' own cases; a test keeps them so. The record's own SHA-256 and that build go with the
boundary row, which so names the proof and the server it holds for. A local deployment's boundary only: production's
waits for real-target qualification."""

import hashlib
import json
from dataclasses import dataclass

CONFIGURATIONS = {"mtls": "configuration A (mtls)", "jwt": "configuration B (jwt)"}

D6_CASES = (  # tests/proofs/d6/test_d6.py
    "test_d6_0_the_writer_and_the_verifier_are_demonstrably_apart",
    "test_d6_1_a_written_anchor_is_a_locked_version",
    "test_d6_2_deleting_the_version_is_refused_to_the_writer_and_to_root",
    "test_d6_3_shortening_or_changing_the_lock_is_refused",
    "test_d6_4_a_plain_delete_adds_a_marker_and_verify_fails",
    "test_d6_5_rewriting_a_key_adds_a_version_and_verify_fails",
    "test_d6_6a_verify_passes_on_an_untouched_sequence",
    "test_d6_6b_verify_fails_on_a_bad_signature",
    "test_d6_6c_verify_fails_on_a_hash_mismatch",
    "test_d6_6d_verify_fails_on_a_missing_anchor",
    "test_d6_6e_verify_fails_on_a_chain_break",
    "test_d6_7_a_listing_longer_than_a_page_is_verified_whole",
    "test_d6_8_every_versions_lock_is_checked",
    "test_d6_9_the_default_retention_is_checked_against_the_configured_periods",
    "test_d6_10_the_monitor_alerts_on_a_missing_scope_and_a_withheld_anchor",
    "test_d6_11_the_monitor_alerts_on_a_lost_or_rolled_back_mark",
)
D12_CASES = (  # tests/proofs/d12/test_d12.py, each run on configuration A, then B
    "test_d12_1_the_inventory_classes_every_rpc_and_lists_every_endpoint",
    "test_d12_1_only_the_frontend_listens_on_the_network",
    "test_d12_2_through_the_sdk",
    "test_d12_2_through_the_temporal_cli",
    "test_d12_2_through_the_http_api",
    "test_d12_3_every_refused_rpc_is_refused_and_audited_on_the_public_frontend",
    "test_d12_3_the_internal_frontend_runs_the_same_authorizer",
    "test_d12_3_nexus_routes_are_closed",
    "test_d12_4_a_bucket_refusing_writes_refuses_every_change",
    "test_d12_4_an_unreachable_bucket_refuses_every_change",
    "test_d12_4_a_failure_injected_for_one_namespace_leaves_the_other_writers",
    "test_d12_5_the_servers_certificate_is_verified",
    "test_d12_6_mutual_tls_only",
    "test_d12_7_a_bearer_token_only",
    "test_d12_8_describe_namespace_reports_retention_and_archival",
    "test_d12_9_and_10_deletion_reads_back_not_found_and_the_prefix_query_finds_a_tenant",
    "test_d12_11_a_paused_schedule_fires_nothing_and_a_stale_update_is_discarded",
    "test_d12_11_premise_temporal_restarts_a_recreated_schedules_token",
    "test_d12_11_incarnation_fencing_keeps_a_stale_unpause_off_a_late_create",
    "test_dw_2_dewpoints_runs_start_and_complete_here",
    "test_dw_1_plaintext_is_refused_outside_development_and_isnt_served",
    "test_dw_3_a_replaced_token_is_picked_up_without_a_restart",
    "test_dw_4_the_check_passes_here",
)
ONE_CONFIGURATION = {  # a case of one configuration's, skipped on the other's
    "test_d12_6_mutual_tls_only": "mtls",
    "test_d12_7_a_bearer_token_only": "jwt",
    "test_dw_3_a_replaced_token_is_picked_up_without_a_restart": "jwt",
}
D12_ELSEWHERE = ("test_dw_4_the_check_fails_on_a_wide_namespace_elsewhere",)  # on a dev server of its own, once


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
    start_checks: dict[str, str] = {}  # each configuration's server: its start check's mode, as its inventory names it
    failed: list[str] = []
    outcomes: dict[tuple[str, str, str], str] = {}  # (proof, case, configuration) -> passed or skipped
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
            start_checks[environment.removeprefix("d12-")] = str(entry["inventory"].get("start_check", "missing"))
        if "case" in entry:
            if entry.get("outcome") == "failed":
                failed.append(str(entry["case"]))
            elif entry.get("outcome") in ("passed", "skipped"):
                outcomes[_case(str(entry["case"]))] = str(entry["outcome"])
    if failed:
        raise ProofRefusedError(f"{len(failed)} case(s) failed, the first {failed[0]}")
    if not builds:
        raise ProofRefusedError("no inventory: D12.1 didn't run")
    for configuration, name in CONFIGURATIONS.items():
        if configuration not in builds:
            raise ProofRefusedError(f"no inventory for {name}")
    if len(set(builds.values())) != 1:
        raise ProofRefusedError("the inventories name two server builds")
    for configuration, name in CONFIGURATIONS.items():  # a prerequisite only: on proves nothing by itself
        mode = start_checks.get(configuration)
        if mode != "on":
            raise ProofRefusedError(f"the start check wasn't on for {name} (its inventory shows {mode}): "
                                    "a prerequisite of any boundary's record")  # fmt: skip
    required = [("d6", name, "") for name in D6_CASES]
    required += [("d12", name, config) for name in D12_CASES for config in CONFIGURATIONS]
    required += [("d12", name, "") for name in D12_ELSEWHERE]
    for proof, name, config in required:
        outcome = outcomes.get((proof, name, config))
        other = ONE_CONFIGURATION.get(name)
        if outcome == "passed" or (outcome == "skipped" and other is not None and other != config):
            continue
        raise ProofRefusedError(f"{name}{f' [{config}]' if config else ''} didn't pass")
    passed = sum(1 for (proof, _, _), outcome in outcomes.items() if proof == "d12" and outcome == "passed")
    [build] = set(builds.values())
    return Evidence(digest="sha256:" + hashlib.sha256(record).hexdigest(), server_build=build,
                    configurations=tuple(sorted(builds)), passed=passed)  # fmt: skip


def _case(node: str) -> tuple[str, str, str]:
    """A recorded case's (proof, name, configuration) from its pytest node id."""
    proof = "d12" if "/proofs/d12/" in node else "d6" if "/proofs/d6/" in node else ""
    name, _, rest = node.rpartition("::")[2].partition("[")
    return proof, name, rest.rstrip("]")
