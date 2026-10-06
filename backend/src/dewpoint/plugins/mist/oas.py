# SPDX-License-Identifier: Apache-2.0
"""Mist's OpenAPI description as data (plugins-3 D2): `mistsys/mist_openapi`'s `mist.openapi.json` at `COMMIT`,
vendored gzipped (MIT, its licence beside it) and refused unless its SHA-256 is `SHA256`. Its README says it's for
documentation, not code generation: the policy map (D28) decides what any operation may do, and overrides the
description where it's wrong."""

import gzip
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

COMMIT = "0613a22acd8d627c938a74dbf2f0f80167bdcb93"
SHA256 = "22f55432535ab38f6c0539392a729b8fd515a9ccae9df693fbd4ff23d40b8fac"
METHODS = ("get", "put", "post", "delete", "patch")


class OasUnreadableError(Exception):
    """The vendored description isn't the pinned one."""


@dataclass(frozen=True)
class Operation:
    id: str
    method: str  # upper case
    path: str  # as the description writes it, `/api/v1/...` with `{name}` placeholders
    deprecated: bool
    spec: Mapping[str, Any]  # the operation object
    parameters: tuple[Mapping[str, Any], ...]  # the path item's then the operation's, each `$ref` resolved


def parse(blob: bytes) -> dict[str, Any]:
    """The description in `blob` (gzipped), once its SHA-256 is the pinned one."""
    try:
        raw = gzip.decompress(blob)
    except (OSError, EOFError) as e:
        raise OasUnreadableError("the vendored description isn't gzip") from e
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise OasUnreadableError("the vendored description isn't the pinned one")
    document: dict[str, Any] = json.loads(raw)
    return document


@cache
def document() -> Mapping[str, Any]:
    """The packaged description. Read once per process; nothing may change it."""
    return parse((resources.files(__package__) / "data" / "mist.openapi.json.gz").read_bytes())


def resolve(doc: Mapping[str, Any], node: Any) -> Any:
    """`node` with its local `$ref`s followed until it isn't one."""
    seen: set[str] = set()
    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            raise OasUnreadableError("a reference that can't be followed")
        seen.add(ref)
        target: Any = doc
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node


@cache
def operations() -> Mapping[str, Operation]:
    """Every operation of the packaged description, by operationId."""
    doc = document()
    out: dict[str, Operation] = {}
    for path, item in doc["paths"].items():
        shared = tuple(resolve(doc, p) for p in item.get("parameters", ()))
        for method in METHODS:
            spec = item.get(method)
            if not isinstance(spec, Mapping) or "operationId" not in spec:
                continue
            own = tuple(resolve(doc, p) for p in spec.get("parameters", ()))
            out[spec["operationId"]] = Operation(
                spec["operationId"], method.upper(), path, bool(spec.get("deprecated")), spec, shared + own
            )
    return out
