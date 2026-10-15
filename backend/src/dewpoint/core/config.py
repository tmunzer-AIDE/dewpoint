# SPDX-License-Identifier: Apache-2.0
from functools import lru_cache

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from dewpoint.core.temporal_settings import TemporalConnection


class Settings(TemporalConnection):  # Temporal's §10.4 security settings with the others
    model_config = SettingsConfigDict(
        env_prefix="DEWPOINT_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: str
    kek_b64: str = Field(description="Base64 32-byte key-encryption key")
    kek_id: str = "env-1"
    kek_previous_b64: str | None = None  # set only during a KEK rollout (see docs/operations/key-rotation.md)
    kek_previous_id: str | None = None
    # Sealing endpoint secrets (engine 2b spec §8.3): ingress and the API only; never a tenant's data key.
    ingress_key_b64: str | None = None
    ingress_key_id: str = "ingress-1"
    # Set only during an ingress key rollout (see docs/operations/key-rotation.md).
    ingress_key_previous_b64: str | None = None
    ingress_key_previous_id: str | None = None
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
    # CSV uploads and CSV starts at once, per API process: each may hold about 235 MiB (2b-4b M3, `apps/csv_slots.py`)
    csv_concurrency: int = Field(default=2, ge=1)
    max_run_duration_days: int = 30  # spec §6: whole logical run, including continue-as-new and waits
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    # What `dewpoint platform init-environment` records, once (engine 2b spec §2.1): production unless a development
    # setup says otherwise. Every process that talks to Temporal checks its namespace against the record.
    environment: str = "production"
    cel_socket: str | None = None  # the cel-evaluator's socket; a worker without one serves no CEL queue
    cel_max_concurrent: int = 2  # the evaluator's N (docs/operations/cel-evaluator.md)
    cel_schedule_to_start_s: float = 600  # spec §5.7: no evaluator for a profile after this: cel_profile_unavailable
    worker_shutdown_grace_s: float = 30  # a stopping worker lets running attempts finish this long, then cancels them
    # One build at a time (Compose): the worker makes its build the one new runs start on, once it polls. Leave it off
    # where builds overlap, and promote each with `dewpoint deployment set-current` (docs/operations/deployment.md).
    worker_set_current: bool = False
    # D12's start check's two denial reasons are told apart only once they're confirmed to reach the SDK end to end on
    # D12 (the upgrade barrier's revision 17.1): until then every PERMISSION_DENIED on a start is uncertain.
    start_check_reasons_confirmed: bool = False
    audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
    audit_anchor_path: str | None = None
    # The platform's audit retention (engine 2b spec §10.2): `dewpoint audit prune` deletes older entries, never newer
    # than 30 days, and only in a development deployment until an off-host anchor sink exists (#3).
    audit_retention_days: int = Field(default=400, ge=30)
    # D6's off-host anchor sink (#3; 2b-4b M4): an S3 bucket with Object Lock in compliance mode. The anchor writer's
    # credentials are put-only, the verifier's and the monitor's read-only, each from its own environment (AWS's own
    # variables or profile), none on the database host.
    audit_s3_bucket: str | None = None  # set: anchors go to this bucket, not DEWPOINT_AUDIT_ANCHOR_PATH's file
    audit_s3_prefix: str = "dewpoint/"
    audit_s3_endpoint_url: str | None = None  # another S3-compatible server (D6's proof: the pinned MinIO)
    audit_s3_region: str | None = None
    audit_signing_key_id: str = "audit-1"  # signed into each anchor; its public key kept by this id (rotation)
    audit_public_keys: str | None = None  # JSON {key id: base64 raw Ed25519 public key}: what verifies, alone
    # The bucket's lock covers the audit retention plus this: a restored backup's entries stay verifiable (D6.9).
    backup_retention_days: int = Field(default=35, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
