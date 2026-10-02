# SPDX-License-Identifier: Apache-2.0
"""Values at run time (spec §4.3, §5.6). A step's config holds literals and envelopes; each envelope becomes a value
in the step's scope:
- a ref reads the scope; its default replaces a missing *or* null value;
- a template joins its text and the text of its refs;
- CEL runs inline when the version's profile runs in this build and the inputs are within the caps, and otherwise in
  the `cel.evaluate` activity.

A value that can't be computed fails the step (`evaluation_error`, or the CEL outcome's own code), and the step's
error policy applies.

A value may be a handle (engine 2b spec §3.2): a read stops at it and extends its pointer, never reading the claim. A
binding or a template part that is a handle is never evaluated here: it goes to `cel.evaluate`, whose activity
resolves it (§4.2)."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.cel import evaluate
from dewpoint.engine.cel.bind import BindingError, Measure, ScopeView, bind, measure
from dewpoint.engine.cel.ipc import EvaluateRequest
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.cel.route import route
from dewpoint.engine.graph.values import ENVELOPE, Pointer, RefPath, RefValue, TemplateValue, pointer_str
from dewpoint.engine.handles import MISSING, ClaimRef, contains_marker
from dewpoint.engine.runtime.scheduler import Failure, Scheduler, ScopeKey


class ValueFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.failure = Failure(code, message)


def view(
    scheduler: Scheduler,
    key: ScopeKey,
    *,
    trigger: Mapping[str, Any],
    variables: Mapping[str, Any],
    run: Mapping[str, str],
    item: tuple[Any, int] | None = None,
) -> ScopeView:
    """What a step in scope `key` sees: every step of its region and the regions around it (`{}` before a step
    settles), its enclosing loops, the innermost item (or `item`, a filter's), the run."""
    program = scheduler.program
    scope = scheduler.scopes[key]
    steps: dict[str, Mapping[str, Any]] = {}
    loops: dict[str, dict[str, Any]] = {}
    at = key
    for region in program.chain(scope.region):
        current = scheduler.scopes[at]
        for member in program.regions[region].members:
            name = program.steps[member].key
            steps[name] = current.results.get(name, {})
        if at:
            loops[at[-1][0]] = {"item": current.item, "index": current.index}
            at = at[:-1]
    if item is not None:
        value, index = item
    elif scope.index is not None:
        value, index = scope.item, scope.index
    else:
        value, index = None, None
    return ScopeView(trigger=trigger, steps=steps, vars=variables, loops=loops, run=run, item=value, index=index)


def _base(v: ScopeView, path: RefPath) -> Any:
    if path.root == "trigger":
        return v.trigger
    if path.root == "steps":
        entry = v.steps.get(str(path.name), MISSING)
        return entry.get(str(path.section), MISSING) if isinstance(entry, Mapping) else MISSING
    if path.root == "vars":
        return v.vars.get(str(path.name), MISSING)
    if path.root in ("item", "index"):
        return MISSING if v.index is None else (v.item if path.root == "item" else v.index)
    if path.root == "loops":
        loop = v.loops.get(str(path.name))
        return loop.get(str(path.section), MISSING) if loop is not None else MISSING
    if path.root == "run":
        return v.run.get(str(path.section), MISSING)
    return MISSING


def read(v: ScopeView, path: RefPath) -> Any:
    """The value at `path`, or MISSING. Past a handle, the handle to what `path` addresses inside its claim: possibly
    too long (`ClaimRef.too_long`), which the caller derives a claim for."""
    value = _base(v, path)
    for i, seg in enumerate(path.rest):
        handle = ClaimRef.of(value)
        if handle is not None:
            return handle.extend(*path.rest[i:]).to_json()
        if isinstance(seg, int):
            value = value[seg] if isinstance(value, list) and 0 <= seg < len(value) else MISSING
        else:
            value = value.get(seg, MISSING) if isinstance(value, Mapping) else MISSING
        if value is MISSING:
            break
    return value


def ref(v: ScopeView, value: RefValue) -> Any:
    return defaulted(read(v, value.path), value)


def defaulted(found: Any, value: RefValue) -> Any:
    """What a reference gives, for what it `found`: its default replaces a missing or null value."""
    if (found is MISSING or found is None) and value.has_default:
        return value.default
    if found is MISSING:
        raise ValueFailure(evaluate.EVALUATION_ERROR, f"`{value.path.text}` has no value here.")
    return found


def _text(found: Any, path: str) -> str:
    if isinstance(found, str):
        return found
    if isinstance(found, bool):
        return "true" if found else "false"
    if isinstance(found, int | float):
        return json.dumps(found)
    raise ValueFailure(evaluate.TYPE_MISMATCH, f"`{path}` isn't text, a number or a boolean.")


@dataclass(frozen=True)
class Part:
    """A template's reference, read: what it found (MISSING when nothing), its default, and its path for messages."""

    found: Any
    default: str | None
    path: str

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"path": self.path, "default": self.default}
        if self.found is not MISSING:
            out["value"] = self.found
        return out

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "Part":
        return Part(data.get("value", MISSING), data["default"], data["path"])


