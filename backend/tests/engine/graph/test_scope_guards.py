# SPDX-License-Identifier: Apache-2.0
"""The guards a scope gives (4c-2a rulings 6, 7): a formula made of them and the read publishes with no guard
problem, is never an error at run time, and reads sensitive data exactly when validation says it does."""

import functools
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.bind import ScopeView
from dewpoint.engine.cel.evaluate import evaluate_local
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.cel.runtime import compile_checked, evaluate
from dewpoint.engine.graph.scope import Entry, scope
from dewpoint.engine.graph.validate import ValidationResult, validate
from dewpoint.engine.runtime import resolve
from tests.engine.graph.test_scope import CTX, graph
from tests.support.graphs import G, cel, nid

GUARD_CODES = {"cel.conditional_ref", "cel.has_on_typed_path", "cel.invalid", "cel.unknown_name", "cel.bad_path",
               "cel.unproven_list", "ref.unknown_field", "ref.unknown_step", "ref.not_upstream"}  # fmt: skip
PER_PARENT = 25  # Mist's device kinds declare many fields: a sample of each list keeps the run short


@functools.cache
def collected() -> tuple[Entry, ...]:
    """Every entry `c`'s condition can read that a reference can name, up to six segments deep."""
    out: list[Entry] = []
    seen: set[str] = set()
    todo = [e for e in scope(graph().build(), CTX, nid("c"), "/condition").entries]
    while todo:
        e = todo.pop()
        if e.path in seen or not e.nameable:
            continue
        seen.add(e.path)
        out.append(e)
        if e.children and e.path.count(".") + e.path.count("[") < 6:
            todo += list(scope(graph().build(), CTX, nid("c"), "/condition", under=e.path).entries)[:PER_PARENT]
    return tuple(sorted(out, key=lambda e: e.path))


@functools.cache
def entries() -> tuple[Entry, ...]:
    """Those a formula can name: what the guards are for."""
    return tuple(e for e in collected() if e.formula is not None)


def guarded(e: Entry, read: str) -> str:
    assert e.formula is not None
    return " && ".join([*(g.cel() for g in e.formula.guards), read])


def checked(expr: str) -> ValidationResult:
    g: G = graph()
    for node in g.nodes:
        if node["key"] == "c":
            node["config"] = {"condition": cel(expr)}
    return validate(g.build(), CTX)


@functools.cache
def verdicts() -> dict[str, tuple[list[str], bool]]:
    """Per entry: the guard problems validation finds at `c`, and whether it finds `c`'s condition tainted."""
    out: dict[str, tuple[list[str], bool]] = {}
    for e in entries():
        result = checked(guarded(e, f"{e.path} == {e.path}"))
        mine = [d.code for d in result.diagnostics if d.node == nid("c") and d.code in GUARD_CODES]
        tainted = (str(nid("c")), "/condition") in result.tainted_sites
        out[e.path] = (mine, tainted)
    return out


def test_covers_the_cases_that_need_guards() -> None:
    kinds = {g.kind for e in entries() for g in e.formula.guards}  # type: ignore[union-attr]
    assert kinds == {"present", "not_null", "is_map", "is_list", "min_size"}


def test_every_guarded_read_publishes_without_a_guard_problem() -> None:
    problems = {path: codes for path, (codes, _) in verdicts().items() if codes}
    assert problems == {}


def there(e: Entry) -> str:
    """ "is there" (4c-2a ruling 6): the guards, and not null where it may be null or is untyped."""
    assert e.formula is not None
    tests = [g.cel() for g in e.formula.guards]
    if e.formula.null_test:
        tests.append(f"{e.path} != null")
    return " && ".join(tests) or "true"


def test_is_there_publishes_without_a_guard_problem() -> None:
    for e in entries():
        result = checked(there(e))
        assert [d.code for d in result.diagnostics if d.node == nid("c") and d.code in GUARD_CODES] == [], e.path


def test_says_a_formula_reads_sensitive_data_exactly_when_validation_does() -> None:
    wrong = {e.path for e in entries() if e.formula.sensitive != verdicts()[e.path][1]}  # type: ignore[union-attr]
    assert wrong == set()


