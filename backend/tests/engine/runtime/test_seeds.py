# SPDX-License-Identifier: Apache-2.0
"""A single-step run's seeds (S2; the simulation design §5.3): the scope view built from them, and what they cover."""

from dewpoint.engine.runtime.seeds import Seeds, segments


def test_pointers_are_unescaped_segments() -> None:
    assert segments("") == ()
    assert segments("/steps/a~1b/output/x~0y") == ("steps", "a/b", "output", "x~y")


def test_values_build_the_tree_an_outer_value_first() -> None:
    s = Seeds.of({"values": {"/trigger/owner/name": "n", "/trigger/owner": {"tag": 1}}, "absent": []}, None)
    assert s.trigger == {"owner": {"tag": 1, "name": "n"}}


def test_an_absent_value_leaves_its_containers_in_place() -> None:
    s = Seeds.of({"values": {}, "absent": ["/trigger/owner/tag", "/steps/a/output/x"]}, None)
    view = s.view({"id": "r"})
    assert s.trigger == {"owner": {}} and view.steps == {"a": {"output": {}}}


def test_the_innermost_frame_is_item_and_index_and_its_loops_alias() -> None:
    s = Seeds.of({"values": {"/item": {"mac": "m"}, "/index": 2}, "absent": []}, "l")
    view = s.view({"id": "r"})
    assert (view.item, view.index, view.loops["l"]) == ({"mac": "m"}, 2, {"item": {"mac": "m"}, "index": 2})
    assert s.covers(("loops", "l", "item", "mac")) and not s.covers(("loops", "outer", "item"))


def test_a_read_is_covered_by_a_given_or_an_absent_value_above_it() -> None:
    s = Seeds.of({"values": {"/trigger/site": "HQ"}, "absent": ["/vars/n"]}, None)
    assert s.covers(("trigger", "site")) and s.covers(("vars", "n", "deep"))
    assert not s.covers(("trigger",)) and not s.covers(("steps", "a", "output"))


def test_the_frame_is_there_without_its_index() -> None:
    """A step that reads only its item gets the item's frame: `item` is in scope with no `index` given."""
    view = Seeds.of({"values": {"/item/n": 1}, "absent": []}, "l").view({"id": "r"})
    assert (view.framed, view.item, view.index) == (True, {"n": 1}, None)


def test_an_absent_item_leaves_its_loops_frame_empty() -> None:
    view = Seeds.of({"values": {}, "absent": ["/item"]}, "l").view({"id": "r"})
    assert (view.loops, view.framed, view.item) == ({"l": {}}, True, None)
