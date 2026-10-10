# SPDX-License-Identifier: Apache-2.0
"""Whether a draft would break the workflow's live schedules (4c-3a ruling 7). Each schedule holds a sealed input,
checked against the active version when it's written and again at each firing; publishing an input the stored one
doesn't fit makes the schedule fail at every firing, and nobody can see the stored input to know. So validate and
publish check it, and say which schedules and why, never what their input holds: a warning, never a refusal.

The check is of the stored input's shape alone. JSON Schema's own validator checks it against the draft's input as
written, extended so that it evaluates only structure (`type`, `properties`, `required`, `additionalProperties`,
`items`, `prefixItems`, references, `allOf`, `anyOf`, `dependentRequired`, `dependentSchemas`), with its own types
(`2.0` is an integer); every other keyword holds for every value. `oneOf` is evaluated as `anyOf`; the structure a
shape can't keep (`not`, `if`, `propertyNames`, …) holds, and is named, for validate to say the check was partial. So
the check accepts every value the draft does: a value it refuses, the draft refuses too. The document is kept as
written, so references resolve as they do for the draft, but for `$schema`: the check's own dialect is removed where
a schema names it, since jsonschema validates a schema it descends into with the validator its `$schema` names; another
dialect isn't checked, and is named. Never a value's content: a draft's `maximum`, `maxLength` or `const` checked
against a stored value would let whoever can validate a draft learn a sensitive value a bit at a time. A reason names
the draft's own places and fields, never the stored input's. A draft that takes a CSV file fits no schedule: its rows
come from an upload only (engine 2b spec §8.1).

Its work is bounded in units, never time:
- a check fetches the oldest schedules whose sealed inputs fit 2 MiB together, 100 at most, picked by their stored
  length in the same statement that counts them, so no other input is fetched;
- every keyword it evaluates, at any depth, spends one of the check's 50,000 steps, and its `anyOf` tries a branch only
  up to its first error, keeping none (JSON Schema's own builds every error of every failing branch first);
- from one stored input it reads 100 errors, lazily, and keeps 5 distinct reasons, each of 300 characters at most.
What a bound leaves out is said: a schedule as unchecked, a reason list as having more. Decoding and checking run in a
worker thread."""

import asyncio
import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dewpoint.apps.schedules import INPUT_PURPOSE
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource, key_unreadable
from dewpoint.core.models.schedules import Schedule
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.runtime.projection import location
from dewpoint.engine.schema_refs import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE

log = structlog.get_logger("dewpoint.schedule_checks")
MAX_CHECKED = 100  # live schedules one check reads, the oldest first; the rest are counted unchecked
MAX_INPUT_BYTES = 2 * 1024 * 1024  # their sealed input one check reads, the oldest first; past it, counted unchecked
MAX_STEPS = 50_000  # keywords one check evaluates, at any depth, for all its inputs together
MAX_ERRORS = 100  # errors read from one stored input, lazily
MAX_REASONS = 5  # distinct reasons kept for one, in the order found
MAX_REASON_CHARS = 300  # a reason's length at most: a name the draft gives may be long
CSV = "This input takes a CSV file now: a schedule can't give its rows."
REFUSED = (
    "Publishing this would make {n} live schedule{s} fail at every firing: their stored input doesn't fit this input. "
    "Once it's published, replace it, or keep the input as it was."
)
PARTLY = (
    "The live schedules were checked against this input in part: its {keywords} can't be checked by shape, so a "
    "schedule it would refuse may not be listed."
)
UNCHECKED = (
    "Not checked against this input: {n} live schedule{s}, either past what one check reads (the oldest 100, 2 MiB of "
    "stored input, 50,000 checking steps) or with a stored input that couldn't be read."
)
_TYPES = {"string": "text", "integer": "a whole number", "number": "a number", "boolean": "yes or no",
          "array": "a list", "object": "an object", "null": "null"}  # fmt: skip
# The keywords the check evaluates (4c-3a ruling 7): structure. Every other keyword is evaluated as nothing: one that
# tests a value's content (`const`, `maximum`, `maxLength`, `format`, …) or annotates, and the structure a shape can't
# keep without refusing what the draft accepts (`PARTIAL`, named). `oneOf` is evaluated as `anyOf`, which only widens.
_STRUCTURE = frozenset({"type", "properties", "required", "additionalProperties", "items", "prefixItems", "$ref",
                        "allOf", "anyOf", "dependentRequired", "dependentSchemas"})  # fmt: skip
