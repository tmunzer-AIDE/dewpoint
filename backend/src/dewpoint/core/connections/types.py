# SPDX-License-Identifier: Apache-2.0
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

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
class ConnectionType:
    key: str
    label: str
    config_model: type[BaseModel]
    secret_model: type[BaseModel]
    verify: Callable[[BaseModel, BaseModel, httpx.AsyncClient], Awaitable[VerifyResult]]


def _registry() -> dict[str, ConnectionType]:
    from dewpoint.core.connections.mist_verify import verify_mist

    return {"mist": ConnectionType("mist", "Juniper Mist", MistConfig, MistSecret, verify_mist)}  # type: ignore[arg-type]


CONNECTION_TYPES: dict[str, ConnectionType] = _registry()
