# SPDX-License-Identifier: Apache-2.0
"""Production readiness's checks, each failing closed (the 2b-4b plan's M6). The ingress capacity's is here first (the
owner's ruling on 2b-4b's M3 checkpoint 3): M6's enable command and D14's ingress switch refuse while it's not whole."""

from typing import Any

CAPACITY = ("starts_per_s", "headroom", "queue_wait_s")


def ingress_capacity(platform: Any) -> list[str]:
    """The ingress capacity's values still unset, in their order: none when it's whole."""
    values = (platform.ingress_starts_per_s, platform.ingress_headroom, platform.ingress_queue_wait_s)
    return [name for name, value in zip(CAPACITY, values, strict=True) if value is None]