# At run time. The data holds what its schemas declare: admission checks a run's input against its input schema, and
# a plugin's output is checked against its output schema. So each position the scope types gets a value of one of its
# types (or nothing where it may be missing, or null where it may be null), and a position it doesn't type gets any
# JSON at all: the wrong type, an empty list, a string where a list might have been.
_KEYS = sorted({seg for e in collected() for seg in e.path.replace("[", ".").replace("]", "").split(".")} | {"z"})
_SCALARS = st.none() | st.booleans() | st.integers(-3, 3) | st.floats(allow_nan=False, allow_infinity=False)
_ANY = st.recursive(
    _SCALARS | st.text(max_size=2),
    lambda c: st.lists(c, max_size=3) | st.dictionaries(st.sampled_from(_KEYS), c, max_size=4),
    max_leaves=12,
)
_DECLS = {"trigger": T.MAP, "steps": T.MAP, "vars": T.MAP, "loops": T.MAP, "run": T.MAP}


@functools.cache
def children() -> dict[str, tuple[Entry, ...]]:
    out: dict[str, list[Entry]] = {}
    for e in collected():
        if e.parent is not None:
            out.setdefault(e.parent, []).append(e)
    return {k: tuple(v) for k, v in out.items()}


def _optional(e: Entry) -> bool:
    """Whether a field may be absent from its parent itself (`missing` also counts a step that may not have run): its
    read is guarded by has(). One a formula can't name falls back to `missing`."""
    if e.formula is None:
        return e.missing
    return any(g.kind == "present" and g.path == e.path for g in e.formula.guards)


def _data(draw: Any, e: Entry) -> Any:
    if e.nullable and draw(st.booleans()):
        return None
    kind = draw(st.sampled_from(e.types or ("any",)))
    below = children().get(e.path, ())
    if kind == "object":  # a field is left out only where it may be absent itself: where its read is guarded by has()
        return {c.name: _data(draw, c) for c in below if not (_optional(c) and draw(st.booleans()))}
    if kind == "array":
        element = next((c for c in below if c.name == "[0]"), None)
        if element is None:
            return draw(st.lists(_ANY, max_size=2))
        return [_data(draw, element) for _ in range(draw(st.integers(0, 2)))]
    if kind == "string":
        return draw(st.text(max_size=2))
    if kind == "integer":
        return draw(st.integers(-3, 3))
    if kind == "number":
        return draw(st.integers(-3, 3) | st.floats(allow_nan=False, allow_infinity=False))
    if kind == "boolean":
        return draw(st.booleans())
    if kind == "null":
        return None
    return draw(_ANY)


@functools.cache
def records() -> tuple[tuple[str, ExpressionRecord], ...]:
    """Each guarded read as validation records it, with what it declares and the names it binds: what a run
    evaluates."""
    out: list[tuple[str, ExpressionRecord]] = []
    for e in entries():
        result = checked(guarded(e, f"{e.path} == {e.path}"))
        out.append((e.path, next(x for x in result.expressions if x.node == str(nid("c")) and x.field == "/condition")))
    return tuple(out)


@settings(max_examples=120, deadline=None)
@given(st.data())
def test_a_guarded_read_is_never_an_error_at_run_time(data: st.DataObject) -> None:
    tops = {e.path: e for e in collected() if e.parent is None}
    trigger = _data(data.draw, tops["trigger"])
    # As the runtime binds them (engine/cel/bind.py): `{}` for a step that hasn't run, `{"output": …}` once it has.
    steps: dict[str, Any] = {}
    for path, e in tops.items():
        if path.startswith("steps.") and path.endswith(".output"):
            ran = not e.missing or data.draw(st.booleans())
            steps[path.split(".")[1]] = {"output": _data(data.draw, e)} if ran else {}
    run = {"id": "r", "started_at": "2026-01-01T00:00:00Z", "now": "2026-01-01T00:00:00Z"}
    view = ScopeView(trigger=trigger, steps=steps, vars={"count": 0}, loops={}, run=run)
    for path, record in records():
        # As a run evaluates it (engine/runtime/execution.py's _cel_task): bound first, each name it reads a root, then
        # evaluated. A name it can't bind, a type's, failed every run though the raw evaluation passed (the fix found
        # while planning 4c-2b).
        resolve.bind_view(record, view)
        result = evaluate_local(record, view)
        assert result.ok, (path, result.message)


def test_is_there_is_false_for_a_value_only_null() -> None:
    nothing = next(e for e in entries() if e.path == "trigger.nothing")
    program = compile_checked(there(nothing), _DECLS)
    result = evaluate(program, {"trigger": {"nothing": None}, "steps": {}, "vars": {}, "loops": {}, "run": {}})
    assert (result.kind, result.value) == ("value", False)
