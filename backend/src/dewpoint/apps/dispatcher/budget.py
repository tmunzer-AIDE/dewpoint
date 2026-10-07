# SPDX-License-Identifier: Apache-2.0
"""A dispatcher pass's soft budget (the owner's D16 review of the 2b-4b M1 checkpoint 3: a prototype to test, not a
guarantee, its numbers not approved). Each pass takes its items through `passing`:

- It always takes its first item. It takes no new one once it has run `PASS_S`, or once a Temporal call made in it
  took longer than `SLOW_S`, ran out its deadline or found Temporal unavailable (`instrument` times every call the
  client makes, retries included, on the SDK's one RPC path). An item it took runs to its end: each is resumable or
  idempotent, and the items it didn't take stay due, `deferred`, for the next cycle.
- Each pass has its own budget, so the passes after a slow one in the cycle still take theirs.
- Among the items a pass picked, it takes first those it hasn't taken lately (`_visits`, per pass, in this process),
  so one slow item can't keep the others waiting: the pass's own order (its candidates') breaks ties.

So a pass lasts at most `PASS_S` and one item's calls, each at its own worst: its deadline, and the SDK's retries for
the calls that retry. No deadline here is shorter (the owner kept the 10-second ones)."""

import time
from collections.abc import Callable, Hashable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

PASS_S = 10.0  # a pass takes no new item once it has run this long (its first, always)
SLOW_S = 1.0  # a call slower than this ends its pass's admission once its item ends
SLOW = (RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE)  # answers that end it too
DEGRADED_ALERT_S = 300.0  # a pass a slow call stopped alerts at most this often

log = structlog.get_logger("dewpoint.dispatcher.budget")
_alerted: dict[str, float] = {}  # per pass: when it last alerted

_visits: dict[str, dict[Hashable, float]] = {}  # per pass: when each item it picked was last taken
_current: ContextVar["Admitted | None"] = ContextVar("dewpoint_pass", default=None)


class Admitted:
    """A pass's admission: call it with the items picked for those it takes, in its order: by `key`, those it took
    least lately first; without one, in theirs (dispatch's: its own rotation is its order)."""

    def __init__(self, name: str) -> None:
        self.name, self.started, self.slow, self.taken, self.deferred = name, time.monotonic(), False, 0, 0

    def reported(self, counts: dict[str, int], *, full: bool = False) -> None:
        """Its degraded state, explicit in `counts` (the owner's review of checkpoint 4: a steadily slow Temporal
        leaves each pass one item a cycle, never taken for its accounting): the items picked but not taken
        (`deferred`), a slow call having stopped it (`slow`), and its selection full (`backlog`: more may wait beyond
        what it picked, which `deferred` doesn't count)."""
        if self.deferred:
            counts["deferred"] = self.deferred
        if self.slow:
            counts["slow"] = 1
        if full:
            counts["backlog"] = 1

    def _admits(self) -> bool:
        return not self.taken or not (self.slow or time.monotonic() - self.started >= PASS_S)

    def __call__[T](self, items: Iterable[T], key: Callable[[T], Hashable] | None = None) -> Iterator[T]:
        ordered, seen = list(items), {}
        if key is not None:
            seen = {k: at for k, at in _visits.get(self.name, {}).items() if k in {key(i) for i in ordered}}
            _visits[self.name] = seen
            ranked = sorted(enumerate(ordered), key=lambda p: (seen.get(key(p[1]), float("-inf")), p[0]))
            ordered = [item for _, item in ranked]
        for n, item in enumerate(ordered):
            if not self._admits():
                self.deferred = len(ordered) - n
                return
            self.taken += 1
            if key is not None:
                seen[key(item)] = time.monotonic()
            yield item


@contextmanager
def passing(name: str) -> Iterator[Admitted]:
    """A pass's budget, from now: the calls made within count against it."""
    admitted = Admitted(name)
    token = _current.set(admitted)
    try:
        yield admitted
    finally:
        _current.reset(token)
        now = time.monotonic()
        if admitted.slow and now - _alerted.get(name, float("-inf")) >= DEGRADED_ALERT_S:
            _alerted[name] = now
            log.error("dispatcher_pass_degraded", pass_name=name, taken=admitted.taken, deferred=admitted.deferred)


def _slowed() -> None:
    admitted = _current.get()
    if admitted is not None:
        admitted.slow = True


def instrument(client: Client) -> None:
    """Every call `client` makes timed, on the SDK's one RPC path (the service client's `_rpc_call`, which every
    workflow-service call and every handle's goes through, its retries inside it); once, however often it's called."""
    service: Any = client.service_client
    if getattr(service, "_dewpoint_timed", False):
        return

    async def timed(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            return await type(service)._rpc_call(service, *args, **kwargs)
        except RPCError as e:
            if e.status in SLOW:
                _slowed()
            raise
        finally:
            if time.monotonic() - started > SLOW_S:
                _slowed()

    service._rpc_call = timed
    service._dewpoint_timed = True
