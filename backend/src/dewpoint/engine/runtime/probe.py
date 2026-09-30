# SPDX-License-Identifier: Apache-2.0
"""Proto only (2b-1b go/no-go): what each execution's scheduler measured, by workflow id, for the harness to read in
the same process (passed through the sandbox, so every workflow writes the one dict); and the prototype's handles and
limits (engine 2b spec §5.1-5.4), which stand in for 2b-1b's claims.

Handles are dicts under the reserved key `$probe`:
- a list:  {"$probe": "list", "id", "n", "per", "from"}: n items in segments `id/k` of `per` items, from index `from`;
- an item: {"$probe": "item", "id", "i", "per"}: one item of such a list;
- a value: {"$probe": "value", "id", "bytes"}: a spilled value, in segment `id`;
- a collection: {"$probe": "coll", "base", "n", "offset", "segs", "tail"}: a loop's collected values, in segments
  `base/first` ([first, count, bytes] each, sparse [[index, value], ...] pairs) and an inline tail of pairs."""

import json
from dataclasses import dataclass
from typing import Any

PEAKS: dict[str, dict[str, int]] = {}

KIND = "$probe"
LIST, ITEM, VALUE, COLL = "list", "item", "value", "coll"
INLINE_LIMIT = 65_536  # §5.1: a value larger than this is a size claim
FLOOR = 1_024  # §5.4: above the budget, activities claim outputs larger than this
LIVE_BUDGET = 1_048_576  # §5.3: the live-state budget
SEG_BYTES = 262_144  # a collection's tail is spilled as one segment once it passes this
SPILL = "probe.spill"


@dataclass(frozen=True)
class SpillInput:
    id: str
    value: Any


def note(workflow_id: str, probe: dict[str, Any]) -> None:
    current = PEAKS.setdefault(workflow_id, {})
    for key, value in probe.items():
        current[key] = max(current.get(key, 0), int(value))


def size(value: Any) -> int:
    """What a value adds to the live state: its compact JSON."""
    return len(json.dumps(value, separators=(",", ":")))


def is_kind(value: Any, kind: str) -> bool:
    return isinstance(value, dict) and value.get(KIND) == kind


def count(items: Any) -> int:
    return int(items["n"]) if is_kind(items, LIST) else len(items)


def item_at(items: Any, pos: int) -> Any:
    if is_kind(items, LIST):
        return {KIND: ITEM, "id": items["id"], "i": int(items.get("from", 0)) + pos, "per": items["per"]}
    return items[pos]


def sliced(items: Any, start: int, stop: int) -> Any:
    if is_kind(items, LIST):
        return {
            KIND: LIST,
            "id": items["id"],
            "n": stop - start,
            "per": items["per"],
            "from": int(items.get("from", 0)) + start,
        }
    return items[start:stop]
