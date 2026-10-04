# SPDX-License-Identifier: Apache-2.0
"""Ingress's limits before authentication (engine 2b spec §8.3; the owner's rulings 5 and 7), which depend on nothing
an endpoint has, so none tells a sender an endpoint exists. Both are each process's own, in memory: a failed request
costs no database write."""

import math
from collections import OrderedDict


class FailureLimiter:
    """Failed requests per address in fixed windows: an address that has failed `failures` times in the window its
    first failure opened is refused until that window ends. The table is bounded: a full one drops the address that
    failed least recently (in constant time, so a flood of addresses costs each request no more)."""

    def __init__(self, failures: int, window_s: float, max_entries: int = 65_536) -> None:
        self.failures, self.window_s, self.max_entries = failures, window_s, max_entries
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()  # address -> (window start, failures)

    def __len__(self) -> int:
        return len(self._windows)

    def blocked(self, key: str, now: float) -> int | None:
        """The whole seconds until `key` may try again, or None."""
        window = self._windows.get(key)
        if window is None or now >= window[0] + self.window_s or window[1] < self.failures:
            return None
        return max(1, math.ceil(window[0] + self.window_s - now))

    def fail(self, key: str, now: float) -> None:
        window = self._windows.pop(key, None)
        if window is None or now >= window[0] + self.window_s:
            window = (now, 0)
        while len(self._windows) >= self.max_entries:
            self._windows.popitem(last=False)
        self._windows[key] = (window[0], window[1] + 1)  # last: the most recent failure


class InFlight:
    """The requests a process is serving; one past the limit is refused before its body is read."""

    def __init__(self, limit: int) -> None:
        self.limit, self.count = limit, 0

    def try_acquire(self) -> bool:
        if self.count >= self.limit:
            return False
        self.count += 1
        return True

    def release(self) -> None:
        self.count -= 1
