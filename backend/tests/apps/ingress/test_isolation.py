# SPDX-License-Identifier: Apache-2.0
"""Ingress loads neither the API, the dispatcher, the worker nor Temporal, and no tenant key's code (engine 2b spec
§8.3): the import contract's forbidden modules (`pyproject.toml`, checked by `lint-imports`), here as a fresh process
actually loads them, which also catches an import the static contract can't see. Its settings include Temporal's
connection settings (`core.config.Settings`), which live apart from the client that connects
(`core.temporal_settings`, not `core.temporal_connect`)."""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parents[3] / "pyproject.toml"


def _forbidden() -> list[str]:
    contracts = tomllib.loads(PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    [ingress] = [c for c in contracts if c.get("source_modules") == ["dewpoint.apps.ingress"]]
    return list(ingress["forbidden_modules"])


def test_ingress_loads_none_of_the_contracts_forbidden_modules() -> None:
    forbidden = _forbidden()
    assert "temporalio" in forbidden
    code = "import sys, json, dewpoint.apps.ingress.main; print(json.dumps(sorted(sys.modules)))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60)
    loaded = json.loads(done.stdout)
    assert sorted(m for m in loaded if any(m == f or m.startswith(f + ".") for f in forbidden)) == []
