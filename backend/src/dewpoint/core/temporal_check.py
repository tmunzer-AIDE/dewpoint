# SPDX-License-Identifier: Apache-2.0
"""What `dewpoint temporal check` reads in Temporal's own description of the namespace (2b-4b M4, DW.4; M6's
readiness calls it): a retention of at most 30 days (D3g), archival disabled for history and visibility (erasure
requires it), and a connection whose TLS was verified, never plaintext. The authorizer on D12's server keeps the
namespace so; this reads that it is."""

from temporalio.api.enums.v1 import ArchivalState
from temporalio.api.workflowservice.v1 import DescribeNamespaceResponse

MAX_RETENTION_S = 30 * 86400


def problems(answer: DescribeNamespaceResponse, *, plaintext: bool) -> list[str]:
    found: list[str] = []
    if plaintext:
        found.append("plaintext: TLS isn't verified (DEWPOINT_TEMPORAL_INSECURE_DEV, development only)")
    config = answer.config
    if not config.HasField("workflow_execution_retention_ttl"):
        found.append("no retention reported")
    else:
        ttl = config.workflow_execution_retention_ttl
        if ttl.seconds > MAX_RETENTION_S:
            found.append(f"retention of {ttl.seconds // 86400} days, above 30 (D3g)")
        elif ttl.seconds == MAX_RETENTION_S and ttl.nanos > 0:
            found.append("retention above 30 days (by a fraction of a second)")
    for name, state in (("history", config.history_archival_state),
                        ("visibility", config.visibility_archival_state)):  # fmt: skip
        if state == ArchivalState.ARCHIVAL_STATE_ENABLED:
            found.append(f"{name} archival enabled: archival must stay disabled")
    return found
