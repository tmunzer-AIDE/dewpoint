# SPDX-License-Identifier: Apache-2.0
import secrets
import time
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.passwords import hash_password, verify_password
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.models.identity import RecoveryCode, User, UserMfa

ISSUER = "Dewpoint"
PURPOSE = "user.totp"


async def has_totp(s: AsyncSession, user_id: object) -> bool:
    row = await s.get(UserMfa, user_id)
    return bool(row and row.totp_confirmed_at)


def _context(user: User, *, pending: bool) -> str:
    # Distinct AAD contexts: a pending ciphertext can't be copied into the confirmed slot (or vice versa).
    return f"{user.id}:pending" if pending else str(user.id)


async def start_enrollment(s: AsyncSession, keyring: Keyring, user: User, settings: Settings) -> str:
    """Stage a new secret. The confirmed factor (if any) stays in force until confirm_enrollment succeeds."""
    secret = pyotp.random_base32()
    ct = await keyring.encrypt(
        s, tenant_id=None, purpose=PURPOSE, context=_context(user, pending=True), plaintext=secret.encode()
    )
    row = await s.get(UserMfa, user.id, with_for_update=True) or UserMfa(user_id=user.id)
    row.totp_pending_ct = ct
    row.totp_pending_expires_at = datetime.now(UTC) + timedelta(minutes=settings.totp_pending_minutes)
    s.add(row)
    await s.flush()
    return pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)


def _match(secret: str, code: str, last_step: int | None) -> int | None:
    """The matching time step (current +/- 1) newer than last_step, else None."""
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = totp.timecode(datetime.fromtimestamp(time.time(), UTC))
    for step in (current - 1, current, current + 1):
        if step > (last_step if last_step is not None else -1) and secrets.compare_digest(
            totp.generate_otp(step), code
        ):
            return step
    return None


async def _secret(s: AsyncSession, keyring: Keyring, user: User, blob: bytes, *, pending: bool) -> str:
    raw = await keyring.decrypt(s, tenant_id=None, purpose=PURPOSE, context=_context(user, pending=pending), blob=blob)
    return raw.decode()


async def confirm_enrollment(s: AsyncSession, keyring: Keyring, user: User, code: str) -> list[str] | None:
    """Promote the pending secret to the confirmed factor. Returns fresh recovery codes, or None."""
    row = await s.get(UserMfa, user.id, with_for_update=True)
    if row is None or row.totp_pending_ct is None or row.totp_pending_expires_at is None:
        return None
    if row.totp_pending_expires_at <= datetime.now(UTC):
        return None
    secret = await _secret(s, keyring, user, row.totp_pending_ct, pending=True)
    step = _match(secret, code, None)
    if step is None:
        return None
    row.totp_secret_ct = await keyring.encrypt(
        s, tenant_id=None, purpose=PURPOSE, context=_context(user, pending=False), plaintext=secret.encode()
    )
    row.totp_confirmed_at, row.last_totp_step = datetime.now(UTC), step
    row.totp_pending_ct, row.totp_pending_expires_at = None, None
    await s.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(10)]
    s.add_all(RecoveryCode(user_id=user.id, code_hash=hash_password(c)) for c in codes)
    await s.flush()
    return codes


async def verify(s: AsyncSession, keyring: Keyring, user: User, code: str) -> bool:
    """Check a code against the confirmed factor only, with replay protection."""
    row = await s.get(UserMfa, user.id, with_for_update=True)
    if row is None or row.totp_confirmed_at is None or row.totp_secret_ct is None:
        return False
    step = _match(await _secret(s, keyring, user, row.totp_secret_ct, pending=False), code, row.last_totp_step)
    if step is None:
        return False
    row.last_totp_step = step
    await s.flush()
    return True


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
