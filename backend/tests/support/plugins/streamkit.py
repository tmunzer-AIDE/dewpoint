# SPDX-License-Identifier: Apache-2.0
"""A connection type with a stream endpoint, and nodes that use it (plugins-3 D26), for the runtime's stream tests: kept
apart from testkit, whose connection types other tests list."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

from dewpoint.sdk import (
    ConnectionType,
    HeaderAuth,
    HostMap,
    Node,
    Plugin,
    RateScope,
    SideEffect,
    StepContext,
    StreamEndpoint,
    connection_field,
)

STREAM_HOST = "stream.test"


class StreamkitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Literal["local"]


class StreamkitSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


STREAM_SCOPE = RateScope("streamkit.stream", secret="token", capacity=5, refill_per_s=5)  # noqa: S106 - a field's name
STREAMKIT_CONNECTION = ConnectionType(
    key="streamkit",
    label="Streamkit",
    Config=StreamkitConfig,
    Secret=StreamkitSecret,
    auth=HeaderAuth("Authorization", "Bearer {token}"),
    host=HostMap("region", {"local": "api.stream.test"}),
    rate_scopes=(RateScope("streamkit.token", secret="token", capacity=50, refill_per_s=50),),  # noqa: S106
    stream=StreamEndpoint(HostMap("region", {"local": STREAM_HOST}), "/v1/stream", (STREAM_SCOPE,)),
)
PLAIN_CONNECTION = ConnectionType(  # a type without a stream
    key="streamkit.plain",
    label="Streamkit without a stream",
    Config=StreamkitConfig,
    Secret=StreamkitSecret,
    auth=HeaderAuth("Authorization", "Bearer {token}"),
    host=HostMap("region", {"local": "api.stream.test"}),
)


class StreamCallConfig(BaseModel):
    connection: uuid.UUID = connection_field("streamkit")  # either type: the runtime reads `credentials`
    send: str = "hello"
    probe: bool = False
    receive: int = 1


class StreamCallOutput(BaseModel):
    received: list[str | None]


class StreamCall(Node):
    """Opens its connection's stream, sends one message and reads `receive` answers."""

    type = "streamkit.stream_call"
    version = 1
    title = "Stream call"
    Config = StreamCallConfig
    Output = StreamCallOutput
    credentials = ("streamkit", "streamkit.plain")
    side_effect = SideEffect.IDEMPOTENT

    async def run(self, ctx: StepContext, config: StreamCallConfig) -> StreamCallOutput:
        conn = await ctx.connection(config.connection)
        stream = await conn.ws.connect()
        try:
            await stream.send(config.send, probe=config.probe)
            return StreamCallOutput(received=[await stream.receive(5) for _ in range(config.receive)])
        finally:
            await stream.close()


class AmbiguousStreamCall(StreamCall):
    type = "streamkit.ambiguous_stream_call"
    side_effect = SideEffect.AMBIGUOUS


STREAMKIT = Plugin(
    name="streamkit",
    version="0.0.0",
    nodes=(StreamCall, AmbiguousStreamCall),
    connection_types=(STREAMKIT_CONNECTION, PLAIN_CONNECTION),
)
