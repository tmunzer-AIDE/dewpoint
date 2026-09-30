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
import uuid
from dataclasses import dataclass
from typing import Any

PEAKS: dict[str, dict[str, int]] = {}
ROOT_BUDGET: list[int] = []  # proto: the harness may lower a root run's iteration cap (the module passes the sandbox)

KIND = "$probe"
LIST, ITEM, VALUE, COLL = "list", "item", "value", "coll"
AT = "at"  # {"$probe": "at", "of": a list or collection handle, "ptr"}: a pointer into a handle-backed list
CHAIN = "$chain"  # a chain claim: {"$chain": a container's part, "prev": the previous claim's handle, or null}
POINTER_MAX = 256  # §3.2: a handle's pointer, encoded, at most; a longer reference derives a new claim
CLAIM_ID_MAX = 36 + 1 + 10  # proto: a claim id is a UUID, and a segment's `/<k>`
DERIVE = "probe.derive"
CLAIM_INPUT = "probe.claim_input"
TRIGGER_INLINE = 65_536  # §3.5: a trigger or sub-flow input envelope, at most, once claimed
_NS = uuid.UUID("5e3b1c0e-2b1b-4f00-9a00-000000000001")
INLINE_LIMIT = 65_536  # §5.1: a value larger than this is a size claim
FLOOR = 1_024  # §5.4: above the budget, activities claim outputs larger than this
LIVE_BUDGET = 1_048_576  # §5.3: the live-state budget
SEG_BYTES = 262_144  # a collection's tail is spilled as one segment once it passes this
SPILL = "probe.spill"


@dataclass(frozen=True)
class SpillInput:
    id: str
    value: Any


@dataclass(frozen=True)
class DeriveInput:
    """Proto (§3.2): copy what `handle` addresses into claim `id`, so the reference holds that claim's handle."""

    id: str
    handle: dict[str, Any]


@dataclass(frozen=True)
class ClaimInput:
    """Proto (§3.5): split a sub-flow's input to its envelope before the child starts; claims under `base`."""

    base: str
    value: Any


def claim_id(logical: str) -> str:
    """Proto: a claim's id, derived deterministically from its logical path, and bounded (a UUID)."""
    return str(uuid.uuid5(_NS, logical))


def esc(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def tokens(ptr: str) -> list[str]:
    return [t.replace("~1", "/").replace("~0", "~") for t in ptr.split("/")[1:]] if ptr else []


def handle(claim: str) -> dict[str, Any]:
    """A claim's handle, with an empty pointer."""
    return {KIND: VALUE, "id": claim}


def is_handle(value: Any) -> bool:
    return isinstance(value, dict) and value.get(KIND) in (VALUE, ITEM, LIST, COLL, AT)


def extend(h: dict[str, Any], seg: Any) -> dict[str, Any]:
    """A reference one step further into what handle `h` addresses: its pointer grows, so the workflow never reads
    the claim (§3.3). Past POINTER_MAX, the workflow derives a claim of it instead (`DeriveInput`)."""
    tok = esc(seg)
    kind = h[KIND]
    if kind == VALUE:
        return {KIND: VALUE, "id": h["id"], "ptr": h.get("ptr", "") + "/" + tok}
    if kind == ITEM:
        return {KIND: VALUE, "id": f"{h['id']}/{h['i'] // h['per']}", "ptr": f"/{h['i'] % h['per']}/{tok}"}
    if kind == AT:
        return {**h, "ptr": h["ptr"] + "/" + tok}
    return {KIND: AT, "of": h, "ptr": "/" + tok}


def long_pointer(h: dict[str, Any]) -> bool:
    return size(h.get("ptr", "")) > POINTER_MAX


# the largest handle the live state can hold: a claim id at its longest and a pointer at POINTER_MAX
HANDLE_MAX = len(
    json.dumps({KIND: VALUE, "id": "x" * CLAIM_ID_MAX, "ptr": "x" * (POINTER_MAX - 2)}, separators=(",", ":"))
)


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
