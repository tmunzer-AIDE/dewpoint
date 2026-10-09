# SPDX-License-Identifier: Apache-2.0
"""A tenant's queue of webhook requests, capped by the deployment's ingress capacity (the owner's ruling 2 on 2b-4b's M3
checkpoint 2): the matcher holds an event pending past it, and the platform admin's API shows it."""

import math
from typing import Any

from dewpoint.core.ingress.filters import MAX_BINDINGS

# A tenant's queued webhook requests at most, until the deployment's ingress capacity is set: development-only, never a
# production value
DEV_QUEUED = 10_000


def queue_cap(platform: Any) -> int:
    """A tenant's queued webhook requests at most: the headroom's share of the deployment's measured starts for the
    agreed wait, never below an event's most bindings (one must fit, or it never matches); `DEV_QUEUED` until all
    three are set."""
    starts, headroom, wait = platform.ingress_starts_per_s, platform.ingress_headroom, platform.ingress_queue_wait_s
    if starts is None or headroom is None or wait is None:
        return DEV_QUEUED
    return max(MAX_BINDINGS, math.floor(starts * headroom * wait))
