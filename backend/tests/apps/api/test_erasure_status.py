# SPDX-License-Identifier: Apache-2.0
"""The API never shows an unproven erasure as complete (2b-4b M4 recovery, task 16; design revision 5 §3, revision 6
§4 and §5).

An erasure's view gains what's unresolved for its tenant (`erasure_unresolved`), its `verified_close`, whether it's
proven (`erasure_proven`: completed, no qualification, nothing unresolved), its `qualification` and
`legacy_completed_at`, and its known executions counted by provenance (`retained_out` apart from `gone`). Its
`status` is `complete` only when proven: a held erasure, or one completed under the old standard, is `incomplete`."""

import uuid
from typing import Any

from tests.apps.api.test_erasure_api import admin_of, tenant_of, url
from tests.core.retention.support import sql


async def _shown(app: Any, owner: Any, settings: Any, *provenances: str, **record: Any) -> dict[str, Any]:
    """An erasure started through the API, its record then set to `record` and its known executions written (as the
    retention process would), read back."""
    admin, _ = await admin_of(app, owner, settings)
    tenant, slug = await tenant_of(app, owner, settings)
    async with admin:
        assert (await admin.post(url(tenant), json={"confirm": slug})).status_code == 202
        await _known(owner, tenant, *provenances)
        sets = ", ".join(f"{name} = {value}" for name, value in record.items())
        await sql(owner, f"update tenant_erasures set {sets} where tenant_id = :t", t=tenant)  # noqa: S608  # fixed
        shown: dict[str, Any] = (await admin.get(url(tenant))).json()
    return shown


async def _known(owner: Any, tenant: uuid.UUID, *provenances: str) -> None:
    for n, provenance in enumerate(provenances):
        await sql(owner, "insert into tenant_erasure_known (tenant_id, kind, workflow_id, run_id, provenance) "
                  "values (:t, 'execution', :w, 'r1', :p)", t=tenant, w=f"w:{n}", p=provenance)  # fmt: skip


async def test_a_held_erasure_shows_incomplete_with_its_count_its_verified_close_and_no_bound(
    app, owner_sessionmaker, api_settings
) -> None:
    shown = await _shown(app, owner_sessionmaker, api_settings, "absent", "gone", step="90",
                         failure="'absence_unresolved'", absence_unresolved="1", verified_close="now()")  # fmt: skip
    assert (shown["status"], shown["unresolved"], shown["proven"]) == ("incomplete", 1, False)
    assert shown["verified_close"] is not None and (shown["latest_close"], shown["check_after"]) == (None, None)
    assert shown["known"] == {"absent": 1, "gone": 1}


async def test_one_completed_under_the_old_standard_shows_its_completion_and_is_not_proven(
    app, owner_sessionmaker, api_settings
) -> None:
    shown = await _shown(app, owner_sessionmaker, api_settings, "legacy", step="100",
                         completed_at="'2026-09-01T00:00:00Z'", legacy_completed_at="'2026-09-01T00:00:00Z'",
                         qualification="'legacy_completion_unproven'")  # fmt: skip
    assert (shown["status"], shown["proven"]) == ("incomplete", False)
    assert shown["qualification"] == "legacy_completion_unproven"
    assert shown["completed_at"][:10] == shown["legacy_completed_at"][:10] == "2026-09-01"
    assert shown["unresolved"] == 1


async def test_a_proven_erasure_is_complete_its_retained_out_counted_apart_from_gone(
    app, owner_sessionmaker, api_settings
) -> None:
    shown = await _shown(app, owner_sessionmaker, api_settings, "gone", "retained_out", step="100",
                         completed_at="now()")  # fmt: skip
    assert (shown["status"], shown["proven"], shown["unresolved"]) == ("complete", True, 0)
    assert shown["known"] == {"gone": 1, "retained_out": 1}
