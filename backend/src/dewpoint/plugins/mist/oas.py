# SPDX-License-Identifier: Apache-2.0
"""Mist's OpenAPI description as data (plugins-3 D2): `mistsys/mist_openapi`'s `mist.openapi.json` at `COMMIT`,
vendored gzipped (MIT, its licence beside it) and refused unless its SHA-256 is `SHA256`. Its README says it's for
documentation, not code generation: the policy map (D28) decides what any operation may do, and the overlay
(`data/oas-overlay.json`) patches the description where Mist's real answers showed it wrong, each patch citing its
evidence, until the upstream description is fixed."""

import copy
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
JSON_TYPES = ("application/json", "application/vnd.api+json", "application/vnd.json+api")


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
def overlay() -> Mapping[str, Any]:
    """The reviewed patches laid over the vendored description (`data/oas-overlay.json`)."""
    found: dict[str, Any] = json.loads((resources.files(__package__) / "data" / "oas-overlay.json").read_text())
    if found.get("oas_sha256") != SHA256:
        raise OasUnreadableError("the overlay was written for another description")
    return found


def _nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(schema)
    kind = out.get("type")
    if isinstance(kind, str):
        out["type"] = [kind, "null"]
    elif isinstance(kind, list):
        out["type"] = [*kind, "null"]
    else:  # a reference or a union: either it, or null
        keep = {k: v for k, v in out.items() if k in ("description", "title")}
        out = {**keep, "anyOf": [{k: v for k, v in out.items() if k not in keep}, {"type": "null"}]}
    return out


def overlaid(doc: dict[str, Any], patches: Mapping[str, Any]) -> dict[str, Any]:
    """`doc` with every patch of `patches` applied, each only once its target reads as it expects: a patch that no
    longer applies (the description fixed, or changed) raises, naming it."""
    schemas = doc["components"]["schemas"]
    for patch in patches["patches"]:
        op = patch["op"]
        if op == "answer":
            name = patch["operation"]
            spec = next((item[m] for item in doc["paths"].values() for m in METHODS
                         if isinstance(item.get(m), dict) and item[m].get("operationId") == name), None)  # fmt: skip
            if spec is None or spec["responses"].get("200") != patch["expect"]:
                raise OasUnreadableError(f"the overlay's patch of {name}'s answer no longer applies")
            spec["responses"]["200"] = {
                "description": "OK", "content": {"application/json": {"schema": copy.deepcopy(patch["to"])}},
            }  # fmt: skip
            continue
        holder = schemas.get(patch["schema"])
        label = f"{patch['schema']}.{patch.get('property', '')}".rstrip(".")
        if op == "not_required":
            required = holder.get("required") if isinstance(holder, dict) else None
            if not isinstance(required, list) or not set(patch["names"]) <= set(required):
                raise OasUnreadableError(f"the overlay's patch of {label} no longer applies")
            holder["required"] = [n for n in required if n not in patch["names"]]
            continue
        name = patch["property"]
        container = holder.get("properties") if isinstance(holder, dict) else None
        target = holder.get("additionalProperties") if name == "{*}" and isinstance(holder, dict) else (
            container.get(name) if isinstance(container, dict) else None)  # fmt: skip
        if not isinstance(target, dict) or any(target.get(k) != v for k, v in patch["expect"].items()):
            raise OasUnreadableError(f"the overlay's patch of {label} no longer applies")
        if op == "nullable":
            changed = _nullable(target)
        else:  # the new type replaces the old, a reference included: JSON Schema would apply both
            changed = {**{k: v for k, v in target.items() if k != "$ref"}, "type": copy.deepcopy(patch["to"])}
        if name == "{*}":
            holder["additionalProperties"] = changed
        else:
            container[name] = changed  # type: ignore[index]
    return doc


@cache
def document() -> Mapping[str, Any]:
    """The packaged description, with the overlay laid over it. Read once per process; nothing may change it."""
    raw = parse((resources.files(__package__) / "data" / "mist.openapi.json.gz").read_bytes())
    return overlaid(raw, overlay())


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


def media(doc: Mapping[str, Any], op: Operation) -> Mapping[str, Any] | None:
    """An operation's 2xx answer's JSON media object, or None when it answers nothing."""
    responses = op.spec.get("responses", {})
    found = resolve(doc, responses.get("200") or responses.get("201") or {})
    content = found.get("content") or {}
    chosen = next((content[t] for t in JSON_TYPES if t in content), None)
    return chosen if isinstance(chosen, Mapping) else None


def answer(doc: Mapping[str, Any], op: Operation) -> Any:
    """An operation's 2xx answer's JSON schema, or None when it answers nothing."""
    found = media(doc, op)
    return found.get("schema") if found is not None else None
