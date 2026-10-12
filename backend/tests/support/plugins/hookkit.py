# SPDX-License-Identifier: Apache-2.0
"""A connection type whose base URL is a secret (plugins-3 D4's `url` auth, `SecretUrl`) and a node posting to it, for
the runtime's and the API's tests of incoming-webhook connections: kept apart from testkit, whose types other tests
list."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    ConnectionType,
    Node,
    Plugin,
    RateScope,
    SecretUrl,
    SideEffect,
    StepContext,
    connection_field,
)

HOOK_URL = r"https://hooks\.test(:[0-9]{1,5})?/v1/spaces/[a-z0-9]{1,32}/messages\?key=[A-Za-z0-9]{8,64}"
SPACE = RateScope("hookkit.space", secret="webhook_url", secret_pattern=r"/spaces/([a-z0-9]+)/", capacity=1,
                  refill_per_s=0.001)  # fmt: skip


class HookkitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HookkitSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: SecretStr = Field(max_length=2048)


HOOKKIT_CONNECTION = ConnectionType(
    key="hookkit",
    label="Hookkit",
    Config=HookkitConfig,
    Secret=HookkitSecret,
    host=SecretUrl("webhook_url", HOOK_URL),
    rate_scopes=(SPACE,),
)


class HookPostConfig(BaseModel):
    connection: uuid.UUID = connection_field("hookkit")
    text: str = "hello"
    url: str = ""  # what the node asks for; only "" reaches the URL
    params: dict[str, str] | None = None


class HookPostOutput(BaseModel):
    status: int


class HookPost(Node):
    type = "hookkit.post"
    version = 1
    title = "Hook post"
    Config = HookPostConfig
    Output = HookPostOutput
    credentials = ("hookkit",)
    side_effect = SideEffect.AMBIGUOUS

    async def run(self, ctx: StepContext, config: HookPostConfig) -> HookPostOutput:
        conn = await ctx.connection(config.connection)
        params: Any = config.params
        answer = await conn.http.request("POST", config.url, json={"text": config.text}, params=params)
        return HookPostOutput(status=answer.status_code)


HOOKKIT = Plugin(name="hookkit", version="0.0.0", nodes=(HookPost,), connection_types=(HOOKKIT_CONNECTION,))
