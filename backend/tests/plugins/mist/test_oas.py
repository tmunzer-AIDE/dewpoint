# SPDX-License-Identifier: Apache-2.0
"""The Mist OpenAPI description, vendored as data (plugins-3 D2): `mistsys/mist_openapi`'s `mist.openapi.json` at
0613a22, gzipped, refused unless its SHA-256 is the pinned one; each curated operation keeps the method and path the
outline's appendix lists."""

import gzip
import json
from importlib import resources
from pathlib import Path

import pytest

from dewpoint.plugins.mist import oas

CURATED = json.loads((Path(__file__).parent / "curated.json").read_text())


def packaged() -> bytes:
    return (resources.files("dewpoint.plugins.mist") / "data" / "mist.openapi.json.gz").read_bytes()


def test_the_vendored_description_is_the_pinned_commit() -> None:
    doc = oas.document()
    assert (doc["openapi"], doc["info"]["version"]) == ("3.1.0", "2609.1.0")
    assert oas.SHA256 == "22f55432535ab38f6c0539392a729b8fd515a9ccae9df693fbd4ff23d40b8fac"
    assert oas.COMMIT == "0613a22acd8d627c938a74dbf2f0f80167bdcb93"


def test_a_changed_byte_is_refused() -> None:
    raw = gzip.decompress(packaged())
    assert oas.parse(packaged())["openapi"] == "3.1.0"
    with pytest.raises(oas.OasUnreadableError):
        oas.parse(gzip.compress(raw.replace(b'"3.1.0"', b'"3.1.1"', 1)))
    with pytest.raises(oas.OasUnreadableError):
        oas.parse(b"not gzip")


def test_each_curated_operation_keeps_its_method_and_path() -> None:
    ops = oas.operations()
    assert len(CURATED) == 262
    for op_id, method, path in CURATED:
        assert (ops[op_id].method, ops[op_id].path, ops[op_id].deprecated) == (method, path, False), op_id


def test_operations_are_read_with_their_path_parameters() -> None:
    op = oas.operations()["getSiteDevice"]
    assert [p["name"] for p in op.parameters if p["in"] == "path"] == ["site_id", "device_id"]
    assert all("$ref" not in p for p in op.parameters)


def test_its_licence_ships_with_it() -> None:
    licence = (resources.files("dewpoint.plugins.mist") / "data" / "mist_openapi.LICENSE").read_text()
    assert licence.startswith("MIT License") and "Copyright (c) 2020 Thomas Munzer" in licence
    notice = (Path(__file__).parents[4] / "NOTICE").read_text()
    assert "mist_openapi" in notice and "MIT" in notice
