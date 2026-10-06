# SPDX-License-Identifier: Apache-2.0
"""The answers of the routes the web client uses, as models: they name each shape in the OpenAPI schema the client is
generated from (sub-project 4, B1). Each forbids extra keys, so an answer that drifts from its model fails its tests
instead of silently losing a field. A route whose answer omits a key (a tenant's `role`, a connection type's
`clouds`) uses `response_model_exclude_unset`, so the JSON stays exactly what it was."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

SessionState = Literal["mfa_pending", "enroll_required", "active"]
Role = Literal["owner", "admin", "editor", "operator", "viewer"]


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StateOut(_Answer):
    state: SessionState
    csrf_token: str


class CsrfOut(_Answer):
    csrf_token: str


class SessionUserOut(_Answer):
    id: str
    email: str
    is_platform_admin: bool


class SessionOut(_Answer):
    user: SessionUserOut
    state: SessionState
    auth_methods: list[str]
    csrf_token: str


class TotpEnrollOut(_Answer):
    otpauth_uri: str


class RecoveryCodesOut(_Answer):
    recovery_codes: list[str]
    state: SessionState
    csrf_token: str


class PasskeyOut(_Answer):
    id: str
    name: str
    created_at: str
    last_used_at: str | None


class PasskeyOptionsOut(_Answer):
    options: dict[str, Any]  # WebAuthn's own options, passed to the browser as they are
    challenge_id: str


class TenantOut(_Answer):
    id: str
    name: str
    slug: str
    require_passkey: bool
    role: Role | None = None  # absent where the caller holds no role


class MemberOut(_Answer):
    user_id: str
    email: str
    role: Role


class MemberRoleOut(_Answer):
    user_id: str
    role: Role


class ConnectionTypeOut(_Answer):
    key: str
    label: str
    config_schema: dict[str, Any]
    secret_fields: list[str]
    clouds: dict[str, str] | None = None  # Mist's clouds, by key; absent for other types


class ConnectionOut(_Answer):
    id: str
    type: str
    name: str
    revision: int
    config: dict[str, Any]
    secret_set: bool
    status: Literal["unverified", "ok", "error"]
    status_detail: str
    privilege: str | None
    last_verified_at: str | None


class PlatformStatusOut(_Answer):
    environment: Literal["production", "development"] | None
    production_runs: bool
