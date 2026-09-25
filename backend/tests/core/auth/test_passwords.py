# SPDX-License-Identifier: Apache-2.0
from dewpoint.core.auth.passwords import hash_password, needs_rehash, policy_violations, verify_password


def test_hash_verify() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "wrong")
    assert not needs_rehash(h)


def test_policy() -> None:
    assert "min_length" in policy_violations("short", "a@b.c")
    assert "contains_email" in policy_violations("alice-is-great-2026", "alice@corp.test")
    assert "common" in policy_violations("password1234", "x@y.z")
    assert policy_violations("violet-otter-canyon-42", "alice@corp.test") == []
