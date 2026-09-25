# SPDX-License-Identifier: Apache-2.0
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=".env", extra="ignore")

    database_url: str
    kek_b64: str = Field(description="Base64 32-byte key-encryption key")
    kek_id: str = "env-1"
    kek_previous_b64: str | None = None  # set only during a KEK rollout (see docs/operations/key-rotation.md)
    kek_previous_id: str | None = None
    public_origin: str = Field(description="Browser origin, e.g. https://dewpoint.example.com")
    rp_id: str | None = None  # WebAuthn RP ID; defaults to host of public_origin
    mfa_required: bool = True
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5  # per account and per MFA user
    login_ip_max_failures: int = 50  # per source IP: higher, because offices share NAT addresses
    login_lockout_minutes: int = 15
    audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
    audit_anchor_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
