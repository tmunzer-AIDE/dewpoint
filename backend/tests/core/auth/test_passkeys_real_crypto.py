# SPDX-License-Identifier: Apache-2.0
"""WebAuthn with real signatures (no mocks), using a software authenticator."""

import pytest

from dewpoint.core.auth import passkeys
from dewpoint.core.auth.users import create_user
from tests.support.soft_authenticator import SoftAuthenticator

PW = "violet-otter-canyon-42"


async def _registered(s, api_settings, *, user_verified: bool = True):  # type: ignore[no-untyped-def]
    user = await create_user(s, email="real@corp.test", password=PW)
    auth = SoftAuthenticator("testserver", api_settings.public_origin, user_verified=user_verified)
    opts, cid = await passkeys.registration_options(s, user, api_settings)
    cred = await passkeys.finish_registration(s, user, cid, auth.register(opts), "soft", api_settings)
    return user, auth, cred


async def test_register_and_authenticate_with_real_signatures(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        user, auth, cred = await _registered(s, api_settings)
        for expected_count in (1, 2):
            opts, cid = await passkeys.authentication_options(s, api_settings, None)
            assert (await passkeys.finish_authentication(s, cid, auth.authenticate(opts), api_settings)).id == user.id
            assert cred.sign_count == expected_count


async def test_wrong_origin_and_tampered_signature_rejected(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        _, auth, _ = await _registered(s, api_settings)
        opts, cid = await passkeys.authentication_options(s, api_settings, None)
        with pytest.raises(passkeys.PasskeyError):
            await passkeys.finish_authentication(
                s, cid, auth.authenticate(opts, origin="https://evil.example"), api_settings
            )
        opts, cid = await passkeys.authentication_options(s, api_settings, None)
        response = auth.authenticate(opts)
        sig = bytearray(response["response"]["signature"].encode())
        sig[-2] = ord("A") if sig[-2] != ord("A") else ord("B")
        response["response"]["signature"] = sig.decode()
        with pytest.raises(passkeys.PasskeyError):
            await passkeys.finish_authentication(s, cid, response, api_settings)


async def test_replayed_assertion_rejected(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        _, auth, _ = await _registered(s, api_settings)
        opts, cid = await passkeys.authentication_options(s, api_settings, None)
        response = auth.authenticate(opts)
        await passkeys.finish_authentication(s, cid, response, api_settings)
        with pytest.raises(passkeys.PasskeyError):  # challenge consumed
            await passkeys.finish_authentication(s, cid, response, api_settings)


async def test_registration_requires_user_verification(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        with pytest.raises(passkeys.PasskeyError):
            await _registered(s, api_settings, user_verified=False)
