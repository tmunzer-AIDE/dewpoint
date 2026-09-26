# SPDX-License-Identifier: Apache-2.0
"""What the evaluator process loads and accepts (spec §5.7, §10 evaluator isolation)."""

import json
import os
import subprocess
import sys

FORBIDDEN = (
    "sqlalchemy", "asyncpg", "fastapi", "starlette", "pydantic", "jsonschema", "httpx", "temporalio",
    "cryptography", "dewpoint.core", "dewpoint.engine.graph", "dewpoint.engine.registry", "dewpoint.plugins",
    "dewpoint.sdk",
)  # fmt: skip


def test_the_evaluator_imports_only_the_runtime_and_engine_cel() -> None:
    code = "import sys, json, dewpoint.apps.cel_evaluator.__main__; print(json.dumps(sorted(sys.modules)))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60)
    loaded = json.loads(done.stdout)
    leaked = [m for m in loaded if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    assert leaked == []
    assert "cel_expr_python" in {m.split(".")[0] for m in loaded}


def test_it_refuses_to_start_with_anything_secret_looking_in_its_environment() -> None:
    secret = "kek-value-that-must-not-leak"
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": os.environ.get("PYTHONPATH", ""), "DEWPOINT_KEK_B64": secret}
    done = subprocess.run(
        [sys.executable, "-m", "dewpoint.apps.cel_evaluator"], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 2
    assert "DEWPOINT_KEK_B64" in done.stderr and secret not in done.stderr  # names the variable, never its value
