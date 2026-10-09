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

from dewpoint.engine.cel import ast as cel_ast
from dewpoint.engine.cel import runtime as cel_runtime
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph import cel_check
from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.csv import INPUT_ROOT as CSV_INPUT_ROOT
from dewpoint.engine.graph.csv import RESERVED as CSV_RESERVED
from dewpoint.engine.graph.csv import is_canonical, trigger_schema
from dewpoint.engine.graph.diagnostics import Diagnostic, Severity
from dewpoint.engine.graph.model import CsvSettings, Graph, GraphNode
from dewpoint.engine.graph.schema_messages import problems
from dewpoint.engine.graph.schemas import (
    PathError,
    Resolved,
    allowed_kinds,
    compatible,
    contains_literal,
    declared_non_object,
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
from dewpoint.engine.handles import RESERVED, contains_marker
from dewpoint.engine.registry import control as C
from dewpoint.engine.registry.catalog import Catalog, NodeTypeSpec, marked_below_top
from dewpoint.engine.schema_refs import PREFIX as REF_PREFIX
from dewpoint.engine.schema_refs import ref_problems, subschemas
from dewpoint.engine.sensitive import (
    SENSITIVE,
    expand,
    is_marked,
    keys_sensitive,
    map_values,
    marked_positions,
    resolve,
)
from dewpoint.engine.taint import CLEAN, TAINTED, Shape, from_schema, make
from dewpoint.sdk.fields import CONNECTION, KINDS

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
    declares_csv: bool = False


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
    declassified: tuple[tuple[str, str, str], ...] = ()  # (node id, field, what it reveals): listed, and tainted
    tainted_sites: tuple[tuple[str | None, str], ...] = ()  # (node id, field) of every tainted value (2b spec §4.1)
    output_taint: Mapping[str, Any] = field(default_factory=dict)  # each workflow output's `Shape`, as JSON
    # (node id, field, connection id, type) of every connection a node's config names (plugins-3 D6)
    connections: tuple[tuple[str, str, uuid.UUID, str], ...] = ()
    # (input field, node ref, options field, connection id, the types it may be) of every start-form picker (D19)
    pickers: tuple[tuple[str, str, str, uuid.UUID, tuple[str, ...]], ...] = ()

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


_CONNECTION_INVALID = "A connection is named by its id, a UUID."
_SENSITIVE_LITERAL = (
    "A sensitive value can't be written into the workflow: pass it in the run's input, in a field marked sensitive."
)


_SCHEMA_LITERAL = (
    "A sensitive position can't list values (`enum`, `const`, `examples`): they'd be written into the workflow in "
    "plain text. Leave them out; check the value where it's used instead."
)
_CSV_HEADER = "Another column already has this header: each header maps to one column."
_CSV_NAME = "Another column already has this name: each column is one field of a row."
_CSV_IDENT = "Column names are lowercase identifiers, and not `in`, `true`, `false` or `null`."
_CSV_VALUES = "An `enum` column lists its values, and only an `enum` column has them."
_CSV_SENSITIVE_VALUES = (
    "A sensitive column can't list its values: they'd be written into the workflow. Make it a `string` column."
)
_CSV_INPUT_ROOT = (
    "A workflow that takes a CSV keeps its input schema plain at the root (`properties`, `required`, "
    "`additionalProperties`, `$defs` and annotations): this keyword could refuse the file's `rows` and `row_count`, "
    "or make their count sensitive. Move the constraint into a property's own schema."
)
_CSV_REQUIRED = "A required column takes no default: an empty cell is refused, so the default would never apply."
_CSV_DEFAULT = (
    "The default isn't a value of the column's type, as a cell would be converted: a number for `integer` and "
    "`number`, true or false for `boolean`, one of the values for `enum`, lowercase colon form for `mac`, and "
    "an address or network as Python's `ipaddress` writes it for `ip` and `cidr` (no host bits set)."
)
_RESERVED = "`rows` and `row_count` are a CSV's: declare the file in `settings.csv`, and its rows arrive there."
_CSV_TARGET = "This workflow takes a CSV file, which only a start with an upload supplies: no workflow can start it."
_TIMER = "A wait's duration is visible in the run's history, so it can't come from sensitive data."
_FAIL_MESSAGE = "A failure's message is recorded as it is, so it can't hold sensitive data."
_SUBFLOW_INPUT = "This passes sensitive data into a field the sub-flow doesn't mark sensitive."
TAINTED_REASON = "reads sensitive data"  # why a tainted CEL value runs in the isolated evaluator (§4.2)
_RESERVED_FIX = "Rename the key: a run's data never holds `$claim`."


def _covered(shape: Shape, schema: Mapping[str, Any], path: Pointer) -> bool:
    """Whether every tainted part of a value written at `path` lies where `schema` marks it sensitive."""
    if not shape.tainted or is_marked(schema, path):
        return True
    if shape.all or (shape.other is not None and shape.other.tainted):
        return False  # tainted as a whole, or under keys no schema names: the container itself must be marked
    if shape.items is not None and shape.items.tainted and not _covered(shape.items, schema, (*path, 0)):
        return False
    return all(_covered(sub, schema, (*path, name)) for name, sub in shape.fields)


_REVEALS = {
    C.IF: "the branch taken",
    C.SWITCH: "the port taken",
    C.LOOP: "the item count",
    C.FILTER: "the input count and the kept count",
}


def _decision_sites(graph: Graph, s: Structure) -> dict[tuple[uuid.UUID, str], str]:
    """The fields that may declassify (§4.3), with their node's type: a condition, a case's `when`, a loop's items,
    a filter's items and predicate."""
    out: dict[tuple[uuid.UUID, str], str] = {}
    for n in graph.nodes:
        ref = s.specs[n.id].ref
        if ref == C.IF:
            out[(n.id, "/condition")] = ref
        elif ref == C.SWITCH:
            cases = n.config.get("cases")
            for i in range(len(cases) if isinstance(cases, list) else 0):
                out[(n.id, f"/cases/{i}/when")] = ref
        elif ref == C.LOOP:
            out[(n.id, "/items")] = ref
        elif ref == C.FILTER:
            out[(n.id, "/items")] = ref
            out[(n.id, "/predicate")] = ref
    return out


def _public_length(graph: Graph, n: GraphNode) -> bool:
    """A loop over `trigger.rows` itself, in a version declaring a CSV: its length is already public
    (`trigger.row_count`), so it needs no entry. A derived or filtered list doesn't inherit that (§4.3), and without a
    CSV `trigger.rows` is whatever the caller sent, with no public count (#31)."""
    if graph.settings.csv is None:
        return False
    raw = n.config.get("items")
    body = raw.get(ENVELOPE) if isinstance(raw, Mapping) and is_envelope(raw) else None
    return isinstance(body, Mapping) and body.get("kind") == "ref" and body.get("path") == "trigger.rows"


def _declassify(
    graph: Graph, s: Structure, site_taint: Mapping[tuple[uuid.UUID | None, str], bool]
) -> tuple[list[Diagnostic], tuple[tuple[str, str, str], ...]]:
    """Every tainted decision must be listed in `settings.declassify`, and every entry must be one (§4.3)."""
    listed = [(e.node, e.field) for e in graph.settings.declassify]
    sites = _decision_sites(graph, s)
    out: list[Diagnostic] = []
    for (node, fld), ref in sites.items():
        if not site_taint.get((node, fld)) or (node, fld) in listed:
            continue
        if ref == C.LOOP and _public_length(graph, s.nodes[node]):
            continue
        out.append(
            Diagnostic(
                code="taint.undeclassified",
                node=node,
                field=fld,
                message=f"This decision reads sensitive data, so {_REVEALS[ref]} becomes visible.",
                fix="List it in the workflow's declassify settings, or decide on data that isn't sensitive.",
            )
        )
    declassified: list[tuple[str, str, str]] = []
    for i, (node, fld) in enumerate(listed):
        kind = sites.get((node, fld))
        if kind is None or not site_taint.get((node, fld)):
            out.append(
                Diagnostic(
                    code="taint.stale_declassify",
                    field=f"/settings/declassify/{i}",
                    message="This entry declassifies nothing: it isn't a decision that reads sensitive data.",
                    fix="Remove it.",
                )
            )
        else:
            declassified.append((str(node), fld, _REVEALS[kind]))
    return out, tuple(declassified)


_RUN_ROOTS = frozenset((*cel_check.ROOTS, *cel_check.ITEM_ROOTS))


def _reads_nothing(expr: str) -> bool:
    """Whether a CEL expression reads no run data: none of its free identifiers is a root (a comprehension's own
    variable isn't free, and `string` or `int` is a built-in type). fn-1 is pure, so it gives the same value every
    run, written into the workflow as a literal would be. One that doesn't parse is reported where it's checked."""
    try:
        parsed = cel_runtime.parse(expr)
    except cel_runtime.CompileError:
        return False
    names = cel_ast.global_idents(parsed.expr)
    return not any(n.lstrip(".").split(".")[0] in _RUN_ROOTS for n in names)  # `.trigger`: the root, named from the top


def _holds_marked(schema: Mapping[str, Any]) -> bool:
    """Whether a standalone schema can mark a part of its instances sensitive, by the rules a literal is checked with
    (`marked_positions`): behind a local `$ref`, in a union's branch, under a property, a pattern,
    `additionalProperties`, `items` or a tuple position, or a map whose keys are. Other keywords (`not`, `if`, a
    definition nothing reaches) mark nothing."""
    seen: set[int] = set()
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        branches = expand(node, schema)
        if any(b.get(SENSITIVE) is True for b in branches) or keys_sensitive(branches, schema):
            return True
        stack += map_values(branches)
        for b in branches:
            props, prefix = b.get("properties"), b.get("prefixItems")
            stack += list(props.values()) if isinstance(props, Mapping) else []
            stack += prefix if isinstance(prefix, list) else []
            stack += [b["items"]] if isinstance(b.get("items"), Mapping) else []
    return False


def _writes_sensitive(
    value: Value, root: Mapping[str, Any], pointer: Pointer, target: Mapping[str, Any] | None
) -> bool:
    """Whether a value envelope writes a literal at a sensitive position (§3.8): the literal itself or a reference's
    default, at it or holding a part the target schema marks; a template's default or text (all of it, without a
    reference); a CEL expression that reads nothing, wherever the target marks a part, since publish can't tell which
    parts it writes. Null and the empty string are written too; empty text beside a reference writes nothing."""
    marked = is_marked(root, pointer)
    if isinstance(value, LiteralValue):
        return marked or bool(target is not None and marked_positions(value.value, target))
    if isinstance(value, RefValue):
        return value.has_default and (marked or bool(target is not None and marked_positions(value.default, target)))
    if isinstance(value, CelValue):
        return (marked or (target is not None and _holds_marked(target))) and _reads_nothing(value.expr)
    refs = [p for p in value.parts if isinstance(p, TemplateRef)]
    text = "".join(p for p in value.parts if isinstance(p, str))
    return marked and (not refs or bool(text) or any(p.default is not None for p in refs))


_SCHEMA_LITERALS = ("default", "enum", "const", "examples")  # what a schema writes of its instances


def _sensitive_schema_literals(label: str, schema: Mapping[str, Any]) -> list[Diagnostic]:
    """A literal a schema writes — a `default`, an `enum`'s values, a `const`, `examples` — at a position it marks
    sensitive, or holding a part it does (engine 2b spec §3.8): a secret written into the version, even null or empty;
    an omitted one is what's allowed. Each is found where it's written: nested, in a union's branch, or in a definition
    that a sensitive position reaches through a local `$ref`. A start form masks a sensitive field's enum and default,
    but that never protected the published graph; versions published before this rule keep their masking."""
    found: dict[tuple[str, str], None] = {}  # (where, keyword), in document order
    seen: set[tuple[str, bool]] = set()

    def instances(node: Mapping[str, Any], key: str) -> list[Any]:
        value = node[key]
        return list(value) if key in ("enum", "examples") and isinstance(value, list) else [value]

    def walk(node: Any, path: str, inherited: bool) -> None:
        if not isinstance(node, Mapping) or (path, inherited) in seen:
            return
        seen.add((path, inherited))
        here = inherited or any(b.get(SENSITIVE) is True for b in expand(node, schema))
        for key in _SCHEMA_LITERALS:
            if key in node and (here or any(marked_positions(v, node, schema) for v in instances(node, key))):
                found[(path, key)] = None
        for suffix, sub in subschemas(node):
            walk(sub, path + suffix, here)
        ref = node.get("$ref")
        if here and isinstance(ref, str) and ref.startswith(REF_PREFIX):  # the definition, sensitive from here
            walk(resolve(schema, ref), ref[1:], True)

    walk(schema, "", False)
    return [
        Diagnostic(code="sensitive.default", field=f"/settings/{label}{where}", message=_SENSITIVE_LITERAL)
        if key == "default"
        else Diagnostic(code="sensitive.literal", field=f"/settings/{label}{where}/{key}", message=_SCHEMA_LITERAL)
        for where, key in found
    ]


def _csv_declaration(csv: CsvSettings | None) -> list[Diagnostic]:
    """A CSV declaration's columns (engine 2b spec §8.1): unique headers and identifier names, an enum's values, and a
    default that's its type's canonical value, never on a sensitive column (§3.8) nor beside `required`."""
    out: list[Diagnostic] = []
    headers: set[str] = set()
    names: set[str] = set()
    for i, c in enumerate(csv.columns if csv else ()):
        where = f"/settings/csv/columns/{i}"
        if c.header in headers:
            out.append(Diagnostic(code="csv.duplicate_header", field=f"{where}/header", message=_CSV_HEADER))
        if c.name in names:
            out.append(Diagnostic(code="csv.duplicate_name", field=f"{where}/name", message=_CSV_NAME))
        elif not IDENT.fullmatch(c.name) or c.name in CEL_KEYWORDS:
            out.append(Diagnostic(code="csv.invalid_name", field=f"{where}/name", message=_CSV_IDENT))
        headers.add(c.header)
        names.add(c.name)
        if (c.type == "enum") != (c.values is not None):
            out.append(Diagnostic(code="csv.enum_values", field=f"{where}/values", message=_CSV_VALUES))
        elif c.sensitive and c.values is not None:  # literals in the published graph (§3.8)
            out.append(Diagnostic(code="sensitive.literal", field=f"{where}/values", message=_CSV_SENSITIVE_VALUES))
        if "default" not in c.model_fields_set:
            continue
        if c.sensitive:
            out.append(Diagnostic(code="sensitive.default", field=f"{where}/default", message=_SENSITIVE_LITERAL))
        elif c.required:
            out.append(Diagnostic(code="csv.required_default", field=f"{where}/default", message=_CSV_REQUIRED))
        elif not is_canonical(c.type, c.default, c.values):
            out.append(Diagnostic(code="csv.bad_default", field=f"{where}/default", message=_CSV_DEFAULT))
    return out


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
            out += _sensitive_schema_literals(label, schema)
    out += _csv_declaration(st.csv)
    props = st.input_schema.get("properties")
    out += [
        Diagnostic(code="settings.reserved_name", field=f"/settings/input_schema/properties/{name}", message=_RESERVED)
        for name in CSV_RESERVED
        if isinstance(props, Mapping) and name in props
    ]
    out += [  # a schema that could refuse the generated `rows` would publish a CSV no start can satisfy
        Diagnostic(code="csv.input_schema", field=f"/settings/input_schema/{key}", message=_CSV_INPUT_ROOT)
        for key in st.input_schema
        if st.csv is not None and key not in CSV_INPUT_ROOT
    ]
    if any((d.field or "").startswith("/settings/vars_schema") for d in out):  # never run defaults through it
        return out
    props = st.vars_schema.get("properties", {})
    defs = st.vars_schema.get("$defs", {})
    for name, schema in props.items() if isinstance(props, Mapping) else ():
        where = f"/settings/vars_schema/properties/{name}"
        if not IDENT.fullmatch(name) or name in CEL_KEYWORDS:
            out.append(
                Diagnostic(
                    code="vars.invalid_name",
                    field=where,
                    message="Variable names are lowercase identifiers, and not `in`, `true`, `false` or `null`.",
                )
            )
        if not isinstance(schema, Mapping) or "default" not in schema:
            if not is_marked(st.vars_schema, (name,)):  # a sensitive one is null until set (`_Validator.unset`)
                out.append(
                    Diagnostic(code="vars.no_default", field=where, message="Every variable needs a default value.")
                )
        elif list(Draft202012Validator({**schema, "$defs": defs}).iter_errors(schema["default"])):
            out.append(
                Diagnostic(code="vars.bad_default", field=where, message="The default value doesn't match the type.")
            )
    places = [(f"/settings/outputs/{k}", v) for k, v in st.outputs.items()]
    places += [("/settings/input_schema", st.input_schema), ("/settings/vars_schema", st.vars_schema)]
    for where, value in places:  # the handle marker is Dewpoint's (engine 2b spec §3.2)
        if contains_marker(value):
            out.append(Diagnostic(code="value.reserved_key", field=where, message=RESERVED, fix=_RESERVED_FIX))
    for name in st.outputs:
        if not IDENT.fullmatch(name):
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
        # A sensitive variable has no default (§3.8): it's null until a step sets it. Unless its type allows null,
        # every read must come after a step sure to have set it.
        self.unset = {
            name
            for name, schema in self.vars.items()
            if isinstance(schema, Mapping)
            and "default" not in schema
            and is_marked(self.vars_root, (name,))
            and not Draft202012Validator(standalone(self.vars_root, schema)).is_valid(None)
        }
        self.writers: dict[str, list[uuid.UUID]] = {}
        for n_id in s.topo:  # only the root's: a write in a loop body is refused (`_variables`)
            assignments = s.nodes[n_id].config.get("assignments")
            if s.specs[n_id].ref == C.SET_VARIABLES and s.region_of[n_id] is None and isinstance(assignments, Mapping):
                for name in assignments if not is_envelope(assignments) else ():
                    self.writers.setdefault(name, []).append(n_id)
        # `stop` anywhere, inside a loop body too, ends the whole run: outputs may miss steps that hadn't run yet
        self.has_stop = any(spec.ref == C.STOP for spec in s.specs.values())
        self.availability: dict[tuple[Any, ...], bool] = {}
        self.expressions: list[ExpressionRecord] = []
        self.connections: list[tuple[str, str, uuid.UUID, str]] = []
        # taint (2b spec §4.1): its sources, each node's output, each loop's element, and what this pass learns
        self.trigger_root = trigger_schema(graph.settings.model_dump(mode="json")) if settings_ok else {}
        self.trigger_shape = from_schema(self.trigger_root) if settings_ok else TAINTED
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
            self.item_taint[n.id] = CLEAN  # written in the workflow, unless an `items` value says otherwise below
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
        self._refused_taint(n, spec, resolved)

    def _refused_taint(self, n: GraphNode, spec: NodeTypeSpec, resolved: Mapping[Pointer, Resolved | None]) -> None:
        """Tainted data where history would show it (engine 2b spec §4.5): a timer's duration, a failure's message; or
        where a child's own analysis wouldn't know it's sensitive: a sub-flow input field it doesn't mark."""
        tainted = [(p, r) for p, r in resolved.items() if r is not None and r.taint.tainted]
        if spec.ref in (C.DELAY, C.WAIT_UNTIL):
            for pointer, _ in tainted:
                self.err(
                    "taint.timer", _TIMER, node=n.id, fld=pointer_str(pointer), fix="Wait on data that isn't sensitive."
                )
        elif spec.ref == C.FAIL:
            for pointer, _ in tainted:
                self.err(
                    "taint.fail_message", _FAIL_MESSAGE, node=n.id, fld=pointer_str(pointer), fix="Use a fixed message."
                )
        elif spec.ref == C.RUN_WORKFLOW and (info := self._subflow(n)) is not None:
            for pointer, r in tainted:
                if pointer[:1] == ("input",) and not _covered(r.taint, info.input_schema, pointer[1:]):
                    self.err("taint.subflow_input", _SUBFLOW_INPUT, node=n.id, fld=pointer_str(pointer),
                             fix="Mark that field sensitive (x-sensitive) in the sub-flow's input schema.")  # fmt: skip

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
        for key, value in n.config.items():  # the handle marker is Dewpoint's (engine 2b spec §3.2)
            if contains_marker(value):
                self.err("value.reserved_key", RESERVED, node=n.id, fld=pointer_str((key,)), fix=_RESERVED_FIX)
        stripped, envelopes = strip_values(n.config)
        self._schema_errors(n.id, "", spec.config_schema, stripped, envelopes)
        self._sensitive_literals(n, spec, stripped, envelopes)
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
        self._connections(n, props, stripped)
        if spec.ref == C.SET_VARIABLES and isinstance(stripped.get("assignments"), dict):
            for name, value in stripped["assignments"].items():
                if name in self.vars:
                    inner = [p[2:] for p in envelopes if p[:2] == ("assignments", name)]
                    schema = standalone(self.vars_root, self.vars[name])
                    self._schema_errors(n.id, pointer_str(("assignments", name)), schema, value, inner)
        if spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            if info is not None and info.declares_csv:
                self.err("subflow.csv_target", _CSV_TARGET, node=n.id, fld="/workflow_id")
            if info is not None:
                inner = [p[1:] for p in envelopes if p[:1] == ("input",)]
                self._schema_errors(n.id, "/input", info.input_schema, stripped.get("input", {}), inner)

    def _connections(self, n: GraphNode, props: Any, stripped: Mapping[str, Any]) -> None:
        """Every connection the node names (plugins-3 D6): a top-level field the node type marks, written as a literal
        UUID (an envelope is refused as any literal-only field's is). Publish checks each against the tenant's."""
        for name, prop in props.items() if isinstance(props, Mapping) else ():
            wanted = prop.get(CONNECTION) if isinstance(prop, Mapping) else None
            value = stripped.get(name)
            if not isinstance(wanted, str) or value is None or is_envelope(n.config.get(name)):
                continue
            try:
                named = uuid.UUID(value) if isinstance(value, str) else None
            except ValueError:
                named = None
            if named is None:
                self.err("connection.invalid", _CONNECTION_INVALID, node=n.id, fld=pointer_str((name,)))
                continue
            self.connections.append((str(n.id), pointer_str((name,)), named, wanted))

    def _sensitive_literals(self, n: GraphNode, spec: NodeTypeSpec, stripped: Any, envelopes: list[Pointer]) -> None:
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
            depth = prefix.count("/")
            holes = {pointer_str(p[depth:]) for p in envelopes if pointer_str(p[:depth]) == prefix}
            if isinstance(schema, Mapping):
                for where in marked_positions(value, schema, holes=holes):
                    self.err("sensitive.literal", _SENSITIVE_LITERAL, node=n.id, fld=prefix + where)

    def _schema_errors(
        self, node: uuid.UUID, prefix: str, schema: Mapping[str, Any], instance: Any, envelopes: list[Pointer]
    ) -> None:
        for path, message in problems(schema, instance):
            if any(path[: len(p)] == p for p in envelopes):
                continue  # computed at run time; checked through its reference type instead
            # Said without the value: jsonschema quotes it, and it may be sensitive (ledger M25).
            self.err("config.invalid", message, node=node, fld=prefix + pointer_str(path))

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
        whole_roots = {p.path[0] for p in result.record.projections if len(p.path) == 1} if result.record else set()
        tainted = context.tainted or result.dynamic or any(self._root_tainted(site, root) for root in whole_roots)
        if result.record is not None:  # a tainted value always runs in the isolated evaluator (§4.2)
            record = result.record
            self.expressions.append(
                dataclasses.replace(record, mode="activity", reason=TAINTED_REASON, tainted=True) if tainted else record
            )
        if result.resolved is None:
            return None
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
        for path, message in problems(schema, instance):
            self.err("config.invalid", message, node=site.node, fld=site.field + pointer_str(path))

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
                return navigate(self.trigger_root, p.rest)
            if p.root == "run":
                return Resolved(RUN_SCHEMAS[str(p.section)], False)
            if p.root == "vars":
                if p.name not in self.vars:
                    self.err(
                        "ref.unknown_var", f"`{p.name}` isn't a declared variable.", node=site.node, fld=site.field
                    )
                    return None
                if p.name in self.unset and not self._set_before(site, str(p.name)):
                    self.err(
                        "vars.unassigned",
                        f"`vars.{p.name}` has no default, so it's null until a step sets it, and its type doesn't "
                        "allow null.",
                        node=site.node,
                        fld=site.field,
                        fix="Set it in a step that always runs before this one, or allow null in its type.",
                    )
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
            return Resolved(None, bool(p.rest), missing=bool(p.rest))
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
        found = self._consumer(site, home, producer)
        if found is None:
            return None
        consumer, upstream, consumer_key = found
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
            return dataclasses.replace(
                r, conditional=r.conditional or not available, missing=r.missing or not available
            )
        available = on_error != "continue" and self._implies(home, consumer_key, consumer, producer, "ok", region)
        if site.at_exit and site.region is None and self.has_stop:
            available = False  # `stop` may end the run while this step is still pending
        schema = self.out_schema.get(producer)
        if schema is None:  # only when the producer is already reported (unknown sub-flow): don't add noise
            return Resolved(None, not available, missing=not available)
        r = navigate(schema, p.rest)
        return dataclasses.replace(r, conditional=r.conditional or not available, missing=r.missing or not available)

    def _consumer(
        self, site: _Site, home: uuid.UUID | None, producer: uuid.UUID
    ) -> tuple[lv.Cond, bool, tuple[Any, ...]] | None:
        """When `site` runs, as `home`'s liveness sees it (the site, or the loop node in `home` containing it), whether
        `producer` runs before that, and the memo key. None: no node in `home` contains the site."""
        region = self.live[home]
        if home == site.region and site.at_exit:
            return region.exit, True, ("exit",)
        if home == site.region and site.node is not None:
            return region.live[site.node], site.node in self.desc[producer], ("node", site.node)
        chain = self.s.chain(site.region)
        ancestor = chain[chain.index(home) - 1]  # the loop node, in `home`, that contains the consumer
        if ancestor is None:
            return None
        return region.live[ancestor], ancestor in self.desc[producer], ("node", ancestor)

    def _set_before(self, site: _Site, name: str) -> bool:
        """Whether a step sure to have set variable `name` has run when `site` reads it (spec §4.3 path availability,
        as for a step's output)."""
        if site.at_exit and site.region is None and self.has_stop:
            return False  # `stop` may end the run before any of them ran
        for writer in self.writers.get(name, ()):
            found = self._consumer(site, None, writer)
            if found is None or not found[1] or self.s.nodes[writer].options.on_error == "continue":
                continue
            if self._implies(None, found[2], found[0], writer, "ok", self.live[None]):
                return True
        return False

    def _declared_optional(self, site: _Site, p: RefPath) -> tuple[int, ...]:
        """Positions in `p.rest` the schema declares optional (spec §4.3): CEL guards them, references default them."""
        return self._declared(site, p, declared_optional)

    def _declared_non_object(self, site: _Site, p: RefPath) -> tuple[int, ...]:
        """Positions in `p.rest` the schema declares may not be objects: CEL guards reads below them (4c-2a)."""
        return self._declared(site, p, declared_non_object)

    def _declared_nullable(self, site: _Site, p: RefPath) -> tuple[int, ...]:
        """Positions in `p.rest` the schema declares may be null (spec §4.3): CEL guards reads below them."""
        return self._declared(site, p, declared_nullable)

    def _declared(
        self, site: _Site, p: RefPath, find: Callable[[Any, Sequence[str | int], Any], tuple[int, ...]]
    ) -> tuple[int, ...]:
        if p.root == "trigger":
            return find(self.trigger_root, p.rest, None)
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
            if info.declares_csv:
                self.err("subflow.csv_target", _CSV_TARGET, fld="/settings/failure_handler")


class _CelSite:
    """The validator's view for one CEL value (cel_check.CelContext)."""

    def __init__(self, v: _Validator, site: _Site) -> None:
        self.v, self.site = v, site
        self.has_item = site.item_node is not None
        self.tainted = False

    def resolve(self, path: RefPath, *, report: bool, reads: bool = True) -> Resolved | None:
        resolved = self.v._resolve(self.site, path, report=report)
        if report and reads and resolved is not None and resolved.taint.tainted:
            self.tainted = True  # a path the expression reads: its typing questions (`report=False`) aren't reads
        return resolved

    def optional_fields(self, path: RefPath) -> tuple[int, ...]:
        return self.v._declared_optional(self.site, path)

    def nullable_fields(self, path: RefPath) -> tuple[int, ...]:
        return self.v._declared_nullable(self.site, path)

    def non_object_fields(self, path: RefPath) -> tuple[int, ...]:
        return self.v._declared_non_object(self.site, path)

    def error(self, code: str, message: str, *, fix: str | None = None, severity: Severity = "error") -> None:
        self.v.err(code, message, node=self.site.node, fld=self.site.field, fix=fix, severity=severity)


PICKER = "x-dewpoint-picker"  # a start-form field listing a node type's options through a connection (plugins-3 D19)
_PICKER_KEYS = frozenset({"node", "field", "connection"})
_PICKER_INVALID = "A picker is {node: a node type version, field: one of its options fields, connection: a UUID}."
_PICKER_NODE = "No active node type of that version: a picker needs one."
_PICKER_FIELD = "That field isn't one the node type lists options for."
_PICKER_STRING = "A picked value is text: the field must be of type string."
_PICKER_TOP = "A picker is a top-level field of the input schema: the start form shows only those."

type Picker = tuple[str, str, str, uuid.UUID, tuple[str, ...]]


def picker_refs(graph: Graph) -> set[str]:
    """The node type versions the start-form pickers name, which the catalog must hold to check them."""
    props = graph.settings.input_schema.get("properties")
    found: set[str] = set()
    for prop in props.values() if isinstance(props, Mapping) else ():
        picker = prop.get(PICKER) if isinstance(prop, Mapping) else None
        node = picker.get("node") if isinstance(picker, Mapping) else None
        if isinstance(node, str) and "@" in node:
            found.add(node)
    return found


def _pickers(graph: Graph, catalog: Catalog) -> tuple[list[Diagnostic], list[Picker]]:
    """Every start-form picker (plugins-3 D19): its shape and its node's options field here, its connection at
    publish (which records it, so it can't be deleted while it's in use)."""
    schema = graph.settings.input_schema
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    out: list[Diagnostic] = []
    found: list[Picker] = []
    for name, prop in props.items() if isinstance(props, Mapping) else ():
        if not isinstance(prop, Mapping) or PICKER not in prop:
            continue
        where = f"/settings/input_schema/properties{pointer_str((name, PICKER))}"
        picker = prop[PICKER]
        if (
            not isinstance(picker, Mapping)
            or set(picker) != _PICKER_KEYS
            or not all(isinstance(picker[k], str) for k in _PICKER_KEYS)
        ):
            out.append(Diagnostic(code="picker.invalid", field=where, message=_PICKER_INVALID))
            continue
        try:
            connection = uuid.UUID(picker["connection"])
        except ValueError:
            out.append(Diagnostic(code="picker.invalid", field=where, message=_PICKER_INVALID))
            continue
        spec = catalog.get(picker["node"])
        if spec is None or spec.state == "retired":
            out.append(Diagnostic(code="picker.unknown_node", field=where, message=_PICKER_NODE))
        elif picker["field"] not in spec.options:
            out.append(Diagnostic(code="picker.not_an_options_field", field=where, message=_PICKER_FIELD))
        elif prop.get("type") != "string":
            out.append(Diagnostic(code="picker.not_a_string", field=where, message=_PICKER_STRING))
        else:
            found.append((str(name), spec.ref, picker["field"], connection, spec.credentials))
    if isinstance(schema, Mapping) and marked_below_top(schema, PICKER):
        out.append(Diagnostic(code="picker.not_top_level", field="/settings/input_schema", message=_PICKER_TOP))
    return out, found


def picker_problems(diagnostics: Sequence[Diagnostic]) -> bool:
    return any(d.code.startswith("picker.") for d in diagnostics)


def validate(graph: Graph, ctx: ValidationContext) -> ValidationResult:
    settings = _settings(graph)
    if not any((d.field or "").startswith("/settings/input_schema") for d in settings):
        picker_diags, pickers = _pickers(graph, ctx.catalog)
        settings += picker_diags
    else:
        pickers = []
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
    declassify, declassified = _declassify(graph, structure, v.site_taint)
    return ValidationResult(
        diagnostics=tuple([*settings, *structural, *v.diags, *declassify]),
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
        declassified=declassified,
        connections=tuple(sorted(v.connections, key=lambda c: (c[0], c[1]))),
        pickers=tuple(pickers) if not picker_problems(settings) else (),
    )
