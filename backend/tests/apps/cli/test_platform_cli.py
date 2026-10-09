# SPDX-License-Identifier: Apache-2.0
"""`dewpoint platform init-environment` records what this deployment is, once (engine 2b spec §2.1). Compose's migrate
step runs it; running it again with the same values changes nothing."""

import base64

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.core.config import get_settings


@pytest.fixture
def owner_env(monkeypatch: pytest.MonkeyPatch, pg_url: str) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", pg_url)
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    monkeypatch.delenv("DEWPOINT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("DEWPOINT_TEMPORAL_NAMESPACE", raising=False)
    get_settings.cache_clear()


@pytest.mark.usefixtures("owner_env")
def test_a_deployment_is_production_unless_told_otherwise_and_records_it_once() -> None:
    first = CliRunner().invoke(cli.app, ["platform", "init-environment"])
    again = CliRunner().invoke(cli.app, ["platform", "init-environment", "--environment", "production"])
    assert first.exit_code == 0
    assert first.output == "this deployment is production, with the Temporal namespace `default`\n"
    assert again.exit_code == 0
    other = CliRunner().invoke(cli.app, ["platform", "init-environment", "--environment", "development"])
    assert other.exit_code == 2
    assert "recorded as production" in other.output


@pytest.mark.usefixtures("owner_env")
def test_a_development_setup_says_so_with_its_own_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_ENVIRONMENT", "development")
    get_settings.cache_clear()
    result = CliRunner().invoke(cli.app, ["platform", "init-environment", "--temporal-namespace", "dewpoint-ci"])
    assert (result.exit_code, result.output) == (
        0,
        "this deployment is development, with the Temporal namespace `dewpoint-ci`\n",
    )


PW = "violet-otter-canyon-42"
SAID = "Measured on this deployment's Temporal."


async def test_the_capacity_command_signs_in_through_the_api_and_its_change_names_the_admin(
    client, owner_sessionmaker, development_deployment
) -> None:  # fmt: skip
    """The owner's ruling on the 2b-4b M3 checkpoint 3 (D11): the command signs in as the platform admin, password
    then second factor, and asks the API, which audits the change with that admin's id."""
    import time
    from urllib.parse import parse_qs, urlparse

    import pyotp
    from sqlalchemy import text

    from dewpoint.core.auth.users import create_user

    async with owner_sessionmaker() as s, s.begin():
        user = await create_user(s, email="ops@corp.test", password=PW)
        await s.execute(text("update users set is_platform_admin = true where id = :u"), {"u": user.id})
    csrf = (await client.post("/api/v1/auth/login", json={"email": "ops@corp.test", "password": PW})).json()[
        "csrf_token"
    ]
    uri = (await client.post("/api/v1/auth/mfa/totp/enroll", headers={"X-CSRF-Token": csrf})).json()["otpauth_uri"]
    totp = pyotp.TOTP(parse_qs(urlparse(uri).query)["secret"][0])
    await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": totp.now()}, headers={"X-CSRF-Token": csrf})
    client.cookies.clear()  # the command signs in on its own
    answer = await cli.capacity_via_api(client, email="ops@corp.test", password=PW, code=totp.at(time.time() + 30),
                                        change={"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 300},
                                        attestation=SAID)  # fmt: skip
    assert answer == {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 300, "limit": 1200, "outstanding": 0,
                      "active_tenants": 0, "problems": []}  # fmt: skip
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select actor_id from audit_log where action = 'platform.ingress_capacity.set'"))
        assert list(found.scalars()) == [user.id]
    with pytest.raises(cli.CapacityApiError, match="invalid_credentials"):
        await cli.capacity_via_api(client, email="ops@corp.test", password="wrong-wrong-wrong", code="000000",
                                   change={"unset": True}, attestation=SAID)  # fmt: skip


def test_the_command_sends_only_what_it_was_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value left out keeps what it was: the command sends only the options given, or `unset`."""
    sent: list[dict[str, object]] = []

    async def asked(_client: object, **kwargs: object) -> dict[str, object]:
        sent.append(kwargs)
        return {"starts_per_s": 8.0, "headroom": 0.5, "queue_wait_s": 600, "limit": 2400, "outstanding": 0,
                "active_tenants": 0, "problems": []}  # fmt: skip

    monkeypatch.setattr(cli, "capacity_via_api", asked)
    base = ["platform", "set-ingress-capacity", "--api", "https://dewpoint.test", "--email", "ops@corp.test",
            "--attestation", SAID]  # fmt: skip
    wait = CliRunner().invoke(cli.app, [*base, "--queue-wait-s", "600"], input=f"{PW}\n123456\n")
    assert wait.exit_code == 0, wait.output
    assert wait.output.endswith("ingress capacity: 8.0 starts a second measured, 0.5 of them for ingress, a 600 s "
                                "wait: the deployment's outstanding work at most 2400 requests\n")  # fmt: skip
    unset = CliRunner().invoke(cli.app, [*base, "--unset"], input=f"{PW}\n123456\n")
    assert unset.exit_code == 0, unset.output
    assert [(k["change"], k["password"], k["code"], k["attestation"]) for k in sent] == [
        ({"queue_wait_s": 600}, PW, "123456", SAID), ({"unset": True}, PW, "123456", SAID),
    ]  # fmt: skip
    nothing = CliRunner().invoke(cli.app, base)
    assert nothing.exit_code == 2 and "--unset" in nothing.output
