# SPDX-License-Identifier: Apache-2.0
"""Publish-time validation of a workflow graph (spec §4). Pure: the caller loads the catalog and sub-flow data."""

import contextlib
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Graph, GraphNode
from dewpoint.engine.graph.schemas import (
    PathError,
    Resolved,
    allowed_kinds,
    compatible,
    contains_literal,
    describe,
    element_schema,
    json_types,
    literal_on_path,
    literal_type,
    navigate,
    standalone,
    target_schema,
)
from dewpoint.engine.graph.structure import Structure, analyze_structure
from dewpoint.engine.graph.values import (
    ENVELOPE,
    LiteralValue,
    Pointer,
    RefPath,
    RefValue,
    TemplateRef,
    TemplateValue,
    Value,
    ValueSyntaxError,
    is_envelope,
    iter_values,
    pointer_str,
    strip_values,
)
from dewpoint.engine.registry import control as C
from dewpoint.engine.registry.catalog import Catalog, NodeTypeSpec
from dewpoint.engine.schema_refs import ref_problems
from dewpoint.sdk.fields import KINDS

MAX_SUBFLOW_DEPTH = 5
IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"code": {"type": "string"}, "message": {"type": "string"}, "attempt": {"type": "integer"}},
    "required": ["code", "message", "attempt"],
    "additionalProperties": False,
}
RUN_SCHEMAS: dict[str, dict[str, Any]] = {
    "id": {"type": "string", "format": "uuid"},
    "started_at": {"type": "string", "format": "date-time"},
    "now": {"type": "string", "format": "date-time"},
}
_WHOLE_LITERAL = {(C.SET_VARIABLES, "assignments"), (C.TRANSFORM, "fields")}
_LITERAL_ONLY = "This field must be written directly; it can't come from another step."


@dataclass(frozen=True)
class SubflowInfo:
    workflow_id: uuid.UUID
    version_id: uuid.UUID
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ValidationContext:
    catalog: Catalog
    subflows: Mapping[uuid.UUID, SubflowInfo] = field(default_factory=dict)
    max_run_duration: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class ValidationResult:
    diagnostics: tuple[Diagnostic, ...]
    node_refs: tuple[str, ...] = ()
    subflow_pins: Mapping[str, str] = field(default_factory=dict)  # node id -> pinned version id
    failure_handler_version_id: uuid.UUID | None = None
    output_schema: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def referenced_workflows(graph: Graph) -> set[uuid.UUID]:
    """Workflows this graph pins (run_workflow targets and the failure handler). The caller loads their active
    versions and passes them back through ValidationContext.subflows."""
    out: set[uuid.UUID] = set()
    for n in graph.nodes:
        raw = n.config.get("workflow_id")
        if n.type == C.RUN_WORKFLOW and isinstance(raw, str):
            with contextlib.suppress(ValueError):
                out.add(uuid.UUID(raw))
    if graph.settings.failure_handler is not None:
        out.add(graph.settings.failure_handler)
    return out


@dataclass(frozen=True)
class _Site:
    node: uuid.UUID | None  # None for workflow outputs
    field: str  # JSON pointer, for diagnostics
    region: uuid.UUID | None  # the scope the value is evaluated in
    at_exit: bool = False  # evaluated when that scope ends (loop `collect`, workflow outputs)


def _descendants(s: Structure) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    desc: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
    for n in reversed(s.topo):
        acc: set[uuid.UUID] = set()
        for e in s.out_edges[n]:
            acc.add(e.to.node)
            acc |= desc[e.to.node]
        desc[n] = frozenset(acc)
    return desc


def _object_schema(props: Mapping[str, Mapping[str, Any]], required: list[str]) -> dict[str, Any]:
    """An object schema from per-field schemas, hoisting their $defs to the root so $refs still resolve."""
    defs: dict[str, Any] = {}
    clean: dict[str, Any] = {}
    for name, schema in props.items():
        inner = dict(schema)
        nested = inner.pop("$defs", None)
        if isinstance(nested, Mapping):
            defs.update(nested)
        clean[name] = inner
    out: dict[str, Any] = {"type": "object", "properties": clean, "required": required, "additionalProperties": False}
    if defs:
        out["$defs"] = defs
    return out


