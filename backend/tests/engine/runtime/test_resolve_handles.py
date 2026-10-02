# SPDX-License-Identifier: Apache-2.0
"""Values that are handles, in the workflow (engine 2b spec §3.2, §4.2): a read stops at a handle and extends its
pointer, never reading the claim; a binding or a template part that is a handle is never evaluated here."""

import uuid
from typing import Any

import pytest

from dewpoint.engine import handles
from dewpoint.engine.cel import bind as bind_module
from dewpoint.engine.cel.bind import ScopeView, bind
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.values import RefPath, TemplateValue, iter_values, parse_ref
from dewpoint.engine.handles import POINTER_MAX, ClaimRef
from dewpoint.engine.runtime import resolve
from dewpoint.engine.runtime.resolve import MISSING
from tests.engine.cel.support import make_record
from tests.support.graphs import template

C = str(uuid.UUID(int=7))
H = ClaimRef(C).to_json()


def scope_view(**roots: Any) -> ScopeView:
    base: dict[str, Any] = {"trigger": {}, "steps": {}, "vars": {}, "loops": {}, "run": {}, "item": None, "index": None}
    return ScopeView(**{**base, **roots})


def path(text: str) -> RefPath:
    return parse_ref(text)


def test_a_read_stops_at_a_handle_and_extends_its_pointer() -> None:
    v = scope_view(trigger={"login": H, "plain": {"a": 1}}, steps={"s": {"output": ClaimRef(C, "/rows/3").to_json()}})
    assert resolve.read(v, path("trigger.login")) == H
    assert resolve.read(v, path("trigger.login.pw")) == ClaimRef(C, "/pw").to_json()
    assert resolve.read(v, path("steps.s.output.name")) == ClaimRef(C, "/rows/3/name").to_json()
    assert resolve.read(v, path("trigger.plain.a")) == 1
    assert resolve.read(v, path("trigger.plain.b")) is MISSING


def test_a_whole_trigger_that_is_a_handle_is_read_through_it() -> None:
    v = scope_view(trigger=H)
    assert resolve.read(v, path("trigger.token")) == ClaimRef(C, "/token").to_json()


def test_a_template_part_that_is_a_handle_goes_to_the_activity() -> None:
    v = scope_view(trigger={"token": H, "name": "ann"})
    [(_, plain)] = list(iter_values({"v": template("Hi ", {"ref": "trigger.name"})}))
    [(_, secret)] = list(iter_values({"v": template("Bearer ", {"ref": "trigger.token"})}))
    assert isinstance(plain, TemplateValue) and isinstance(secret, TemplateValue)
    assert resolve.template(v, plain) == "Hi ann"
    parts = resolve.template_parts(v, secret)
    assert resolve.holds_handle(parts)
    assert resolve.join(parts) is None  # not joined here: the activity resolves it


def test_a_binding_that_is_a_handle_is_kept_whole_and_never_evaluated_here() -> None:
    record = make_record("trigger.login.pw + trigger.name")
    v = scope_view(trigger={"login": H, "name": "x"})
    bound = bind(record, v)
    assert bound["trigger"] == {"login": H, "name": "x"}
    task = resolve.cel_task(
        record,
        [resolve.Bound(bound, resolve.bind_view(record, v).measured)],
        local_profile=CURRENT_CEL_PROFILE,
        version_profile=CURRENT_CEL_PROFILE,
    )
    assert not task.local


@pytest.mark.parametrize("declared", [{}, {"trigger.rows": "list<dyn>"}])
def test_binding_plain_values_never_walks_them_for_the_marker(
    declared: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI's gate 7b, the workflow task's CPU: 2b-1b's handle checks walked every bound value twice more, inside the
    workflow task, which took its heaviest load past the 1 s target. Binding looks for the marker only in a value that
    doesn't conform to its declared type, and routing reads what `measure`'s own walk saw: a plain binding is never
    walked for it, and a handle still never runs here."""
    walks: list[Any] = []

    def counting(value: Any) -> bool:
        walks.append(value)
        return handles.contains_marker(value)

    monkeypatch.setattr(bind_module, "contains_marker", counting)
    monkeypatch.setattr(resolve, "contains_marker", counting)
    record = make_record("size(trigger.rows) > 0", declared)

    def local(view: ScopeView) -> bool:
        bound, profile = [resolve.bind_view(record, view)], CURRENT_CEL_PROFILE
        return resolve.cel_task(record, bound, local_profile=profile, version_profile=profile).local

    assert local(scope_view(trigger={"rows": [[1, 2], [3, 4]]})) and walks == []
    assert not local(scope_view(trigger={"rows": H}))


def test_a_typed_path_through_a_handle_extends_its_pointer() -> None:
    record = make_record("size(trigger.events) > 0", {"trigger.events": "list<map<string, dyn>>"})
    bound = bind(record, scope_view(trigger={"events": H}))
    assert bound["trigger.events"] == H
    bound = bind(record, scope_view(trigger=H))
    assert bound["trigger.events"] == ClaimRef(C, "/events").to_json()


def test_a_pointer_past_its_bound_is_too_long() -> None:
    long_key = "k" * POINTER_MAX
    v = scope_view(trigger={"login": H})
    found = resolve.read(v, path(f"trigger.login.{long_key}"))
    ref = ClaimRef.of(found)
    assert ref is not None and ref.too_long()
