# SPDX-License-Identifier: Apache-2.0
"""Rotating the ingress key (engine 2b spec §8.3): a process holds the current key and, during a rollout, the previous
one; a sealed secret names its key's id and opens under whichever the process holds. `reseal` seals every endpoint's
secrets again under the current key, their plaintext unchanged (a dedupe secret stays the same, so deduplication
carries on), each write a compare-and-swap; `usage` counts them by key id, so the previous key retires once none
names it."""

import os
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET, IngressKey, UnknownIngressKeyError
from dewpoint.core.ingress import secrets_reseal
from tests.core.ingress.support import endpoint

OLD, NEW = os.urandom(32), os.urandom(32)


def test_a_key_with_its_previous_opens_both_and_seals_under_the_current() -> None:
    old, both = IngressKey("old", OLD), IngressKey("new", NEW, previous=[("old", OLD)])
    assert both.open(HMAC_SECRET, "e", old.seal(HMAC_SECRET, "e", b"s")) == b"s"
    assert both.open(HMAC_SECRET, "e", both.seal(HMAC_SECRET, "e", b"t")) == b"t"
    assert both.seal(HMAC_SECRET, "e", b"t")[2:5] == b"new"
    with pytest.raises(UnknownIngressKeyError):
        IngressKey("other", os.urandom(32)).open(HMAC_SECRET, "e", old.seal(HMAC_SECRET, "e", b"s"))
    with pytest.raises(ValueError, match="unique"):
        IngressKey("new", NEW, previous=[("new", OLD)])


async def _sealed_endpoint(owner: Any, key: IngressKey, *, hmac: bool) -> tuple[uuid.UUID, bytes, bytes | None]:
    endpoint_id, dedupe, secret = uuid.uuid4(), os.urandom(32), (b"hmac-secret" if hmac else None)
    columns: dict[str, Any] = {"dedupe_key": key.seal(DEDUPE_KEY, str(endpoint_id), dedupe)}
    if secret is not None:
        sealed = key.seal(HMAC_SECRET, str(endpoint_id), secret)
        columns |= {"auth_kind": "hmac", "bearer_digest": None, "hmac_secret": sealed, "signature_header": "x-sig",
                    "timestamp_header": "x-ts"}  # fmt: skip
    await endpoint(owner, endpoint_id, **columns)
    return endpoint_id, dedupe, secret


async def _row(owner: Any, endpoint_id: uuid.UUID) -> Any:
    async with owner() as s:
        return (await s.execute(text("select hmac_secret, dedupe_key from webhook_endpoints where id = :e"),
                                {"e": endpoint_id})).one()  # fmt: skip


async def test_every_endpoints_secrets_are_sealed_again_under_the_current_key(owner_sessionmaker,
                                                                              admin_sessionmaker) -> None:  # fmt: skip
    old, both = IngressKey("old", OLD), IngressKey("new", NEW, previous=[("old", OLD)])
    signed = await _sealed_endpoint(owner_sessionmaker, old, hmac=True)
    bearer = await _sealed_endpoint(owner_sessionmaker, old, hmac=False)
    async with admin_sessionmaker() as s:
        assert await secrets_reseal.usage(s) == {"old": 3}
    assert await secrets_reseal.reseal(admin_sessionmaker, both, batch=1) == {"hmac_secret": 1, "dedupe_key": 2}
    for endpoint_id, dedupe, secret in (signed, bearer):
        hmac_blob, dedupe_blob = await _row(owner_sessionmaker, endpoint_id)
        assert IngressKey("new", NEW).open(DEDUPE_KEY, str(endpoint_id), bytes(dedupe_blob)) == dedupe
        if secret is not None:
            assert IngressKey("new", NEW).open(HMAC_SECRET, str(endpoint_id), bytes(hmac_blob)) == secret
    async with admin_sessionmaker() as s:
        assert await secrets_reseal.usage(s) == {"new": 3}
    assert await secrets_reseal.reseal(admin_sessionmaker, both) == {"hmac_secret": 0, "dedupe_key": 0}


async def test_a_secret_rotated_meanwhile_is_never_overwritten(monkeypatch, owner_sessionmaker,
                                                               admin_sessionmaker) -> None:  # fmt: skip
    old, both = IngressKey("old", OLD), IngressKey("new", NEW, previous=[("old", OLD)])
    endpoint_id, _, _ = await _sealed_endpoint(owner_sessionmaker, old, hmac=True)
    rotated = both.seal(HMAC_SECRET, str(endpoint_id), b"rotated meanwhile")

    async def meanwhile(column: str) -> None:
        if column == "hmac_secret":
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text("update webhook_endpoints set hmac_secret = :h where id = :e"),
                                {"h": rotated, "e": endpoint_id})  # fmt: skip

    monkeypatch.setattr(secrets_reseal, "_after_choosing", meanwhile)
    assert (await secrets_reseal.reseal(admin_sessionmaker, both))["hmac_secret"] == 0
    assert bytes((await _row(owner_sessionmaker, endpoint_id))[0]) == rotated
