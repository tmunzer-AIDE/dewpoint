# SPDX-License-Identifier: Apache-2.0
"""One node type per curated Mist operation (plugins-3 D23), generated when the plugin loads from the policy map
(D28) and the vendored OAS (D2): each allowed operation's curated node, named by the map, version 1, with the map's
side effect and capability, and config and output schemas from the OAS (`schemas`). Every node checks the map again
when it runs, so an operation the map no longer allows sends nothing.

A node's shape follows its operation: a read answers the object; a list (`X-Page-*` headers) or a search (the body's
`next`) answers its results, under a page cap, and whether it was cut; a create posts its body; an update merges
(D15: reads the object, applies each set field into it, rebuilding each touched structure whole, and sends those, Mist's
PUT being a top-level merge) or replaces (sends only what's set); `clear` names fields sent as null; a delete
answers `already_absent` when a retry finds the object gone; an action answers nothing."""

import re
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, ClassVar

from pydantic import BaseModel

from dewpoint.plugins.mist import oas, policy
from dewpoint.plugins.mist.client import InvalidAnswer, MistClient, NotFound
from dewpoint.plugins.mist.schemas import converted, resolved, top_properties, with_defs
from dewpoint.sdk import FatalError, Node, SideEffect, StepContext, declared_model
from dewpoint.sdk.fields import CONNECTION, LITERAL

PAGE_CAP = 10
JSON_TYPES = ("application/json", "application/vnd.api+json", "application/vnd.json+api")


