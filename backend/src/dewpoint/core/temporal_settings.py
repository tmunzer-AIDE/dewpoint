# SPDX-License-Identifier: Apache-2.0
"""The Temporal connection's settings (engine 2b spec §10.4), apart from the client that connects with them
(`core.temporal_connect`): `core.config.Settings` includes them, and processes that never talk to Temporal, webhook
ingress among them, read their settings without loading Temporal's SDK (the import contract, spec §8.3)."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TLS_SETTINGS = ("temporal_tls_ca", "temporal_tls_server_name", "temporal_tls_cert", "temporal_tls_key",
                "temporal_bearer_token_file")  # fmt: skip


class TemporalConnection(BaseSettings):
    """The settings every Temporal-connected process's own settings include."""

    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=".env", extra="ignore")

    temporal_tls_ca: str | None = None  # a CA file; the system roots verify the server when unset
    temporal_tls_server_name: str | None = None  # the name verified, when it isn't the address's host
    temporal_tls_cert: str | None = None  # mTLS: the client's certificate file
    temporal_tls_key: str | None = None  # mTLS: its private key file
    temporal_bearer_token_file: str | None = None  # a JWT, reread every TOKEN_REFRESH_S by a long-running process
    temporal_insecure_dev: bool = False  # plaintext: a deployment recorded as development only

    @field_validator(*TLS_SETTINGS, mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        """An empty setting (as a template leaves one) is unset: never a mode chosen with no file (the review's M1)."""
        return None if isinstance(value, str) and not value.strip() else value
