# SPDX-License-Identifier: Apache-2.0
"""Evaluator settings: read from an allow-listed environment. Anything else present refuses the start, so a
deployment mistake can't hand the evaluator a credential."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SETTINGS = frozenset({"DEWPOINT_CEL_SOCKET", "DEWPOINT_CEL_MAX_SLOTS", "DEWPOINT_CEL_CGROUP", "DEWPOINT_CEL_PROFILE"})
# Set by the OS, the container runtime or the python base image; none of them can carry a secret.
PLATFORM = frozenset(
    {
        "PATH", "HOME", "HOSTNAME", "LANG", "LC_ALL", "TERM", "TZ",
        "PYTHONPATH", "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
        "PYTHON_VERSION", "PYTHON_SHA256", "GPG_KEY",
    }
)  # fmt: skip
ALLOWED = SETTINGS | PLATFORM
DEFAULT_SOCKET = "/run/dewpoint-cel/cel.sock"


class StartupError(RuntimeError):
    """The evaluator refuses to start; the message says why and what to change."""


@dataclass(frozen=True)
class Config:
    socket: str
    max_slots: int | None
    cgroup: Path
    expected_profile: str | None


def load(environ: Mapping[str, str]) -> Config:
    unexpected = sorted(set(environ) - ALLOWED)
    if unexpected:
        raise StartupError(
            "refusing to start: unexpected environment variables "
            f"{', '.join(unexpected)}. The evaluator holds no secrets; give it only {', '.join(sorted(SETTINGS))}."
        )
    raw_slots = environ.get("DEWPOINT_CEL_MAX_SLOTS")
    try:
        max_slots = int(raw_slots) if raw_slots else None
    except ValueError:
        raise StartupError("DEWPOINT_CEL_MAX_SLOTS must be a whole number") from None
    return Config(
        socket=environ.get("DEWPOINT_CEL_SOCKET", DEFAULT_SOCKET),
        max_slots=max_slots,
        cgroup=Path(environ.get("DEWPOINT_CEL_CGROUP", "/sys/fs/cgroup")),
        expected_profile=environ.get("DEWPOINT_CEL_PROFILE") or None,
    )
