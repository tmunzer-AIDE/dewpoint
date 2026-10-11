# SPDX-License-Identifier: Apache-2.0
"""A request made `starting` by a test, as the dispatcher makes it (migration 0054's fence): its send counted and
recorded in flight (`unresolved_sends`, `start_sends`) in the same transaction. No test bypasses the fence."""

import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.engine.runtime.ids import run_workflow_id


async def mark_starting(s: Any, request_id: uuid.UUID, **columns: Any) -> int:
    """In `s`'s transaction: the request `starting`, one more send counted, and that send's intent recorded, with any
    other columns set as given (`sends` among them sets the count itself). Its attempt number."""
    row = (await s.execute(text("select tenant_id, sends, start_request_id from run_requests where id = :i"),
                           {"i": request_id})).one()  # fmt: skip
    sends = columns.pop("sends", row.sends + 1)
    start_request_id = columns.pop("start_request_id", row.start_request_id) or uuid.uuid4()
    await s.execute(
        text("insert into unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, state) "
             "values (:r, :t, :w, :s, 'pending') on conflict (request_id) do nothing"),
        {"r": request_id, "t": row.tenant_id, "w": run_workflow_id(str(row.tenant_id), str(request_id)),
         "s": start_request_id},
    )  # fmt: skip
    await s.execute(
        text("insert into start_sends (request_id, attempt) values (:r, :n)"), {"r": request_id, "n": sends}
    )
    assigned = "".join(f", {name} = :{name}" for name in columns)
    since = "" if "starting_at" in columns else ", starting_at = now()"
    await s.execute(
        text(f"update run_requests set status = 'starting', sends = :sends, "  # noqa: S608
             f"start_request_id = :start_request_id{since}{assigned} where id = :i"),
        {"i": request_id, "sends": sends, "start_request_id": start_request_id, **columns},
    )  # fmt: skip
    return int(sends)
