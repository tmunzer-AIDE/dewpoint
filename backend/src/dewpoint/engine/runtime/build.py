# SPDX-License-Identifier: Apache-2.0
"""The engine's build id (spec §7): `dewpoint-<version>+abi<ENGINE_ABI>`.

ENGINE_ABI increments on any change that can alter `RunGraph`'s command sequence; its golden histories live in
`tests/engine/replay/<build id>/`. A change that leaves it alone must still replay that directory."""

ENGINE_ABI = 2  # 2a-3b: loop batches, sub-flows, the failure handler and continue-as-new


def build_id(version: str) -> str:
    return f"dewpoint-{version}+abi{ENGINE_ABI}"


__all__ = ["ENGINE_ABI", "build_id"]
