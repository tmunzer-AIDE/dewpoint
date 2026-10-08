# SPDX-License-Identifier: Apache-2.0
"""The API process's CSV work, bounded (the 2b-4b plan's M3, item 5). At the platform's caps (5 MiB, 10,000 rows, 200
declared columns) an upload's parse peaks near 145 MiB and holds about 90 MiB while it awaits the database, and a CSV
start's rows near 235 MiB until its transaction commits (`tests/probes/csv_memory.py`, Python's own allocations). So a
process takes at most `csv_concurrency` such pieces of work at once; one past it is refused at once, before an upload's
body is read or a start opens its staged file, and the client asks again. A slot is held for the request's whole
handling and freed however it ends. One event loop takes them in turn: no lock is needed."""

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
