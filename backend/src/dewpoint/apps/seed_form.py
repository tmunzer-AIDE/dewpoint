# SPDX-License-Identifier: Apache-2.0
"""A step's seed contract as the Test tab shows it (B8; the simulation design §5.2, §6.6, §7.6): each entry with its
types, presence, null and sensitivity, prefilled from its step's own sample only where D-s2 allows, else typed, saying
why. Whether a sample fits is the contract's own check, as admission makes it: the UI ships no schema validator."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.retention.cutoff import Cutoff
from dewpoint.core.runs import samples
from dewpoint.engine.graph import seeds
from dewpoint.engine.handles import MARKER
from dewpoint.engine.runtime.projection import REDACTED, TRUNCATED

NON_FINITE = frozenset({"nan", "inf", "-inf"})  # how storage names a number JSON can't hold (`projection.storable`)
UNSTORABLE = "�"  # storage's stand-in for NUL and lone surrogates
_ABSENT = object()


@dataclass(frozen=True)
class Prefill:
    """A seed's value from its step's sample, or why it's typed: `sensitive`, `not_step_output` (the trigger,
    variables, a loop's frame, an error path), `no_sample`, `not_faithful`, `not_in_sample`, `doesnt_fit`."""

    value: Any = None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"state": "typed" if self.reason else "prefilled", "value": self.value, "reason": self.reason}


def faithful(value: Any) -> bool:
    """Whether a stored preview is, provably, what the step output (D-s2): no redaction, truncation or handle marker,
    no U+FFFD, no non-finite number's name, anywhere in it."""
    if isinstance(value, str):
        return value not in (REDACTED, TRUNCATED) and value not in NON_FINITE and UNSTORABLE not in value
    if isinstance(value, dict):
        return MARKER not in value and all(UNSTORABLE not in k and faithful(v) for k, v in value.items())
    if isinstance(value, list):
        return all(faithful(v) for v in value)
    return True


def output_of(pointer: str) -> tuple[str, list[str]] | None:
    """The step a `/steps/<key>/output…` pointer reads, and the path inside its output; None for any other pointer."""
    segments = [s.replace("~1", "/").replace("~0", "~") for s in pointer.split("/")[1:]]
    if len(segments) >= 3 and segments[0] == "steps" and segments[2] == "output":
        return segments[1], segments[3:]
    return None


def _at(value: Any, path: Sequence[str]) -> Any:
    """What `path` addresses in `value`, `_ABSENT` when nothing; a marker on the way is returned as it is."""
    for segment in path:
        if isinstance(value, dict) and MARKER not in value:
            if segment not in value:
                return _ABSENT
            value = value[segment]
        elif isinstance(value, list):
            if not (segment.isdigit() and int(segment) < len(value)):
                return _ABSENT
            value = value[int(segment)]
        elif faithful(value):  # a value with nothing inside it
            return _ABSENT
        else:
            return value  # a marker or a handle where a container was: never followed
    return value


def prefill(entry: seeds.SeedEntry, sample: samples.Sample | None) -> Prefill:
    """D-s2, for one entry: from its own step's sample, only when the value there is faithful and fits the entry."""
    if entry.sensitive:
        return Prefill(reason="sensitive")
    if output_of(entry.pointer) is None:
        return Prefill(reason="not_step_output")
    if sample is None:
        return Prefill(reason="no_sample")
    _, path = output_of(entry.pointer) or ("", [])
    value = _at(sample.output, path)
    if value is _ABSENT:
        return Prefill(reason="not_in_sample")
    if not faithful(value):
        return Prefill(reason="not_faithful")
    if seeds.check(seeds.SeedContract(entries=(entry,)), {entry.pointer: value}, ()):
        return Prefill(reason="doesnt_fit")
    return Prefill(value)


async def prefills(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID, steps: Mapping[str, uuid.UUID],
    contract: seeds.SeedContract, at: Cutoff,
) -> dict[str, Prefill]:  # fmt: skip
    """Each entry's prefill, by pointer: `steps` names the draft's steps by key; each step's newest B7 sample (its
    first iteration's, in a loop) is read once."""
    found: dict[str, samples.Sample | None] = {}
    filled: dict[str, Prefill] = {}
    for entry in contract.entries:
        read = output_of(entry.pointer)
        key = read[0] if read is not None and not entry.sensitive else None
        if key is not None and key not in found:
            step_id = steps.get(key)
            search = None if step_id is None else await samples.newest(
                s, tenant_id, workflow_id, step_id, iteration_key=None, at=at
            )  # fmt: skip
            found[key] = None if search is None else search.sample
        filled[entry.pointer] = prefill(entry, found.get(key) if key is not None else None)
    return filled
