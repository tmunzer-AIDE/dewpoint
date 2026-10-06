# SPDX-License-Identifier: Apache-2.0
"""Any endpoint (plugins-3 D14): `mist.api.read` (GET, no side effect) and `mist.api.write` (POST, PUT or DELETE,
always `ambiguous`: RunGraph reads a node's side effect from its manifest, so one node can't choose it per method).

Neither authorizes anything by its method or by the OAS: a request reaches only an operation the policy map allows to
that node, matched by method and path (the most specific template wins), and

- the always-refused routes (`policy.refused`) are refused whatever the map says;
- an org path's org is the connection's (written as its id or as `{org_id}`), a site path's site is checked to be the
  connection's org's;
- each path value matches its parameter's description and is a plain segment, then encoded; the query names only the
  operation's parameters, each value checked; the body is checked against the operation's request body;
- the answer is undeclared, so the run claims it whole, tainted.

The config's `path` lists the paths its version may reach, so a version never widens: publish checks a literal path,
and the run checks a computed one, before the map is read again."""

import copy
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, ClassVar

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel

from dewpoint.plugins.mist import oas, policy
from dewpoint.plugins.mist.client import SEGMENT, InvalidPathValue, MistClient
from dewpoint.plugins.mist.nodes import OperationUnavailable, _example
from dewpoint.plugins.mist.schemas import converted, resolved, with_defs
from dewpoint.sdk import FatalError, Node, SideEffect, StepContext, declared_model
from dewpoint.sdk.fields import CONNECTION, LITERAL

READ, WRITE = "mist.api.read", "mist.api.write"
WRITE_METHODS = ("DELETE", "POST", "PUT")
ORG_PLACEHOLDER = "{org_id}"
SCALARS = ["string", "integer", "number", "boolean"]


