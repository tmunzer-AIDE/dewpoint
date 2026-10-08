# SPDX-License-Identifier: Apache-2.0
"""ServiceNow (plugins-3 3d-2, D22): incidents through the Table API.

The connection names the instance, `https://` and its host (its `service-now.com` name or a custom URL), and holds a
REST API key, which the runtime sends as the `x-sn-apikey` header: the plugin never holds it. ServiceNow calls basic
auth legacy and restricts it on new instances; its OAuth client credentials are off by default. The key's user's roles
decide what a node may do (itil creates and resolves incidents). Requests go to `/api/now/v2/table/incident`: version
2 answers a query matching nothing with 200 and an empty list. One quota scope a key on an instance: bursts of 10,
then 2 a second; an instance's own hourly rules answer 429 with a `Retry-After`. Verify reads one incident."""

import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from dewpoint.sdk import (
    CallContext,
    Connection,
    ConnectionType,
    HeaderAuth,
    Plugin,
    RateScope,
    TransportError,
    UrlField,
    VerifyResult,
)
from dewpoint.sdk.connections import HOST_RE

TABLE = "/api/now/v2/table/incident"
KEY_TEXT = re.compile(r"[\x21-\x7e]{16,1024}")  # a key's format isn't documented: printable ASCII, no space


class ServiceNowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_url: str = Field(max_length=261, title="Instance URL",
                              description="https:// and its host, e.g. https://acme.service-now.com")  # fmt: skip

    @field_validator("instance_url")
    @classmethod
    def _instance(cls, value: str) -> str:
        scheme, _, host = value.partition("://")
        if scheme != "https" or not HOST_RE.fullmatch(host) or _numeric(host):
            raise ValueError("https:// and a lowercase host name, no port, no path")
        return value


def _numeric(host: str) -> bool:
    """An IPv4 address passes the host pattern: an instance has a name."""
    return all(label.isdigit() for label in host.split("."))


class ServiceNowSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(title="REST API key", description="The token of a REST API Key record.")

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: SecretStr) -> SecretStr:
        if not KEY_TEXT.fullmatch(value.get_secret_value()):
            raise ValueError("16 to 1,024 printable ASCII characters, no space")
        return value


async def verify(ctx: CallContext, connection: Connection) -> VerifyResult:
    """Reads one incident: the key opens the Table API and its user may read incidents."""
    try:
        answer = await connection.http.request("GET", TABLE, params={"sysparm_limit": "1", "sysparm_fields": "sys_id"})
    except TransportError:
        return VerifyResult(False, "unreachable")
    if answer.status_code == 200:
        return VerifyResult(True, "ok")
    if answer.status_code == 401:
        return VerifyResult(False, "invalid_key")
    if answer.status_code == 403:
        return VerifyResult(False, "no_table_access")
    return VerifyResult(False, "unexpected_status")


SCOPE = RateScope("servicenow.key", config=("instance_url",), secret="api_key", capacity=10, refill_per_s=2)  # noqa: S106 - a field


SERVICENOW = ConnectionType(
    key="servicenow",
    label="ServiceNow",
    Config=ServiceNowConfig,
    Secret=ServiceNowSecret,
    auth=HeaderAuth("x-sn-apikey", "{api_key}"),
    host=UrlField("instance_url"),
    rate_scopes=(SCOPE,),
    verify=verify,
)


PLUGIN = Plugin(name="servicenow", version="1.0.0", nodes=(), connection_types=(SERVICENOW,))
