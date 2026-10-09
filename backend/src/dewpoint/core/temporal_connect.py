# SPDX-License-Identifier: Apache-2.0
"""How every process connects to Temporal (engine 2b spec §10.4; 2b-4b M4, the owner's rulings on its design).

Verified TLS always: the server's certificate is checked against `DEWPOINT_TEMPORAL_TLS_CA`, or the system roots when
it's unset. The client is authenticated by exactly one of mTLS (`DEWPOINT_TEMPORAL_TLS_CERT` and `…_KEY`; production's
mode) or a JWT bearer token read from `DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE`, validated by the server's claim mapper (not
a Temporal Cloud API key). Plaintext only with `DEWPOINT_TEMPORAL_INSECURE_DEV`, in a deployment recorded as
development, and warned about. Anything else is refused before a connection is tried; a refusal names the setting,
never its value."""

import asyncio
from pathlib import Path
from typing import Any

import structlog
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio.client import Client
from temporalio.service import TLSConfig

log = structlog.get_logger("dewpoint.temporal")
DEVELOPMENT = "development"
TOKEN_REFRESH_S = 60.0  # a long-running process rereads its token file this often
TLS_SETTINGS = ("temporal_tls_ca", "temporal_tls_server_name", "temporal_tls_cert", "temporal_tls_key",
                "temporal_bearer_token_file")  # fmt: skip


class TemporalConfigError(Exception):
    """This process's Temporal settings are refused: it must not connect."""


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


def _setting(name: str) -> str:
    return f"DEWPOINT_{name.upper()}"


def _read(path: str, name: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        raise TemporalConfigError(f"{_setting(name)} can't be read.") from None


def _token(path: str) -> str:
    token = _read(path, "temporal_bearer_token_file").decode("utf-8", errors="replace").strip()
    if not token:
        raise TemporalConfigError(f"{_setting('temporal_bearer_token_file')} holds no token.")
    return token


def options(settings: TemporalConnection, recorded_environment: str) -> dict[str, Any]:
    """`Client.connect`'s `tls` (and `api_key`) for these settings, in a deployment recorded as `recorded_environment`.
    Raises TemporalConfigError when they're refused."""
    if settings.temporal_insecure_dev:
        if recorded_environment != DEVELOPMENT:
            raise TemporalConfigError(f"{_setting('temporal_insecure_dev')} is for a deployment recorded as "
                                      "development only.")  # fmt: skip
        if any(getattr(settings, name) is not None for name in TLS_SETTINGS):
            raise TemporalConfigError(f"{_setting('temporal_insecure_dev')} can't be combined with TLS settings or a "
                                      "bearer token.")  # fmt: skip
        log.warning("temporal_insecure_dev")
        return {"tls": False}
    mtls = settings.temporal_tls_cert is not None, settings.temporal_tls_key is not None
    bearer = settings.temporal_bearer_token_file is not None
    if not (mtls == (True, True) and not bearer or mtls == (False, False) and bearer):
        raise TemporalConfigError(
            "Temporal needs exactly one client authentication: mTLS (DEWPOINT_TEMPORAL_TLS_CERT and "
            "DEWPOINT_TEMPORAL_TLS_KEY) or a bearer token (DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE)."
        )
    tls = TLSConfig(
        server_root_ca_cert=_read(settings.temporal_tls_ca, "temporal_tls_ca") if settings.temporal_tls_ca else None,
        domain=settings.temporal_tls_server_name,
        client_cert=_read(settings.temporal_tls_cert, "temporal_tls_cert") if settings.temporal_tls_cert else None,
        client_private_key=_read(settings.temporal_tls_key, "temporal_tls_key") if settings.temporal_tls_key else None,
    )
    if settings.temporal_bearer_token_file is not None:
        return {"tls": tls, "api_key": _token(settings.temporal_bearer_token_file)}
    return {"tls": tls}


async def connect(settings: Any, recorded_environment: str, **kwargs: Any) -> Client:
    """A client for this process's `temporal_address` and `temporal_namespace`, with its §10.4 security; `kwargs` are
    `Client.connect`'s others (a data converter, an identity, a retry policy)."""
    found = options(settings, recorded_environment)
    return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace, **found, **kwargs)


async def refresh_token(client: Client, path: str) -> bool:
    """The token file reread, and a new token set on the live client: whether it changed. An unreadable or empty file
    keeps the token in use (a rotation half-written), logged."""
    try:
        token = _token(path)
    except TemporalConfigError:
        log.warning("temporal_token_unreadable")
        return False
    if token == client.api_key:
        return False
    client.api_key = token
    return True


async def keep_token_fresh(client: Client, settings: TemporalConnection) -> None:
    """A long-running process's token, reread every TOKEN_REFRESH_S (bearer mode only; returns at once otherwise)."""
    if settings.temporal_bearer_token_file is None:
        return
    while True:
        await asyncio.sleep(TOKEN_REFRESH_S)
        await refresh_token(client, settings.temporal_bearer_token_file)
