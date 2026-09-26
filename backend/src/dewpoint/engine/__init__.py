# SPDX-License-Identifier: Apache-2.0
"""Pure engine code: graph model, validator, registry checks. No DB, no network, no clock."""

ENGINE_ABI = 1  # bump on any change that can alter a run's command sequence (spec §7)
