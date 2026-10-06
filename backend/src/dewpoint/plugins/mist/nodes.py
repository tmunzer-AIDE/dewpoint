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

from pydantic import BaseModel

from dewpoint.plugins.mist import fixtures, oas, policy, routing
from dewpoint.plugins.mist.client import SEGMENT, InvalidAnswer, InvalidPathValue, MistClient, NotFound, may_have_more
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
# D15: Mist's PUT has no version check (no ETag in the OAS), so a merge update always says so.
RACE = " Merging reads the object first: a change made to it between that read and this write is overwritten."


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
    takes_limit: ClassVar[bool] = False  # its query takes `limit`
    credentials = ("mist",)

    async def options(self, ctx: CallContext, field: str, query: OptionsQuery) -> list[Option]:
        """A path value's choices: one page of the list the map allows at its collection's path, through the
        connection's read-only HTTP, filtered by the typed text, which never enters the request."""
        listed = self.pickers.get(field)
        if listed is None:
            raise NoOptions()
        entry = policy.load().read(self.operation, self.type, listed)  # a read the map must allow (O2, L10)
        if entry is None:
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

    def _merges(self, mode: Any) -> bool:
        """Whether an update reads the object first: `merge` asked, or by default when it may."""
        return self.method == "PUT" and (mode or ("merge" if self.merge_with else "replace")) == "merge"

    def _checked(self, config: Any) -> tuple[dict[str, Any], Any, list[str]]:
        """The config's values once nothing in them stops the request, and the map still allows the operation."""
        values: dict[str, Any] = dict(config.root)
        body, clear = values.get("body"), list(values.get("clear", ()))
        if self.method == "PUT":
            if set(body or {}) & set(clear):
                raise ConflictingChange()
            if not body and not clear:
                raise NothingToChange()
        found = policy.load()
        if found.allowed(self.operation, self.type) is None:
            raise OperationUnavailable()
        if self.scope == "site" and found.read(self.operation, self.type, routing.SITE_CHECK) is None:
            raise OperationUnavailable()  # the site check is a read the map must allow (the owner's review, O2)
        if self._merges(values.get("mode")) and (
            self.merge_with is None or found.read(self.operation, self.type, self.merge_with) is None
        ):
            raise OperationUnavailable()  # so is a merge's read, in a run and a simulation alike; replace reads nothing
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
        try:
            found = fixture_of(type(self))[0]
        except fixtures.FixtureUnavailable:
            raise NotImplementedError from None  # the runtime's `simulation_unavailable`: no fixture fits
        return self.Output.model_construct(copy.deepcopy(found))

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        values, body, clear = self._checked(config)
        client = MistClient(await ctx.connection(uuid.UUID(values["connection"])))
        path = client.path(self.path, values)
        if self.scope == "site":
            try:
                await client.check_site(values["site_id"])
            except NotFound:
                if self.shape == "delete" and ctx.attempt > 1:  # its site gone, so is the object (review M2, D16)
                    gone: Any = {"already_absent": True}
                    return self.Output.model_construct(gone)
                raise
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
            cut = self.takes_limit and may_have_more(answer.body, query)  # a list that pages by `limit` alone
            return {"results": answer.body, "total": None, "truncated": cut}
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
        if not self._merges(mode):
            return {**body, **cleared}
        if self.merge_with is None or policy.load().read(self.operation, self.type, self.merge_with) is None:
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


def _example(doc: Mapping[str, Any], op: oas.Operation) -> Any:
    """The 2xx answer's first example in the OAS, or None."""
    media = oas.media(doc, op)
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


_FIXTURES: dict[str, tuple[Any, str]] = {}


def fixture_of(node: type["MistOperation"]) -> tuple[Any, str]:
    """`_fixture(node)`, made once per node type."""
    if node.type not in _FIXTURES:
        _FIXTURES[node.type] = _fixture(node)
    return _FIXTURES[node.type]


def _fixture(node: type["MistOperation"]) -> tuple[Any, str]:
    """What a simulated step of `node` answers, and where its values come from: a delete's or an action's fixed
    answer; else the output schema's fixture with the OAS example, shaped as the output, laid over (`fixtures`)."""
    if node.shape in ("empty", "delete"):
        return _shaped(node, None), "fixed"
    example = _shaped(node, _example(oas.document(), oas.operations()[node.operation]))
    return fixtures.fixture(node.Output.model_json_schema(), example)


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


def _class_name(type_: str) -> str:
    return "".join(part.title() for part in re.split(r"[._]", type_))


def build() -> tuple[type[Node], ...]:
    """Every allowed operation's curated node, in the map's order."""
    doc, ops, entries = oas.document(), oas.operations(), policy.load().entries
    by_path = {(e.method, e.path): op_id for op_id, e in entries.items() if e.state == "allowed"}
    lists = {e.path: op_id for op_id, e in sorted(entries.items()) if e.state == "allowed"
             and routing.is_list(doc, ops[op_id])}  # fmt: skip
    out: list[type[Node]] = []
    for op_id, entry in sorted(entries.items()):
        if entry.state != "allowed" or entry.side_effect is None:
            continue
        op, type_ = ops[op_id], entry.nodes[0]
        answer = oas.answer(doc, op)
        shape, paging = _shape(doc, op, answer)
        merge_with = by_path.get(("GET", op.path)) if op.method == "PUT" else None
        merge_with = merge_with if merge_with in entry.reads else None  # the map lists every read (O2)
        pickers = {f: o for f, o in routing.pickers(op.path, entry.scope, lists).items() if o in entry.reads}
        name = _class_name(type_)
        attrs: dict[str, Any] = {
            "__module__": __name__,
            "__qualname__": name,
            "type": type_,
            "version": 1,
            "title": _title(op_id),
            "description": _description(op) + (RACE if merge_with is not None else ""),
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
            "takes_limit": any(p["in"] == "query" and p["name"] == "limit" for p in op.parameters),
        }
        out.append(type(name, (MistOperation,), attrs))
    return tuple(out)


NODES = build()