class RouteRefused(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.route_refused", "This Mist route is never reachable from a workflow.")


class OrgMismatch(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.org_mismatch", "The path names an org other than the connection's.")


class InvalidQuery(FatalError):
    def __init__(self) -> None:
        super().__init__(
            "mist.invalid_query", "The query names a parameter the operation doesn't take, or a bad value."
        )


class InvalidBody(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.invalid_body", "The body doesn't match the operation's description.")


@dataclass(frozen=True)
class Route:
    """An allowed operation as the generic nodes reach it."""

    operation: str
    method: str
    segments: tuple[str, ...]
    scope: str


def routes(node: str) -> list[Route]:
    """The operations the map allows to `node`, whatever their routes: the run refuses the always-refused ones."""
    return [
        Route(op_id, e.method, tuple(e.path.split("/")), e.scope or "")
        for op_id, e in sorted(policy.load().entries.items())
        if e.state == "allowed" and node in e.nodes
    ]


VALUE = "[A-Za-z0-9_.~-]+"  # a path value: one segment of unreserved characters (as the client checks)


def _pattern(path: str) -> str:
    """A path template as the config's pattern: each value a plain segment, the org's also `{org_id}`."""
    parts = [
        f"(?:{VALUE}|\\{{org_id\\}})" if s == ORG_PLACEHOLDER else VALUE if s.startswith("{") else re.escape(s)
        for s in path.split("/")
    ]
    return "^" + "/".join(parts) + "$"


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


_CHECKERS: dict[str, tuple[dict[str, Draft202012Validator], dict[str, Draft202012Validator], Any]] = {}


def _checkers(operation: str) -> tuple[dict[str, Draft202012Validator], dict[str, Draft202012Validator], Any]:
    """An operation's path value and query validators, and its body's (None when it takes none), made once."""
    if operation not in _CHECKERS:
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
        _CHECKERS[operation] = (path, query, body)
    return _CHECKERS[operation]


class MistApi(Node):
    """A generic node: `mist.api.read` or `mist.api.write`."""

    fixed_method: ClassVar[str | None] = None
    credentials = ("mist",)

    def _target(self, config: Any) -> tuple[dict[str, Any], str, Route, dict[str, str]]:
        """The config's values, its method, the route it reaches and its path values: refused before anything is
        sent, and before the connection is opened, unless the map allows the route to this node."""
        values: dict[str, Any] = dict(config.root)
        method = self.fixed_method or str(values.get("method", ""))
        path = values.get("path")
        if not isinstance(path, str) or policy.refused(path):
            raise RouteRefused()
        segments = path.split("/")
        if any(not SEGMENT.match(s) and s != ORG_PLACEHOLDER for s in segments[1:]):
            raise InvalidPathValue()
        found = matched(routes(self.type), method, segments)
        if found is None:
            raise OperationUnavailable()
        route, path_values = found
        if policy.load().allowed(route.operation, self.type) is None or policy.refused(path):
            raise OperationUnavailable()
        return values, method, route, path_values

    def _checked(
        self, route: Route, path_values: dict[str, str], org: str | None, values: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, Any], Any]:
        checks, query_checks, body_check = _checkers(route.operation)
        out: dict[str, str] = {}
        for name, value in path_values.items():
            if name == "org_id":
                if org is not None and value not in (org, ORG_PLACEHOLDER):
                    raise OrgMismatch()
                continue
            if not checks[name].is_valid(value):
                raise InvalidPathValue()
            out[name] = value
        query = values.get("query") or {}
        if not isinstance(query, Mapping) or any(
            name not in query_checks or not query_checks[name].is_valid(v) for name, v in query.items()
        ):
            raise InvalidQuery()
        body = values.get("body")
        if (body_check is None and body is not None) or (body_check is not None and body is not None
                                                          and not body_check.is_valid(body)):  # fmt: skip
            raise InvalidBody()
        return out, dict(query), body

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        values, method, route, path_values = self._target(config)
        self._checked(route, path_values, None, values)  # every check that needs no connection, first
        client = MistClient(await ctx.connection(uuid.UUID(values["connection"])))
        checked, query, body = self._checked(route, path_values, client.org_id, values)
        path = client.path("/".join(route.segments), checked)
        if route.scope == "site":
            await client.check_site(checked["site_id"])
        answer = await client.call(method, path, query=query, body=body)
        out: Any = {"status": answer.status, "body": answer.body}
        return self.Output.model_construct(out)  # a declared model's value; the runtime checks it

    async def simulate(self, ctx: StepContext, config: Any) -> BaseModel:
        """The matched operation's 2xx example from the OAS, never a request."""
        values, _, route, path_values = self._target(config)
        self._checked(route, path_values, None, values)
        example = _example(oas.document(), oas.operations()[route.operation])
        out: Any = {"status": 200, "body": copy.deepcopy(example)}
        return self.Output.model_construct(out)


def _config(node: str, write: bool) -> dict[str, Any]:
    paths = sorted({"/".join(r.segments) for r in routes(node)})
    props: dict[str, Any] = {
        "connection": {"type": "string", "format": "uuid", "title": "Connection", LITERAL: True, CONNECTION: "mist"},
    }
    if write:
        props["method"] = {"enum": list(WRITE_METHODS), "title": "Method"}
    props["path"] = {
        "type": "string",
        "title": "Path",
        "description": "A path the policy map allows this node, e.g. /api/v1/orgs/{org_id}/wlans; {org_id} is the "
        "connection's org.",
        "maxLength": 512,
        "anyOf": [{"pattern": _pattern(p)} for p in paths],
    }
    props["query"] = {"type": "object", "title": "Query", "additionalProperties": {"type": SCALARS}}
    if write:
        props["body"] = {"title": "Body"}
    required = ["connection", "method", "path"] if write else ["connection", "path"]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


OUTPUT = {
    "type": "object",
    "properties": {"status": {"type": "integer", "title": "Status"}, "body": {}},
    "required": ["status", "body"],
    "additionalProperties": False,
}


def build() -> tuple[type[Node], ...]:
    read = type(
        "MistApiRead",
        (MistApi,),
        {
            "__module__": __name__, "__qualname__": "MistApiRead", "type": READ, "version": 1, "title": "Mist API read",
            "description": "A GET of any operation the policy map allows, inside the connection's org.",
            "Config": declared_model("MistApiReadConfig", _config(READ, write=False), formats=()),
            "Output": declared_model("MistApiReadOutput", OUTPUT, formats=()),
            "side_effect": SideEffect.NONE, "capabilities": frozenset({"mist.read"}), "fixed_method": "GET",
            "timeout": timedelta(minutes=1),
        },
    )  # fmt: skip
    write = type(
        "MistApiWrite",
        (MistApi,),
        {
            "__module__": __name__, "__qualname__": "MistApiWrite", "type": WRITE, "version": 1,
            "title": "Mist API write",
            "description": "A POST, PUT or DELETE of any operation the policy map allows, inside the connection's org; "
            "never retried once sent.",
            "Config": declared_model("MistApiWriteConfig", _config(WRITE, write=True), formats=()),
            "Output": declared_model("MistApiWriteOutput", OUTPUT, formats=()),
            "side_effect": SideEffect.AMBIGUOUS, "capabilities": frozenset({"mist.write"}),
            "timeout": timedelta(minutes=1),
        },
    )  # fmt: skip
    return read, write


NODES = build()
