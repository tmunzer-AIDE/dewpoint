# SPDX-License-Identifier: Apache-2.0
"""Compose's wiring (`deploy/compose/docker-compose.yml`), rendered as Compose renders it for a `.env` whose Temporal
namespace isn't the default."""

import re
from pathlib import Path
from typing import Any

import yaml

COMPOSE = Path(__file__).parents[3] / "deploy" / "compose" / "docker-compose.yml"
ENV = {
    "POSTGRES_PASSWORD": "owner-pw",
    "DEWPOINT_API_DB_PASSWORD": "api-pw",
    "DEWPOINT_ADMIN_DB_PASSWORD": "admin-pw",
    "DEWPOINT_AUDITOR_DB_PASSWORD": "auditor-pw",
    "DEWPOINT_WORKER_DB_PASSWORD": "worker-pw",
    "DEWPOINT_DISPATCH_DB_PASSWORD": "dispatch-pw",
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
