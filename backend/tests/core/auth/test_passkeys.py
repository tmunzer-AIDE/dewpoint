# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from dewpoint.core.auth import passkeys
from dewpoint.core.auth.users import create_user
from dewpoint.core.models.identity import WebauthnChallenge

CRED = {"id": "Y3JlZA", "rawId": "Y3JlZA", "type": "public-key", "response": {}}


@pytest.fixture
def fake_webauthn(monkeypatch):
    calls: dict[str, dict] = {}

    def reg(**kw):
        calls["reg"] = kw
        return SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0)

    def auth(**kw):
        calls["auth"] = kw
        return SimpleNamespace(new_sign_count=7)

    monkeypatch.setattr(passkeys, "verify_registration_response", reg)
    monkeypatch.setattr(passkeys, "verify_authentication_response", auth)
    return calls


async def test_register_then_authenticate(owner_sessionmaker, api_settings, fake_webauthn) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email="p@corp.test", password="violet-otter-canyon-42")
        opts, cid = await passkeys.registration_options(s, u, api_settings)
        assert opts["authenticatorSelection"]["userVerification"] == "required"
        cred = await passkeys.finish_registration(s, u, cid, CRED, "laptop", api_settings)
        assert cred.credential_id == b"cred"
        assert fake_webauthn["reg"]["require_user_verification"] is True
        with pytest.raises(passkeys.PasskeyError):  # challenge is single-use
            await passkeys.finish_registration(s, u, cid, CRED, "again", api_settings)

        _, aid = await passkeys.authentication_options(s, api_settings, None)
        user = await passkeys.finish_authentication(s, aid, CRED, api_settings)
        assert user.id == u.id and cred.sign_count == 7
        assert fake_webauthn["auth"]["require_user_verification"] is True


async def test_expired_and_user_mismatch(owner_sessionmaker, api_settings, fake_webauthn) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email="q@corp.test", password="violet-otter-canyon-42")
        _, cid = await passkeys.registration_options(s, u, api_settings)
        await passkeys.finish_registration(s, u, cid, CRED, "k", api_settings)
        _, aid = await passkeys.authentication_options(s, api_settings, None)
        await s.execute(update(WebauthnChallenge).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        with pytest.raises(passkeys.PasskeyError):
            await passkeys.finish_authentication(s, aid, CRED, api_settings)
        _, aid2 = await passkeys.authentication_options(s, api_settings, None)
        with pytest.raises(passkeys.PasskeyError):
            await passkeys.finish_authentication(s, aid2, CRED, api_settings, expected_user_id=uuid.uuid4())