PARTIAL = frozenset({"oneOf", "not", "if", "then", "else", "propertyNames", "patternProperties",
                     "unevaluatedProperties", "unevaluatedItems", "contains"})  # fmt: skip
# The check's own dialect: `$schema` naming it is removed wherever a schema stands, since jsonschema picks the
# validator of a schema it descends into by that schema's `$schema`, and the registered one has no budget.
DIALECT = frozenset({"https://json-schema.org/draft/2020-12/schema", "https://json-schema.org/draft/2020-12/schema#"})


def _read(schema: Any) -> tuple[Any, frozenset[str]]:
    """`schema` as the check reads it, and what it can't keep. The document stays as written, so every reference
    resolves as it does for the draft, but for one keyword: `$schema` naming the check's own dialect is removed
    wherever a schema stands (`schema_refs`' schema positions), so descending never leaves the check's validator.
    Another dialect is read by its own rules: a draft naming one isn't checked (`$schema`, named)."""
    found: set[str] = set()

    def walk(node: Any) -> Any:
        if not isinstance(node, Mapping):
            return node  # a boolean schema
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$schema" and isinstance(value, str):
                if value not in DIALECT:
                    found.add(key)
                continue
            if key in PARTIAL:
                found.add(key)
            if key in SCHEMA_ONE:
                out[key] = walk(value)
            elif key in SCHEMA_LIST and isinstance(value, list):
                out[key] = [walk(sub) for sub in value]
            elif key in SCHEMA_MAP and isinstance(value, Mapping):
                out[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                out[key] = value
        return out

    return walk(schema), frozenset(found)


def _reasons(e: ValidationError, schema: Mapping[str, Any]) -> Iterator[str]:
    """Why a value doesn't have the shape, in the draft's own words: a place as far as the draft declares it (a key
    the data supplied shows as `*`), a name the draft gives; never a value, never a stored name."""
    where = location(list(e.absolute_path), schema)
    named = "" if where == "(root)" else f"{where}."
    present = e.instance if isinstance(e.instance, dict) else {}
    rule: Any = e.validator_value  # the draft's own: a list of names, a map of them, a type
    match e.validator:
        case "required":
            yield from (f"`{named}{n}` is required now." for n in (rule if isinstance(rule, list) else [])
                        if isinstance(n, str) and n not in present)  # fmt: skip
        case "dependentRequired":
            pairs = rule.items() if isinstance(rule, Mapping) else []
            yield from (f"`{named}{d}` is required now, beside `{named}{k}`." for k, deps in pairs if k in present
                        for d in deps if isinstance(d, str) and d not in present)  # fmt: skip
        case "type":
            kinds = [rule] if isinstance(rule, str) else list(rule) if isinstance(rule, list) else []
            yield f"`{where}` must be {' or '.join(_TYPES.get(k, str(k)) for k in kinds)} now."
        case "additionalProperties":
            yield f"{'It' if not named else f'`{where}`'} has a field this input no longer allows."
        case "anyOf":
            yield f"{'It' if not named else f'`{where}`'} fits none of the shapes this input allows."
        case _:
            yield f"{'It' if not named else f'`{where}`'} doesn't have the shape this input declares."


class Exhausted(Exception):
    """The check's steps ran out: what's left isn't checked."""


class Budget:
    """The steps a check has left, for all its inputs: each keyword it evaluates spends one."""

    def __init__(self, steps: int) -> None:
        self.left = steps

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise Exhausted


def _any_of(validator: Any, branches: list[Any], instance: Any, schema: Any) -> Iterator[ValidationError]:
    """`anyOf`, tried a branch at a time up to its first error, none kept: the check never names them. A branch that
    has none ends it."""
    for index, branch in enumerate(branches):
        if next(validator.descend(instance, branch, schema_path=index), None) is None:
            return
    yield ValidationError("no branch fits")


def _ignored(validator: Any, value: Any, instance: Any, schema: Any) -> None:
    """A keyword the check doesn't evaluate: it holds for every value."""


def _counting(schema: Mapping[str, Any], budget: Budget) -> Any:
    """JSON Schema's own validator for `schema`, extended: each keyword spends a step of `budget` before it's
    evaluated; only structure is evaluated, every other keyword holding; `anyOf` (and `oneOf`) tried lazily."""

    def counted(keyword: Any) -> Any:
        def evaluated(validator: Any, value: Any, instance: Any, at: Any) -> Any:
            budget.spend()
            return keyword(validator, value, instance, at)

        return evaluated

    keywords = {
        name: counted(fn if name in _STRUCTURE else _ignored) for name, fn in Draft202012Validator.VALIDATORS.items()
    }
    keywords |= {"anyOf": counted(_any_of), "oneOf": counted(_any_of)}
    extended = validators.extend(Draft202012Validator, keywords)  # type: ignore[no-untyped-call]  # unannotated in 4.26
    return extended(schema)


def _short(reason: str) -> str:
    return reason if len(reason) <= MAX_REASON_CHARS else reason[: MAX_REASON_CHARS - 1] + "…"


@dataclass(frozen=True)
class Checked:
    """Why one stored input wouldn't fit, in order; `more` when the check stopped at a budget with more to say."""

    reasons: list[str]
    more: bool = False


@dataclass(frozen=True)
class Shape:
    """A draft's input as the check reads it, to check stored inputs' shape against (4c-3a ruling 7)."""

    takes_csv: bool
    schema: Mapping[str, Any]
    partial: frozenset[str]  # the structure it couldn't keep: what the check didn't read
    validator: Any  # built once, for every stored input it checks, spending from `budget`; None: not checked
    budget: Budget

    def check(self, value: Any) -> Checked:
        """Why `value` wouldn't fit, each told once, in order; no reason when its shape fits. Its errors are read
        lazily, `MAX_ERRORS` at most, and `MAX_REASONS` distinct reasons kept: past either, `more`. Raises Exhausted
        when the check's steps run out."""
        if self.takes_csv:
            return Checked([CSV])
        if self.validator is None:  # another dialect's: not checked, and named in `partial`
            return Checked([])
        kept: list[str] = []
        for read, e in enumerate(self.validator.iter_errors(value)):
            if read == MAX_ERRORS:
                return Checked(sorted(kept), more=True)
            for reason in map(_short, _reasons(e, self.schema)):
                if reason in kept:
                    continue
                if len(kept) == MAX_REASONS:
                    return Checked(sorted(kept), more=True)
                kept.append(reason)
        return Checked(sorted(kept))


def shape(input_schema: Mapping[str, Any], *, takes_csv: bool) -> Shape:
    """`input_schema` as the check reads it: its shape, with JSON Schema's own type checker (`2.0` is an integer)."""
    read, partial = _read(input_schema)
    schema = read if isinstance(read, Mapping) else {}
    budget = Budget(MAX_STEPS)
    return Shape(takes_csv, schema, partial, None if "$schema" in partial else _counting(schema, budget), budget)


def checked_all(
    input_schema: Mapping[str, Any], takes_csv: bool, opened: list[tuple[uuid.UUID, bytes]]
) -> tuple[frozenset[str], list[tuple[uuid.UUID, Checked]], int]:
    """The stored inputs `opened` checked against `input_schema`'s shape, the oldest first: CPU work, run in a worker
    thread. The structure the shape couldn't keep, each input that wouldn't fit, and how many weren't checked: the one
    the steps ran out in, and the rest."""
    drafted = shape(input_schema, takes_csv=takes_csv)
    refused: list[tuple[uuid.UUID, Checked]] = []
    for n, (schedule_id, plaintext) in enumerate(opened):
        try:
            checked = drafted.check(json.loads(plaintext))
        except Exhausted:
            return drafted.partial, refused, len(opened) - n
        if checked.reasons:
            refused.append((schedule_id, checked))
    return drafted.partial, refused, 0


@dataclass(frozen=True)
class Read:
    rows: list[tuple[uuid.UUID, bytes | None]]  # the oldest live schedules, 100 at most; an input past the bytes, None
    live: int  # every live schedule of the workflow


async def read_schedules(s: AsyncSession, workflow_id: uuid.UUID) -> Read:
    """The oldest `MAX_CHECKED` live schedules (a deleted one's tombstone left out), each with its sealed input when
    the oldest ones' inputs fit `MAX_INPUT_BYTES` together, and how many are live, in one statement and one snapshot.
    The inputs are picked by their stored length (`octet_length`, which reads no payload), so no other is fetched."""
    order = (Schedule.created_at, Schedule.id)
    sized = (
        select(Schedule.id.label("id"), func.count().over().label("live"),
               func.row_number().over(order_by=order).label("n"),
               func.sum(func.octet_length(Schedule.input)).over(order_by=order).label("running"))
        .where(Schedule.workflow_id == workflow_id, Schedule.deleted_at.is_(None))
        .subquery()
    )  # fmt: skip
    kept = aliased(Schedule)
    found = (await s.execute(
        select(sized.c.id, kept.input, sized.c.live)
        .select_from(sized)
        .outerjoin(kept, and_(kept.id == sized.c.id, sized.c.running <= MAX_INPUT_BYTES))
        .where(sized.c.n <= MAX_CHECKED)
        .order_by(sized.c.n)
    )).all()  # fmt: skip
    return Read([(r.id, r.input) for r in found], found[0].live if found else 0)


@dataclass(frozen=True)
class Breaks:
    refused: list[tuple[uuid.UUID, Checked]]  # each live schedule whose stored input wouldn't fit, with why
    unchecked: int  # live schedules past `MAX_CHECKED`, or whose stored input couldn't be read
    partial: frozenset[str] = frozenset()  # the draft's structure the check didn't read, when it read a schedule


async def breaks(
    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *,
    input_schema: Mapping[str, Any], takes_csv: bool,
) -> Breaks:  # fmt: skip
    """The workflow's live schedules (a deleted one's tombstone left out) whose stored input `input_schema` wouldn't
    fit, by its shape (`read_schedules` says which are read). One past what a check reads, or whose key can't be
    read, is counted unchecked; anything else raises. The checking runs in a worker thread."""
    read = await read_schedules(s, workflow_id)
    unchecked = read.live - sum(1 for _, sealed in read.rows if sealed is not None)
    cipher = ClaimCipher(keys, purpose=INPUT_PURPOSE)
    opened: list[tuple[uuid.UUID, bytes]] = []
    for schedule_id, sealed in read.rows:
        if sealed is None:  # past the bytes a check reads: counted above, never fetched
            continue
        try:
            opened.append((schedule_id, await cipher.open(str(tenant_id), str(schedule_id), sealed)))
        except Exception as e:
            if not key_unreadable(e):
                raise
            log.warning("schedule_input_unread", error=type(e).__name__)
            unchecked += 1
    partial, refused, exhausted = await asyncio.to_thread(checked_all, input_schema, takes_csv, opened)
    return Breaks(refused, unchecked + exhausted, partial if opened and not takes_csv else frozenset())


def warnings(found: Breaks, *, takes_csv: bool) -> list[Diagnostic]:
    """What validate and publish warn of: the schedules that would break, at the input (or the CSV declaration), and
    the ones not checked."""
    out: list[Diagnostic] = []
    if found.refused:
        n = len(found.refused)
        out.append(Diagnostic(code="schedule.input_refused", message=REFUSED.format(n=n, s="s" if n > 1 else ""),
                              field="/settings/csv" if takes_csv else "/settings/input_schema",
                              severity="warning"))  # fmt: skip
    if found.unchecked:
        n = found.unchecked
        out.append(Diagnostic(code="schedule.unchecked", message=UNCHECKED.format(n=n, s="s" if n > 1 else ""),
                              severity="warning"))  # fmt: skip
    if found.partial:
        named = ", ".join(f"`{k}`" for k in sorted(found.partial))
        out.append(Diagnostic(code="schedule.partly_checked", message=PARTLY.format(keywords=named),
                              field="/settings/input_schema", severity="warning"))  # fmt: skip
    return out


def checkable(diagnostics: Sequence[Diagnostic]) -> bool:
    """Whether a draft's input can be checked against: not when its input schema or CSV declaration has an error."""
    return not any(d.severity == "error" and (d.field or "").startswith(("/settings/input_schema", "/settings/csv"))
                   for d in diagnostics)  # fmt: skip
