# SPDX-License-Identifier: Apache-2.0
"""The nodes that change an incident by its sys_id (plugins-3 3d-2, D22), each a PATCH to `/incident/{sys_id}`:
`servicenow.update_incident` and `servicenow.resolve_incident` are idempotent (a repeat sets the same values); resolve
checks the answer's `state` is the one it set. `servicenow.add_work_note` is ambiguous: each note appends."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from dewpoint.plugins.servicenow import TABLE, AddWorkNote, ResolveIncident, UpdateIncident
from dewpoint.sdk import FatalError, RetryableError, SideEffect
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply

SYS_ID = "9d385017c611228701d22104cc95c371"
CONNECTION = "00000000-0000-0000-0000-000000000001"
RECORD = f"{TABLE}/{SYS_ID}"


def config(node: Any, **changes: Any) -> Any:
    return node.Config.model_validate({"connection": CONNECTION, "sys_id": SYS_ID, **changes})


def resolve(**changes: Any) -> Any:
    return config(ResolveIncident, **{"close_code": "Solution provided", "close_notes": "Disk cleaned.", **changes})


def patched(**fields: Any) -> Reply:
    return Reply(200, {"result": {"sys_id": SYS_ID, "number": "INC0010002", **fields}})


async def run(node: Any, value: Any, script: Any) -> tuple[Any, FakeHttp]:
    http = FakeHttp(script)
    conn = FakeConnection(http, config={"instance_url": "https://acme.service-now.com"}, id=uuid.UUID(CONNECTION),
                          type="servicenow")  # fmt: skip
    out = await node().run(FakeStep(conn), value)
    return out.model_dump(mode="json"), http


def test_side_effects() -> None:
    assert UpdateIncident.side_effect == ResolveIncident.side_effect == SideEffect.IDEMPOTENT
    assert AddWorkNote.side_effect == SideEffect.AMBIGUOUS
    assert [n.type for n in (UpdateIncident, ResolveIncident, AddWorkNote)] == [
        "servicenow.update_incident", "servicenow.resolve_incident", "servicenow.add_work_note"]  # fmt: skip
    assert all(n.credentials == ("servicenow",) for n in (UpdateIncident, ResolveIncident, AddWorkNote))


OWN = {UpdateIncident: {"short_description": "x"}, ResolveIncident: {"close_code": "c", "close_notes": "n"},
       AddWorkNote: {"text": "t"}}  # fmt: skip


@pytest.mark.parametrize("node", [UpdateIncident, ResolveIncident, AddWorkNote])
@pytest.mark.parametrize("sys_id", ["", "A" * 32, "a" * 31, "../" + "a" * 29, "a" * 32 + "\n"])
def test_a_record_is_named_by_its_sys_id(node: Any, sys_id: str) -> None:
    assert node.Config.model_validate({"connection": CONNECTION, "sys_id": SYS_ID, **OWN[node]}).sys_id == SYS_ID
    with pytest.raises(ValidationError):
        node.Config.model_validate({"connection": CONNECTION, "sys_id": sys_id, **OWN[node]})


async def test_an_update_patches_only_what_it_sets() -> None:
    value = config(UpdateIncident, short_description="db-1 disk full\nagain", urgency="2", state="2",
                   assignment_group="b" * 32)  # fmt: skip
    out, http = await run(UpdateIncident, value, lambda sent: patched())
    [sent] = http.sent
    assert (sent.method, sent.url, sent.params, sent.headers) == ("PATCH", RECORD, {"sysparm_fields": "sys_id,number"},
                                                                  {"Accept": "application/json"})  # fmt: skip
    assert sent.json == {"short_description": "db-1 disk full again", "urgency": "2", "state": "2",
                         "assignment_group": "b" * 32}  # fmt: skip
    assert out == {"sys_id": SYS_ID, "number": "INC0010002", "truncated": []}


def test_an_update_sets_something() -> None:
    with pytest.raises(ValidationError):
        config(UpdateIncident)


@pytest.mark.parametrize(
    ("field", "value"),
    [("state", "Resolved"), ("state", "-1"), ("state", "12345"), ("impact", "4"), ("assignment_group", "x"),
     ("category", "a\nb")],
)  # fmt: skip
def test_an_update_of_another_form_is_refused(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        config(UpdateIncident, **{field: value})


async def test_long_texts_are_cut_and_reported() -> None:
    value = config(UpdateIncident, short_description="s" * 200, description="d" * 5000)
    out, http = await run(UpdateIncident, value, lambda sent: patched())
    body = http.sent[0].json
    assert len(body["short_description"]) == 160 and len(body["description"]) == 4000
    assert out["truncated"] == ["short_description", "description"]


async def test_a_resolve_sets_the_resolved_state_and_checks_it() -> None:
    out, http = await run(ResolveIncident, resolve(), lambda sent: patched(state="6"))
    [sent] = http.sent
    assert (sent.method, sent.url) == ("PATCH", RECORD)
    assert sent.params == {"sysparm_fields": "sys_id,number,state"}
    assert sent.json == {"state": "6", "close_code": "Solution provided", "close_notes": "Disk cleaned."}
    assert out == {"sys_id": SYS_ID, "number": "INC0010002", "state": "6", "truncated": []}


async def test_an_instances_own_resolved_state_is_set() -> None:
    out, http = await run(ResolveIncident, resolve(resolved_state="106"), lambda sent: patched(state="106"))
    assert http.sent[0].json["state"] == "106" and out["state"] == "106"


@pytest.mark.parametrize("state", ["2", "7", None, 6])
async def test_a_resolve_the_instance_didnt_apply_fails(state: Any) -> None:
    with pytest.raises(FatalError) as raised:
        await run(ResolveIncident, resolve(), lambda sent: patched(state=state))
    assert raised.value.code == "servicenow.not_resolved"


@pytest.mark.parametrize("missing", ["close_code", "close_notes"])
def test_a_resolve_names_its_code_and_notes(missing: str) -> None:
    values = {"connection": CONNECTION, "sys_id": SYS_ID, "close_code": "c", "close_notes": "n"}
    del values[missing]
    with pytest.raises(ValidationError):
        ResolveIncident.Config.model_validate(values)


@pytest.mark.parametrize(("field", "value"), [("close_code", ""), ("close_code", "a\nb"), ("close_code", "c" * 101),
                                              ("close_notes", ""), ("resolved_state", "Resolved")])  # fmt: skip
def test_a_resolve_of_another_form_is_refused(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        resolve(**{field: value})


async def test_long_close_notes_are_cut_and_reported() -> None:
    out, http = await run(ResolveIncident, resolve(close_notes="n" * 5000), lambda sent: patched(state="6"))
    assert len(http.sent[0].json["close_notes"]) == 4000 and out["truncated"] == ["close_notes"]


@pytest.mark.parametrize(("visibility", "field"), [("work_notes", "work_notes"), ("comments", "comments")])
async def test_a_note_appends_a_work_note_or_a_comment(visibility: str, field: str) -> None:
    value = config(AddWorkNote, text="Rebooted db-1.\nWatching.", visibility=visibility)
    out, http = await run(AddWorkNote, value, lambda sent: patched())
    [sent] = http.sent
    assert (sent.method, sent.url, sent.params) == ("PATCH", RECORD, {"sysparm_fields": "sys_id,number"})
    assert sent.json == {field: "Rebooted db-1.\nWatching."}
    assert out == {"sys_id": SYS_ID, "number": "INC0010002", "truncated": []}


def test_a_note_is_internal_unless_asked() -> None:
    assert config(AddWorkNote, text="x").visibility == "work_notes"


async def test_a_long_note_is_cut_and_reported() -> None:
    out, http = await run(AddWorkNote, config(AddWorkNote, text="n" * 5000), lambda sent: patched())
    assert len(http.sent[0].json["work_notes"]) == 4000 and out["truncated"] == ["text"]


@pytest.mark.parametrize("node", [UpdateIncident, ResolveIncident, AddWorkNote])
@pytest.mark.parametrize(
    ("status", "error", "code"),
    [(400, FatalError, "servicenow.invalid_request"), (401, FatalError, "servicenow.unauthorized"),
     (403, FatalError, "servicenow.forbidden"), (404, FatalError, "servicenow.not_found"),
     (500, RetryableError, "servicenow.unavailable"), (201, RetryableError, "servicenow.unexpected")],
)  # fmt: skip
async def test_answers(node: Any, status: int, error: type[Exception], code: str) -> None:
    value = {UpdateIncident: lambda: config(UpdateIncident, urgency="1"), ResolveIncident: resolve,
             AddWorkNote: lambda: config(AddWorkNote, text="x")}[node]()  # fmt: skip
    with pytest.raises(error) as raised:
        await run(node, value, lambda sent: Reply(status, {"error": {"message": "secret-looking detail"}}))
    assert raised.value.code == code and "secret-looking" not in str(raised.value)  # type: ignore[attr-defined]


@pytest.mark.parametrize("node", [UpdateIncident, AddWorkNote])
@pytest.mark.parametrize(
    "body",
    [None, {"result": []}, {"result": {"sys_id": "b" * 32, "number": "INC1"}}, {"result": {"sys_id": SYS_ID}}],
)  # fmt: skip
async def test_an_answer_for_another_record_or_none_is_unexpected(node: Any, body: Any) -> None:
    value = config(UpdateIncident, urgency="1") if node is UpdateIncident else config(AddWorkNote, text="x")
    with pytest.raises(RetryableError) as raised:
        await run(node, value, lambda sent: Reply(200, body))
    assert raised.value.code == "servicenow.unexpected"


@pytest.mark.parametrize(
    ("node", "value", "out"),
    [
        (UpdateIncident, {"description": "d" * 5000},
         {"sys_id": SYS_ID, "number": "INC0000000", "truncated": ["description"]}),
        (ResolveIncident, {"close_code": "c", "close_notes": "n"},
         {"sys_id": SYS_ID, "number": "INC0000000", "state": "6", "truncated": []}),
        (AddWorkNote, {"text": "x"}, {"sys_id": SYS_ID, "number": "INC0000000", "truncated": []}),
    ],
)  # fmt: skip
async def test_simulating_sends_nothing(node: Any, value: dict[str, Any], out: dict[str, Any]) -> None:
    http = FakeHttp(lambda sent: patched())
    step = FakeStep(FakeConnection(http, id=uuid.UUID(CONNECTION), type="servicenow"))
    result = await node().simulate(step, config(node, **value))
    assert http.sent == [] and step.opened == []
    assert result.model_dump(mode="json") == out
