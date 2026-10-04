# SPDX-License-Identifier: Apache-2.0
"""A workflow's CSV input (engine 2b spec §8.1): the column types a declaration may use, the platform's caps, and each
type's canonical value. A cell is converted to its column's canonical value once, by admission; a declared default
must already be one, so the version holds exactly what a run would."""

import ipaddress
import re
from typing import Any, Literal

CsvType = Literal["string", "integer", "number", "boolean", "mac", "ip", "cidr", "enum"]
MAX_ROWS = 10_000  # the platform's caps; a declaration may lower them, never raise them
MAX_BYTES = 5 * 1024 * 1024
INT_MIN, INT_MAX = -(2**63), 2**63 - 1  # CEL's int

_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")  # the canonical form: lowercase, colon-separated


def ip(text: str) -> str | None:
    """`text` as `ipaddress` writes it (IPv6 compressed and lowercase); None if it isn't an address."""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def cidr(text: str) -> str | None:
    """`text` as `ipaddress` writes it; None if it isn't a network, or has host bits set."""
    try:
        return str(ipaddress.ip_network(text, strict=True))
    except ValueError:
        return None


def is_canonical(type_: CsvType, value: Any, values: list[str] | None = None) -> bool:
    """Whether `value` is a canonical value of `type_`: what converting a cell would give, and nothing else."""
    if type_ == "integer":
        return type(value) is int and INT_MIN <= value <= INT_MAX
    if type_ == "number":
        return type(value) in (int, float)
    if type_ == "boolean":
        return type(value) is bool
    if not isinstance(value, str):
        return False
    if type_ == "enum":
        return value in (values or ())
    if type_ == "mac":
        return _MAC.fullmatch(value) is not None
    if type_ == "ip":
        return ip(value) == value
    if type_ == "cidr":
        return cidr(value) == value
    return True
