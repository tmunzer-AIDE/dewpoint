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
    reauth_minutes: int = 5  # adding/replacing a factor from an active session needs a second factor this recent
    totp_pending_minutes: int = 10  # an unconfirmed new TOTP secret expires after this
    passkey_options_per_ip: int = 30  # anonymous passkey challenges per source IP per 15-minute window
    webauthn_challenges_max: int = 10_000  # outstanding (unexpired) challenges across the platform
    max_request_body_bytes: int = 1_048_576  # counted as received: chunked bodies have no Content-Length
    max_run_duration_days: int = 30  # spec §6: whole logical run, including continue-as-new and waits
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    cel_socket: str | None = None  # the cel-evaluator's socket; a worker without one serves no CEL queue
    cel_max_concurrent: int = 2  # the evaluator's N (docs/operations/cel-evaluator.md)
    cel_schedule_to_start_s: float = 600  # spec §5.7: no evaluator for a profile after this: cel_profile_unavailable
    audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
    audit_anchor_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
