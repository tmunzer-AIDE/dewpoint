# SPDX-License-Identifier: Apache-2.0
"""A connection type that declares an SMTP server (plugins-3 D20, `SmtpServer`) and a node mailing through it, for the
runtime's tests of `connection.smtp`: kept apart from testkit, whose types other tests list."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    ConnectionType,
    Node,
    Plugin,
    RateScope,
    SideEffect,
    SmtpServer,
    StepContext,
    connection_field,
)

MESSAGE = b"From: alerts@example.com\r\nTo: ops@example.com\r\nSubject: Disk full\r\n\r\nDisk full on db-1\r\n"
SERVER = RateScope("mailkit.server", config=("host",), capacity=1, refill_per_s=0.001)


class MailkitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = Field(ge=1, le=65535)
    security: Literal["starttls", "tls", "none"]
    from_address: str
    username: str | None = None


class MailkitSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = SecretStr("")


MAILKIT_CONNECTION = ConnectionType(
    key="mailkit",
    label="Mailkit",
    Config=MailkitConfig,
    Secret=MailkitSecret,
    smtp=SmtpServer(
        host="host",
        port="port",
        security="security",
        sender="from_address",
        username="username",
        password="password",  # noqa: S106 - a field's name
    ),
    rate_scopes=(SERVER,),
)


class MailSendConfig(BaseModel):
    connection: uuid.UUID = connection_field("mailkit")
    to: list[str] = ["ops@example.com"]


class MailSendOutput(BaseModel):
    refused: list[str]


class MailSend(Node):
    type = "mailkit.send"
    version = 1
    title = "Mail send"
    Config = MailSendConfig
    Output = MailSendOutput
    credentials = ("mailkit",)
    side_effect = SideEffect.AMBIGUOUS

    async def run(self, ctx: StepContext, config: MailSendConfig) -> MailSendOutput:
        conn = await ctx.connection(config.connection)
        return MailSendOutput(refused=await conn.smtp.send(config.to, MESSAGE))


MAILKIT = Plugin(name="mailkit", version="0.0.0", nodes=(MailSend,), connection_types=(MAILKIT_CONNECTION,))
