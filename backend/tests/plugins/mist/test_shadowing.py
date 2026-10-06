# SPDX-License-Identifier: Apache-2.0
"""A path value never reaches another operation (the 3b-1 review's H1): a curated node's id taking the literal a
sibling route has at that position (`DELETE …/alarmtemplates/suppress` is `unsuppressOrgSuppressedAlarms`, held) is
refused at publish, by the config's checks, and again by the node before anything is sent, run or simulated: each
value must match its parameter, and the concrete path must resolve to the node's own operation among all of the
OAS's."""

import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.plugins.mist import PLUGIN, oas, routing
from dewpoint.plugins.mist.nodes import MistOperation
from dewpoint.sdk import FatalError
from tests.plugins.mist.fakes import ORG, SITE, FakeConnection, FakeHttp, FakeStep, Reply
from tests.support.catalog import catalog
from tests.support.graphs import G


def shadowings() -> list[tuple[type[MistOperation], str, str, str]]:
    """(node, its placeholder, the literal another operation has there, that operation)."""
    found = []
    ops = oas.operations()
    for node in PLUGIN.nodes:
        if not issubclass(node, MistOperation):
            continue
        mine = node.path.split("/")
        for other in ops.values():
            theirs = other.path.split("/")
            if other.id == node.operation or other.method != node.method or len(theirs) != len(mine):
                continue
            for i, (a, b) in enumerate(zip(mine, theirs, strict=True)):
                if a.startswith("{") and a != "{org_id}" and not b.startswith("{"):
                    rest = [(x, y) for j, (x, y) in enumerate(zip(mine, theirs, strict=True)) if j != i]
                    if all(x == y or x.startswith("{") or y.startswith("{") for x, y in rest):
                        found.append((node, a[1:-1], b, other.id))
    return found


SHADOWS = shadowings()


def test_the_description_has_such_siblings() -> None:
    assert len(SHADOWS) >= 19  # the review's count; a test that finds none proves nothing
    assert any(op == "unsuppressOrgSuppressedAlarms" for *_, op in SHADOWS)


def config(node: type[MistOperation], field: str, literal: str) -> dict[str, Any]:
    values = {p["name"]: str(uuid.uuid4()) for p in oas.operations()[node.operation].parameters if p["in"] == "path"}
    values.pop("org_id", None)
    values["site_id"] = SITE
    values = {k: v for k, v in values.items() if k in node.Config.model_json_schema()["properties"]}
    return {**values, field: literal}


@pytest.mark.parametrize(("node", "field", "literal", "other"), SHADOWS, ids=lambda v: getattr(v, "type", str(v)))
async def test_a_siblings_literal_is_refused_everywhere(
    node: type[MistOperation], field: str, literal: str, other: str
) -> None:
    http = FakeHttp({("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"org_id": ORG})})
    connection = FakeConnection(http)
    raw = {"connection": str(connection.id), **config(node, field, literal)}
    with pytest.raises(Exception, match="Doesn't match"):
        node.Config.model_validate(raw)
    g = G().node("a", f"{node.type}@1", raw)
    found = validate(g.build(), ValidationContext(catalog=catalog(PLUGIN)))
    assert any(
        d.code == "config.invalid"
        and d.field == f"/nodes/{g.nodes[0]['id']}/config/{field}"
        or d.code == "config.invalid"
        and field in (d.field or "")
        for d in found.diagnostics
    ), found.diagnostics
    value = node.Config.model_construct(raw)  # past every config check: the node's own refuses it
    for call in (node().run, node().simulate):
        with pytest.raises(FatalError) as e:
            await call(FakeStep(connection), value)  # type: ignore[arg-type]
        assert e.value.code == "mist.invalid_path_value"
    assert http.sent == []


ALARM_TEMPLATE = "3c2b1a09-8f7e-4d6c-9b5a-4f3e2d1c0b9a"


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("DELETE", "/api/v1/orgs/{o}/alarmtemplates/suppress", "unsuppressOrgSuppressedAlarms"),
        ("DELETE", f"/api/v1/orgs/{{o}}/alarmtemplates/{ALARM_TEMPLATE}", "deleteOrgAlarmTemplate"),
        ("GET", "/api/v1/sites/{s}/wxrules/derived", "ListSiteWxRulesDerived"),
        ("GET", "/api/v1/sites/{s}/wxrules/count", None),  # ties with /{zone_type}/count
        ("GET", "/api/v1/sites/{s}/nowhere/at/all", None),
    ],
)
def test_a_concrete_path_reaches_its_most_specific_operation(method: str, path: str, operation: str | None) -> None:
    assert routing.reaches(method, path.format(o=ORG, s=SITE)) == operation


async def test_a_value_its_parameter_accepts_still_cant_reach_another_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = next(n for n in PLUGIN.nodes if n.type == "mist.org_alarm_templates.delete")
    assert issubclass(node, MistOperation)
    accepts_all = Draft202012Validator({})
    checks = routing.checkers(node.operation)
    monkeypatch.setattr(routing, "checkers", lambda op: routing.Checkers(
        {k: accepts_all for k in checks.path}, checks.query, checks.body))  # fmt: skip
    connection = FakeConnection(FakeHttp({}))
    value = node.Config.model_construct({"connection": str(connection.id), "alarmtemplate_id": "suppress"})
    with pytest.raises(FatalError) as e:
        await node().run(FakeStep(connection), value)  # type: ignore[arg-type]
    assert e.value.code == "mist.invalid_path_value" and connection.http.sent == []