def template_parts(v: ScopeView, value: TemplateValue) -> list[str | Part]:
    return [p if isinstance(p, str) else Part(read(v, p.path), p.default, p.path.text) for p in value.parts]


def holds_handle(parts: Sequence[str | Part]) -> bool:
    return any(isinstance(p, Part) and p.found is not MISSING and contains_marker(p.found) for p in parts)


def join(parts: Sequence[str | Part]) -> str | None:
    """A template's text, or None when a part is a handle: the activity joins it, having resolved it."""
    if holds_handle(parts):
        return None
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif part.found is MISSING or part.found is None:
            if part.default is not None:
                out.append(part.default)
            elif part.found is MISSING:
                raise ValueFailure(evaluate.EVALUATION_ERROR, f"`{part.path}` has no value here.")
            # null, no default: nothing
        else:
            out.append(_text(part.found, part.path))
    return "".join(out)


def template(v: ScopeView, value: TemplateValue) -> str:
    """A template's text, here: for one that holds no handle."""
    joined = join(template_parts(v, value))
    if joined is None:
        raise RuntimeError("A template over a handle is joined in the activity, which resolves it.")
    return joined


@dataclass(frozen=True)
class CelTask:
    """One expression, evaluated once per view: inline, or in one `cel.evaluate` request (1 to 1,000 views)."""

    record: ExpressionRecord
    bindings: tuple[Mapping[str, Any], ...]
    local: bool

    def request(self, profile: str) -> dict[str, Any]:
        return EvaluateRequest(profile, self.record.expr, dict(self.record.declarations), self.bindings).to_json()

    def run_one(self, bindings: Mapping[str, Any]) -> evaluate.Outcome:
        """One binding set, in-process."""
        return evaluate.run(evaluate.compiled(self.record.expr, self.record.declarations), bindings)


def request_end(
    start: int, count: int, size_of: Callable[[int], int], *, envelope: int, batch: int, limit: int
) -> tuple[int, int]:
    """Where the `cel.evaluate` request that starts at binding set `start` ends (exclusive), and its JSON bytes: as
    many sets as fit in `limit`, at most `batch` (#15). A request's JSON is its envelope (no sets) plus each set's JSON
    and a comma between sets, so `size_of(i)` measures one set at a time. Requests that fit are cut every `batch` sets,
    as before. An end equal to `start` means set `start` alone passes the limit. A loop's batch is cut the same way,
    its items in place of the sets (engine 2b spec §5.2)."""
    end, size = start, envelope
    while end < min(start + batch, count):
        extra = size_of(end) + (1 if end > start else 0)
        if size + extra > limit:
            break
        size += extra
        end += 1
    return end, size


@dataclass(frozen=True)
class Bound:
    """One view's binding set, measured: routing reads the caps, the yield budget the values bound."""

    bindings: Mapping[str, Any]
    measured: Measure


def bind_view(record: ExpressionRecord, view: ScopeView) -> Bound:
    try:
        b = bind(record, view)
    except BindingError as e:
        raise ValueFailure(evaluate.TYPE_MISMATCH, str(e)) from None
    return Bound(b, measure(b))


def cel_task(
    record: ExpressionRecord, bound: Sequence[Bound], *, local_profile: str | None, version_profile: str
) -> CelTask:
    """Inline only when every binding set is within the caps, the profile runs here, and no binding is a handle
    (engine 2b spec §4.2)."""
    local = all(
        route(record, b.measured, local_profile=local_profile, version_profile=version_profile) == "local"
        and not contains_marker(b.bindings)
        for b in bound
    )
    return CelTask(record, tuple(b.bindings for b in bound), local)


def outcome_value(outcome: evaluate.Outcome) -> Any:
    if not outcome.ok:
        raise ValueFailure(str(outcome.error), outcome.message)
    return outcome.value


def assemble(config: Any, values: Mapping[str, Any], base: Pointer = ()) -> Any:
    """`config` with every envelope replaced by its value (by JSON pointer); envelopes without one become None."""
    if isinstance(config, Mapping):
        if ENVELOPE in config:
            return values.get(pointer_str(base))
        return {k: assemble(v, values, (*base, k)) for k, v in config.items()}
    if isinstance(config, list):
        return [assemble(v, values, (*base, i)) for i, v in enumerate(config)]
    return config


__all__ = [
    "MISSING",
    "CelTask",
    "Part",
    "ValueFailure",
    "assemble",
    "cel_task",
    "defaulted",
    "holds_handle",
    "join",
    "outcome_value",
    "read",
    "ref",
    "template",
    "template_parts",
    "view",
]
