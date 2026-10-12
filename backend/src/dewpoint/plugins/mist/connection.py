# SPDX-License-Identifier: Apache-2.0
"""The `mist` connection type, as it was in `core` (plugins-3 D11): an org on one of Mist's clouds, a token sent as
`Authorization: Token …`, charged per token and per org (D9), and verified by reading `/self` (and the org, for an
MSP token) through the connection's read-only HTTP. Its stream (D26) is the cloud's websocket host at
`/api-ws/v1/stream`, with the same header, each opening charged to the token's stream scope."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    CallContext,
    Connection,
    ConnectionType,
    HeaderAuth,
    HostMap,
    RateScope,
    StreamEndpoint,
    TransportError,
    VerifyResult,
)

# Source: mistapi's cloud list (verify against the current library when updating).
MIST_CLOUDS: dict[str, str] = {
    "global_01": "api.mist.com",
    "global_02": "api.gc1.mist.com",
    "global_03": "api.ac2.mist.com",
    "global_04": "api.gc2.mist.com",
    "global_05": "api.gc4.mist.com",
    "emea_01": "api.eu.mist.com",
    "emea_02": "api.gc3.mist.com",
    "emea_03": "api.ac6.mist.com",
    "emea_04": "api.gc6.mist.com",
    "apac_01": "api.ac5.mist.com",
    "apac_02": "api.gc5.mist.com",
    "apac_03": "api.gc7.mist.com",
}
# Mist's websocket hosts (guides/websocket/1_hosts): each cloud's API host with `api-ws.` for `api.`.
MIST_STREAM_CLOUDS: dict[str, str] = {cloud: host.replace("api.", "api-ws.", 1) for cloud, host in MIST_CLOUDS.items()}
MIST_STREAM_PATH = "/api-ws/v1/stream"  # guides/websocket/2_best_practices
MistCloud = Literal[
    "global_01",
    "global_02",
    "global_03",
    "global_04",
    "global_05",
    "emea_01",
    "emea_02",
    "emea_03",
    "emea_04",
    "apac_01",
    "apac_02",
    "apac_03",
]
MIST_BUDGET = (50.0, 1.25)  # burst and refill per second, below the documented 5,000 an hour (plugins-3 D9)
# Streams opened per token: a burst of 50, then 1,800 an hour, under the documented 2,000 (websocket/3_rate_limit).
MIST_STREAM_BUDGET = (50.0, 0.5)
JSON = {"Accept": "application/json"}


class MistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud: MistCloud
    org_id: uuid.UUID


class MistSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_token: SecretStr = Field(min_length=20, max_length=200)


def _privileges(body: Any) -> list[dict[str, Any]]:
    found = body.get("privileges") if isinstance(body, dict) else None
    return [p for p in found if isinstance(p, dict)] if isinstance(found, list) else []


async def verify(ctx: CallContext, connection: Connection) -> VerifyResult:
    """The token's privilege on the connection's org: its org role, or `msp` when an MSP token can read the org."""
    org = str(connection.config.get("org_id", "")).lower()
    try:
        answer = await connection.http.request("GET", "/api/v1/self", headers=JSON)
        if answer.status_code in (401, 403):
            return VerifyResult(False, "invalid_token")
        if answer.status_code != 200:
            return VerifyResult(False, "unexpected_status")
        privileges = _privileges(answer.json())
        for p in privileges:
            if p.get("scope") == "org" and str(p.get("org_id", "")).lower() == org:
                return VerifyResult(True, "ok", str(p.get("role")))
        if any(p.get("scope") == "msp" for p in privileges):
            org_answer = await connection.http.request("GET", f"/api/v1/orgs/{uuid.UUID(org)}", headers=JSON)
            if org_answer.status_code == 200:
                return VerifyResult(True, "ok", "msp")
        return VerifyResult(False, "no_org_access")
    except (TransportError, ValueError):
        return VerifyResult(False, "unreachable")


STREAM_SCOPE = RateScope(
    "mist.stream",
    secret="api_token",  # noqa: S106 - a field's name
    capacity=MIST_STREAM_BUDGET[0],
    refill_per_s=MIST_STREAM_BUDGET[1],
)
MIST = ConnectionType(
    key="mist",
    label="Juniper Mist",
    Config=MistConfig,
    Secret=MistSecret,
    auth=HeaderAuth("Authorization", "Token {api_token}"),
    host=HostMap("cloud", MIST_CLOUDS),
    rate_scopes=(
        RateScope("mist.org", config=("cloud", "org_id"), capacity=MIST_BUDGET[0], refill_per_s=MIST_BUDGET[1]),
        RateScope("mist.token", secret="api_token", capacity=MIST_BUDGET[0], refill_per_s=MIST_BUDGET[1]),  # noqa: S106 - a field's name
    ),
    verify=verify,
    stream=StreamEndpoint(HostMap("cloud", MIST_STREAM_CLOUDS), MIST_STREAM_PATH, (STREAM_SCOPE,)),
)
