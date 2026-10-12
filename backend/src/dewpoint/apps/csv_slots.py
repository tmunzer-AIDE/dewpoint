# SPDX-License-Identifier: Apache-2.0
"""The API process's CSV work, bounded (the 2b-4b plan's M3, item 5). At the platform's caps (5 MiB, 10,000 rows, 200
declared columns) an upload's parse peaks near 145 MiB and holds about 90 MiB while it awaits the database, and a CSV
start's rows near 235 MiB until its transaction commits (`tests/probes/csv_memory.py`, Python's own allocations). So a
process takes at most `csv_concurrency` such pieces of work at once; one past it is refused at once, before an upload's
body is read or a start opens its staged file, and the client asks again. A request's slot (`Slot`) is held from when
its CSV work begins until its transaction has committed, and given back however it ends. One event loop takes them in
turn: no lock is needed."""

from collections.abc import Iterator
from contextlib import contextmanager


class CsvBusyError(Exception):
    """Every slot of this process is held."""


class CsvSlots:
    def __init__(self, slots: int) -> None:
        self.slots, self.held_now = slots, 0

    @contextmanager
    def held(self) -> Iterator[None]:
        if self.held_now >= self.slots:
            raise CsvBusyError
        self.held_now += 1
        try:
            yield
        finally:
            self.held_now -= 1


class Slot:
    """One request's hold on its process's slots: taken when its CSV work begins, given back once its transaction has
    committed (the owner's ruling on the M3 checkpoint: the flush and the commit are its work too)."""

    def __init__(self, slots: CsvSlots) -> None:
        self.slots, self.taken = slots, False

    def take(self) -> None:
        """Raises CsvBusyError when every slot is held."""
        if self.taken:
            return
        if self.slots.held_now >= self.slots.slots:
            raise CsvBusyError
        self.slots.held_now += 1
        self.taken = True

    def give_back(self) -> None:
        if self.taken:
            self.slots.held_now -= 1
            self.taken = False
