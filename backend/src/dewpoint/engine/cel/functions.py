# SPDX-License-Identifier: Apache-2.0
"""Function library `fn-1` (spec §5.4): declarations, metadata and pure Python implementations.

Implementations never read time, randomness, I/O or locale. A failure raises ValueError, which the runtime turns
into a CEL error value (so `||` and `&&` can absorb it like any other error)."""

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from dewpoint.engine.cel import types as T

LIBRARY = "fn-1"
MAX_ARGUMENT = 64  # code points: IP, CIDR and MAC arguments are short; longer input is an error, not work
_MAC_LAYOUTS = (
    re.compile(r"[0-9a-f]{12}"),
    re.compile(r"(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}"),
    re.compile(r"(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}"),
)


@dataclass(frozen=True)
class Overload:
    id: str
    result: str
    params: tuple[str, ...]
    impl: Callable[..., Any]


@dataclass(frozen=True)
class Function:
    name: str
    overloads: tuple[Overload, ...]
    cost: Literal["constant", "n log n"]
    output: str  # the output bound, as documented
    takes_map: bool
    deterministic: bool = True


def _fail(function: str, detail: str) -> ValueError:
    return ValueError(f"invalid_argument: {function}: {detail}")


def _short(function: str, text: str) -> str:
    if len(text) > MAX_ARGUMENT:
        raise _fail(function, f"argument longer than {MAX_ARGUMENT} characters")
    return text


def sorted_keys(m: dict[str, Any]) -> list[str]:
    return sorted(m)  # Python orders str by code point, as the spec requires


def as_list(value: list[Any]) -> list[Any]:
    return value  # the runtime dispatches only list arguments here; anything else has no matching overload


def ip_in_cidr(ip: str, cidr: str) -> bool:
    try:
        address = ipaddress.ip_address(_short("ipInCidr", ip))
        network = ipaddress.ip_network(_short("ipInCidr", cidr), strict=False)
    except ValueError as e:
        raise _fail("ipInCidr", str(e)) from None
    return address.version == network.version and address in network


def cidr_contains(outer: str, inner: str) -> bool:
    try:
        a = ipaddress.ip_network(_short("cidrContains", outer), strict=False)
        b = ipaddress.ip_network(_short("cidrContains", inner), strict=False)
    except ValueError as e:
        raise _fail("cidrContains", str(e)) from None
    if a.version != b.version:
        return False
    return b.subnet_of(a)  # type: ignore[arg-type]  # same version, checked above


def mac_normalize(text: str) -> str:
    lowered = _short("macNormalize", text).lower()
    if not any(layout.fullmatch(lowered) for layout in _MAC_LAYOUTS):
        raise _fail("macNormalize", "not a MAC address")
    return re.sub(r"[:.-]", "", lowered)


def mac_oui(text: str) -> str:
    return mac_normalize(text)[:6]


FUNCTIONS: tuple[Function, ...] = (
    Function(
        "sortedKeys",
        (Overload("sortedKeys_map", T.LIST_OF_STRINGS, (T.MAP,), sorted_keys),),
        "n log n",
        "≤ input",
        True,
    ),
    Function("asList", (Overload("asList_list", T.LIST, (T.LIST,), as_list),), "constant", "= input", False),
    Function(
        "ipInCidr",
        (Overload("ipInCidr_string_string", T.BOOL, (T.STRING, T.STRING), ip_in_cidr),),
        "constant",
        "bool",
        False,
    ),
    Function(
        "cidrContains",
        (Overload("cidrContains_string_string", T.BOOL, (T.STRING, T.STRING), cidr_contains),),
        "constant",
        "bool",
        False,
    ),
    Function(
        "macNormalize",
        (Overload("macNormalize_string", T.STRING, (T.STRING,), mac_normalize),),
        "constant",
        "12 code points",
        False,
    ),
    Function(
        "macOui", (Overload("macOui_string", T.STRING, (T.STRING,), mac_oui),), "constant", "6 code points", False
    ),
)
NAMES = frozenset(f.name for f in FUNCTIONS)
OVERLOAD_IDS = frozenset(o.id for f in FUNCTIONS for o in f.overloads)
