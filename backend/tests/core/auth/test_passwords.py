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


def test_email_type_accepts_internal_domains_and_rejects_garbage() -> None:
    import pytest
    from pydantic import TypeAdapter, ValidationError

    from dewpoint.core.auth.users import Email

    ta = TypeAdapter(Email)
    for ok in ("dana@corp.test", "ops@site.local", "a.b+c@mist.internal", "  x@example.com "):
        assert ta.validate_python(ok) == ok.strip()
    for bad in ("", "nodomain", "@x.y", "a@", "a b@c.d", "a@b@c", "x" * 321 + "@a.b"):
        with pytest.raises(ValidationError):
            ta.validate_python(bad)
