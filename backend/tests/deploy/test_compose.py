# SPDX-License-Identifier: Apache-2.0
"""Compose's wiring (`deploy/compose/docker-compose.yml`), rendered as Compose renders it for a `.env` whose Temporal
namespace isn't the default."""

import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).parents[3] / "deploy" / "compose" / "docker-compose.yml"
ENV = {
    "POSTGRES_PASSWORD": "owner-pw",
    "DEWPOINT_API_DB_PASSWORD": "api-pw",
    "DEWPOINT_ADMIN_DB_PASSWORD": "admin-pw",
    "DEWPOINT_AUDITOR_DB_PASSWORD": "auditor-pw",
    "DEWPOINT_WORKER_DB_PASSWORD": "worker-pw",
    "DEWPOINT_DISPATCH_DB_PASSWORD": "dispatch-pw",
    "DEWPOINT_INGRESS_DB_PASSWORD": "ingress-pw",
    "DEWPOINT_RETENTION_DB_PASSWORD": "retention-pw",
    "DEWPOINT_KEK_B64": "k" * 44,
    "DEWPOINT_AUDIT_SIGNING_KEY_B64": "s" * 44,
    "DEWPOINT_TEMPORAL_NAMESPACE": "dewpoint-ci",
}


def rendered(value: str) -> str:
    """Compose's interpolation: `${VAR}`, `${VAR:-default}`, `${VAR:?message}`, and `$$` for a literal `$`."""

    def one(m: re.Match[str]) -> str:
        name, op, arg = m.group(1), m.group(2), m.group(3)
        if name is None:
            return "$"
        value = ENV.get(name, "")
        if not value and op == ":?":
            raise KeyError(f"{name}: {arg}")
        return arg if not value and op == ":-" else value

    return re.sub(r"\$\$|\$\{(\w+)(?:(:-|:\?)([^}]*))?\}", one, value)


def service(name: str) -> dict[str, Any]:
    compose: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    return compose["services"][name]  # type: ignore[no-any-return]


def environment(name: str) -> dict[str, str]:
    return {k: rendered(str(v)) for k, v in service(name)["environment"].items()}


def test_the_migrate_step_records_the_namespace_the_worker_checks() -> None:
    """Review (2b-1a): the migrate step records the deployment's Temporal namespace once, for good, and the worker exits
    2 unless its own matches it. Both take it from the same `.env` setting."""
    namespaces = [environment(name).get("DEWPOINT_TEMPORAL_NAMESPACE") for name in ("migrate", "worker")]
    assert namespaces == ["dewpoint-ci", "dewpoint-ci"]


def test_the_migrate_step_gives_tenants_keys_as_the_key_admin() -> None:
    """Review (2b-1a): `keys ensure-tenants` lists every tenant under row-level security as `dewpoint_admin`, the key
    administration role, never as an owner that bypasses it (a managed database's owner may not)."""
    command = rendered(service("migrate")["command"][-1])
    assert "DEWPOINT_DATABASE_URL=$DEWPOINT_ADMIN_DATABASE_URL dewpoint keys ensure-tenants" in command
    assert environment("migrate")["DEWPOINT_ADMIN_DATABASE_URL"] == (
        "postgresql+asyncpg://dewpoint_admin_login:admin-pw@postgres/dewpoint"
    )


OVERRIDE = COMPOSE.with_name("docker-compose.dev.yml")
CI = COMPOSE.parents[2] / ".github" / "workflows" / "ci.yml"


