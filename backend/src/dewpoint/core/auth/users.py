# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime
from typing import Annotated

from pydantic import StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.passwords import hash_password, policy_violations
from dewpoint.core.models.identity import User

# Deliberately lenient: self-hosted customers use internal/special-use domains (.local, .internal, .test)
# that RFC-strict validators reject. Uniqueness is case-insensitive (see ix_users_email_lower).
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
]


class PasswordPolicyError(ValueError):
    def __init__(self, violations: list[str]) -> None:
        super().__init__("password policy")
        self.violations = violations


class EmailTakenError(ValueError):
    pass


async def get_user_by_email(s: AsyncSession, email: str) -> User | None:
    return (await s.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()


async def create_user(s: AsyncSession, *, email: str, password: str, platform_admin: bool = False) -> User:
    if v := policy_violations(password, email):
        raise PasswordPolicyError(v)
    if await get_user_by_email(s, email):
        raise EmailTakenError(email)
    user = User(
        email=email.strip(),
        password_hash=hash_password(password),
        is_platform_admin=platform_admin,
        password_changed_at=datetime.now(UTC),
    )
    s.add(user)
    await s.flush()
    return user
