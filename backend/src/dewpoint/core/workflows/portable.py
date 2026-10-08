# SPDX-License-Identifier: Apache-2.0
"""A workflow as a file (sub-project 4, B12; 4b ruling 18), fail-closed. Exported, every id of the tenant's a draft
holds where a binding goes (a connection field, a `flow.run_workflow`'s `workflow_id`, the failure handler) becomes a
typed placeholder, and a draft that can't be made portable for certain is refused, never approximated. Imported, the
file is checked whole against this server's node types before anything is written; each placeholder is then bound to
one of the importing tenant's connections or workflows, or left unbound, its sites empty. Schedules, webhook bindings
and CSV mappings are rows, not graph: they don't travel."""

import copy
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

FORMAT = "dewpoint.workflow"
FORMAT_VERSION = 1
CONNECTION_MARKER = "x-dewpoint-connection"  # dewpoint.sdk.fields.CONNECTION; the SDK allows it top-level only
RUN_WORKFLOW = "flow.run_workflow@1"  # the flow plugin's; its `workflow_id` is a literal workflow id
FAILURE_HANDLER = "/settings/failure_handler"
UNKNOWN = {"connection": "Unknown connection", "workflow": "Unknown workflow"}

Kind = Literal["connection", "workflow"]


@dataclass(frozen=True)
class Site:
    kind: Kind
    type: str | None  # the connection type a connection site takes; None for a workflow
    node: str | None  # a step's id as the graph holds it; None for the workflow's settings
    field: str  # a top-level config property (`/connection`), or FAILURE_HANDLER


@dataclass(frozen=True)
class Problem:
    reason: str
    binding: str | None = None
    node: str | None = None
    field: str | None = None

    def to_json(self) -> dict[str, str | None]:
        return {"reason": self.reason, "binding": self.binding, "node": self.node, "field": self.field}


class NotPortableError(ValueError):
    """The draft can't be exported without risking one of the tenant's ids in the file."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(", ".join(p.reason for p in problems))
        self.problems = problems


class BadDocumentError(ValueError):
    """The file can't be imported as it is."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(", ".join(p.reason for p in problems))
        self.problems = problems


def _nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [n for n in graph.get("nodes") or [] if isinstance(n, Mapping)]


def _node(graph: Mapping[str, Any], node_id: str) -> Any:
    return next((n for n in _nodes(graph) if str(n.get("id")) == node_id), None)


def _identity(node_id: Any) -> uuid.UUID | str:
    """A step's id as the engine reads it: one UUID whatever its spelling (case, hyphens, braces, a urn: each one the
    graph's format accepts parses here to the same value); an id that isn't a UUID stays as written."""
    try:
        return uuid.UUID(str(node_id))
    except ValueError:
        return str(node_id)


