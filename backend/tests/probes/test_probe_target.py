# SPDX-License-Identifier: Apache-2.0
"""Where the probes find Temporal (2b-4b M4): a CLI dev server of their own, as before, unless
`DEWPOINT_PROBE_TEMPORAL_ADDRESS` names an external server (the D12 server), reached with §10.4's security from the
`DEWPOINT_TEMPORAL_*` settings, never in plaintext. Runs in the normal suite: nothing here starts a server."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from temporalio.service import TLSConfig
from temporalio.testing import WorkflowEnvironment

from dewpoint.core import temporal_connect
from dewpoint.core.temporal_connect import TemporalConfigError
from tests.support import temporal


async def test_without_an_external_address_a_probe_starts_its_own_dev_server(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[dict[str, Any]] = []

    class Local:
        async def __aenter__(self) -> str:
            return "the dev server"

        async def __aexit__(self, *exc: object) -> None: ...

    async def start_local(**kwargs: Any) -> Local:
        started.append(kwargs)
        return Local()

    monkeypatch.delenv("DEWPOINT_PROBE_TEMPORAL_ADDRESS", raising=False)
    monkeypatch.setattr(temporal, "start_local", start_local)
    async with temporal.probe_temporal(data_converter="codec") as environment:
        assert environment == "the dev server"
    assert started == [{"data_converter": "codec"}]


async def test_an_external_address_is_reached_with_verified_tls_and_its_client_authentication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # fmt: skip
    token = tmp_path / "token"
    token.write_bytes(b"a.jwt.token")  # noqa: ASYNC240
    connected: dict[str, Any] = {}

    async def connect(address: str, **kwargs: Any) -> str:
        connected.update(kwargs, address=address)
        return "a client"

    @asynccontextmanager
    async def never(**kwargs: Any) -> AsyncIterator[None]:
        raise AssertionError("started a dev server")
        yield

    monkeypatch.setenv("DEWPOINT_PROBE_TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE", str(token))
    monkeypatch.setattr(temporal_connect.Client, "connect", connect)
    monkeypatch.setattr(WorkflowEnvironment, "from_client", classmethod(lambda cls, client: f"over {client}"))
    monkeypatch.setattr(temporal, "start_local", never)
    async with temporal.probe_temporal(data_converter="codec") as environment:
        assert environment == "over a client"
    assert connected == {"address": "temporal.test:7233", "namespace": "default", "tls": TLSConfig(),
                         "api_key": "a.jwt.token", "data_converter": "codec"}  # fmt: skip


async def test_an_external_server_is_never_reached_in_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_PROBE_TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("DEWPOINT_TEMPORAL_INSECURE_DEV", "true")
    with pytest.raises(TemporalConfigError, match="DEWPOINT_TEMPORAL_INSECURE_DEV"):
        async with temporal.probe_temporal():
            pass
