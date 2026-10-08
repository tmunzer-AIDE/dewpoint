# SPDX-License-Identifier: Apache-2.0
"""A connection type whose credentials are a JSON body field (plugins-3 D4's `body_field`, `BodyField`) and a node
posting through it, for the runtime's tests: kept apart from testkit, whose types other tests list."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    BodyField,
    ConnectionType,
    Node,
    Plugin,
    RateScope,
    SideEffect,
    StepContext,
    UrlField,
    connection_field,
)

ROUTING_KEY = "r" * 32


class BodykitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str


class BodykitSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routing_key: SecretStr = Field(min_length=32, max_length=32)


BODYKIT_CONNECTION = ConnectionType(
    key="bodykit",
    label="Bodykit",
    Config=BodykitConfig,
    Secret=BodykitSecret,
    auth=BodyField("routing_key", "routing_key"),
    host=UrlField("url"),
    rate_scopes=(RateScope("bodykit.key", secret="routing_key", capacity=10, refill_per_s=1.0),),  # noqa: S106 - a field
)


class PostConfig(BaseModel):
    connection: uuid.UUID = connection_field("bodykit")


class PostOutput(BaseModel):
    status: int


class Post(Node):
    type = "bodykit.post"
    version = 1
    title = "Body post"
    Config = PostConfig
    Output = PostOutput
    credentials = ("bodykit",)
    side_effect = SideEffect.KEYED

    async def run(self, ctx: StepContext, config: PostConfig) -> PostOutput:
        conn = await ctx.connection(config.connection)
        answer = await conn.http.request("POST", "/v2/enqueue", json={"event_action": "trigger"})
        return PostOutput(status=answer.status_code)


BODYKIT = Plugin(name="bodykit", version="0.0.0", nodes=(Post,), connection_types=(BODYKIT_CONNECTION,))
