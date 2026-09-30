# SPDX-License-Identifier: Apache-2.0
"""Pure engine code: graph model, validator, registry checks. No DB, no network, no clock."""

# The one engine ABI (spec §7): publishing stamps and hashes a version with it, and the build id names it. Bump it on
# any change that can alter a run's command sequence. 2: 2a-3b's loop batches, sub-flows, the failure handler and
# continue-as-new. 3: 2a-3c's local CEL. 4: issue #15's cel.evaluate requests, cut by their bytes, refused when one
# binding set can't fit, and paced per workflow task. 5: 2b-1a's workflow ids, built from the tenant and the run
# (sub-flows' and failure handlers' too), and what a run sends Temporal, measured before it's sent: a loop's batch cut
# by bytes, a continued run's state within 1.5 MiB, every command paced per workflow task; `cel.evaluate` on a queue of
# the build's ABI.
ENGINE_ABI = 5
