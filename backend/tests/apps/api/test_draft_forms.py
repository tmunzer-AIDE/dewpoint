# SPDX-License-Identifier: Apache-2.0
"""What the editor asks before simulating (B8; the simulation design §6.6, §7.1, §7.6), at the revision it will send,
`workflow.edit` and `run.start` as simulating needs: the draft's start form, in `start-form`'s shape (which reads only
the active version); and a step's seed contract, the draft validated first as admission validates it, each entry
prefilled from its step's own sample only where the sample is provably faithful and fits (D-s2), else typed, saying
why."""

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.test_run_requests_api import as_role, keyed_app
from tests.apps.test_admission import CSV_GRAPH, TOKEN_GRAPH, current, published
from tests.apps.test_admission_drafts import LOOP_GRAPH, drafted
from tests.apps.test_workflow_ops import create, save
from tests.core.retention.support import run
from tests.support.graphs import G, cel, nid, ref

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
PICKER = {"node": "testkit.pick@1", "field": "site_id", "connection": "c0ffee00-0000-4000-8000-000000000001"}

READS = (
    G().node("a", "flow.transform@1", {"fields": {"n": cel("1 + 1")}})
    .node("c", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
    .node("d", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
    .node("e", "testkit.echo@1", {"value": 1})
    .node("f", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
    .node("g", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
    .node("b", "flow.transform@1", {"fields": {
        "m": ref("steps.a.output.n"), "t": ref("trigger.site"), "u": ref("steps.e.output.value"),
        "v": ref("steps.c.output.k"), "w": ref("steps.d.output.k"), "x": ref("steps.f.output.k"),
        "y": ref("steps.g.output.k"),
    }})
    .edge("a", "b").edge("c", "b").edge("d", "b").edge("e", "b").edge("f", "b").edge("g", "b").data()
    | {"settings": {"input_schema": {"type": "object", "properties": {"site": {"type": "string"}},
                                     "required": ["site"]}}}
)  # fmt: skip


def url(ctx: Any, wf: uuid.UUID, path: str) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/{path}"


async def sampled(owner: Any, ctx: Any, wf: uuid.UUID, outputs: dict[str, Any]) -> None:
    """An ended run of the active version, each step of `outputs` with that output preview: its B7 sample."""
    async with owner() as s:
        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
    run_id = await run(owner, {"t": ctx.tenant_id, "w": wf, "v": version, "u": ctx.user.id}, timedelta())
    async with owner() as s, s.begin():
        for key, output in outputs.items():
            await s.execute(text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
                                 "status, started_at, ended_at, output_preview) values (:t, :r, :s, '', 1, :k, "
                                 "'succeeded', now(), now(), cast(:o as jsonb))"),
                            {"t": ctx.tenant_id, "r": run_id, "s": nid(key), "k": key,
                             "o": json.dumps(output)})  # fmt: skip


async def test_the_drafts_start_form_reads_the_draft_at_its_revision_published_or_not(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TOKEN_GRAPH)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.get(url(ctx, wf, "start-form"), params={"revision": 1})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["workflow_id"], body["draft_revision"], body["csv"]) == (str(wf), 1, None)
    assert sorted((f["name"], f["required"], f["sensitive"]) for f in body["fields"]) == [
        ("site", False, False), ("token", True, True),
    ]  # fmt: skip
    await save(api_sessionmaker, ctx, wf, CSV_GRAPH)  # revision 2: a CSV, so it can't be simulated whole (D-b7)
    stale = await editor.get(url(ctx, wf, "start-form"), params={"revision": 1})
    assert (stale.status_code, stale.json()) == (409, {"error": "draft_conflict", "draft_revision": 2})
    csv = (await editor.get(url(ctx, wf, "start-form"), params={"revision": 2})).json()["csv"]
    assert csv["columns"] == [{"header": "Site", "name": "site", "type": "string", "required": False,
                               "sensitive": False}]  # fmt: skip


async def test_a_drafts_form_it_cant_read_whole_gives_the_fields_it_can(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """A draft saves any input schema the graph parses: its form answers with what it reads, never a 500 (4f-3 §4.3)."""
    schema = {"type": "object", "properties": {"flag": True, "site": {"type": "string", "x-dewpoint-picker": "x"},
                                               "kit": {"type": "string", "x-dewpoint-picker": PICKER}},
              "required": [{"x": 1}, "kit"]}  # fmt: skip
    graph = G().node("e", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": schema}}
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, graph)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.get(url(ctx, wf, "start-form"), params={"revision": 1})
    assert answer.status_code == 200, answer.text
    assert {f["name"]: f for f in answer.json()["fields"]} == {
        "site": {"name": "site", "type": "string", "required": False, "sensitive": False},
        "kit": {"name": "kit", "type": "string", "required": True, "sensitive": False,
                "picker": PICKER | {"list": {"plugin": "Testkit", "title": "Sites", "noun": "sites"}}},
    }  # fmt: skip


@pytest.mark.parametrize(("role", "status"), [("viewer", 403), ("operator", 403), ("editor", 200), ("admin", 200)])
async def test_the_drafts_forms_need_what_simulating_needs(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, role,
    status,
) -> None:  # fmt: skip
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, READS)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
    for path in ("start-form", f"steps/{nid('b')}/seeds"):
        assert (await client.get(url(ctx, wf, path), params={"revision": 1})).status_code == status, path


async def test_each_seed_is_prefilled_from_its_steps_own_faithful_sample_or_typed_saying_why(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    await current(dispatch_sessionmaker)
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, READS)
    await sampled(owner_sessionmaker, ctx, wf, {
        "a": {"n": 2}, "c": {"k": "[redacted]"}, "d": {"k": "two"}, "e": {"value": 1}, "g": {"other": 1},
    })  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.get(url(ctx, wf, f"steps/{nid('b')}/seeds"), params={"revision": 1})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["draft_revision"], body["step_id"], body["refused"]) == (1, str(nid("b")), None)
    entries = {e["pointer"]: e for e in body["entries"]}
    assert {k: (e["types"], e["required"], e["nullable"]) for k, e in entries.items() if k == "/steps/a/output/n"} == {
        "/steps/a/output/n": (["integer"], True, False),
    }  # fmt: skip
    assert {k: e["prefill"] for k, e in entries.items()} == {
        "/steps/a/output/n": {"state": "prefilled", "value": 2, "reason": None},
        "/trigger/site": {"state": "typed", "value": None, "reason": "not_step_output"},
        "/steps/e/output/value": {"state": "typed", "value": None, "reason": "sensitive"},  # an echo's: tainted
        "/steps/c/output/k": {"state": "typed", "value": None, "reason": "not_faithful"},
        "/steps/d/output/k": {"state": "typed", "value": None, "reason": "doesnt_fit"},
        "/steps/f/output/k": {"state": "typed", "value": None, "reason": "no_sample"},
        "/steps/g/output/k": {"state": "typed", "value": None, "reason": "not_in_sample"},
    }
    assert entries["/steps/e/output/value"]["sensitive"] is True


async def test_the_seeds_read_validates_the_draft_first_and_says_why_a_step_cant_run_alone(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """4d-1a's deferred minor: an invalid draft's CEL values have no record, so the contract would miss their reads."""
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOP_GRAPH)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    loop = (await editor.get(url(ctx, wf, f"steps/{nid('l')}/seeds"), params={"revision": 1})).json()
    assert (loop["refused"], loop["entries"]) == ("This step can't be simulated alone: simulate the workflow to see it "
                                                  "run.", [])  # fmt: skip
    stale = await editor.get(url(ctx, wf, f"steps/{nid('x')}/seeds"), params={"revision": 2})
    assert (stale.status_code, stale.json()) == (409, {"error": "draft_conflict", "draft_revision": 1})
    broken = await create(api_sessionmaker, ctx, G().node("z", "no.such@1").node("y", "flow.transform@1", {
        "fields": {"n": cel("1 +")}}).data(), name="broken")  # fmt: skip
    invalid = await editor.get(url(ctx, broken, f"steps/{nid('y')}/seeds"), params={"revision": 1})
    assert (invalid.status_code, invalid.json()["error"]) == (422, "invalid")
    assert "node.unknown_type" in [d["code"] for d in invalid.json()["diagnostics"]]


async def test_a_step_that_isnt_in_the_draft_has_no_seed_contract(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Not found, as the draft's other reads of what isn't there; a step that is there but can't run alone says why."""
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOP_GRAPH)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.get(url(ctx, wf, f"steps/{uuid.uuid4()}/seeds"), params={"revision": 1})
    assert (answer.status_code, answer.json()) == (404, {"error": "not_found"})


async def test_a_drafts_picker_naming_an_impossible_version_still_gives_its_form(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The final review's M5: a version no registry row can hold is never asked for; the field shows, its list none."""
    picker = PICKER | {"node": "testkit.pick@99999999999"}
    schema = {"type": "object", "properties": {"site": {"type": "string", "x-dewpoint-picker": picker}}}
    graph = G().node("e", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": schema}}
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, graph)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.get(url(ctx, wf, "start-form"), params={"revision": 1})
    assert answer.status_code == 200, answer.text
    assert answer.json()["fields"][0]["picker"] == picker | {"list": None}


@pytest.mark.parametrize("node", ["testkit.pick@x", "testkit.pick@99999999999"])
async def test_a_drafts_picker_naming_an_unreadable_ref_is_a_problem_never_a_500(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, node: str
) -> None:
    """#142 item 6: a ref no registry row can hold is never looked up (`readable_ref`), so validate, export and publish,
    which share the draft's validation context, answer it as a picker naming no node this server holds."""
    picker = PICKER | {"node": node}
    schema = {"type": "object", "properties": {"site": {"type": "string", "x-dewpoint-picker": picker}}}
    graph = G().node("e", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": schema}}
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, graph)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    base = f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}"
    checked = await editor.post(f"{base}/validate")
    assert checked.status_code == 200, checked.text
    assert [d["code"] for d in checked.json()["diagnostics"]] == ["picker.unknown_node"]
    exported = await editor.get(f"{base}/export")
    assert exported.status_code == 200, exported.text
    published = await editor.post(f"{base}/publish", headers={"If-Match": "1"})
    assert published.status_code == 422, published.text
