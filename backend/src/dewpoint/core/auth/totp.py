# SPDX-License-Identifier: Apache-2.0
import secrets
import time
from datetime import UTC, datetime

import pyotp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.passwords import hash_password, verify_password
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.models.identity import RecoveryCode, User, UserMfa

ISSUER = "Dewpoint"
PURPOSE = "user.totp"


async def has_totp(s: AsyncSession, user_id: object) -> bool:
    row = await s.get(UserMfa, user_id)
    return bool(row and row.totp_confirmed_at)


async def start_enrollment(s: AsyncSession, keyring: Keyring, user: User) -> str:
    secret = pyotp.random_base32()
    ct = await keyring.encrypt(s, tenant_id=None, purpose=PURPOSE, context=str(user.id), plaintext=secret.encode())
    row = await s.get(UserMfa, user.id) or UserMfa(user_id=user.id)
    row.totp_secret_ct, row.totp_confirmed_at, row.last_totp_step = ct, None, None
    s.add(row)
    await s.flush()
    return pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)


async def _check(s: AsyncSession, keyring: Keyring, row: UserMfa, user: User, code: str) -> bool:
    if not row.totp_secret_ct or not code.isdigit():
        return False
    secret = (
        await keyring.decrypt(s, tenant_id=None, purpose=PURPOSE, context=str(user.id), blob=row.totp_secret_ct)
    ).decode()
    totp, now = pyotp.TOTP(secret), time.time()
    current = totp.timecode(datetime.fromtimestamp(now, UTC))
    for step in (current - 1, current, current + 1):
        if step > (row.last_totp_step or -1) and secrets.compare_digest(totp.generate_otp(step), code):
            row.last_totp_step = step
            await s.flush()
            return True
    return False


async def confirm_enrollment(s: AsyncSession, keyring: Keyring, user: User, code: str) -> list[str] | None:
    row = await s.get(UserMfa, user.id, with_for_update=True)
    if row is None or not await _check(s, keyring, row, user, code):
        return None
    row.totp_confirmed_at = datetime.now(UTC)
    await s.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(10)]
    s.add_all(RecoveryCode(user_id=user.id, code_hash=hash_password(c)) for c in codes)
    await s.flush()
    return codes


async def verify(s: AsyncSession, keyring: Keyring, user: User, code: str) -> bool:
    row = await s.get(UserMfa, user.id, with_for_update=True)
    return bool(row and row.totp_confirmed_at and await _check(s, keyring, row, user, code))


async def use_recovery_code(s: AsyncSession, user: User, code: str) -> bool:
    rows = (
        (
            await s.execute(
                select(RecoveryCode)
                .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for rc in rows:
        if verify_password(rc.code_hash, code.strip().lower()):
            rc.used_at = datetime.now(UTC)
            await s.flush()
            return True
    return False
