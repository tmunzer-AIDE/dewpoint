# SPDX-License-Identifier: Apache-2.0
"""Control nodes (spec §6): what each one decides once its config is resolved. Publish checked literal configs and
typed every ref and CEL value; the checks here catch open data whose shape publish couldn't know."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dewpoint.engine.cel.evaluate import TYPE_MISMATCH
from dewpoint.engine.registry import control
from dewpoint.engine.runtime import probe
from dewpoint.engine.runtime.scheduler import Failure, RunEnd

INLINE_ITEMS = 100  # larger loops run in batches of this many items, one child workflow per batch (spec §6)
MAX_DELAY_S = 30 * 86_400  # flow.delay's own bound: a value resolved at run time isn't checked by its schema
ITEM_CAP_EXCEEDED = "item_cap_exceeded"
WORKFLOW_FAILED = "workflow_failed"  # a fail node ended the run


@dataclass(frozen=True)
class LoopStart:
    items: Any  # proto: or a handle-backed list
    concurrency: int
    stop_on_error: bool
    batch: int = 0  # > 0: the items run in child workflows of this many


@dataclass(frozen=True)
class SubflowStart:
    """A `run_workflow` step: its pinned version runs as a child with this input. `workflow_id` is the sub-flow's
    workflow, which the child's own row names before its version loads."""

    input: dict[str, Any]
    workflow_id: str


@dataclass(frozen=True)
class Decision:
    output: Any = None
    ports: tuple[str, ...] | None = None  # None: every normal port
    variables: Mapping[str, Any] | None = None
    end: RunEnd | None = None
    wait_s: float | None = None
    wait_until: datetime | None = None  # UTC
    loop: LoopStart | None = None
    filter_items: list[Any] | None = None  # a filter: evaluate its predicate per item
    subflow: SubflowStart | None = None
    failure: Failure | None = None


def _instant(value: Any) -> datetime | None:
    """An RFC 3339 date-time, as UTC; None for anything else, a time without a zone included."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):  # not a date-time; or before year 1 or after 9999 once in UTC
        return None


def _mismatch(message: str) -> Decision:
    return Decision(failure=Failure(TYPE_MISMATCH, message))


def decide(ref: str, config: Mapping[str, Any]) -> Decision:
    if ref == control.IF:
        condition = config.get("condition")
        if not isinstance(condition, bool):
            return _mismatch("`condition` must be true or false.")
        return Decision(output={}, ports=("true" if condition else "false",))
    if ref == control.SWITCH:
        for case in config.get("cases", []):
            if not isinstance(case.get("when"), bool):
                return _mismatch(f"`when` for `{case.get('port')}` must be true or false.")
            if case["when"]:
                return Decision(output={}, ports=(str(case["port"]),))
        return Decision(output={}, ports=("default",))
    if ref == control.SET_VARIABLES:
        return Decision(output={}, variables=dict(config.get("assignments", {})))
    if ref == control.TRANSFORM:
        return Decision(output=dict(config.get("fields", {})))
    if ref == control.STOP:
        return Decision(output={}, end=RunEnd("succeeded", stopped=True))
    if ref == control.FAIL:
        return Decision(output={}, end=RunEnd("failed", Failure(WORKFLOW_FAILED, str(config.get("message", "")))))
    if ref == control.DELAY:
        seconds = config.get("duration_s")
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or not 0 <= seconds <= MAX_DELAY_S:
            return _mismatch(f"`duration_s` must be a number of seconds, from 0 to {MAX_DELAY_S}.")
        return Decision(output={}, wait_s=float(seconds))
    if ref == control.WAIT_UNTIL:
        until = _instant(config.get("until"))
        if until is None:
            return _mismatch("`until` must be a date and time with a time zone, like 2027-01-01T09:00:00+01:00.")
        return Decision(output={}, wait_until=until)
    if ref == control.LOOP:
        items = config.get("items")
        if not isinstance(items, list) and not probe.is_kind(items, probe.LIST):  # proto: or a handle-backed list
            return _mismatch("`items` must be a list.")
        n = probe.count(items)
        cap = int(config.get("item_cap", 10_000))
        if n > cap:
            return Decision(failure=Failure(ITEM_CAP_EXCEEDED, f"{n} items exceed this loop's cap of {cap}."))
        batch = INLINE_ITEMS if n > INLINE_ITEMS else 0
        stop = config.get("on_item_error", "stop") == "stop"
        return Decision(loop=LoopStart(items, int(config.get("concurrency", 1)), stop, batch))
    if ref == control.FILTER:
        items = config.get("items")
        if not isinstance(items, list):
            return _mismatch("`items` must be a list.")
        return Decision(filter_items=items)
    if ref == control.RUN_WORKFLOW:
        data = config.get("input", {})
        if not isinstance(data, dict):
            return _mismatch("`input` must be an object.")
        return Decision(subflow=SubflowStart(dict(data), str(config.get("workflow_id", ""))))
    raise ValueError(f"{ref} isn't a control node")


__all__ = [
    "INLINE_ITEMS",
    "MAX_DELAY_S",
    "ITEM_CAP_EXCEEDED",
    "WORKFLOW_FAILED",
    "Decision",
    "LoopStart",
    "SubflowStart",
    "decide",
]
