# SPDX-License-Identifier: Apache-2.0
"""Which operation a concrete Mist path reaches (the 3b-1 review's H1). A path value may be any plain segment, and
some are another operation's literal at that position (`DELETE …/alarmtemplates/suppress` is
`unsuppressOrgSuppressedAlarms`, not `deleteOrgAlarmTemplate`), or make a path two templates match equally
(`…/wxrules/count` and `…/{zone_type}/count`). So a request goes out only when its concrete path resolves, among
every operation of the description, to the one the node was allowed: the template with the most literal segments,
and a tie refused. Each path value must also match its parameter (a UUID, a MAC), and the query and body theirs."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from dewpoint.plugins.mist import oas, policy
from dewpoint.plugins.mist.schemas import converted, resolved, with_defs

UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ORG_STANDIN = "00000000-0000-4000-8000-000000000000"  # an org id, to resolve a path before the connection is opened
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
SITE_CHECK = "getSiteInfo"  # the operation a site check reads (D14): an auxiliary read the map must allow
SITES = "/api/v1/orgs/{org_id}/sites"


@dataclass(frozen=True)
class Route:
    operation: str
    method: str
    segments: tuple[str, ...]
    scope: str


def matched(found: list[Route], method: str, segments: list[str]) -> tuple[Route, dict[str, str]] | None:
    """The most specific route `method` and `segments` match, and its path values; None when none or two do."""
    best: list[tuple[int, Route, dict[str, str]]] = []
    for route in found:
        if route.method != method or len(route.segments) != len(segments):
            continue
        values: dict[str, str] = {}
        literal = 0
        for template, value in zip(route.segments, segments, strict=True):
            if template.startswith("{"):
                values[template[1:-1]] = value
            elif template == value:
                literal += 1
            else:
                break
        else:
            best.append((literal, route, values))
    if not best:
        return None
    best.sort(key=lambda b: -b[0])
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    return best[0][1], best[0][2]


@cache
def every_route() -> list[Route]:
    """Every operation of the description, whatever the map says of it."""
    return [
        Route(op.id, op.method, tuple(op.path.split("/")), policy.scope_of(op.path) or "")
        for op in oas.operations().values()
    ]


def reaches(method: str, path: str) -> str | None:
    """The operation a concrete `path` reaches, or None when none or two match it equally."""
    found = matched(every_route(), method, path.split("/"))
    return found[0].operation if found is not None else None


def filled(template: str, values: Mapping[str, Any]) -> str:
    """`template` with its values, the org a stand-in: for resolving a path, never for sending it."""
    return PLACEHOLDER.sub(lambda m: ORG_STANDIN if m.group(1) == "org_id" else str(values.get(m.group(1))), template)


@dataclass(frozen=True)
class Checkers:
    path: Mapping[str, Draft202012Validator]
    query: Mapping[str, Draft202012Validator]
    body: Draft202012Validator | None


@cache
def checkers(operation: str) -> Checkers:
    """An operation's path value, query and body validators: its parameters' schemas, UUIDs checked."""
    doc, op = oas.document(), oas.operations()[operation]
    formats = FormatChecker(formats=("uuid",))

    def check(schema: Any, partial: bool = False) -> Draft202012Validator:
        made = with_defs(doc, converted(schema, output=False, partial=partial), [schema], output=False,
                         partial=partial)  # fmt: skip
        return Draft202012Validator(made, format_checker=formats)

    path = {p["name"]: check(p.get("schema", {})) for p in op.parameters if p["in"] == "path"}
    query = {
        p["name"]: check(p.get("schema", {})) for p in op.parameters
        if p["in"] == "query" and resolved(doc, p.get("schema", {})).get("type") != "array"
    }  # fmt: skip
    body = None
    if "requestBody" in op.spec:
        media = (oas.resolve(doc, op.spec["requestBody"]).get("content") or {}).get("application/json", {})
        body = check(media.get("schema", {}), partial=op.method == "PUT")
    return Checkers(path, query, body)


def value_pattern(operation: str, name: str) -> str:
    """A path value's pattern for a config, without anchors: a UUID, the parameter's own pattern, else one segment."""
    for p in oas.operations()[operation].parameters:
        if p["in"] == "path" and p["name"] == name:
            schema = resolved(oas.document(), p.get("schema", {}))
            if schema.get("format") == "uuid":
                return UUID
            own = schema.get("pattern")
            if isinstance(own, str) and own.startswith("^") and own.endswith("$"):
                return own[1:-1]
    return "[A-Za-z0-9_.~-]+"


def is_list(doc: Mapping[str, Any], op: oas.Operation) -> bool:
    """A GET whose 2xx answer is an array."""
    found = oas.answer(doc, op)
    return op.method == "GET" and found is not None and resolved(doc, found).get("type") == "array"


def pickers(path: str, scope: str | None, lists: Mapping[str, str]) -> dict[str, str]:
    """An operation's options fields and the list each reads: a site-scope operation's site from the org's sites; an
    org resource's id (or MAC) from the list at its collection's path (`lists`: those allowed, by path)."""
    out: dict[str, str] = {}
    segments = path.split("/")
    if scope == "site" and SITES in lists:
        out["site_id"] = lists[SITES]
    if scope == "org" and len(segments) > 6 and segments[6].startswith("{"):
        name, collection = segments[6][1:-1], "/".join(segments[:6])
        if collection in lists and name.endswith(("_id", "_mac")):
            out[name] = lists[collection]
    return out