class OperationUnavailable(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.operation_unavailable", "This Mist operation isn't allowed in this build.")


class ConflictingChange(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.conflicting_change", "A field can't be both set and cleared.")


class NothingToChange(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.nothing_to_change", "The update sets and clears nothing.")


def merged(current: Any, change: Any) -> Any:
    """`change` applied into `current`: objects field by field, anything else (arrays, scalars, null) replaced."""
    if isinstance(current, Mapping) and isinstance(change, Mapping):
        return {**current, **{k: merged(current.get(k), v) for k, v in change.items()}}
    return change


class MistOperation(Node):
    """A curated operation's node. Generated subclasses set the class attributes below."""

    operation: ClassVar[str]
    method: ClassVar[str]
    path: ClassVar[str]
    scope: ClassVar[str]
    shape: ClassVar[str]  # object, list, search, empty, delete
    paging: ClassVar[str | None] = None  # headers, next
    merge_with: ClassVar[str | None] = None  # the operation reading the object an update merges into
    credentials = ("mist",)

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        values: dict[str, Any] = dict(config.root)
        body, clear = values.get("body"), list(values.get("clear", ()))
        if self.method == "PUT":
            if set(body or {}) & set(clear):
                raise ConflictingChange()
            if not body and not clear:
                raise NothingToChange()
        if policy.load().allowed(self.operation, self.type) is None:
            raise OperationUnavailable()
        client = MistClient(await ctx.connection(uuid.UUID(values["connection"])))
        path = client.path(self.path, values)
        if self.scope == "site":
            await client.check_site(values["site_id"])
        result = await self._send(ctx, client, path, values, body, clear)
        return self.Output.model_construct(result)  # the runtime checks it against the output schema

    async def _send(
        self, ctx: StepContext, client: MistClient, path: str, values: dict[str, Any], body: Any, clear: list[str]
    ) -> Any:
        query = values.get("query")
        pages = int(values.get("max_pages", 1))
        if self.shape == "list":
            if self.paging == "headers":
                listed = await client.list_pages(path, query, max_pages=pages)
                return {"results": listed.results, "total": listed.total, "truncated": listed.truncated}
            answer = await client.call("GET", path, query=query)
            if not isinstance(answer.body, list):
                raise InvalidAnswer()
            return {"results": answer.body, "total": None, "truncated": False}
        if self.shape == "search":
            found, truncated = await client.search_pages(path, query, max_pages=pages)
            return {**found, "truncated": truncated}
        if self.shape == "delete":
            try:
                await client.call("DELETE", path, query=query)
            except NotFound:
                if ctx.attempt > 1:  # an earlier attempt's request may have deleted it (D16)
                    return {"already_absent": True}
                raise
            return {"already_absent": False}
        if self.method == "PUT":
            body = await self._update_body(client, path, body or {}, clear, values.get("mode"))
        answer = await client.call(self.method, path, query=query, body=body)
        if self.shape == "empty":
            return {}
        if not isinstance(answer.body, dict):
            raise InvalidAnswer()
        return answer.body

    async def _update_body(
        self, client: MistClient, path: str, body: Mapping[str, Any], clear: list[str], mode: str | None
    ) -> dict[str, Any]:
        cleared = dict.fromkeys(clear)
        if (mode or ("merge" if self.merge_with else "replace")) == "replace":
            return {**body, **cleared}
        if self.merge_with is None or policy.load().entries[self.merge_with].state != "allowed":
            raise OperationUnavailable()
        current = await client.call("GET", path)
        if not isinstance(current.body, dict):
            raise InvalidAnswer()
        return {**{k: merged(current.body.get(k), v) for k, v in body.items()}, **cleared}


def _title(op_id: str) -> str:
    words = re.findall(r"[A-Z]{2,}(?![a-z])|[A-Z]?[a-z0-9]+", op_id)
    text = " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in words)
    return text[:1].upper() + text[1:]


def _description(op: oas.Operation) -> str:
    text = str(op.spec.get("description") or "").strip().split("\n\n", 1)[0].strip()
    return text if len(text) <= 300 else text[:297].rstrip() + "..."


def _answer(doc: Mapping[str, Any], op: oas.Operation) -> Any:
    """The 2xx answer's JSON schema, or None when the operation answers nothing."""
    responses = op.spec.get("responses", {})
    found = oas.resolve(doc, responses.get("200") or responses.get("201") or {})
    content = found.get("content") or {}
    media = next((content[t] for t in JSON_TYPES if t in content), None)
    return media.get("schema") if isinstance(media, Mapping) else None


def _shape(doc: Mapping[str, Any], op: oas.Operation, answer: Any) -> tuple[str, str | None]:
    query = {p["name"] for p in op.parameters if p["in"] == "query"}
    if op.method == "DELETE":
        return "delete", None
    if answer is None:
        return "empty", None
    top = resolved(doc, answer)
    if op.method == "GET" and top.get("type") == "array":
        return "list", "headers" if "page" in query else None
    if op.method == "GET" and "next" in top.get("properties", {}):
        return "search", "next"
    return "object", None


def _query_values(doc: Mapping[str, Any], op: oas.Operation, paging: str | None) -> list[Mapping[str, Any]]:
    """The query parameters a config takes: arrays left out (their encoding isn't verified), and the page when the
    node pages itself."""
    return [
        p for p in op.parameters if p["in"] == "query" and not (paging == "headers" and p["name"] == "page")
        and resolved(doc, p.get("schema", {})).get("type") != "array"
    ]  # fmt: skip


def config_schema(
    doc: Mapping[str, Any], op: oas.Operation, shape: str, paging: str | None, merge: bool
) -> dict[str, Any]:
    update = op.method == "PUT"
    props: dict[str, Any] = {
        "connection": {"type": "string", "format": "uuid", "title": "Connection", LITERAL: True, CONNECTION: "mist"}
    }
    required = ["connection"]
    roots: list[Any] = []
    for p in op.parameters:
        if p["in"] == "path" and p["name"] != "org_id":
            props[p["name"]] = {"title": _title(p["name"]), **converted(p.get("schema", {}), output=False)}
            required.append(p["name"])
            roots.append(p.get("schema", {}))
    query = _query_values(doc, op, paging)
    if query:
        qprops = {p["name"]: converted(p.get("schema", {}), output=False) for p in query}
        for p in query:
            if p.get("description"):
                qprops[p["name"]].setdefault("description", str(p["description"]))
        qrequired = [p["name"] for p in query if p.get("required")]
        props["query"] = {"type": "object", "title": "Query", "properties": qprops, "additionalProperties": False}
        if qrequired:
            props["query"]["required"] = qrequired
            required.append("query")
        roots += [p.get("schema", {}) for p in query]
    body = oas.resolve(doc, op.spec["requestBody"]) if "requestBody" in op.spec else None
    if body is not None:
        schema = (body.get("content") or {}).get("application/json", {}).get("schema", {})
        props["body"] = {"title": "Body", **converted(schema, output=False, partial=update)}
        roots.append(schema)
        if op.method == "POST" and shape != "empty":
            required.append("body")
        if update:
            if merge:
                props["mode"] = {"enum": ["merge", "replace"], "default": "merge", "title": "Mode"}
            props["clear"] = {
                "type": "array", "title": "Fields to clear", "uniqueItems": True,
                "items": {"enum": top_properties(doc, schema)},
            }  # fmt: skip
    if paging is not None:
        props["max_pages"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": PAGE_CAP,
            "default": 1,
            "title": "Pages, at most",
        }
    out = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    return with_defs(doc, out, roots, output=False, partial=update)


def output_schema(doc: Mapping[str, Any], answer: Any, shape: str) -> dict[str, Any]:
    if shape == "empty":
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if shape == "delete":
        return {
            "type": "object", "properties": {"already_absent": {"type": "boolean", "title": "Already absent"}},
            "required": ["already_absent"], "additionalProperties": False,
        }  # fmt: skip
    top = converted(resolved(doc, answer), output=True)
    if shape == "list":
        out: dict[str, Any] = {
            "type": "object",
            "properties": {
                "results": {"type": "array", "items": top.get("items", {})},
                "total": {"type": ["integer", "null"]},
                "truncated": {"type": "boolean"},
            },
            "required": ["results", "total", "truncated"],
            "additionalProperties": False,
        }
        return with_defs(doc, out, [resolved(doc, answer).get("items", {})], output=True, partial=False)
    if shape == "search":
        top.setdefault("properties", {}).pop("next", None)
        top["properties"]["truncated"] = {"type": "boolean"}
        top["required"] = [r for r in top.get("required", []) if r != "next"] + ["truncated"]
    top["type"] = "object"
    return with_defs(doc, top, [resolved(doc, answer)], output=True, partial=False)


def _class_name(type_: str) -> str:
    return "".join(part.title() for part in re.split(r"[._]", type_))


def build() -> tuple[type[Node], ...]:
    """Every allowed operation's curated node, in the map's order."""
    doc, ops, entries = oas.document(), oas.operations(), policy.load().entries
    by_path = {(e.method, e.path): op_id for op_id, e in entries.items() if e.state == "allowed"}
    out: list[type[Node]] = []
    for op_id, entry in sorted(entries.items()):
        if entry.state != "allowed" or entry.side_effect is None:
            continue
        op, type_ = ops[op_id], entry.nodes[0]
        answer = _answer(doc, op)
        shape, paging = _shape(doc, op, answer)
        merge_with = by_path.get(("GET", op.path)) if op.method == "PUT" else None
        name = _class_name(type_)
        attrs: dict[str, Any] = {
            "__module__": __name__,
            "__qualname__": name,
            "type": type_,
            "version": 1,
            "title": _title(op_id),
            "description": _description(op),
            "Config": declared_model(
                f"{name}Config",
                config_schema(doc, op, shape, paging, merge_with is not None),
                formats=(),
                checked=False,
            ),
            "Output": declared_model(f"{name}Output", output_schema(doc, answer, shape), formats=(), checked=False),
            "side_effect": SideEffect(entry.side_effect),
            "capabilities": frozenset({entry.capability}),
            "timeout": timedelta(minutes=5 if paging else 1),
            "operation": op_id,
            "method": op.method,
            "path": op.path,
            "scope": entry.scope,
            "shape": shape,
            "paging": paging,
            "merge_with": merge_with,
        }
        out.append(type(name, (MistOperation,), attrs))
    return tuple(out)


NODES = build()
