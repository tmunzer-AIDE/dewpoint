# SPDX-License-Identifier: Apache-2.0
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()  # argon2id, library defaults (RFC 9106 low-memory profile)
MIN_LENGTH = 12
_COMMON = frozenset({"password1234", "123456789012", "qwertyuiop12", "letmein12345", "welcome12345", "admin1234567"})


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(stored: str, pw: str) -> bool:
    try:
        return _ph.verify(stored, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _ph.check_needs_rehash(stored)


def policy_violations(pw: str, email: str) -> list[str]:
    out: list[str] = []
    if len(pw) < MIN_LENGTH:
        out.append("min_length")
    local = email.split("@", 1)[0].lower()
    if len(local) >= 3 and local in pw.lower():
        out.append("contains_email")
    if pw.lower() in _COMMON:
        out.append("common")
    return out
