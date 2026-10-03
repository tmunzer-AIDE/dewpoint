# SPDX-License-Identifier: Apache-2.0
"""A run's input refused at admission, or a sub-flow's at its crossing (engine 2b spec §3.5): each place it breaks and
the rule, never what's there. A place the data supplied, a map's key, shows as `*`: the key can be a secret."""

from dewpoint.apps.inputs import reasons

KEY = "".join(["canary", "-map-", "key"])  # a key the data supplied
CREDS = {
    "type": "object",
    "properties": {"creds": {"type": "object", "x-sensitive": True, "additionalProperties": {"type": "integer"}}},
    "required": ["creds"],
    "additionalProperties": False,
}
ROWS = {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "integer"}}}, "required": ["rows"]}
WHY = "The run's input doesn't match the workflow's input schema at {}: it breaks `{}`."


def test_a_refusal_names_a_map_key_as_a_star_never_the_key() -> None:
    assert reasons(CREDS, {"creds": {KEY: "not an integer"}}) == [WHY.format("creds.*", "type")]


def test_a_refusal_names_declared_properties_positions_and_the_root() -> None:
    assert reasons(ROWS, {"rows": [1, "x"]}) == [WHY.format("rows.1", "type")]
    assert reasons(ROWS, []) == [WHY.format("its root", "type")]
    assert reasons(CREDS, {"creds": {}, KEY: 1}) == [WHY.format("its root", "additionalProperties")]
