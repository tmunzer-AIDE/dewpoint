# SPDX-License-Identifier: Apache-2.0
"""Publish-time validation of a workflow graph (spec §4). Pure: the caller loads the catalog and sub-flow data."""

import contextlib
import dataclasses
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph import cel_check
from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.diagnostics import Diagnostic, Severity
from dewpoint.engine.graph.model import Graph, GraphNode
from dewpoint.engine.graph.schemas import (
    PathError,
    Resolved,
    allowed_kinds,
    compatible,
    contains_literal,
    declared_nullable,
    declared_optional,
    describe,
    element_schema,
    json_types,
    literal_on_path,
    literal_type,
    navigate,
    object_schema,
    standalone,
    target_schema,
    widen,
)
from dewpoint.engine.graph.structure import Structure, analyze_structure
from dewpoint.engine.graph.values import (
    CEL_KEYWORDS,
    ENVELOPE,
    CelValue,
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
from dewpoint.engine.schema_refs import ref_problems, subschemas
from dewpoint.engine.sensitive import SENSITIVE, empty, expand, is_marked, marked_positions
from dewpoint.engine.taint import CLEAN, TAINTED, Shape, from_schema, make
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
    output_taint: Mapping[str, Any] | None = None  # its version's: each output's `Shape` JSON; None: unknown


@dataclass(frozen=True)
class TaintFacts:
    """What one pass of the analysis learns that reads anywhere depend on (engine 2b spec §4.1): the variables some
    assignment taints, and the loops whose collected values are tainted. The analysis runs again until they stop
    changing; they only grow, so it ends."""

    vars: frozenset[str] = frozenset()
    collects: frozenset[uuid.UUID] = frozenset()


NO_FACTS = TaintFacts()


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
    expressions: tuple[ExpressionRecord, ...] = ()  # every CEL value, classified (spec §5.5)
    tainted_sites: tuple[tuple[str | None, str], ...] = ()  # (node id, field) of every tainted value (2b spec §4.1)
    output_taint: Mapping[str, Any] = field(default_factory=dict)  # each workflow output's `Shape`, as JSON

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
    item_node: uuid.UUID | None = None  # whose `item` and `index` are in scope: the innermost loop, or a filter


def _descendants(s: Structure) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    desc: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
    for n in reversed(s.topo):
        acc: set[uuid.UUID] = set()
        for e in s.out_edges[n]:
            acc.add(e.to.node)
            acc |= desc[e.to.node]
        desc[n] = frozenset(acc)
    return desc


def _static_delay(node: GraphNode, spec: NodeTypeSpec) -> float:
    if spec.ref != C.DELAY:
        return 0.0
    raw: Any = node.config.get("duration_s")
    body = raw.get(ENVELOPE) if is_envelope(raw) else None
    if isinstance(body, Mapping) and body.get("kind") == "literal":
        raw = body.get("value")
    return float(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0.0


def _regex_keywords(schema: Any) -> list[str]:
    """Pointers of `pattern` / `patternProperties` in schema positions of a tenant-authored schema."""
    found: list[str] = []
    stack: list[tuple[Any, str]] = [(schema, "")]
    while stack:
        node, path = stack.pop()
        if not isinstance(node, Mapping):
            continue
        found += [f"{path}/{key}" for key in ("pattern", "patternProperties") if key in node]
        stack.extend((sub, path + suffix) for suffix, sub in subschemas(node))
    return sorted(found)


_SENSITIVE_LITERAL = (
    "A sensitive value can't be written into the workflow: pass it in the run's input, in a field marked sensitive."
)


def _writes_sensitive(
    value: Value, root: Mapping[str, Any], pointer: Pointer, target: Mapping[str, Any] | None
) -> bool:
    """Whether a value envelope writes a literal at a sensitive position (§3.8): the literal itself, a part of it the
    target schema marks, or a reference's or a template's default."""
    if isinstance(value, LiteralValue):
        if empty(value.value):
            return False
        return is_marked(root, pointer) or bool(target is not None and marked_positions(value.value, target))
    if not is_marked(root, pointer):
        return False
    if isinstance(value, RefValue):
        return value.has_default and not empty(value.default)
    if isinstance(value, TemplateValue):
        return any(isinstance(p, TemplateRef) and not empty(p.default) for p in value.parts)
    return False


def _sensitive_defaults(label: str, schema: Mapping[str, Any]) -> list[Diagnostic]:
    """A `default` at a position the schema marks sensitive, or holding a part it does (engine 2b spec §3.8): a
    secret written into the version. A null or empty default writes nothing."""
    found: list[str] = []

    def walk(node: Any, path: str, inherited: bool) -> None:
        if not isinstance(node, Mapping):
            return
        branches = expand(node, schema)
        here = inherited or any(b.get(SENSITIVE) is True for b in branches)
        defaults = [b["default"] for b in branches if "default" in b and not empty(b["default"])]
        if defaults and (here or any(marked_positions(d, node, schema) for d in defaults)):
            found.append(path)
        for suffix, sub in subschemas(node):
            walk(sub, path + suffix, here)

    walk(schema, "", False)
    return [
        Diagnostic(code="sensitive.default", field=f"/settings/{label}{where}", message=_SENSITIVE_LITERAL)
        for where in found
    ]


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
        regexes = _regex_keywords(schema)
        out += [
            Diagnostic(
                code="settings.unsupported_keyword",
                field=f"/settings/{label}{where}",
                message="Regular-expression keywords (`pattern`, `patternProperties`) aren't supported in workflow "
                "schemas yet: Python's regex engine can take exponential time on some inputs.",
            )
            for where in regexes
        ]
        # Tenant-authored schemas: only resolvable local $refs, so validation can never raise (see schema_refs).
        out += [
            Diagnostic(code="settings.unresolvable_ref", field=f"/settings/{label}", message=f"{problem}.")
            for problem in ref_problems(schema)
        ]
    for label, schema in (("input_schema", st.input_schema), ("vars_schema", st.vars_schema)):
        if not any((d.field or "").startswith(f"/settings/{label}") for d in out):
            out += _sensitive_defaults(label, schema)
    if any((d.field or "").startswith("/settings/vars_schema") for d in out):  # never run defaults through it
        return out
    props = st.vars_schema.get("properties", {})
    defs = st.vars_schema.get("$defs", {})
    for name, schema in props.items() if isinstance(props, Mapping) else ():
        where = f"/settings/vars_schema/properties/{name}"
        if not IDENT.match(name) or name in CEL_KEYWORDS:
            out.append(
                Diagnostic(
                    code="vars.invalid_name",
                    field=where,
                    message="Variable names are lowercase identifiers, and not `in`, `true`, `false` or `null`.",
                )
            )
        if not isinstance(schema, Mapping) or "default" not in schema:
            if not is_marked(st.vars_schema, (name,)):  # a sensitive variable is null until a step sets it
                out.append(
                    Diagnostic(code="vars.no_default", field=where, message="Every variable needs a default value.")
                )
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
    def __init__(
        self, graph: Graph, s: Structure, ctx: ValidationContext, settings_ok: bool, facts: TaintFacts = NO_FACTS
    ) -> None:
        self.g, self.s, self.ctx, self.facts = graph, s, ctx, facts
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
        # `stop` anywhere, inside a loop body too, ends the whole run: outputs may miss steps that hadn't run yet
        self.has_stop = any(spec.ref == C.STOP for spec in s.specs.values())
        self.availability: dict[tuple[Any, ...], bool] = {}
        self.expressions: list[ExpressionRecord] = []
        # taint (2b spec §4.1): its sources, each node's output, each loop's element, and what this pass learns
        self.trigger_shape = from_schema(graph.settings.input_schema) if settings_ok else TAINTED
        self.vars_shape = from_schema(self.vars_root)
        self.out_taint: dict[uuid.UUID, Shape] = {}
        self.item_taint: dict[uuid.UUID, Shape] = {}
        self.site_taint: dict[tuple[uuid.UUID | None, str], bool] = {}
        self.assigned: set[str] = set()
        self.collected_tainted: set[uuid.UUID] = set()
        self.output_taint: dict[str, Any] = {}

    def err(
        self,
        code: str,
        message: str,
        *,
        node: uuid.UUID | None = None,
        fld: str | None = None,
        fix: str | None = None,
        severity: Severity = "error",
    ) -> None:
        self.diags.append(Diagnostic(code=code, message=message, node=node, field=fld, fix=fix, severity=severity))

    def run(self) -> None:
        for n in self.g.nodes:
            if n.key in CEL_KEYWORDS:
                self.err(
                    "graph.reserved_key",
                    f"`{n.key}` can't be a step key: expressions couldn't refer to it.",
                    node=n.id,
                    fix="Rename the step.",
                )
        for n_id in self.s.topo:
            self._node(self.s.nodes[n_id])
        for site, value in self.deferred:
            collect = self._value(site, value, None, ())
            if collect is not None and collect.taint.tainted and site.node is not None:
                self.collected_tainted.add(site.node)
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
        values = list(iter_values(n.config))
        if spec.ref in (C.LOOP, C.FILTER):  # `items` first: the predicate and `collect` read its element type
            values.sort(key=lambda pv: pv[0][:1] != ("items",))
        for pointer, value in values:
            where = pointer_str(pointer)
            if not pointer or ((spec.ref, pointer[0]) in _WHOLE_LITERAL and len(pointer) == 1):
                self.err("value.literal_only", _LITERAL_ONLY, node=n.id, fld=where)
                continue
            if spec.ref == C.LOOP and pointer[0] == "collect":
                self.deferred.append((_Site(n.id, where, n.id, at_exit=True, item_node=n.id), value))
                continue
            item_node = n.id if spec.ref == C.FILTER and pointer[0] == "predicate" else region
            root, inner = self._value_root(n, spec, pointer)
            resolved[pointer] = self._value(_Site(n.id, where, region, item_node=item_node), value, root, inner)
            if spec.ref in (C.LOOP, C.FILTER) and pointer == ("items",):
                items = resolved[pointer]
                self.item_schema[n.id] = element_schema(items.schema) if items is not None else None
                self.item_taint[n.id] = items.taint.element() if items is not None else TAINTED
        if spec.ref in (C.LOOP, C.FILTER) and n.id not in self.item_taint:
            self.item_taint[n.id] = CLEAN  # written in the workflow: nothing tainted (sensitive literals are refused)
        if spec.ref == C.SET_VARIABLES:
            for pointer, r in resolved.items():
                if pointer[:1] == ("assignments",) and len(pointer) >= 2 and r is not None and r.taint.tainted:
                    self.assigned.add(str(pointer[1]))
        if spec.ref == C.RUN_WORKFLOW:
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
        self.out_taint[n.id] = self._output_taint(n, spec, resolved)

    def _output_taint(self, n: GraphNode, spec: NodeTypeSpec, resolved: Mapping[Pointer, Resolved | None]) -> Shape:
        """What a node's output holds that's tainted (§4.1)."""

        def under(prefix: Pointer) -> Shape:
            exact = resolved.get(prefix)
            if exact is not None:
                return exact.taint
            deeper = [r for p, r in resolved.items() if p[: len(prefix)] == prefix and r is not None]
            return TAINTED if any(r.taint.tainted for r in deeper) else CLEAN

        if spec.ref == C.TRANSFORM:
            fields = n.config.get("fields")
            names = sorted(fields) if isinstance(fields, Mapping) and not is_envelope(fields) else []
            return make([(name, under(("fields", name))) for name in names])
        if spec.ref == C.LOOP:  # its count and failures stay plain; its collected items take `collect`'s taint
            return make([("items", make(items=TAINTED) if n.id in self.facts.collects else CLEAN)])
        if spec.ref == C.FILTER:  # tainted items or predicate: the kept items stay tainted; the count is plain
            source, predicate = under(("items",)), under(("predicate",))
            return make([("items", TAINTED if source.tainted or predicate.tainted else CLEAN)])
        if spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            if info is None or info.output_taint is None:
                return TAINTED  # a version without a taint map: unknown counts as tainted
            return make([(name, Shape.from_json(t)) for name, t in info.output_taint.items()])
        if spec.ref in C.CONTROL_TYPES:
            return CLEAN
        return from_schema(spec.output_schema)  # a plugin's: its sensitive positions, and what it doesn't declare

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
        self._sensitive_literals(n, spec, stripped)
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

    def _sensitive_literals(self, n: GraphNode, spec: NodeTypeSpec, stripped: Any) -> None:
        """Config written as literals where a schema marks it sensitive (engine 2b spec §3.8): the node's own config,
        a variable an assignment writes, a child's input. Envelopes are checked where they're resolved (`_value`)."""
        own: Any = stripped
        parts: list[tuple[str, Any, Mapping[str, Any] | None]] = []
        if isinstance(stripped, dict) and spec.ref == C.SET_VARIABLES:
            own = {k: v for k, v in stripped.items() if k != "assignments"}
            parts.append(("/assignments", stripped.get("assignments"), self.vars_root))
        elif isinstance(stripped, dict) and spec.ref == C.RUN_WORKFLOW:
            own = {k: v for k, v in stripped.items() if k != "input"}
            info = self._subflow(n)
            parts.append(("/input", stripped.get("input"), info.input_schema if info else None))
        parts.append(("", own, spec.config_schema))
        for prefix, value, schema in parts:
            if isinstance(schema, Mapping):
                for where in marked_positions(value, schema):
                    self.err("sensitive.literal", _SENSITIVE_LITERAL, node=n.id, fld=prefix + where)

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
            return object_schema(props, required)
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
        if root is not None and _writes_sensitive(value, root, pointer, target):
            self.err("sensitive.literal", _SENSITIVE_LITERAL, node=site.node, fld=site.field)
        out: Resolved | None
        if isinstance(value, LiteralValue):
            self._check_instance(site, target, value.value)
            out = Resolved({"type": literal_type(value.value)}, False)
        elif isinstance(value, RefValue):
            out = self._ref_value(site, value, target)
        elif isinstance(value, TemplateValue):
            out = self._template(site, value, target)
        else:
            out = self._cel(site, value, target)
        if out is not None:
            self.site_taint[(site.node, site.field)] = out.taint.tainted
        return out

    def _cel(self, site: _Site, value: CelValue, target: Mapping[str, Any] | None) -> Resolved | None:
        context = _CelSite(self, site)
        result = cel_check.check(
            value.expr, target, context, node=str(site.node) if site.node else None, field=site.field
        )
        if result.record is not None:
            self.expressions.append(result.record)
        if result.resolved is None:
            return None
        whole_roots = {p.path[0] for p in result.record.projections if len(p.path) == 1} if result.record else set()
        tainted = context.tainted or any(self._root_tainted(site, root) for root in whole_roots)
        return dataclasses.replace(result.resolved, taint=TAINTED if tainted else CLEAN)

    def _root_tainted(self, site: _Site, root: str) -> bool:
        """A CEL expression that reads a root whole (§4.1: a whole read is tainted if any part of it is)."""
        if root == "trigger":
            return self.trigger_shape.tainted
        if root == "vars":
            return self.vars_shape.tainted or bool(self.facts.vars)
        if root in ("run", "index"):
            return False
        if root == "item":
            return site.item_node is None or self.item_taint.get(site.item_node, TAINTED).tainted
        return True  # `steps` or `loops` read whole: on the safe side

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
        if not value.has_default:
            return resolved
        self._check_instance(site, target, value.default)
        return Resolved(widen(resolved.schema, value.default), False, resolved.taint)

    def _template(self, site: _Site, value: TemplateValue, target: Mapping[str, Any] | None) -> Resolved:
        if target is not None and not compatible({"type": "string"}, target):
            self.err(
                "template.not_string", "Text with references can only fill text fields.", node=site.node, fld=site.field
            )
        taint = CLEAN
        for part in value.parts:
            if not isinstance(part, TemplateRef):
                continue
            r = self._resolve(site, part.path)
            if r is None:
                continue
            if r.taint.tainted:
                taint = TAINTED
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
        return Resolved({"type": "string"}, False, taint)

    # ---- references -----------------------------------------------------------------------------------------

    def _resolve(self, site: _Site, p: RefPath, *, report: bool = True) -> Resolved | None:
        """`report=False` answers a question (e.g. is this path a typed list?) without adding diagnostics."""
        mark = len(self.diags)
        resolved = self._resolve_reported(site, p)
        if not report:
            del self.diags[mark:]
        return resolved

    def _resolve_reported(self, site: _Site, p: RefPath) -> Resolved | None:
        resolved = self._resolve_typed(site, p)
        return dataclasses.replace(resolved, taint=self._taint_of(site, p)) if resolved is not None else None

    def _taint_of(self, site: _Site, p: RefPath) -> Shape:
        """What a read of `p` holds that's tainted (§4.1)."""
        if p.root == "trigger":
            return self.trigger_shape.at(p.rest)
        if p.root in ("run", "index") or p.section == "index":
            return CLEAN
        if p.root == "vars":
            return TAINTED if p.name in self.facts.vars else self.vars_shape.at((str(p.name), *p.rest))
        if p.root in ("item", "loops"):
            loop = site.item_node if p.root == "item" else self.s.by_key.get(str(p.name))
            return self.item_taint.get(loop, TAINTED).at(p.rest) if loop is not None else TAINTED
        if p.section == "error":
            return CLEAN  # fixed codes, and masked messages
        producer = self.s.by_key.get(str(p.name))
        return self.out_taint.get(producer, TAINTED).at(p.rest) if producer is not None else TAINTED

    def _resolve_typed(self, site: _Site, p: RefPath) -> Resolved | None:
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
            if p.root in ("item", "index", "loops"):
                return self._resolve_loop(site, p)
            return self._resolve_step(site, p)
        except PathError as e:
            self.err("ref.unknown_field", f"`{p.text}`: {e}", node=site.node, fld=site.field)
            return None

    def _resolve_loop(self, site: _Site, p: RefPath) -> Resolved | None:
        if p.root in ("item", "index"):
            loop = site.item_node
            if loop is None:
                self.err(
                    "ref.loop_outside",
                    "`item` and `index` exist only inside a loop body or a filter predicate.",
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
        consumer_key: tuple[Any, ...]
        if home == site.region and site.at_exit:
            consumer, upstream, consumer_key = region.exit, True, ("exit",)
        elif home == site.region and site.node is not None:
            consumer, upstream = region.live[site.node], site.node in self.desc[producer]
            consumer_key = ("node", site.node)
        else:
            ancestor = chain[chain.index(home) - 1]  # the loop node, in `home`, that contains the consumer
            if ancestor is None:
                return None
            consumer, upstream = region.live[ancestor], ancestor in self.desc[producer]
            consumer_key = ("node", ancestor)
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
            available = on_error == "port" and self._implies(home, consumer_key, consumer, producer, "err", region)
            r = navigate(ERROR_SCHEMA, p.rest)
            return Resolved(r.schema, r.conditional or not available)
        available = on_error != "continue" and self._implies(home, consumer_key, consumer, producer, "ok", region)
        if site.at_exit and site.region is None and self.has_stop:
            available = False  # `stop` may end the run while this step is still pending
        schema = self.out_schema.get(producer)
        if schema is None:  # only when the producer is already reported (unknown sub-flow): don't add noise
            return Resolved(None, not available)
        r = navigate(schema, p.rest)
        return Resolved(r.schema, r.conditional or not available)

    def _declared_optional(self, site: _Site, p: RefPath) -> tuple[int, ...]:
        """Positions in `p.rest` the schema declares optional (spec §4.3): CEL guards them, references default them."""
        return self._declared(site, p, declared_optional)

    def _declared_nullable(self, site: _Site, p: RefPath) -> tuple[int, ...]:
        """Positions in `p.rest` the schema declares may be null (spec §4.3): CEL guards reads below them."""
        return self._declared(site, p, declared_nullable)

    def _declared(
        self, site: _Site, p: RefPath, find: Callable[[Any, Sequence[str | int], Any], tuple[int, ...]]
    ) -> tuple[int, ...]:
        if p.root == "trigger":
            return find(self.g.settings.input_schema, p.rest, None)
        if p.root == "vars" and p.name in self.vars:
            return find(self.vars_root, p.rest, self.vars[str(p.name)])
        if p.root in ("item", "loops") and p.section == "item":
            loop = site.item_node if p.root == "item" else self.s.by_key.get(str(p.name))
            return find(self.item_schema.get(loop) if loop else None, p.rest, None)
        if p.root == "steps":
            producer = self.s.by_key.get(str(p.name))
            schema = ERROR_SCHEMA if p.section == "error" else self.out_schema.get(producer) if producer else None
            return find(schema, p.rest, None)
        return ()

    def _implies(
        self,
        home: uuid.UUID | None,
        consumer_key: tuple[Any, ...],
        consumer: lv.Cond,
        producer: uuid.UUID,
        outcome: str,
        region: lv.RegionLiveness,
    ) -> bool:
        """lv.implies, memoized: many references share a consumer and a producer, and each check can cost
        MAX_TERMS² term comparisons."""
        key = (home, consumer_key, producer, outcome)
        if key not in self.availability:
            target = region.err[producer] if outcome == "err" else region.ok[producer]
            self.availability[key] = lv.implies(consumer, target)
        return self.availability[key]

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
                self.output_taint[name] = r.taint.to_json() if r is not None else True
                continue
            inner = [
                self._value(_Site(None, where + pointer_str(pointer), None, at_exit=True), value, None, ())
                for pointer, value in iter_values(raw)
            ]
            props[name] = {"type": literal_type(raw)}
            required.append(name)
            self.output_taint[name] = any(r is None or r.taint.tainted for r in inner)
        self.output_schema = object_schema(props, required)

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


class _CelSite:
    """The validator's view for one CEL value (cel_check.CelContext)."""

    def __init__(self, v: _Validator, site: _Site) -> None:
        self.v, self.site = v, site
        self.has_item = site.item_node is not None
        self.tainted = False

    def resolve(self, path: RefPath, *, report: bool) -> Resolved | None:
        resolved = self.v._resolve(self.site, path, report=report)
        if report and resolved is not None and resolved.taint.tainted:
            self.tainted = True  # a path the expression reads: its typing questions (`report=False`) aren't reads
        return resolved

    def optional_fields(self, path: RefPath) -> tuple[int, ...]:
        return self.v._declared_optional(self.site, path)

    def nullable_fields(self, path: RefPath) -> tuple[int, ...]:
        return self.v._declared_nullable(self.site, path)

    def error(self, code: str, message: str, *, fix: str | None = None, severity: Severity = "error") -> None:
        self.v.err(code, message, node=self.site.node, fld=self.site.field, fix=fix, severity=severity)


def validate(graph: Graph, ctx: ValidationContext) -> ValidationResult:
    settings = _settings(graph)
    structure, structural = analyze_structure(graph, ctx.catalog)
    node_refs = tuple(sorted({n.type for n in graph.nodes}))
    if structure is None:
        return ValidationResult(tuple([*settings, *structural]), node_refs)
    unusable = ("settings.invalid_schema", "settings.unresolvable_ref", "settings.unsupported_keyword")
    settings_ok = not any(d.code in unusable for d in settings)
    facts = NO_FACTS
    while True:  # the taint analysis's fixpoint (§4.1): facts only grow, so this ends
        v = _Validator(graph, structure, ctx, settings_ok, facts)
        v.run()
        learned = TaintFacts(facts.vars | v.assigned, facts.collects | frozenset(v.collected_tainted))
        if learned == facts:
            break
        facts = learned
    return ValidationResult(
        diagnostics=tuple([*settings, *structural, *v.diags]),
        node_refs=node_refs,
        subflow_pins=dict(v.pins),
        failure_handler_version_id=v.failure_handler_version_id,
        output_schema=v.output_schema,
        expressions=tuple(sorted(v.expressions, key=lambda r: (r.node or "", r.field))),
        tainted_sites=tuple(
            sorted(
                ((str(node) if node else None, fld) for (node, fld), t in v.site_taint.items() if t),
                key=lambda site: (site[0] or "", site[1]),
            )
        ),
        output_taint=dict(v.output_taint),
    )
