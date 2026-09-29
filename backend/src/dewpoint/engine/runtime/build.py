# SPDX-License-Identifier: Apache-2.0
"""The engine's build id (spec §7): `dewpoint-<version>+abi<ENGINE_ABI>`.

ENGINE_ABI (`dewpoint.engine`) increments on any change that can alter `RunGraph`'s command sequence; its golden
histories live in `tests/engine/replay/<build id>/`. A change that leaves it alone must still replay that directory."""

from dewpoint.engine import ENGINE_ABI


def build_id(version: str) -> str:
    return f"dewpoint-{version}+abi{ENGINE_ABI}"


def abi_of(build: str) -> int | None:
    """The engine ABI a Dewpoint build ID names; None for an ID that isn't one."""
    name, plus, abi = build.rpartition("+abi")
    return int(abi) if plus and name.startswith("dewpoint-") and abi.isdecimal() else None


__all__ = ["abi_of", "build_id"]
