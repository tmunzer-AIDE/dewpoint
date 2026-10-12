# SPDX-License-Identifier: Apache-2.0
"""The CSV work's memory stays within what each API process's CSV slots were sized for (the 2b-4b plan's M3, item 5;
`apps/csv_slots.py`): the densest file the caps allow, 200 two-character cells a row, here 250 rows of it, its
allocations per cell. The probe (`tests/probes/csv_memory.py`) measured the caps themselves, 8,736 such rows: an upload
holds about 55 bytes a cell, a start about 140, so at most about 90 and 235 MiB. Python's own allocations, counted
(`tracemalloc`): the same on every machine."""

from tests.probes.csv_memory import COLUMNS, measure, measure_start, shapes

ROWS = 250
MIB = 1024 * 1024


def test_the_densest_files_upload_and_start_hold_no_more_a_cell_than_the_slots_were_sized_for() -> None:
    data, columns = shapes(ROWS)["short"]
    upload, start = measure(data, columns), measure_start(data, columns)
    cells = ROWS * COLUMNS
    assert upload["rows"] == start["rows"] == ROWS
    assert upload["retained_mib"] * MIB / cells <= 65
    assert start["retained_mib"] * MIB / cells <= 165
