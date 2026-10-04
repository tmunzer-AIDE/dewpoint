# SPDX-License-Identifier: Apache-2.0
"""Ingress's settings come from its own environment only: never a `.env` file, which in a shared checkout or image may
hold the key-encryption key ingress must never read (engine 2b spec §8.3)."""

import base64

import pytest
from pydantic import ValidationError

from dewpoint.apps.ingress.config import IngressSettings


def test_a_dotenv_file_is_never_read(tmp_path, monkeypatch) -> None:
    for name in ("DEWPOINT_DATABASE_URL", "DEWPOINT_INGRESS_KEY_B64"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "DEWPOINT_DATABASE_URL=postgresql+asyncpg://x@db/x\n"
        f"DEWPOINT_INGRESS_KEY_B64={base64.b64encode(b'i' * 32).decode()}\n"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        IngressSettings()


def test_its_environment_is_read_and_a_bad_proxy_refused(monkeypatch) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://x@db/x")
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(b"i" * 32).decode())
    monkeypatch.setenv("DEWPOINT_INGRESS_TRUSTED_PROXIES", "172.18.0.0/16")
    assert IngressSettings().ingress_trusted_proxies == "172.18.0.0/16"
    monkeypatch.setenv("DEWPOINT_INGRESS_TRUSTED_PROXIES", "172.18.0.1/16")
    with pytest.raises(ValidationError, match="DEWPOINT_INGRESS_TRUSTED_PROXIES"):
        IngressSettings()


@pytest.mark.parametrize(
    ("cap", "valid"), [(5 * 1024 * 1024, True), (1, True), (5 * 1024 * 1024 + 1, False), (0, False)]
)
def test_the_global_body_cap_is_at_most_5_mib(monkeypatch, cap: int, valid: bool) -> None:
    """The database's bursts are sized to cover a body this large (the owner's M2 review): a larger cap set in the
    configuration would make a body past a small endpoint limit a 429 for ever."""
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://x@db/x")
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(b"i" * 32).decode())
    monkeypatch.setenv("DEWPOINT_INGRESS_BODY_CAP", str(cap))
    if valid:
        assert IngressSettings().ingress_body_cap == cap
    else:
        with pytest.raises(ValidationError, match="ingress_body_cap"):
            IngressSettings()


@pytest.mark.parametrize("key", ["", "not base64!", base64.b64encode(b"short").decode()])
def test_an_ingress_key_that_isnt_32_bytes_of_base64_is_refused_by_name(monkeypatch, key: str) -> None:
    """Compose passes an empty key when none is set: ingress says which setting to fix, never quoting a value."""
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://x@db/x")
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", key)
    with pytest.raises(ValidationError, match="DEWPOINT_INGRESS_KEY_B64") as refused:
        IngressSettings()
    assert not key or key not in str(refused.value)
