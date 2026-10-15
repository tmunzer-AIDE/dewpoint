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
