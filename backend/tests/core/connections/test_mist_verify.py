# SPDX-License-Identifier: Apache-2.0
import uuid

import httpx
import pytest
import respx
from pydantic import ValidationError

from dewpoint.core.connections.mist_verify import verify_mist
from dewpoint.core.connections.types import MistConfig, MistSecret

ORG = uuid.uuid4()


def _cfg() -> MistConfig:
    return MistConfig(cloud="emea_01", org_id=ORG)


@respx.mock
async def test_org_privilege_ok() -> None:
    route = respx.get("https://api.eu.mist.com/api/v1/self").respond(
        200, json={"privileges": [{"scope": "org", "org_id": str(ORG), "role": "write"}]}
    )
    async with httpx.AsyncClient() as http:
        r = await verify_mist(_cfg(), MistSecret(api_token="x" * 40), http)
    assert r.ok and r.privilege == "write"
    assert route.calls.last.request.headers["Authorization"] == "Token " + "x" * 40


@respx.mock
async def test_msp_access_confirmed_via_org_endpoint() -> None:
    respx.get("https://api.eu.mist.com/api/v1/self").respond(
        200, json={"privileges": [{"scope": "msp", "role": "admin"}]}
    )
    respx.get(f"https://api.eu.mist.com/api/v1/orgs/{ORG}").respond(200, json={"id": str(ORG)})
    async with httpx.AsyncClient() as http:
        r = await verify_mist(_cfg(), MistSecret(api_token="x" * 40), http)
    assert r.ok and r.privilege == "msp"


@respx.mock
async def test_bad_token_and_no_access() -> None:
    respx.get("https://api.eu.mist.com/api/v1/self").respond(401)
    async with httpx.AsyncClient() as http:
        r = await verify_mist(_cfg(), MistSecret(api_token="x" * 40), http)
    assert not r.ok and r.detail == "invalid_token"


def test_unknown_cloud_rejected() -> None:
    with pytest.raises(ValidationError):
        MistConfig(cloud="evil.example.com", org_id=ORG)  # type: ignore[arg-type]


def test_cloud_literal_matches_allowlist() -> None:
    from typing import get_args

    from dewpoint.core.connections.types import MIST_CLOUDS, MistCloud

    assert set(MIST_CLOUDS) == set(get_args(MistCloud))
