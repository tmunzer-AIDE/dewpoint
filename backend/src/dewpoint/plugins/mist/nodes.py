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

import copy
import re
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, ClassVar

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from dewpoint.plugins.mist import oas, policy, routing
from dewpoint.plugins.mist.client import SEGMENT, InvalidAnswer, InvalidPathValue, MistClient, NotFound
from dewpoint.plugins.mist.schemas import converted, resolved, top_properties, with_defs
from dewpoint.sdk import (
    CallContext,
    FatalError,
    Node,
    Option,
    OptionsQuery,
    SideEffect,
    StepContext,
    declared_model,
)
from dewpoint.sdk.fields import CONNECTION, LITERAL, OPTIONS

PAGE_CAP = 10
OPTIONS_PAGE = 1000  # a picker reads one page of a list, filtered by the typed text
LABEL_FIELDS = ("name", "ssid")
JSON_TYPES = ("application/json", "application/vnd.api+json", "application/vnd.json+api")


class OperationUnavailable(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.operation_unavailable", "This Mist operation isn't allowed in this build.")


class NoOptions(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.no_options", "This field has no choices to list.")


class ConnectionRequired(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.connection_required", "Choose the node's Mist connection first.")


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
    pickers: ClassVar[Mapping[str, str]] = {}  # an options field and the list operation it reads
    credentials = ("mist",)

    async def options(self, ctx: CallContext, field: str, query: OptionsQuery) -> list[Option]:
        """A path value's choices: one page of the list the map allows at its collection's path, through the
        connection's read-only HTTP, filtered by the typed text, which never enters the request."""
        listed = self.pickers.get(field)
        if listed is None:
            raise NoOptions()
        found = policy.load()
        entry = found.entries.get(listed)
        if found.allowed(self.operation, self.type) is None or entry is None or entry.state != "allowed":
            raise OperationUnavailable()
        if query.connection_id is None:
            raise ConnectionRequired()
        client = MistClient(await ctx.connection(query.connection_id))
        answer = await client.call("GET", client.path(entry.path, {}), query={"limit": OPTIONS_PAGE})
        if not isinstance(answer.body, list):
            raise InvalidAnswer()
        key, text = ("mac" if field.endswith("_mac") else "id"), query.text.lower()
        out: list[Option] = []
        for item in answer.body:
            value = item.get(key) if isinstance(item, Mapping) else None
            if not isinstance(value, str) or not 0 < len(value) <= 1000:
                continue
            label = next((item[k] for k in LABEL_FIELDS if isinstance(item.get(k), str) and item[k].strip()), value)
            if text in label.lower() or text in value.lower():
                out.append(Option(value, label[:200]))
        return sorted(out, key=lambda o: (o.label.lower(), o.value))

    def _checked(self, config: Any) -> tuple[dict[str, Any], Any, list[str]]:
        """The config's values once nothing in them stops the request, and the map still allows the operation."""
        values: dict[str, Any] = dict(config.root)
        body, clear = values.get("body"), list(values.get("clear", ()))
        if self.method == "PUT":
            if set(body or {}) & set(clear):
                raise ConflictingChange()
            if not body and not clear:
                raise NothingToChange()
        if policy.load().allowed(self.operation, self.type) is None:
            raise OperationUnavailable()
        checks = routing.checkers(self.operation).path
        for name, check in checks.items():
            value = values.get(name)
            if name != "org_id" and (not isinstance(value, str) or not SEGMENT.fullmatch(value)
                                     or not check.is_valid(value)):  # fmt: skip
                raise InvalidPathValue()
        concrete = routing.filled(self.path, values)
        if policy.refused(concrete) or routing.reaches(self.method, concrete) != self.operation:
            raise InvalidPathValue()  # a value that is another operation's literal, or ties with one (review H1)
        return values, body, clear

    async def simulate(self, ctx: StepContext, config: Any) -> BaseModel:
        """The operation's fixture (D13), never a request: the connection isn't even opened."""
        self._checked(config)
        return self.Output.model_construct(copy.deepcopy(fixture_of(type(self))[0]))

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        values, body, clear = self._checked(config)
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


def _media(doc: Mapping[str, Any], op: oas.Operation) -> Mapping[str, Any] | None:
    """The 2xx answer's JSON media object, or None when the operation answers nothing."""
    responses = op.spec.get("responses", {})
    found = oas.resolve(doc, responses.get("200") or responses.get("201") or {})
    content = found.get("content") or {}
    media = next((content[t] for t in JSON_TYPES if t in content), None)
    return media if isinstance(media, Mapping) else None


def _answer(doc: Mapping[str, Any], op: oas.Operation) -> Any:
    """The 2xx answer's JSON schema, or None when the operation answers nothing."""
    media = _media(doc, op)
    return media.get("schema") if media is not None else None


def _example(doc: Mapping[str, Any], op: oas.Operation) -> Any:
    """The 2xx answer's first example in the OAS, or None."""
    media = _media(doc, op)
    if media is None:
        return None
    if "example" in media:
        return media["example"]
    for example in (media.get("examples") or {}).values():
        found = oas.resolve(doc, example)
        if isinstance(found, Mapping) and "value" in found:
            return found["value"]
    return None


def _shaped(node: type["MistOperation"], answer: Any) -> Any:
    """An answer as the node outputs it, or None when it can't be."""
    if node.shape == "empty":
        return {}
    if node.shape == "delete":
        return {"already_absent": False}
    if node.shape == "list":
        if not isinstance(answer, list):
            return None
        return {"results": answer, "total": len(answer) if node.paging else None, "truncated": False}
    if not isinstance(answer, dict):
        return None
    if node.shape == "search":
        return {**{k: v for k, v in answer.items() if k != "next"}, "truncated": False}
    return answer


def synthesized(schema: Mapping[str, Any], node: Any = None, depth: int = 0) -> Any:
    """The smallest value `node` (in `schema`, whose `$defs` it may name) accepts: an object of its required fields,
    an empty array or string, zero, false or null; a union's first branch."""
    node = schema if node is None else node
    if not isinstance(node, Mapping) or depth > 32:
        return None
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return synthesized(schema, schema.get("$defs", {}).get(ref[len("#/$defs/") :]), depth + 1)
    for key in ("anyOf", "oneOf"):
        if node.get(key):
            return synthesized(schema, node[key][0], depth + 1)
    if node.get("allOf"):
        parts = [synthesized(schema, sub, depth + 1) for sub in node["allOf"]]
        objects = [p for p in parts if isinstance(p, dict)]
        return {k: v for p in objects for k, v in p.items()} if objects else parts[0]
    kind = node.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "object" or (kind is None and "properties" in node):
        props = node.get("properties", {})
        return {name: synthesized(schema, props.get(name, {}), depth + 1) for name in node.get("required", ())}
    return {"array": [], "string": "", "integer": 0, "number": 0, "boolean": False}.get(str(kind))


_FIXTURES: dict[str, tuple[Any, str]] = {}


def fixture_of(node: type["MistOperation"]) -> tuple[Any, str]:
    """`_fixture(node)`, made once per node type."""
    if node.type not in _FIXTURES:
        _FIXTURES[node.type] = _fixture(node)
    return _FIXTURES[node.type]


def _fixture(node: type["MistOperation"]) -> tuple[Any, str]:
    """What a simulated step of `node` answers, and where it comes from: a delete's or an action's fixed answer; the
    OAS's example, shaped as the output, when the output schema accepts it; else a value made from the schema."""
    if node.shape in ("empty", "delete"):
        return _shaped(node, None), "fixed"
    doc = oas.document()
    schema = node.Output.model_json_schema()
    validator = Draft202012Validator(schema)
    shaped = _shaped(node, _example(doc, oas.operations()[node.operation]))
    if shaped is not None and validator.is_valid(shaped):
        return shaped, "example"
    made = synthesized(schema)
    if not validator.is_valid(made):  # a schema no small value satisfies: the build fails, not a simulated step
        raise ValueError(f"{node.type}: no fixture matches its output schema")
    return made, "schema"


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
    doc: Mapping[str, Any],
    op: oas.Operation,
    shape: str,
    paging: str | None,
    merge: bool,
    pickers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    update = op.method == "PUT"
    props: dict[str, Any] = {
        "connection": {"type": "string", "format": "uuid", "title": "Connection", LITERAL: True, CONNECTION: "mist"}
    }
    required = ["connection"]
    roots: list[Any] = []
    for p in op.parameters:
        if p["in"] == "path" and p["name"] != "org_id":
            props[p["name"]] = {
                "title": _title(p["name"]),
                **converted(p.get("schema", {}), output=False),
                "pattern": f"^{routing.value_pattern(op.id, p['name'])}$",  # publish refuses another route's literal
            }
            if p["name"] in (pickers or {}):
                props[p["name"]][OPTIONS] = True
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


def _pickers(doc: Mapping[str, Any], op: oas.Operation, scope: str | None, lists: Mapping[str, str]) -> dict[str, str]:
    """A node's options fields and the list each reads: a site-scope node's site from the org's sites; an org
    resource's id (or MAC) from the list the map allows at its collection's path."""
    out: dict[str, str] = {}
    segments = op.path.split("/")
    if scope == "site" and "/api/v1/orgs/{org_id}/sites" in lists:
        out["site_id"] = lists["/api/v1/orgs/{org_id}/sites"]
    if scope == "org" and len(segments) > 6 and segments[6].startswith("{"):
        name, collection = segments[6][1:-1], "/".join(segments[:6])
        if collection in lists and name.endswith(("_id", "_mac")):
            out[name] = lists[collection]
    return out


def _class_name(type_: str) -> str:
    return "".join(part.title() for part in re.split(r"[._]", type_))


def build() -> tuple[type[Node], ...]:
    """Every allowed operation's curated node, in the map's order."""
    doc, ops, entries = oas.document(), oas.operations(), policy.load().entries
    by_path = {(e.method, e.path): op_id for op_id, e in entries.items() if e.state == "allowed"}
    lists = {
        e.path: op_id for op_id, e in entries.items() if e.state == "allowed" and e.method == "GET"
        and _shape(doc, ops[op_id], _answer(doc, ops[op_id]))[0] == "list"
    }  # fmt: skip
    out: list[type[Node]] = []
    for op_id, entry in sorted(entries.items()):
        if entry.state != "allowed" or entry.side_effect is None:
            continue
        op, type_ = ops[op_id], entry.nodes[0]
        answer = _answer(doc, op)
        shape, paging = _shape(doc, op, answer)
        merge_with = by_path.get(("GET", op.path)) if op.method == "PUT" else None
        pickers = _pickers(doc, op, entry.scope, lists)
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
                config_schema(doc, op, shape, paging, merge_with is not None, pickers),
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
            "pickers": pickers,
        }
        out.append(type(name, (MistOperation,), attrs))
    return tuple(out)


NODES = build()
