# SPDX-License-Identifier: Apache-2.0
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import User, WebauthnChallenge, WebauthnCredential

CHALLENGE_TTL = timedelta(minutes=5)


class PasskeyError(Exception):
    pass


def _rp_id(settings: Settings) -> str:
    return settings.rp_id or (urlparse(settings.public_origin).hostname or "")


async def _store(s: AsyncSession, challenge: bytes, user_id: uuid.UUID | None, purpose: str) -> uuid.UUID:
    row = WebauthnChallenge(
        challenge=challenge, user_id=user_id, purpose=purpose, expires_at=datetime.now(UTC) + CHALLENGE_TTL
    )
    s.add(row)
    await s.flush()
    return row.id


async def _consume(s: AsyncSession, challenge_id: uuid.UUID, purpose: str) -> WebauthnChallenge:
    row = (
        await s.execute(
            delete(WebauthnChallenge)
            .where(WebauthnChallenge.id == challenge_id, WebauthnChallenge.purpose == purpose)
            .returning(WebauthnChallenge)
        )
    ).scalar_one_or_none()
    if row is None or row.expires_at <= datetime.now(UTC):
        raise PasskeyError("challenge")
    return row


async def registration_options(s: AsyncSession, user: User, settings: Settings) -> tuple[dict[str, Any], uuid.UUID]:
    existing = (
        (await s.execute(select(WebauthnCredential.credential_id).where(WebauthnCredential.user_id == user.id)))
        .scalars()
        .all()
    )
    opts = generate_registration_options(
        rp_id=_rp_id(settings),
        rp_name="Dewpoint",
        user_id=user.id.bytes,
        user_name=user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing],
    )
    return json.loads(options_to_json(opts)), await _store(s, opts.challenge, user.id, "register")


async def finish_registration(
    s: AsyncSession, user: User, challenge_id: uuid.UUID, credential: dict[str, Any], name: str, settings: Settings
) -> WebauthnCredential:
    ch = await _consume(s, challenge_id, "register")
    if ch.user_id != user.id:
        raise PasskeyError("user")
    try:
        v = verify_registration_response(
            credential=credential,
            expected_challenge=ch.challenge,
            expected_origin=settings.public_origin,
            expected_rp_id=_rp_id(settings),
            require_user_verification=True,
        )
    except Exception as exc:  # library raises several types; never leak details
        raise PasskeyError("verify") from exc
    cred = WebauthnCredential(
        user_id=user.id,
        credential_id=v.credential_id,
        public_key=v.credential_public_key,
        sign_count=v.sign_count,
        transports=[],
        name=name[:100],
    )
    s.add(cred)
    await s.flush()
    return cred


async def authentication_options(
    s: AsyncSession, settings: Settings, user_id: uuid.UUID | None
) -> tuple[dict[str, Any], uuid.UUID]:
    allow = []
    if user_id:
        ids = (
            (await s.execute(select(WebauthnCredential.credential_id).where(WebauthnCredential.user_id == user_id)))
            .scalars()
            .all()
        )
        allow = [PublicKeyCredentialDescriptor(id=c) for c in ids]
    opts = generate_authentication_options(
        rp_id=_rp_id(settings), allow_credentials=allow, user_verification=UserVerificationRequirement.REQUIRED
    )
    return json.loads(options_to_json(opts)), await _store(s, opts.challenge, user_id, "authenticate")


async def finish_authentication(
    s: AsyncSession,
    challenge_id: uuid.UUID,
    credential: dict[str, Any],
    settings: Settings,
    expected_user_id: uuid.UUID | None = None,
) -> User:
    ch = await _consume(s, challenge_id, "authenticate")
    try:
        raw_id = base64url_to_bytes(str(credential["rawId"]))
    except Exception as exc:
        raise PasskeyError("format") from exc
    cred = (
        await s.execute(select(WebauthnCredential).where(WebauthnCredential.credential_id == raw_id).with_for_update())
    ).scalar_one_or_none()
    if (
        cred is None
        or (ch.user_id and ch.user_id != cred.user_id)
        or (expected_user_id and expected_user_id != cred.user_id)
    ):
        raise PasskeyError("credential")
    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=ch.challenge,
            expected_origin=settings.public_origin,
            expected_rp_id=_rp_id(settings),
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise PasskeyError("verify") from exc
    cred.sign_count, cred.last_used_at = v.new_sign_count, datetime.now(UTC)
    user = await s.get(User, cred.user_id)
    if user is None or not user.is_active:
        raise PasskeyError("user")
    await s.flush()
    return user
