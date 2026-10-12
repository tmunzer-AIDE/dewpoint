# SPDX-License-Identifier: Apache-2.0
"""How every process connects to Temporal (engine 2b spec §10.4; 2b-4b M4, the owner's rulings on its design):
verified TLS always, the server's certificate checked against the configured CA or the system roots; a client
authenticated by exactly one of mTLS (`DEWPOINT_TEMPORAL_TLS_CERT` and `…_KEY`) or a JWT bearer token read from a file
(`DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE`); plaintext only with `DEWPOINT_TEMPORAL_INSECURE_DEV` in a deployment
recorded as development, warned about. Anything else is refused before a connection is tried, naming the setting,
never a value."""

from pathlib import Path

import pytest
import structlog
from temporalio.service import TLSConfig

from dewpoint.core import temporal_connect
from dewpoint.core.temporal_connect import TemporalConfigError, TemporalConnection, options

DEVELOPMENT, PRODUCTION = "development", "production"


def files(tmp_path: Path, **contents: bytes) -> dict[str, str]:
    paths = {}
    for name, body in contents.items():
        path = tmp_path / name
        path.write_bytes(body)
        paths[name] = str(path)
    return paths


def test_plaintext_is_for_a_development_deployment_only_and_warned_about() -> None:
    with structlog.testing.capture_logs() as logs:
        assert options(TemporalConnection(temporal_insecure_dev=True), DEVELOPMENT) == {"tls": False}
    assert [entry["event"] for entry in logs] == ["temporal_insecure_dev"]
    with pytest.raises(TemporalConfigError, match="DEWPOINT_TEMPORAL_INSECURE_DEV"):
        options(TemporalConnection(temporal_insecure_dev=True), PRODUCTION)


def test_plaintext_with_any_tls_setting_is_refused(tmp_path: Path) -> None:
    given = files(tmp_path, ca=b"ca")
    with pytest.raises(TemporalConfigError, match="DEWPOINT_TEMPORAL_INSECURE_DEV"):
        options(TemporalConnection(temporal_insecure_dev=True, temporal_tls_ca=given["ca"]), DEVELOPMENT)


def test_mtls_verifies_the_server_against_the_ca_and_presents_the_certificate(tmp_path: Path) -> None:
    given = files(tmp_path, ca=b"ca", cert=b"cert", key=b"key")
    found = options(TemporalConnection(temporal_tls_ca=given["ca"], temporal_tls_cert=given["cert"],
                                       temporal_tls_key=given["key"], temporal_tls_server_name="temporal.test"),
                    PRODUCTION)  # fmt: skip
    assert found == {"tls": TLSConfig(server_root_ca_cert=b"ca", domain="temporal.test", client_cert=b"cert",
                                      client_private_key=b"key")}  # fmt: skip


def test_a_bearer_token_goes_over_verified_tls_without_a_client_certificate(tmp_path: Path) -> None:
    given = files(tmp_path, token=b"header.claims.signature\n")
    found = options(TemporalConnection(temporal_bearer_token_file=given["token"]), PRODUCTION)
    assert found == {"tls": TLSConfig(), "api_key": "header.claims.signature"}  # the system roots verify the server


@pytest.mark.parametrize("given", [
    {"temporal_tls_cert": "cert"},  # a certificate without its key
    {"temporal_tls_key": "key"},  # a key without its certificate
    {"temporal_tls_cert": "cert", "temporal_tls_key": "key", "temporal_bearer_token_file": "token"},  # both modes
    {},  # no client authentication at all
    {"temporal_tls_ca": "ca"},  # a CA alone authenticates no client
])  # fmt: skip
def test_exactly_one_client_authentication_is_required(tmp_path: Path, given: dict[str, str]) -> None:
    paths = files(tmp_path, ca=b"ca", cert=b"cert", key=b"key", token=b"token")
    with pytest.raises(TemporalConfigError, match="client authentication"):
        options(TemporalConnection(**{k: paths[v] for k, v in given.items()}), PRODUCTION)


@pytest.mark.parametrize("setting", ["temporal_tls_ca", "temporal_bearer_token_file"])
def test_an_unreadable_file_is_refused_naming_its_setting(tmp_path: Path, setting: str) -> None:
    given = {"temporal_bearer_token_file": str(files(tmp_path, token=b"token")["token"]),
             setting: str(tmp_path / "missing")}  # fmt: skip
    with pytest.raises(TemporalConfigError, match=f"DEWPOINT_{setting.upper()}") as refused:
        options(TemporalConnection(**given), PRODUCTION)
    assert "missing" not in str(refused.value)  # names the setting, never its value


def test_an_empty_token_file_is_refused(tmp_path: Path) -> None:
    given = files(tmp_path, token=b"\n")
    with pytest.raises(TemporalConfigError, match="DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE"):
        options(TemporalConnection(temporal_bearer_token_file=given["token"]), PRODUCTION)


async def test_a_token_replaced_in_its_file_is_set_on_the_live_client(tmp_path: Path) -> None:
    """What Dewpoint does; whether the SDK then sends the new token on the open connection is verified against the
    D12 server (DW.3) before restart-free rotation is promised (the owner's ruling)."""
    given = files(tmp_path, token=b"first")

    class Live:
        api_key: str | None = "first"

    client = Live()
    assert not await temporal_connect.refresh_token(client, given["token"])  # type: ignore[arg-type]
    Path(given["token"]).write_bytes(b"second\n")  # noqa: ASYNC240
    assert await temporal_connect.refresh_token(client, given["token"])  # type: ignore[arg-type]
    assert client.api_key == "second"
    Path(given["token"]).write_bytes(b"")  # noqa: ASYNC240  # a half-written or emptied file never replaces a token
    with structlog.testing.capture_logs() as logs:
        assert not await temporal_connect.refresh_token(client, given["token"])  # type: ignore[arg-type]
    assert client.api_key == "second" and [entry["event"] for entry in logs] == ["temporal_token_unreadable"]


def test_every_process_connects_through_this_helper_alone() -> None:
    """A `Client.connect` elsewhere would skip §10.4's checks: plaintext, or no client authentication."""
    source = Path(__file__).parents[2] / "src" / "dewpoint"
    found = sorted(str(path.relative_to(source)) for path in source.rglob("*.py")
                   if "Client.connect(" in path.read_text() and path.name != "temporal_connect.py")  # fmt: skip
    assert found == []


def test_an_empty_setting_is_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The review's M1: `DEWPOINT_TEMPORAL_TLS_CERT=` and `…_KEY=` (empty, as a template leaves them) authenticate no
    client: with nothing else, refused at startup, never a server-only TLS connection that fails later."""
    monkeypatch.setenv("DEWPOINT_TEMPORAL_TLS_CERT", "")
    monkeypatch.setenv("DEWPOINT_TEMPORAL_TLS_KEY", " ")
    with pytest.raises(TemporalConfigError, match="client authentication"):
        options(TemporalConnection(), PRODUCTION)
    token = files(tmp_path, token=b"a.jwt.token")["token"]
    monkeypatch.setenv("DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE", token)
    assert options(TemporalConnection(), PRODUCTION)["api_key"] == "a.jwt.token"  # the empty pair isn't a second mode
