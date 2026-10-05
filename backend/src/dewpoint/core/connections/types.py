# SPDX-License-Identifier: Apache-2.0
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.core.ratelimit.buckets import Scope

# Source: mistapi cloud list (verify against the current library when updating).
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


class MistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud: MistCloud
    org_id: uuid.UUID


class MistSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_token: SecretStr = Field(min_length=20, max_length=200)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    detail: str
    privilege: str | None = None


@dataclass(frozen=True)
class HeaderAuth:
    """Credentials the runtime sends as one header, `template` filled from the secret's fields (plugins-3 D4)."""

    header: str
    template: str


# A credential's quota-scope key: an HMAC under a key derived from the tenant's data key, never the credential.
type CredentialKey = Callable[[str], str]


@dataclass(frozen=True)
class ConnectionType:
    """A connection type (until 3a-2 moves them into manifests, plugins-3 D11): its models, its verify call, and what
    the runtime needs to use it for a step: its base URL, how its credentials are applied (the plugin never holds
    them) and the provider's quota scopes it charges (D9)."""

    key: str
    label: str
    config_model: type[BaseModel]
    secret_model: type[BaseModel]
    verify: Callable[[BaseModel, BaseModel, httpx.AsyncClient], Awaitable[VerifyResult]]
    base_url: Callable[[BaseModel, BaseModel], str] | None = None
    auth: HeaderAuth | None = None
    rate_scopes: Callable[[BaseModel, CredentialKey, BaseModel], list[Scope]] | None = None


MIST_BUDGET = (50.0, 1.25)  # burst and refill per second, below the documented 5,000 an hour (plugins-3 D9)


def _mist_base(config: BaseModel, secret: BaseModel) -> str:
    assert isinstance(config, MistConfig)  # noqa: S101 - the registry pairs them
    return f"https://{MIST_CLOUDS[config.cloud]}"


def _mist_scopes(config: BaseModel, credential: CredentialKey, secret: BaseModel) -> list[Scope]:
    """Per token and per org: the docs say both (plugins-3 D9, unresolved until verified)."""
    assert isinstance(config, MistConfig) and isinstance(secret, MistSecret)  # noqa: S101 - the registry pairs them
    return [
        Scope(f"mist.org:{config.cloud}:{config.org_id}", *MIST_BUDGET),
        Scope(f"mist.token:{credential(secret.api_token.get_secret_value())}", *MIST_BUDGET),
    ]


def _registry() -> dict[str, ConnectionType]:
    from dewpoint.core.connections.mist_verify import verify_mist

    mist = ConnectionType(
        "mist",
        "Juniper Mist",
        MistConfig,
        MistSecret,
        verify_mist,  # type: ignore[arg-type]
        base_url=_mist_base,
        auth=HeaderAuth("Authorization", "Token {api_token}"),
        rate_scopes=_mist_scopes,
    )
    return {"mist": mist}


CONNECTION_TYPES: dict[str, ConnectionType] = _registry()
