# SPDX-License-Identifier: Apache-2.0
"""A CSV cell converted to its column's canonical value (engine 2b spec §8.1, the owner's ruling 7): `boolean` takes
true/false, yes/no and 1/0 in any case; `integer` is decimal, within CEL's int; `number` is finite; `mac` is written in
lowercase colon form; `ip` and `cidr` as Python's `ipaddress` writes them, a `cidr` with host bits set refused; `enum`
matches exactly. A cell that doesn't convert gives a fixed code, never its text."""

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.graph.csv import CELL_CODES, CsvType, convert, is_canonical


@pytest.mark.parametrize(
    ("type_", "text", "value"),
    [
        ("string", "  paris ", "  paris "),
        ("integer", "42", 42), ("integer", "-7", -7), ("integer", "+3", 3), ("integer", "007", 7),
        ("number", "1.5", 1.5), ("number", "2", 2.0), ("number", "-1e3", -1000.0), ("number", ".5", 0.5),
        ("boolean", "TRUE", True), ("boolean", "yes", True), ("boolean", "1", True),
        ("boolean", "False", False), ("boolean", "NO", False), ("boolean", "0", False),
        ("mac", "AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"), ("mac", "aa-bb-cc-dd-ee-ff", "aa:bb:cc:dd:ee:ff"),
        ("mac", "aabb.ccdd.eeff", "aa:bb:cc:dd:ee:ff"), ("mac", "AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff"),
        ("ip", "10.0.0.1", "10.0.0.1"), ("ip", "2001:DB8:0:0::1", "2001:db8::1"),
        ("cidr", "10.0.0.0/8", "10.0.0.0/8"), ("cidr", "2001:DB8::/32", "2001:db8::/32"),
        ("enum", "ap", "ap"),
    ],
)  # fmt: skip
def test_a_cell_converts_to_its_canonical_value(type_: CsvType, text: str, value: Any) -> None:
    assert convert(type_, text, ["ap", "switch"]) == (value, None)
    assert is_canonical(type_, value, ["ap", "switch"])


@pytest.mark.parametrize(
    ("type_", "text", "code"),
    [
        ("integer", "4.2", "not_integer"), ("integer", "١٢", "not_integer"), ("integer", "1_000", "not_integer"),
        ("integer", str(2**63), "out_of_range"), ("integer", " 4", "not_integer"),
        ("number", "nan", "not_number"), ("number", "inf", "not_number"), ("number", "1e400", "not_number"),
        ("number", "1,5", "not_number"), ("number", "0x10", "not_number"),
        ("boolean", "y", "not_boolean"), ("boolean", "2", "not_boolean"),
        ("mac", "aa:bb:cc:dd:ee", "not_mac"), ("mac", "aa:bb-cc:dd:ee:ff", "not_mac"),
        ("mac", "gg:bb:cc:dd:ee:ff", "not_mac"),
        ("ip", "10.0.0.256", "not_ip"), ("ip", "010.0.0.1", "not_ip"), ("ip", "host.example", "not_ip"),
        ("cidr", "10.0.0.1/8", "not_cidr"), ("cidr", "10.0.0.0/33", "not_cidr"),
        ("enum", "AP", "not_in_enum"), ("enum", "router", "not_in_enum"),
    ],
)  # fmt: skip
def test_a_cell_that_doesnt_convert_gives_its_code(type_: CsvType, text: str, code: str) -> None:
    assert convert(type_, text, ["ap", "switch"]) == (None, code)
    assert code in CELL_CODES


@settings(max_examples=500, deadline=None)
@given(
    st.sampled_from(["string", "integer", "number", "boolean", "mac", "ip", "cidr", "enum"]),
    st.text(max_size=64),
)
def test_any_text_converts_to_a_canonical_value_or_a_fixed_code(type_: CsvType, text: str) -> None:
    value, code = convert(type_, text, ["ap", "switch"])
    if code is None:
        assert is_canonical(type_, value, ["ap", "switch"])
        assert convert(type_, str(value).lower() if type_ == "boolean" else str(value), ["ap", "switch"])[1] is None
    else:
        assert value is None and code in CELL_CODES
