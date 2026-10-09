# SPDX-License-Identifier: Apache-2.0
"""`dewpoint temporal check` (2b-4b M4, DW.4; M6's readiness will call it): with the deployment's own §10.4
settings, Temporal's namespace as it reports itself: TLS verified (never plaintext), a retention of at most 30 days
(D3g), archival disabled for history and visibility (erasure requires it). Read-only; a problem is exit 1."""

import base64
from types import SimpleNamespace

import pytest
from google.protobuf.duration_pb2 import Duration
from temporalio.api.enums.v1 import ArchivalState
from temporalio.api.namespace.v1 import NamespaceConfig
from temporalio.api.workflowservice.v1 import DescribeNamespaceResponse
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.temporal_check import problems
from tests.apps.cli.test_keys import _env, _recorded

DAY = 86400
KEK = base64.b64encode(bytes(32)).decode()
DISABLED = ArchivalState.ARCHIVAL_STATE_DISABLED


def answer(seconds: int | None = 30 * DAY, nanos: int = 0, history: int = DISABLED,
           visibility: int = DISABLED) -> DescribeNamespaceResponse:  # fmt: skip
    config = NamespaceConfig(history_archival_state=history, visibility_archival_state=visibility)  # type: ignore[arg-type]
    if seconds is not None:
        config.workflow_execution_retention_ttl.CopyFrom(Duration(seconds=seconds, nanos=nanos))
    return DescribeNamespaceResponse(config=config)


def test_a_namespace_within_the_rules_over_tls_has_no_problem() -> None:
    assert problems(answer(), plaintext=False) == []
    assert problems(answer(seconds=DAY), plaintext=False) == []


@pytest.mark.parametrize(("given", "found"), [
    (answer(seconds=31 * DAY), "retention of 31 days, above 30 (D3g)"),
    (answer(nanos=1), "retention above 30 days"),
    (answer(seconds=30 * DAY - 1, nanos=999_999_999 + 1), "malformed retention"),  # the review's C1
    (answer(seconds=None), "no retention reported"),
    (answer(history=ArchivalState.ARCHIVAL_STATE_ENABLED), "history archival enabled"),
    (answer(visibility=ArchivalState.ARCHIVAL_STATE_ENABLED), "visibility archival enabled"),
])  # fmt: skip
def test_each_breach_is_a_problem(given: DescribeNamespaceResponse, found: str) -> None:
    [problem] = problems(given, plaintext=False)
    assert found in problem


def test_plaintext_is_a_problem() -> None:
    [problem] = problems(answer(), plaintext=True)
    assert "plaintext" in problem and "DEWPOINT_TEMPORAL_INSECURE_DEV" in problem


class _Temporal:
    def __init__(self, reply: DescribeNamespaceResponse | Exception) -> None:
        self.asked: list[str] = []

        async def describe_namespace(request: object) -> DescribeNamespaceResponse:
            self.asked.append(request.namespace)  # type: ignore[attr-defined]
            if isinstance(reply, Exception):
                raise reply
            return reply

        self.workflow_service = SimpleNamespace(describe_namespace=describe_namespace)


def _connected(monkeypatch: pytest.MonkeyPatch, temporal: _Temporal) -> list[str]:
    from dewpoint.apps.cli import main as cli

    environments: list[str] = []

    async def connect(settings: object, environment: str, **kwargs: object) -> _Temporal:
        environments.append(environment)
        return temporal

    monkeypatch.setattr(cli, "temporal_connect", connect)
    return environments


def _tls(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment's settings: not plaintext (the connection itself is the stand-in's)."""
    from dewpoint.core.config import get_settings

    monkeypatch.delenv("DEWPOINT_TEMPORAL_INSECURE_DEV", raising=False)
    get_settings.cache_clear()


def test_the_check_reports_and_passes(pg_url, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=KEK)
    _recorded(pg_url)
    _tls(monkeypatch)
    temporal = _Temporal(answer())
    environments = _connected(monkeypatch, temporal)
    done = CliRunner().invoke(app, ["temporal", "check"])
    assert done.exit_code == 0, done.output
    assert temporal.asked == ["default"] and environments == ["development"]
    assert "retention: 30 days" in done.output and "archival: disabled" in done.output


def test_the_check_fails_on_a_breach(pg_url, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=KEK)
    _recorded(pg_url)
    _tls(monkeypatch)
    _connected(monkeypatch, _Temporal(answer(seconds=31 * DAY)))
    done = CliRunner().invoke(app, ["temporal", "check"])
    assert done.exit_code == 1 and "PROBLEM: retention of 31 days, above 30 (D3g)" in done.output


def test_the_check_fails_when_temporal_cant_be_asked(pg_url, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=KEK)
    _recorded(pg_url)
    _tls(monkeypatch)
    _connected(monkeypatch, _Temporal(ConnectionError("refused")))
    done = CliRunner().invoke(app, ["temporal", "check"])
    assert done.exit_code == 1 and "couldn't be asked (ConnectionError)" in done.output


def test_the_check_refuses_an_unrecorded_namespace_before_connecting(pg_url, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=KEK)
    environments = _connected(monkeypatch, _Temporal(answer()))
    done = CliRunner().invoke(app, ["temporal", "check"])
    assert done.exit_code == 2 and environments == []
