# SPDX-License-Identifier: Apache-2.0
"""Ingress's own settings, from its environment only: its database login, the ingress key and its limits. No
key-encryption key: ingress never holds a tenant's data key (engine 2b spec §8.3), so it has no setting for one."""

import base64
import binascii

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dewpoint.apps.ingress.addresses import parse_proxies

MIB = 1024 * 1024
# The largest body limit an endpoint may set. The database sizes every endpoint's byte burst to cover a body this large
# (migration 0032), so a larger cap would make a body past a small limit a 429 for ever (the owner's M2 review).
MAX_BODY_CAP = 5 * MIB


class IngressSettings(BaseSettings):
    # The environment only, never a `.env` file: a shared one may hold the key-encryption key.
    # Errors never quote a value: a key of the wrong length may still be a real key.
    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=None, extra="ignore", hide_input_in_errors=True)

    database_url: str  # the ingress login's: no table privilege, only ingress's functions
    ingress_key_b64: str
    ingress_key_id: str = "ingress-1"
    ingress_key_previous_b64: str | None = None  # set only during a rollout: it opens, never seals
    ingress_key_previous_id: str | None = None
    # Proxies whose X-Forwarded-For is believed (the owner's ruling 11): none by default.
    ingress_trusted_proxies: str = ""
    # The limits before authentication (§15, provisional; the load probe revisits them).
    ingress_max_in_flight: int = 32
    ingress_address_failures: int = 30  # failed requests per address (an IPv6 /64) a minute, per process
    ingress_body_cap: int = Field(default=MAX_BODY_CAP, ge=1, le=MAX_BODY_CAP)
    ingress_body_deadline_s: float = 10

    @field_validator("ingress_key_b64")
    @classmethod
    def _key(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except binascii.Error:
            decoded = b""
        if len(decoded) != 32:
            raise ValueError("DEWPOINT_INGRESS_KEY_B64 must be 32 bytes, base64-encoded (openssl rand -base64 32)")
        return value

    @field_validator("ingress_trusted_proxies")
    @classmethod
    def _proxies(cls, value: str) -> str:
        parse_proxies(value)
        return value
