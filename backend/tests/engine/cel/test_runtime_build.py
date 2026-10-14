# SPDX-License-Identifier: Apache-2.0
"""The patched CEL runtime's build record (deploy/cel-runtime/manifest.json) names the inputs committed beside it.
Nothing here builds: deploy/cel-runtime/README.md says how."""

import hashlib
import json
from pathlib import Path
from typing import Any

RECIPE = Path(__file__).parents[4] / "deploy" / "cel-runtime"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict[str, Any]:
    return json.loads((RECIPE / "manifest.json").read_text())


def test_the_build_record_names_the_committed_inputs() -> None:
    record = manifest()
    assert record["patch"]["sha256"] == sha256(RECIPE / record["patch"]["file"])
    assert record["MODULE.bazel.lock"]["sha256"] == sha256(RECIPE / "MODULE.bazel.lock")
    assert record["assembly"]["sha256"] == sha256(RECIPE / "assemble.sh")
    assert record["build_linux_script"]["sha256"] == sha256(RECIPE / "build-linux.sh")
    assert {p.name: sha256(p) for p in (RECIPE / "third_party_licenses").iterdir()} == record["third_party_licenses"]