def _static_delay(node: GraphNode, spec: NodeTypeSpec) -> float:
    if spec.ref != C.DELAY:
        return 0.0
    raw: Any = node.config.get("duration_s")
    body = raw.get(ENVELOPE) if is_envelope(raw) else None
    if isinstance(body, Mapping) and body.get("kind") == "literal":
        raw = body.get("value")
    return float(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0.0


def _settings(graph: Graph) -> list[Diagnostic]:
    st = graph.settings
    out: list[Diagnostic] = []
    for label, schema in (("input_schema", st.input_schema), ("vars_schema", st.vars_schema)):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            out.append(
                Diagnostic(
                    code="settings.invalid_schema",
                    field=f"/settings/{label}",
                    message=f"Not a valid JSON Schema: {e.message}",
                )
            )
            continue
        if schema.get("type", "object") != "object":
            out.append(
                Diagnostic(
                    code="settings.invalid_schema", field=f"/settings/{label}", message="It must describe an object."
                )
            )
        # Tenant-authored schemas: only resolvable local $refs, so validation can never raise (see schema_refs).
        out += [
            Diagnostic(code="settings.unresolvable_ref", field=f"/settings/{label}", message=f"{problem}.")
            for problem in ref_problems(schema)
        ]
    if any(d.field == "/settings/vars_schema" for d in out):
        return out
    props = st.vars_schema.get("properties", {})
    defs = st.vars_schema.get("$defs", {})
    for name, schema in props.items() if isinstance(props, Mapping) else ():
        where = f"/settings/vars_schema/properties/{name}"
        if not IDENT.match(name):
            out.append(
                Diagnostic(code="vars.invalid_name", field=where, message="Variable names are lowercase identifiers.")
            )
        if not isinstance(schema, Mapping) or "default" not in schema:
            out.append(Diagnostic(code="vars.no_default", field=where, message="Every variable needs a default value."))
        elif list(Draft202012Validator({**schema, "$defs": defs}).iter_errors(schema["default"])):
            out.append(
                Diagnostic(code="vars.bad_default", field=where, message="The default value doesn't match the type.")
            )
    for name in st.outputs:
        if not IDENT.match(name):
            out.append(
                Diagnostic(
                    code="settings.output_name",
                    field=f"/settings/outputs/{name}",
                    message="Output names are lowercase identifiers.",
                )
            )
    return out


class _Validator:
    def __init__(self, graph: Graph, s: Structure, ctx: ValidationContext, settings_ok: bool) -> None:
        self.g, self.s, self.ctx = graph, s, ctx
        self.diags: list[Diagnostic] = []
        self.live = {r: lv.analyze_region(s, r) for r in s.regions}
        self.desc = _descendants(s)
        self.out_schema: dict[uuid.UUID, Mapping[str, Any] | None] = {}
        self.item_schema: dict[uuid.UUID, Mapping[str, Any] | None] = {}
        self.pins: dict[str, str] = {}
        self.failure_handler_version_id: uuid.UUID | None = None
        self.output_schema: dict[str, Any] = {}
        self.deferred: list[tuple[_Site, Value | ValueSyntaxError]] = []
        vars_schema = graph.settings.vars_schema
        props = vars_schema.get("properties") if settings_ok else None
        self.vars: dict[str, Any] = dict(props) if isinstance(props, Mapping) else {}
        self.vars_root: dict[str, Any] = {"type": "object", "properties": self.vars, "additionalProperties": False}
        if settings_ok and isinstance(vars_schema.get("$defs"), Mapping):
            self.vars_root["$defs"] = vars_schema["$defs"]
        self.root_has_stop = any(s.specs[i].ref == C.STOP for i in s.regions[None].members)

    def err(
        self, code: str, message: str, *, node: uuid.UUID | None = None, fld: str | None = None, fix: str | None = None
    ) -> None:
        self.diags.append(Diagnostic(code=code, message=message, node=node, field=fld, fix=fix))

    def run(self) -> None:
        for n_id in self.s.topo:
            self._node(self.s.nodes[n_id])
        for site, value in self.deferred:
            self._value(site, value, None, ())
        self._variables()
        self._waits()
        self._outputs()
        self._failure_handler()

    # ---- per node -------------------------------------------------------------------------------------------

    def _node(self, n: GraphNode) -> None:
        spec = self.s.specs[n.id]
        self._check_literals(n, spec)
        resolved: dict[Pointer, Resolved | None] = {}
        region = self.s.region_of[n.id]
        for pointer, value in iter_values(n.config):
            where = pointer_str(pointer)
            if not pointer or ((spec.ref, pointer[0]) in _WHOLE_LITERAL and len(pointer) == 1):
                self.err("value.literal_only", _LITERAL_ONLY, node=n.id, fld=where)
                continue
            if spec.ref == C.LOOP and pointer[0] == "collect":
                self.deferred.append((_Site(n.id, where, n.id, at_exit=True), value))
                continue
            root, inner = self._value_root(n, spec, pointer)
            resolved[pointer] = self._value(_Site(n.id, where, region), value, root, inner)
        if spec.ref == C.LOOP:
            items = resolved.get(("items",))
            self.item_schema[n.id] = element_schema(items.schema) if items is not None else None
        elif spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            if info is None:
                self.err(
                    "subflow.unknown",
                    "The workflow this step runs doesn't exist here or has no published version.",
                    node=n.id,
                    fld="/workflow_id",
                    fix="Publish that workflow first.",
                )
            else:
                self.pins[str(n.id)] = str(info.version_id)
        self.out_schema[n.id] = self._output_schema(n, spec, resolved)

    def _subflow(self, n: GraphNode) -> SubflowInfo | None:
        raw = n.config.get("workflow_id")
        if not isinstance(raw, str):
            return None
        try:
            return self.ctx.subflows.get(uuid.UUID(raw))
        except ValueError:
            return None

    def _value_root(
        self, n: GraphNode, spec: NodeTypeSpec, pointer: Pointer
    ) -> tuple[Mapping[str, Any] | None, Pointer]:
        if spec.ref == C.SET_VARIABLES and pointer[0] == "assignments":
            return self.vars_root, pointer[1:]
        if spec.ref == C.RUN_WORKFLOW and pointer[0] == "input":
            info = self._subflow(n)
            return (info.input_schema if info else None), pointer[1:]
        return spec.config_schema, pointer

    def _check_literals(self, n: GraphNode, spec: NodeTypeSpec) -> None:
        stripped, envelopes = strip_values(n.config)
        self._schema_errors(n.id, "", spec.config_schema, stripped, envelopes)
        props = spec.config_schema.get("properties")
        for name, prop in props.items() if isinstance(props, Mapping) else ():
            kinds = prop.get(KINDS) if isinstance(prop, Mapping) else None
            written = name in n.config and not is_envelope(n.config[name])
            if isinstance(kinds, list) and "literal" not in kinds and written:
                self.err(
                    "value.kind_not_allowed",
                    f"This field accepts only: {', '.join(sorted(kinds))}.",
                    node=n.id,
                    fld=pointer_str((name,)),
                )
        if not isinstance(stripped, dict):
            return
        if spec.ref == C.SET_VARIABLES and isinstance(stripped.get("assignments"), dict):
            for name, value in stripped["assignments"].items():
                if name in self.vars:
                    inner = [p[2:] for p in envelopes if p[:2] == ("assignments", name)]
                    schema = standalone(self.vars_root, self.vars[name])
                    self._schema_errors(n.id, pointer_str(("assignments", name)), schema, value, inner)
        if spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            if info is not None:
                inner = [p[1:] for p in envelopes if p[:1] == ("input",)]
                self._schema_errors(n.id, "/input", info.input_schema, stripped.get("input", {}), inner)

    def _schema_errors(
        self, node: uuid.UUID, prefix: str, schema: Mapping[str, Any], instance: Any, envelopes: list[Pointer]
    ) -> None:
        errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(list(e.absolute_path)))
        for e in errors:
            path = tuple(e.absolute_path)
            if any(path[: len(p)] == p for p in envelopes):
                continue  # computed at run time; checked through its reference type instead
            self.err("config.invalid", e.message, node=node, fld=prefix + pointer_str(path))

    def _output_schema(
        self, n: GraphNode, spec: NodeTypeSpec, resolved: Mapping[Pointer, Resolved | None]
    ) -> Mapping[str, Any] | None:
        if spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            return info.output_schema if info else None
        if spec.ref == C.TRANSFORM:
            fields = n.config.get("fields")
            if not isinstance(fields, Mapping) or is_envelope(fields):
                return None
            props: dict[str, Mapping[str, Any]] = {}
            required: list[str] = []
            for name in sorted(fields):
                if is_envelope(fields[name]):
                    r = resolved.get(("fields", name))
                    props[name] = r.schema if r is not None and r.schema is not None else {}
                    if r is not None and not r.conditional:
                        required.append(name)
                else:
                    props[name] = {"type": literal_type(fields[name])}
                    required.append(name)
            return _object_schema(props, required)
        return spec.output_schema

    # ---- values ---------------------------------------------------------------------------------------------

    def _value(
        self, site: _Site, value: Value | ValueSyntaxError, root: Mapping[str, Any] | None, pointer: Pointer
    ) -> Resolved | None:
        if isinstance(value, ValueSyntaxError):
            self.err("value.syntax", value.message, node=site.node, fld=site.field)
            return None
        target = target_schema(root, pointer) if root is not None else None
        if (
            root is not None
            and value.kind != "literal"
            and (literal_on_path(root, pointer) or contains_literal(root, target))
        ):
            self.err("value.literal_only", _LITERAL_ONLY, node=site.node, fld=site.field)
            return None
        kinds = allowed_kinds(root, pointer) if root is not None else None
        if kinds is not None and value.kind not in kinds:
            self.err(
                "value.kind_not_allowed",
                f"This field accepts only: {', '.join(sorted(kinds))}.",
                node=site.node,
                fld=site.field,
            )
            return None
        if isinstance(value, LiteralValue):
            self._check_instance(site, target, value.value)
            return Resolved({"type": literal_type(value.value)}, False)
        if isinstance(value, RefValue):
            return self._ref_value(site, value, target)
        if isinstance(value, TemplateValue):
            return self._template(site, value, target)
        self.err(
            "cel.unavailable",
            "CEL expressions aren't available in this build yet.",
            node=site.node,
            fld=site.field,
            fix="Use a reference or a template for now.",
        )
        return None

    def _check_instance(self, site: _Site, schema: Mapping[str, Any] | None, instance: Any) -> None:
        if schema is None:
            return
        for e in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(list(e.absolute_path))):
            self.err("config.invalid", e.message, node=site.node, fld=site.field + pointer_str(tuple(e.absolute_path)))

    def _ref_value(self, site: _Site, value: RefValue, target: Mapping[str, Any] | None) -> Resolved | None:
        resolved = self._resolve(site, value.path)
        if resolved is None:
            return None
        if resolved.conditional and not value.has_default:
            self.err(
                "ref.conditional",
                f"`{value.path.text}` may be missing when this runs: a branch may skip it, or the field is optional.",
                node=site.node,
                fld=site.field,
                fix="Add a default value.",
            )
        if not compatible(resolved.schema, target):
            self.err(
                "ref.type_mismatch",
                f"`{value.path.text}` is {describe(resolved.schema)}, but this field expects {describe(target)}.",
                node=site.node,
                fld=site.field,
            )
        if value.has_default:
            self._check_instance(site, target, value.default)
        return Resolved(resolved.schema, resolved.conditional and not value.has_default)

    def _template(self, site: _Site, value: TemplateValue, target: Mapping[str, Any] | None) -> Resolved:
        if target is not None and not compatible({"type": "string"}, target):
            self.err(
                "template.not_string", "Text with references can only fill text fields.", node=site.node, fld=site.field
            )
        for part in value.parts:
            if not isinstance(part, TemplateRef):
                continue
            r = self._resolve(site, part.path)
            if r is None:
                continue
            if r.conditional and part.default is None:
                self.err(
                    "ref.conditional",
                    f"`{part.path.text}` may be missing when this runs.",
                    node=site.node,
                    fld=site.field,
                    fix="Give this part a default.",
                )
            types = json_types(r.schema)
            if types is not None and types & {"object", "array"}:
                self.err(
                    "template.part_not_scalar",
                    f"`{part.path.text}` is {describe(r.schema)}; only text, numbers and booleans go into text.",
                    node=site.node,
                    fld=site.field,
                )
        return Resolved({"type": "string"}, False)

    # ---- references -----------------------------------------------------------------------------------------

    def _resolve(self, site: _Site, p: RefPath) -> Resolved | None:
        try:
            if p.root == "trigger":
                return navigate(self.g.settings.input_schema, p.rest)
            if p.root == "run":
                return Resolved(RUN_SCHEMAS[str(p.section)], False)
            if p.root == "vars":
                if p.name not in self.vars:
                    self.err(
                        "ref.unknown_var", f"`{p.name}` isn't a declared variable.", node=site.node, fld=site.field
                    )
                    return None
                return navigate(self.vars_root, p.rest, start=self.vars[str(p.name)])
            if p.root in ("loop", "loops"):
                return self._resolve_loop(site, p)
            return self._resolve_step(site, p)
        except PathError as e:
            self.err("ref.unknown_field", f"`{p.text}`: {e}", node=site.node, fld=site.field)
            return None

    def _resolve_loop(self, site: _Site, p: RefPath) -> Resolved | None:
        if p.root == "loop":
            loop = site.region
            if loop is None:
                self.err(
                    "ref.loop_outside",
                    "`loop.*` is only available inside a loop's body.",
                    node=site.node,
                    fld=site.field,
                )
                return None
        else:
            found = self.s.by_key.get(str(p.name))
            if found is None or self.s.specs[found].ref != C.LOOP:
                self.err("ref.unknown_step", f"There's no loop called `{p.name}`.", node=site.node, fld=site.field)
                return None
            if found not in self.s.chain(site.region):
                self.err(
                    "ref.loop_outside",
                    f"`{p.text}` is only available inside loop `{p.name}`.",
                    node=site.node,
                    fld=site.field,
                )
                return None
            loop = found
        if p.section == "index":
            return Resolved({"type": "integer"}, False)
        item = self.item_schema.get(loop)
        if item is None:
            return Resolved(None, bool(p.rest))
        return navigate(item, p.rest)

    def _resolve_step(self, site: _Site, p: RefPath) -> Resolved | None:
        producer = self.s.by_key.get(str(p.name))
        if producer is None:
            self.err("ref.unknown_step", f"There's no step called `{p.name}`.", node=site.node, fld=site.field)
            return None
        home = self.s.region_of[producer]
        chain = self.s.chain(site.region)
        if home not in chain:
            self.err(
                "ref.out_of_scope",
                f"`{p.name}` runs inside a loop body, so its result isn't available here.",
                node=site.node,
                fld=site.field,
                fix="Return it through the loop's `collect` value.",
            )
            return None
        region = self.live[home]
        consumer: lv.Cond
        if home == site.region and site.at_exit:
            consumer, upstream = region.exit, True
        elif home == site.region and site.node is not None:
            consumer, upstream = region.live[site.node], site.node in self.desc[producer]
        else:
            ancestor = chain[chain.index(home) - 1]  # the loop node, in `home`, that contains the consumer
            if ancestor is None:
                return None
            consumer, upstream = region.live[ancestor], ancestor in self.desc[producer]
        if not upstream:
            self.err(
                "ref.not_upstream",
                f"`{p.name}` doesn't run before this step.",
                node=site.node,
                fld=site.field,
                fix="Connect it upstream of this step.",
            )
            return None
        on_error = self.s.nodes[producer].options.on_error
        if p.section == "error":
            if on_error == "fail":
                self.err(
                    "ref.no_error_output",
                    f"`{p.name}` stops the run when it fails, so it never has an error value.",
                    node=site.node,
                    fld=site.field,
                    fix="Set its error behaviour to continue or to an error output.",
                )
                return None
            available = on_error == "port" and lv.implies(consumer, region.err[producer])
            r = navigate(ERROR_SCHEMA, p.rest)
            return Resolved(r.schema, r.conditional or not available)
        available = on_error != "continue" and lv.implies(consumer, region.ok[producer])
        if site.at_exit and site.region is None and self.root_has_stop:
            available = False  # `stop` may end the run while this step is still pending
        schema = self.out_schema.get(producer)
        if schema is None:  # only when the producer is already reported (unknown sub-flow): don't add noise
            return Resolved(None, not available)
        r = navigate(schema, p.rest)
        return Resolved(r.schema, r.conditional or not available)

    # ---- whole-graph checks ---------------------------------------------------------------------------------

    def _variables(self) -> None:
        writers: dict[str, list[uuid.UUID]] = {}
        for n_id in self.s.topo:
            n = self.s.nodes[n_id]
            if self.s.specs[n_id].ref != C.SET_VARIABLES:
                continue
            if self.s.region_of[n_id] is not None:
                self.err(
                    "vars.write_in_loop",
                    "Variables can't be set inside a loop body.",
                    node=n_id,
                    fix="Return per-item results through the loop's `collect` value.",
                )
                continue
            assignments = n.config.get("assignments")
            if not isinstance(assignments, Mapping) or is_envelope(assignments):
                continue
            for name in assignments:
                if name not in self.vars:
                    self.err(
                        "vars.undeclared",
                        f"`{name}` isn't declared.",
                        node=n_id,
                        fld=pointer_str(("assignments", name)),
                        fix="Declare it in the workflow's variables.",
                    )
                    continue
                writers.setdefault(name, []).append(n_id)
        root = self.live[None]
        for name, nodes in writers.items():
            for i, a in enumerate(nodes):
                for b in nodes[i + 1 :]:
                    ordered = b in self.desc[a] or a in self.desc[b]
                    if not ordered and not lv.exclusive(root.live[a], root.live[b]):
                        self.err(
                            "vars.concurrent_writers",
                            f"`{self.s.nodes[a].key}` and `{self.s.nodes[b].key}` can both set `{name}` at once.",
                            node=b,
                            fix="Order them, or put them on exclusive branches.",
                        )

    def _waits(self) -> None:
        limit = self.ctx.max_run_duration.total_seconds()
        longest: dict[uuid.UUID, float] = {}
        for n_id in self.s.topo:
            before = max((longest[e.source.node] for e in self.s.in_edges[n_id]), default=0.0)
            own = _static_delay(self.s.nodes[n_id], self.s.specs[n_id])
            longest[n_id] = before + own
            if own and longest[n_id] > limit:
                self.err(
                    "wait.exceeds_deadline",
                    f"Waits on this path add up to {longest[n_id] / 86_400:.1f} days, more than the "
                    f"{limit / 86_400:.0f}-day run limit.",
                    node=n_id,
                )

    def _outputs(self) -> None:
        props: dict[str, Mapping[str, Any]] = {}
        required: list[str] = []
        for name in sorted(self.g.settings.outputs):
            raw = self.g.settings.outputs[name]
            where = pointer_str(("settings", "outputs", name))
            if is_envelope(raw):
                [(_, value)] = list(iter_values(raw))
                r = self._value(_Site(None, where, None, at_exit=True), value, None, ())
                props[name] = r.schema if r is not None and r.schema is not None else {}
                if r is not None and not r.conditional:
                    required.append(name)
                continue
            for pointer, value in iter_values(raw):
                self._value(_Site(None, where + pointer_str(pointer), None, at_exit=True), value, None, ())
            props[name] = {"type": literal_type(raw)}
            required.append(name)
        self.output_schema = _object_schema(props, required)

    def _failure_handler(self) -> None:
        workflow = self.g.settings.failure_handler
        if workflow is None:
            return
        info = self.ctx.subflows.get(workflow)
        if info is None:
            self.err(
                "subflow.unknown",
                "The failure-handler workflow doesn't exist here or has no published version.",
                fld="/settings/failure_handler",
            )
        else:
            self.failure_handler_version_id = info.version_id


def validate(graph: Graph, ctx: ValidationContext) -> ValidationResult:
    settings = _settings(graph)
    structure, structural = analyze_structure(graph, ctx.catalog)
    node_refs = tuple(sorted({n.type for n in graph.nodes}))
    if structure is None:
        return ValidationResult(tuple([*settings, *structural]), node_refs)
    unusable = ("settings.invalid_schema", "settings.unresolvable_ref")
    v = _Validator(graph, structure, ctx, settings_ok=not any(d.code in unusable for d in settings))
    v.run()
    return ValidationResult(
        diagnostics=tuple([*settings, *structural, *v.diags]),
        node_refs=node_refs,
        subflow_pins=dict(v.pins),
        failure_handler_version_id=v.failure_handler_version_id,
        output_schema=v.output_schema,
    )