def test_the_dispatcher_runs_as_the_dispatch_role_on_the_recorded_namespace() -> None:
    """Engine 2b spec §7.3, §14: `dewpoint dispatcher` (with its reconciler) logs in as `dewpoint_dispatch`, and checks
    the namespace the migrate step recorded before it connects to Temporal (§2.1)."""
    dispatcher, env = service("dispatcher"), environment("dispatcher")
    assert dispatcher["command"] == ["dewpoint", "dispatcher"]
    assert env["DEWPOINT_DATABASE_URL"] == "postgresql+asyncpg://dewpoint_dispatch_login:dispatch-pw@postgres/dewpoint"
    assert (env["DEWPOINT_TEMPORAL_ADDRESS"], env["DEWPOINT_TEMPORAL_NAMESPACE"]) == ("temporal:7233", "dewpoint-ci")
    assert dispatcher["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}
    assert dispatcher["depends_on"]["temporal"] == {"condition": "service_healthy"}


def test_a_stopping_dispatcher_outlasts_a_starts_deadline() -> None:
    """A start in flight when the dispatcher is stopped gets its answer, or its deadline, before the process goes."""
    from dewpoint.apps.dispatcher.dispatch import START_DEADLINE

    grace = service("dispatcher")["stop_grace_period"]
    assert grace.endswith("s") and int(grace[:-1]) > START_DEADLINE.total_seconds()


def test_plain_compose_is_production_and_the_development_override_initializes_development() -> None:
    """§2.1: ordinary Compose is `production`, and gated; CI and local development opt in through their own override,
    which changes nothing else."""
    assert environment("migrate")["DEWPOINT_ENVIRONMENT"] == "production"
    override: dict[str, Any] = yaml.safe_load(OVERRIDE.read_text())
    assert override["services"] == {"migrate": {"environment": {"DEWPOINT_ENVIRONMENT": "development"}}}


def test_ci_runs_every_compose_command_with_the_development_override() -> None:
    e2e = yaml.safe_load(CI.read_text())["jobs"]["e2e"]
    assert e2e["env"]["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.dev.yml"


def test_a_dispatcher_that_exits_is_restarted() -> None:
    """The whole-branch review: a dispatcher process that ends (whatever the cause) comes back, so queued runs keep
    starting once what stopped it recovers."""
    assert service("dispatcher")["restart"] == "unless-stopped"


def test_the_database_init_makes_an_ingress_login_from_its_password() -> None:
    """2b-3b: ingress logs in as `dewpoint_ingress_login`, which a fresh database's init creates in the group role, from
    `DEWPOINT_INGRESS_DB_PASSWORD`; CI writes one like every other login's."""
    assert environment("postgres")["DEWPOINT_INGRESS_DB_PASSWORD"] == "ingress-pw"
    init = (COMPOSE.parent / "initdb" / "10-roles.sh").read_text()
    assert '-v ingress_pw="$DEWPOINT_INGRESS_DB_PASSWORD"' in init
    assert "CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD :'ingress_pw' IN ROLE dewpoint_ingress;" in init
    assert "rolname='dewpoint_ingress') THEN CREATE ROLE dewpoint_ingress NOLOGIN" in init
    ci = (COMPOSE.parents[2] / ".github" / "workflows" / "ci.yml").read_text()
    assert 'echo "DEWPOINT_INGRESS_DB_PASSWORD=$(openssl rand -hex 16)"' in ci
    assert "DEWPOINT_INGRESS_DB_PASSWORD=" in (COMPOSE.parent / ".env.example").read_text()


def test_the_database_init_makes_a_retention_login_from_its_password() -> None:
    """2b-4 (engine 2b spec §10.3): retention logs in as `dewpoint_retention_login`, which a fresh database's init
    creates in the group role, from `DEWPOINT_RETENTION_DB_PASSWORD`; CI writes one like every other login's."""
    assert environment("postgres")["DEWPOINT_RETENTION_DB_PASSWORD"] == "retention-pw"
    init = (COMPOSE.parent / "initdb" / "10-roles.sh").read_text()
    assert '-v retention_pw="$DEWPOINT_RETENTION_DB_PASSWORD"' in init
    assert "CREATE ROLE dewpoint_retention_login LOGIN PASSWORD :'retention_pw' IN ROLE dewpoint_retention;" in init
    assert "rolname='dewpoint_retention') THEN CREATE ROLE dewpoint_retention NOLOGIN" in init
    ci = (COMPOSE.parents[2] / ".github" / "workflows" / "ci.yml").read_text()
    assert 'echo "DEWPOINT_RETENTION_DB_PASSWORD=$(openssl rand -hex 16)"' in ci
    assert "DEWPOINT_RETENTION_DB_PASSWORD=" in (COMPOSE.parent / ".env.example").read_text()


def test_retention_runs_as_its_own_login_without_a_key_and_comes_back() -> None:
    """§10.3: `dewpoint retention` is its own process, as the only login that deletes retained data. It never decrypts
    anything, so it holds no key-encryption key; one that ends comes back, since the SLO needs a sweep a day."""
    retention = service("retention")
    assert retention["command"] == ["dewpoint", "retention"]
    env = environment("retention")
    assert env == {
        "DEWPOINT_DATABASE_URL": "postgresql+asyncpg://dewpoint_retention_login:retention-pw@postgres/dewpoint"
    }
    assert retention["restart"] == "unless-stopped" and "ports" not in retention
    assert retention["read_only"] is True and retention["cap_drop"] == ["ALL"]
    assert retention["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}


NGINX = Path(__file__).parents[3] / "deploy" / "docker" / "nginx.conf"
HOOKS_SUBNET = "172.31.255.248/29"


def test_ingress_runs_behind_its_profile_as_its_own_login_without_a_key_encryption_key() -> None:
    """2b-3b (engine 2b spec §8.3): ingress is a gated prototype until 2b-4, so plain Compose never starts it; the
    `ingress` profile does, and it still refuses to start unless the deployment is `development`. Its environment is its
    own (it refuses one holding the key-encryption key), its database login has no table privilege, and it publishes no
    port: it's reached through `web` only."""
    ingress = service("ingress")
    assert ingress["profiles"] == ["ingress"]
    assert ingress["command"] == ["dewpoint", "ingress", "--host", "0.0.0.0", "--port", "8001"]  # noqa: S104 - no port published
    env = environment("ingress")
    assert not [name for name in env if "KEK" in name]
    assert env["DEWPOINT_DATABASE_URL"] == "postgresql+asyncpg://dewpoint_ingress_login:ingress-pw@postgres/dewpoint"
    assert env["DEWPOINT_INGRESS_TRUSTED_PROXIES"] == HOOKS_SUBNET
    assert "ports" not in ingress and ingress["read_only"] is True and ingress["cap_drop"] == ["ALL"]
    assert ingress["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}


def test_web_reaches_ingress_on_a_network_of_their_own_whose_addresses_ingress_trusts() -> None:
    """Ruling 11: X-Forwarded-For is believed only from configured proxies. `web` and ingress share a small network
    (`hooks`), on which ingress is `hooks-ingress`; nginx proxies there, so the peer ingress sees is `web` on that
    network, the one range it trusts. nginx writes the client it recovered into X-Forwarded-For, never a client's own,
    and streams a body to ingress as it arrives (chunked ones too, over HTTP/1.1), so ingress's whole-body deadline and
    its requests-in-flight limit hold through it (the owner's M4 review); its own gap timeout matches."""
    compose: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    assert rendered(compose["networks"]["hooks"]["ipam"]["config"][0]["subnet"]) == HOOKS_SUBNET
    assert service("ingress")["networks"] == {"default": None, "hooks": {"aliases": ["hooks-ingress"]}}
    assert service("web")["networks"] == ["default", "hooks"]
    conf = NGINX.read_text()
    hooks = conf[conf.index("location /hooks/") :].split("}", 1)[0]
    assert "set $ingress http://hooks-ingress:8001;" in conf
    assert "proxy_pass $ingress;" in hooks
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in hooks
    assert "client_body_timeout 10s;" in hooks
    assert "proxy_request_buffering off;" in hooks and "proxy_http_version 1.1;" in hooks


def test_the_api_holds_the_ingress_key_only_when_one_is_set() -> None:
    """The API seals endpoints' secrets under the ingress key: without one it writes none (503), and plain Compose
    needs none."""
    env = environment("api")
    assert env["DEWPOINT_INGRESS_KEY_B64"] == "" and env["DEWPOINT_INGRESS_KEY_ID"] == "ingress-1"


def test_ci_runs_the_ingress_profile_and_proves_a_webhook_through_nginx() -> None:
    e2e = yaml.safe_load(CI.read_text())["jobs"]["e2e"]
    assert e2e["env"]["COMPOSE_PROFILES"] == "ingress"
    steps = {step.get("name", ""): step for step in e2e["steps"]}
    assert "DEWPOINT_INGRESS_KEY_B64=$(openssl rand -base64 32)" in steps["Write CI env"]["run"]
    proof = steps["A webhook through nginx and ingress (engine 2b spec §8.3, §12)"]
    assert proof["timeout-minutes"] == 5
    assert "http://127.0.0.1:8080/hooks/$endpoint" in proof["run"]
    assert "ci/ingress-proof.py" in proof["run"]
    assert 'test "$trickled" = 408' in proof["run"]  # a slow body's deadline holds through nginx


def _answer_408_after(sock: socket.socket, seconds: float) -> None:
    """A stand-in for nginx and ingress: a request's first bytes, then its 408 once the deadline passes, then the rest
    of the body read away before closing, as nginx does."""
    while True:
        conn, _ = sock.accept()
        try:
            conn.settimeout(5)
            conn.recv(4096)
            time.sleep(seconds)
            conn.sendall(b"HTTP/1.1 408 Request Timeout\r\ncontent-length: 0\r\nconnection: close\r\n\r\n")
            conn.shutdown(socket.SHUT_WR)
            conn.settimeout(1)
            while conn.recv(4096):
                pass
        except OSError:
            pass
        finally:
            conn.close()


def _trickle_check(port: int) -> str:
    """The CI step's trickled-body check, aimed at a local stand-in."""
    e2e = yaml.safe_load(CI.read_text())["jobs"]["e2e"]
    run = {step.get("name", ""): step for step in e2e["steps"]}[
        "A webhook through nginx and ingress (engine 2b spec §8.3, §12)"
    ]["run"]
    block = run[run.index("# A body trickled") : run.index("# Matched by the Compose dispatcher")]
    return "set -e\n" + block.replace("http://127.0.0.1:8080/hooks/$endpoint", f"http://127.0.0.1:{port}/hooks/x")


@pytest.mark.parametrize(("bound", "passes"), [("14", True), ("1", False)])
def test_cis_trickle_check_times_curl_even_where_sigpipe_is_ignored(bound: str, passes: bool) -> None:
    """PR #37's first CI run: GitHub's runner ignores SIGPIPE, so the trickle kept writing (and sleeping) after curl had
    its 408, and the step timed the whole trickle (about 60 s), not curl's answer. The check times curl itself, the
    trickle stops at its first failed write, and the bound still bites (1 s against a 2 s answer)."""
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(4)
    threading.Thread(target=_answer_408_after, args=(sock, 2.0), daemon=True).start()
    check = _trickle_check(sock.getsockname()[1])
    if bound != "14":
        assert "took <= 14" in check
        check = check.replace("took <= 14", f"took <= {bound}")
    began = time.monotonic()
    assert signal.getsignal(signal.SIGPIPE) == signal.SIG_IGN  # CPython's own; the runner's too
    run = subprocess.run(["bash", "-c", check], capture_output=True, text=True, timeout=90, restore_signals=False)
    assert (run.returncode == 0) is passes, run.stderr
    assert time.monotonic() - began < 14  # the trickle stopped once curl had its answer


def test_cis_ingress_checks_each_stop_a_failing_step() -> None:
    """`bash -e` ignores a failure before a list's last `&&`: each check is a command of its own."""
    e2e = yaml.safe_load(CI.read_text())["jobs"]["e2e"]
    run = {step.get("name", ""): step for step in e2e["steps"]}[
        "A webhook through nginx and ingress (engine 2b spec §8.3, §12)"
    ]["run"]
    assert [line for line in run.splitlines() if line.strip().startswith("test ") and "&&" in line] == []


@pytest.mark.parametrize("name", ["api", "ingress"])
def test_the_ingress_keys_holders_take_a_previous_key_for_its_rollout(name: str) -> None:
    """2b-4 (engine 2b spec §8.3): the ingress key's rollout configures the previous key on every process that holds
    it; unset, it's empty."""
    env = environment(name)
    assert env["DEWPOINT_INGRESS_KEY_PREVIOUS_B64"] == "" and env["DEWPOINT_INGRESS_KEY_PREVIOUS_ID"] == ""
