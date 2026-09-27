# SPDX-License-Identifier: Apache-2.0
"""Values at run time (spec §4.3, §5.6): what a step sees, and how refs, templates and CEL become values."""

from typing import Any

import pytest

from dewpoint.engine.cel.bind import ScopeView
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.values import ENVELOPE, Value, iter_values
from dewpoint.engine.runtime import resolve
from dewpoint.engine.runtime.resolve import ValueFailure
from dewpoint.engine.runtime.scheduler import Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, cel, ref, template

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "names": {"type": "array", "items": {"type": "string"}}},
    "required": ["x", "names"],
}


def value(envelope: dict[str, Any]) -> Value:
    [(_, parsed)] = list(iter_values({"v": envelope}))
    assert not isinstance(parsed, Exception)
    return parsed


def scope_view(**roots: Any) -> ScopeView:
    base: dict[str, Any] = {"trigger": {}, "steps": {}, "vars": {}, "loops": {}, "run": {}, "item": None, "index": None}
    return ScopeView(**{**base, **roots})


def test_a_step_sees_its_region_and_the_regions_around_it() -> None:
    g = G().node("a", "testkit.echo@1", {"value": 1}).node("l", "flow.loop@1", {"items": ["p", "q"]})
    g.node("x", "testkit.echo@1").edge("a", "l").edge("l", "x", "body")
    s = Scheduler(program(g))
    s.start()
    [a] = s.take_ready()
    s.succeed(a, {"value": 1})
    [loop] = s.take_ready()
    s.open_loop(loop, ["p", "q"], concurrency=1, stop_on_error=True)
    [x] = s.take_ready()
    run = {"id": "r", "started_at": "2026-09-27T00:00:00+00:00"}

    inside = resolve.view(s, x.scope, trigger={"t": 1}, variables={"n": 0}, run=run)
    assert inside.steps == {"x": {}, "a": {"output": {"value": 1}}, "l": {}}  # `{}`: not settled yet
    assert (inside.loops, inside.item, inside.index) == ({"l": {"item": "p", "index": 0}}, "p", 0)
    outside = resolve.view(s, (), trigger={"t": 1}, variables={"n": 0}, run=run)
    assert outside.steps == {"a": {"output": {"value": 1}}, "l": {}} and outside.index is None
    as_filter = resolve.view(s, (), trigger={}, variables={}, run=run, item=("ap-1", 4))
    assert (as_filter.item, as_filter.index) == ("ap-1", 4)  # a filter's predicate sees its own item


def test_a_default_replaces_a_missing_or_null_value() -> None:
    v = scope_view(
        trigger={"a": None, "b": 0},
        steps={"s": {}, "c": {"output": None, "error": {"code": "boom", "message": "", "attempt": 1}}},
    )
    assert resolve.ref(v, value(ref("trigger.a", default=5))) == 5
    assert resolve.ref(v, value(ref("trigger.nope", default=5))) == 5
    assert resolve.ref(v, value(ref("trigger.b", default=5))) == 0  # a falsy value is still a value
    assert resolve.ref(v, value(ref("steps.s.output.v", default="later"))) == "later"  # not settled yet
    assert resolve.ref(v, value(ref("steps.c.error.code"))) == "boom"
    assert resolve.ref(v, value(ref("trigger.a"))) is None  # null without a default stays null
    with pytest.raises(ValueFailure) as missing:
        resolve.ref(v, value(ref("trigger.nope")))
    assert missing.value.failure.code == "evaluation_error"


def test_a_template_joins_text() -> None:
    v = scope_view(trigger={"s": "ap", "n": 3, "f": 1.5, "b": True, "z": None, "o": {"k": 1}})
    parts = (
        "x=",
        {"ref": "trigger.s"},
        "/",
        {"ref": "trigger.n"},
        "/",
        {"ref": "trigger.f"},
        "/",
        {"ref": "trigger.b"},
    )
    assert resolve.template(v, value(template(*parts))) == "x=ap/3/1.5/true"
    assert resolve.template(v, value(template("[", {"ref": "trigger.z"}, "]"))) == "[]"  # null, no default: nothing
    assert resolve.template(v, value(template({"ref": "trigger.nope", "default": "-"}))) == "-"
    with pytest.raises(ValueFailure) as missing:
        resolve.template(v, value(template({"ref": "trigger.nope"})))
    with pytest.raises(ValueFailure) as shaped:
        resolve.template(v, value(template({"ref": "trigger.o"})))
    assert (missing.value.failure.code, shaped.value.failure.code) == ("evaluation_error", "type_mismatch")


def test_assemble_puts_each_value_at_its_pointer() -> None:
    envelope = {ENVELOPE: {"kind": "ref", "path": "trigger.x"}}
    config = {"a": 1, "b": [envelope, {"c": envelope}], "d": envelope}
    assert resolve.assemble(config, {"/b/0": 5, "/b/1/c": "x"}) == {"a": 1, "b": [5, {"c": "x"}], "d": None}


def test_cel_runs_inline_only_when_this_build_runs_the_profile() -> None:
    g = G()
    g.settings = {"input_schema": SCHEMA}
    fields = {"y": cel("trigger.x * 2"), "z": cel("10 / trigger.x"), "n": cel("size(trigger.names)")}
    p = program(g.node("t", "flow.transform@1", {"fields": fields}))
    step = p.by_key["t"]
    double, divide, count = (p.record(step, f"/fields/{f}") for f in ("y", "z", "n"))
    views = [scope_view(trigger={"x": 3}), scope_view(trigger={"x": 0})]

    remote = resolve.cel_task(double, views, local_profile=None, version_profile=CURRENT_CEL_PROFILE)
    assert not remote.local
    assert remote.request(CURRENT_CEL_PROFILE)["bindings"] == [{"trigger": {"x": 3}}, {"trigger": {"x": 0}}]

    local = resolve.cel_task(divide, views, local_profile=CURRENT_CEL_PROFILE, version_profile=CURRENT_CEL_PROFILE)
    ok, failed = local.run_local()
    assert local.local and resolve.outcome_value(ok) == 3
    with pytest.raises(ValueFailure) as e:
        resolve.outcome_value(failed)
    assert e.value.failure.code == "evaluation_error"

    with pytest.raises(ValueFailure) as bad:  # a typed list path (spec §5.3) is checked as it's bound
        resolve.cel_task(
            count, [scope_view(trigger={"x": 1, "names": "ap-1"})], local_profile=None, version_profile="p"
        )
    assert bad.value.failure.code == "type_mismatch"
