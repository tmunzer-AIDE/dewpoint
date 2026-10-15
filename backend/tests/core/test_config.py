# SPDX-License-Identifier: Apache-2.0
"""A process whose settings fail says which setting, never a value (the owner's rule: a secret seen anywhere is never
repeated). pydantic's message quotes the input unless told not to, and a missing setting's input is every setting read:
the key-encryption key and the database's password among them. A process that can't start prints that message on each
restart attempt (Compose's `unless-stopped`), so every settings class hides it (`hide_input_in_errors`)."""

import ast
import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

import dewpoint
from dewpoint.apps.ingress.config import IngressSettings
from dewpoint.apps.retention import RetentionSettings
from dewpoint.core.config import Settings
from dewpoint.core.temporal_settings import TemporalConnection

# No two share 8 characters in a row, so a quoted one is told apart from the others.
PASSWORD = "pw-0d4e7a5c1e9b"
SECRETS = {
    "DEWPOINT_DATABASE_URL": f"postgresql+asyncpg://dewpoint:{PASSWORD}@db/dewpoint",
    "DEWPOINT_KEK_B64": "kek-3f9b21c8e5a7",
    "DEWPOINT_KEK_PREVIOUS_B64": "kekprev-6a1f0c2d94",
    "DEWPOINT_INGRESS_KEY_B64": base64.b64encode(b"ingress-key-for-the-config-test!").decode(),
    "DEWPOINT_AUDIT_SIGNING_KEY_B64": "audit-4f8a2c9d71",
}


def quoted(text: str) -> list[str]:
    """The secrets any 8 characters of which the text holds: pydantic shortens a long input to its two ends."""
    values = {"password": PASSWORD, **{n: v for n, v in SECRETS.items() if n != "DEWPOINT_DATABASE_URL"}}
    return [name for name, value in values.items() if any(value[i : i + 8] in text for i in range(len(value) - 7))]


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Every secret set and every class's settings valid, no other setting from this process's environment, and no
    `.env` file to read."""
    for name in [n for n in os.environ if n.startswith("DEWPOINT_")]:
        monkeypatch.delenv(name)
    for name, value in {**SECRETS, "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.example.com"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)
    return monkeypatch


@pytest.mark.parametrize("settings", [Settings, TemporalConnection, RetentionSettings, IngressSettings])
def test_the_environment_alone_is_valid(environment: pytest.MonkeyPatch, settings: type[BaseSettings]) -> None:
    """Each test below makes one setting fail: nothing else does."""
    settings()


@pytest.mark.parametrize(
    ("settings", "missing"), [(Settings, "DEWPOINT_PUBLIC_ORIGIN"), (IngressSettings, "DEWPOINT_DATABASE_URL")]
)
def test_a_missing_setting_is_named_and_no_value_quoted(
    environment: pytest.MonkeyPatch, settings: type[BaseSettings], missing: str
) -> None:
    """The api's probe of 2026-10-15 (no `DEWPOINT_PUBLIC_ORIGIN`) printed the end of its key-encryption key."""
    environment.delenv(missing)
    with pytest.raises(ValidationError) as refused:
        settings()
    assert missing.removeprefix("DEWPOINT_").lower() in str(refused.value)
    assert quoted(str(refused.value)) == []


@pytest.mark.parametrize(
    ("settings", "setting"),
    [
        (Settings, "DEWPOINT_SESSION_IDLE_MINUTES"),
        (TemporalConnection, "DEWPOINT_TEMPORAL_INSECURE_DEV"),
        (RetentionSettings, "DEWPOINT_RETENTION_BATCH"),
        (IngressSettings, "DEWPOINT_INGRESS_MAX_IN_FLIGHT"),
    ],
)
def test_a_refused_value_is_named_never_quoted(
    environment: pytest.MonkeyPatch, settings: type[BaseSettings], setting: str
) -> None:
    """A secret given to the wrong setting (a line shifted in an env file) is refused by that setting's name only."""
    environment.setenv(setting, SECRETS["DEWPOINT_KEK_B64"])
    with pytest.raises(ValidationError) as refused:
        settings()
    assert setting.removeprefix("DEWPOINT_").lower() in str(refused.value)
    assert quoted(str(refused.value)) == []


@pytest.mark.parametrize(
    "command",
    [
        ["-m", "uvicorn", "dewpoint.apps.api.main:create_app", "--factory", "--port", "0"],  # the api image's CMD
        ["-c", "from dewpoint.apps.cli.main import app; app()", "worker"],  # `dewpoint worker`: Typer's own hook
    ],
    ids=["api", "worker"],
)
def test_a_process_that_cannot_start_prints_no_value(tmp_path: Path, command: list[str]) -> None:
    """What the process itself prints, as each restart attempt would: Python's or Typer's traceback of the error."""
    env = {"PATH": os.environ["PATH"], **SECRETS}
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    done = subprocess.run([sys.executable, *command], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=60, check=False)  # fmt: skip
    assert done.returncode != 0
    assert "public_origin" in done.stderr
    assert quoted(done.stdout + done.stderr) == []


def _hides(node: ast.Call) -> bool:
    return any(kw.arg == "hide_input_in_errors" and isinstance(kw.value, ast.Constant) and kw.value.value is True
               for kw in node.keywords)  # fmt: skip


def test_every_settings_class_says_it_hides_its_input() -> None:
    """A settings class added later hides its input too: each `SettingsConfigDict` says so itself, never by a base's
    alone, and each class made straight from `BaseSettings` has one (pydantic's default quotes the input)."""
    source = Path(dewpoint.__file__).parent
    found = []
    for path in sorted(source.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "SettingsConfigDict":
                if not _hides(node):
                    found.append(f"{path.relative_to(source)}:{node.lineno}")
            elif isinstance(node, ast.ClassDef) and any(getattr(b, "id", None) == "BaseSettings" for b in node.bases):
                configs = [s for s in node.body if isinstance(s, ast.Assign) and isinstance(s.value, ast.Call)
                           and any(getattr(t, "id", None) == "model_config" for t in s.targets)]  # fmt: skip
                if not configs:
                    found.append(f"{path.relative_to(source)}:{node.lineno}")
    assert found == []
