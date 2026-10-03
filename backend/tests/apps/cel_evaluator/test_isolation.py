# SPDX-License-Identifier: Apache-2.0
"""What the evaluator process loads and accepts (spec §5.7, §10 evaluator isolation)."""

import json
import os
import subprocess
import sys
from pathlib import Path

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


IMAGE = Path(__file__).parents[4] / "deploy" / "docker" / "cel-evaluator.Dockerfile"


def test_every_dewpoint_module_the_evaluator_loads_is_in_its_image() -> None:
    """The e2e job's evaluator exited at startup: `engine.cel.bind` had come to import `engine.handles`, which its
    image doesn't copy. Every Dewpoint module the evaluator loads is a file its Dockerfile copies."""
    copied = [
        source.removeprefix("backend/src/")
        for line in IMAGE.read_text().splitlines()
        if line.startswith("COPY ") and "--from=" not in line
        for source in line.split()[1:-1]
        if source.startswith("backend/src/")
    ]
    code = (
        "import sys, json, dewpoint.apps.cel_evaluator.__main__; "
        "print(json.dumps({m: getattr(v, '__file__', None) for m, v in sys.modules.items() if m[:8] == 'dewpoint'}))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60)
    src = (Path(__file__).parents[3] / "src").resolve()
    files = {m: Path(f).resolve().relative_to(src).as_posix() for m, f in json.loads(done.stdout).items() if f}

    def in_image(file: str) -> bool:
        return any(file == c or file.startswith(c.rstrip("/") + "/") for c in copied)

    assert sorted(m for m, f in files.items() if not in_image(f)) == [], copied


def test_it_refuses_to_start_with_anything_secret_looking_in_its_environment() -> None:
    secret = "kek-value-that-must-not-leak"
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": os.environ.get("PYTHONPATH", ""), "DEWPOINT_KEK_B64": secret}
    done = subprocess.run(
        [sys.executable, "-m", "dewpoint.apps.cel_evaluator"], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 2
    assert "DEWPOINT_KEK_B64" in done.stderr and secret not in done.stderr  # names the variable, never its value


def test_it_accepts_what_its_own_interpreter_sets(tmp_path: Path) -> None:
    """Under a C locale Python itself sets LC_CTYPE (PEP 538): refusing it would stop every evaluator started without
    LANG. The empty cgroup directory makes it exit at once, for another reason."""
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
    env["DEWPOINT_CEL_CGROUP"] = str(tmp_path)
    done = subprocess.run(
        [sys.executable, "-m", "dewpoint.apps.cel_evaluator"], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 2 and "LC_CTYPE" not in done.stderr, done.stderr
