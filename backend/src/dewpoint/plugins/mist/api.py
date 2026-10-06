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
from datetime import timedelta
from functools import cache
from typing import Any, ClassVar

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from dewpoint.plugins.mist import oas, policy, routing
from dewpoint.plugins.mist.client import SEGMENT, InvalidPathValue, MistClient
from dewpoint.plugins.mist.nodes import OperationUnavailable, _example, synthesized
from dewpoint.plugins.mist.routing import UUID, Route, filled, matched, reaches, value_pattern
from dewpoint.plugins.mist.schemas import converted, resolved, secret_fields, with_defs
from dewpoint.sdk import FatalError, Node, SideEffect, StepContext, declared_model
from dewpoint.sdk.fields import CONNECTION, LITERAL, SENSITIVE

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


def routes(node: str) -> list[Route]:
    """The operations the map allows to `node`, whatever their routes: the run refuses the always-refused ones."""
    return [
        Route(op_id, e.method, tuple(e.path.split("/")), e.scope or "")
        for op_id, e in sorted(policy.load().entries.items())
        if e.state == "allowed" and node in e.nodes
    ]


def _pattern(route: Route) -> str:
    """A route as the config's pattern: the org's value a UUID or `{org_id}`, every other its parameter's pattern."""
    parts = [
        f"(?:{UUID}|\\{{org_id\\}})" if s == ORG_PLACEHOLDER
        else f"(?:{value_pattern(route.operation, s[1:-1])})" if s.startswith("{") else re.escape(s)
        for s in route.segments
    ]  # fmt: skip
    return "^" + "/".join(parts) + "$"


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
        if any(not SEGMENT.fullmatch(s) and s != ORG_PLACEHOLDER for s in segments[1:]):
            raise InvalidPathValue()
        found = matched(routes(self.type), method, segments)
        if found is None:
            raise OperationUnavailable()
        route, path_values = found
        if policy.load().allowed(route.operation, self.type) is None or policy.refused(path):
            raise OperationUnavailable()
        if reaches(method, filled("/".join(route.segments), path_values)) != route.operation:
            raise InvalidPathValue()  # a value that is another operation's literal, or ties with one (review H1)
        if route.scope == "site" and policy.load().read(route.operation, self.type, routing.SITE_CHECK) is None:
            raise OperationUnavailable()  # the site check is a read the map must allow (the owner's review, O2)
        return values, method, route, path_values

    def _checked(
        self, route: Route, path_values: dict[str, str], org: str | None, values: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, Any], Any]:
        found = routing.checkers(route.operation)
        checks, query_checks, body_check = found.path, found.query, found.body
        out: dict[str, str] = {}
        for name, value in path_values.items():
            if name == "org_id":
                if org is not None and value not in (org, ORG_PLACEHOLDER):
                    raise OrgMismatch()
                continue
            if not SEGMENT.fullmatch(value) or not checks[name].is_valid(value):
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
        """The matched operation's fixture (`answer_fixture`), never a request."""
        values, _, route, path_values = self._target(config)
        self._checked(route, path_values, None, values)
        out: Any = {"status": 200, "body": copy.deepcopy(answer_fixture(route.operation))}
        return self.Output.model_construct(out)


@cache
def answer_fixture(operation: str) -> Any:
    """What a simulated generic request answers (D13; the owner's review of the checkpoint, O3): the OAS's 2xx example
    when the answer's schema (relaxed as an output's) accepts it, else the smallest value it accepts; null only for an
    operation that answers nothing."""
    doc, op = oas.document(), oas.operations()[operation]
    found = oas.answer(doc, op)
    if found is None:
        return None
    top = resolved(doc, found)
    schema = with_defs(doc, converted(top, output=True), [top], output=True, partial=False)
    example = _example(doc, op)
    if example is not None and Draft202012Validator(schema).is_valid(example):
        return example
    return synthesized(schema)


def _config(node: str, write: bool) -> dict[str, Any]:
    patterns = sorted({_pattern(r) for r in routes(node)})
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
        "anyOf": [{"pattern": p} for p in patterns],
    }
    props["query"] = {"type": "object", "title": "Query", "additionalProperties": {"type": SCALARS}}
    if write:
        props["body"] = {"title": "Body", "$ref": "#/$defs/body"}
    required = ["connection", "method", "path"] if write else ["connection", "path"]
    out: dict[str, Any] = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    if write:  # its operation is known only at run time: Mist's secret-named fields are sensitive at any depth (M3)
        out["$defs"] = {
            "body": {
                "properties": {name: {SENSITIVE: True} for name in secret_fields(oas.document())},
                "additionalProperties": {"$ref": "#/$defs/body"},
                "items": {"$ref": "#/$defs/body"},
            }
        }
    return out


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