def _shape(graph: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[Problem]:
    """What keeps anyone from knowing where a graph's ids are: two steps sharing an id, by identity, not spelling (a
    site would name either), or a step of a type this server doesn't know (its config may hold an id no schema
    marks). A duplicate is named by its first spelling in the graph, which is left as it was."""
    spelt: dict[uuid.UUID | str, list[str]] = {}
    for n in _nodes(graph):
        spelt.setdefault(_identity(n.get("id")), []).append(str(n.get("id")))
    out = [Problem("duplicate_node", node=spellings[0]) for spellings in spelt.values() if len(spellings) > 1]
    for n in _nodes(graph):
        ref = n.get("type")
        if not isinstance(ref, str) or ref not in config_schemas:
            out.append(Problem("unknown_type", node=str(n.get("id"))))
    return out


def sites(graph: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[Site]:
    """Every place a graph may hold an id of the tenant's, by its steps' schemas: each top-level config property a type
    marks as a connection, each `flow.run_workflow`'s `workflow_id`, and the failure handler. Only for a graph in
    which `_shape` finds nothing."""
    out: list[Site] = []
    for node in _nodes(graph):
        ref, node_id = str(node.get("type")), str(node.get("id"))
        for prop, spec in (config_schemas[ref].get("properties") or {}).items():
            if isinstance(spec, Mapping) and isinstance(spec.get(CONNECTION_MARKER), str):
                out.append(Site("connection", spec[CONNECTION_MARKER], node_id, f"/{prop}"))
        if ref == RUN_WORKFLOW:
            out.append(Site("workflow", None, node_id, "/workflow_id"))
    out.append(Site("workflow", None, None, FAILURE_HANDLER))
    return out


def value_at(graph: Mapping[str, Any], site: Site) -> Any:
    """What a site holds; None when it holds nothing."""
    if site.node is None:
        settings = graph.get("settings")
        return settings.get("failure_handler") if isinstance(settings, Mapping) else None
    node = _node(graph, site.node)
    config = node.get("config") if node is not None else None
    return config.get(site.field[1:]) if isinstance(config, Mapping) else None


def _empty(graph: dict[str, Any], site: Site) -> None:
    if site.node is None:
        settings = graph.get("settings")
        if isinstance(settings, dict):
            settings.pop("failure_handler", None)
        return
    node = _node(graph, site.node)
    if node is not None and isinstance(node.get("config"), dict):
        node["config"].pop(site.field[1:], None)


def _canonical(value: Any) -> str | None:
    """The id a value names, canonical; None for anything else (an expression, a number, a string that isn't one)."""
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def held(draft: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[tuple[Site, str]]:
    """Each site holding an id, with that id, canonical. NotPortableError when the draft can't be made portable for
    certain: what `_shape` finds, or a site holding anything but an id."""
    problems = _shape(draft, config_schemas)
    if problems:
        raise NotPortableError(problems)
    out: list[tuple[Site, str]] = []
    for site in sites(draft, config_schemas):
        value = value_at(draft, site)
        if value is None:
            continue
        canonical = _canonical(value)
        if canonical is None:
            problems.append(Problem("unexpected_value", node=site.node, field=site.field))
        else:
            out.append((site, canonical))
    if problems:
        raise NotPortableError(problems)
    return out


def sensitive_problems(diagnostics: Iterable[Any]) -> list[Problem]:
    """A value written into a field its step's type marks sensitive (the validator's `sensitive.literal`, engine 2b spec
    §3.8) would travel in the file to whoever imports it (ledger M25, the owner's ruling): each a reason to refuse the
    export, named by its step and field, never by its value."""
    return [
        Problem("sensitive_literal", node=None if d.node is None else str(d.node), field=d.field)
        for d in diagnostics
        if d.code == "sensitive.literal"
    ]


def export_document(
    name: str,
    draft: Mapping[str, Any],
    config_schemas: Mapping[str, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    """The file: the draft with every site emptied, and one binding per distinct (kind, connection type, id), in the
    order first met, with each site it filled. `labels` maps (kind, canonical id) to its name in the tenant."""
    found = held(draft, config_schemas)
    graph = copy.deepcopy(dict(draft))
    for site in sites(draft, config_schemas):
        _empty(graph, site)
    bindings: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for site, value in found:
        key = (site.kind, site.type, value)
        if key not in bindings:
            bindings[key] = {
                "id": f"b{len(bindings) + 1}",
                "kind": site.kind,
                "type": site.type,
                "label": labels.get((site.kind, value), UNKNOWN[site.kind]),
                "sites": [],
            }
        bindings[key]["sites"].append({"node": site.node, "field": site.field})
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "name": name,
        "graph": graph,
        "bindings": list(bindings.values()),
    }


def check_document(
    graph: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]], config_schemas: Mapping[str, Mapping[str, Any]]
) -> list[Problem]:
    """Every reason a file can't be imported as it is, all at once: what `_shape` finds; an id embedded where a binding
    goes (left unbound, it would stay); a binding id used twice; a site listed twice; a site that isn't, by this
    server's schemas, one of the binding's kind and connection type."""
    problems = _shape(graph, config_schemas)
    if problems:
        return problems
    allowed = {(s.node, s.field): s for s in sites(graph, config_schemas)}
    problems += [
        Problem("embedded_value", node=s.node, field=s.field)
        for s in allowed.values()
        if value_at(graph, s) is not None
    ]
    ids: set[str] = set()
    listed: set[tuple[str | None, str]] = set()
    for binding in bindings:
        if binding["id"] in ids:
            problems.append(Problem("duplicate_binding", binding=binding["id"]))
        ids.add(binding["id"])
        for site in binding["sites"]:
            key = (site["node"], site["field"])
            target = allowed.get(key)
            if key in listed:
                problems.append(Problem("overlapping_site", binding=binding["id"], node=key[0], field=key[1]))
            elif target is None or target.kind != binding["kind"] or target.type != binding["type"]:
                problems.append(Problem("bad_site", binding=binding["id"], node=key[0], field=key[1]))
            listed.add(key)
    return problems


def apply(
    graph: Mapping[str, Any],
    bindings: Sequence[Mapping[str, Any]],
    chosen: Mapping[str, str],
    config_schemas: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The graph with each chosen binding's id written at each of its sites; an unbound binding's stay empty. Refuses
    (BadDocumentError) whatever `check_document` refuses, so nothing unchecked is ever written."""
    problems = check_document(graph, bindings, config_schemas)
    if problems:
        raise BadDocumentError(problems)
    out = copy.deepcopy(dict(graph))
    for binding in bindings:
        value = chosen.get(binding["id"])
        if value is None:
            continue
        for site in binding["sites"]:
            if site["node"] is None:
                out.setdefault("settings", {})["failure_handler"] = value
            else:
                _node(out, site["node"]).setdefault("config", {})[site["field"][1:]] = value
    return out
