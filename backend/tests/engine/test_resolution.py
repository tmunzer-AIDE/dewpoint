# SPDX-License-Identifier: Apache-2.0
"""Resolving a handle (engine 2b spec §3.3, §3.6): what its pointer addresses, through nested claims, with every handle
inside the result resolved too, and tainted when any part it read was: the pointer lies in or holds a sensitive
pointer of its claim, or a nested claim it read is tainted."""

import uuid
from typing import Any

import pytest

from dewpoint.engine.handles import MISSING, ClaimRef, NestingError, StoredClaim, part, resolve

A, B, C = (str(uuid.UUID(int=i)) for i in (1, 2, 3))


def store(**claims: tuple[Any, tuple[str, ...]]) -> Any:
    """An in-memory claim store: `fetch(id)` as an activity's would, and the ids it read."""
    read: list[str] = []

    async def fetch(claim_id: str) -> StoredClaim:
        read.append(claim_id)
        value, sensitive = claims[claim_id]
        return StoredClaim(value, sensitive)

    fetch.read = read  # type: ignore[attr-defined]
    return fetch


async def test_a_pointer_reads_its_part_and_taints_only_what_overlaps_a_sensitive_pointer() -> None:
    fetch = store(**{A: ({"user": {"name": "ann", "password": "s3cret"}, "n": 3}, ("/user/password",))})
    assert (await resolve(ClaimRef(A, "/n"), fetch)).value == 3
    assert not (await resolve(ClaimRef(A, "/n"), fetch)).tainted
    assert not (await resolve(ClaimRef(A, "/user/name"), fetch)).tainted
    for inside in ("/user/password", "/user", ""):  # in it, or holding it
        assert (await resolve(ClaimRef(A, inside), fetch)).tainted, inside


async def test_a_pointer_that_addresses_nothing_is_missing() -> None:
    fetch = store(**{A: ({"rows": [1, 2]}, ())})
    for pointer in ("/absent", "/rows/2", "/rows/x", "/rows/01", "/rows/-"):
        assert (await resolve(ClaimRef(A, pointer), fetch)).value is MISSING, pointer


async def test_a_pointer_continues_through_a_nested_claim_and_takes_its_taint() -> None:
    fetch = store(**{
        A: ({"page": ClaimRef(B).to_json(), "title": "t"}, ()),
        B: ({"rows": [{"token": "s3cret"}, {"token": "other"}]}, ("/rows/0/token",)),
    })  # fmt: skip
    first = await resolve(ClaimRef(A, "/page/rows/0/token"), fetch)
    assert (first.value, first.tainted) == ("s3cret", True)
    second = await resolve(ClaimRef(A, "/page/rows/1"), fetch)
    assert (second.value, second.tainted) == ({"token": "other"}, False)


async def test_every_handle_inside_what_is_read_is_resolved_and_taints_it() -> None:
    fetch = store(**{
        A: ({"a": ClaimRef(B).to_json(), "b": [ClaimRef(C, "/k").to_json()]}, ()),
        B: ("plain", ()),
        C: ({"k": "s3cret"}, ("/k",)),
    })  # fmt: skip
    whole = await resolve(ClaimRef(A), fetch)
    assert whole.value == {"a": "plain", "b": ["s3cret"]} and whole.tainted
    part = await resolve(ClaimRef(A, "/a"), fetch)
    assert (part.value, part.tainted) == ("plain", False)
    assert C not in fetch.read[-1:]  # reading /a never touched C


async def test_claims_nested_without_end_are_refused() -> None:
    fetch = store(**{A: ({"next": ClaimRef(A).to_json()}, ())})
    with pytest.raises(NestingError):
        await resolve(ClaimRef(A), fetch)


async def test_a_part_is_copied_as_it_is_stored_with_its_taint_rebased() -> None:
    """What deriving a claim copies (§3.2): the part a long pointer addresses, its nested handles kept, and its
    sensitive pointers re-based onto it; a part inside a sensitive pointer is sensitive whole."""
    fetch = store(
        **{
            A: ({"login": {"user": "u", "pw": "p"}, "n": ClaimRef(B).to_json(), "secret": {"k": 1}},
                ("/login/pw", "/secret")),
            B: ({"x": 1, "y": 2}, ("/x",)),
        }
    )  # fmt: skip
    assert await part(ClaimRef(A, "/login"), fetch) == StoredClaim({"user": "u", "pw": "p"}, ("/pw",))
    assert await part(ClaimRef(A, "/login/user"), fetch) == StoredClaim("u", ())
    assert await part(ClaimRef(A, "/secret/k"), fetch) == StoredClaim(1, ("",))
    assert await part(ClaimRef(A, "/n"), fetch) == StoredClaim(ClaimRef(B).to_json(), ())  # its taint is its own
    assert await part(ClaimRef(A, "/n/x"), fetch) == StoredClaim(1, ("",))  # through the nested claim, B's taint
    assert await part(ClaimRef(A, "/n/y"), fetch) == StoredClaim(2, ())
    assert await part(ClaimRef(A, "/absent"), fetch) is None
