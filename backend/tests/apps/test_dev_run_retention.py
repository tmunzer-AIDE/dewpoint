# SPDX-License-Identifier: Apache-2.0
"""`dewpoint dev run` under the retention cutoff (engine 2b spec §10.1; the owner's M2 review): an exact retry under an
old key admits nothing new and shows nothing of a request past its tenant's cutoff, nor does a wait on one."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from dewpoint.apps import dev_run
from tests.apps.test_admission import KEYS, TOKEN, current, published

INPUT = {"token": TOKEN, "site": "a"}


@pytest.mark.usefixtures("development_deployment")
@pytest.mark.parametrize(("ago", "kept"), [(timedelta(days=2), False), (timedelta(hours=1), True)])
async def test_an_old_keys_retry_and_its_wait_stop_at_the_cutoff(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, ago: timedelta,
    kept: bool,
) -> None:  # fmt: skip
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text("insert into tenant_retention (tenant_id, runs_days) values (:t, 1)"), {"t": ctx.tenant_id}
        )
    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input=INPUT,
                                  simulate=False, idempotency_key="k1")  # fmt: skip
    async with owner_sessionmaker() as s, s.begin():
        cancelled = ("update run_requests set status = 'cancelled', reason = 'user_cancelled', ended_at = "
                     "now() - cast(:ago as interval) where id = :i")  # fmt: skip
        await s.execute(text(cancelled), {"ago": ago, "i": request.id})
    if kept:
        again = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input=INPUT,
                                    simulate=False, idempotency_key="k1")  # fmt: skip
        assert again.id == request.id
        assert await dev_run.ended(dispatch_sessionmaker, ctx.tenant_id, request.id) == dev_run.Ended(
            "request", "cancelled", "user_cancelled", None
        )  # fmt: skip
        return
    with pytest.raises(dev_run.RequestNotRetainedError):
        await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input=INPUT,
                            simulate=False, idempotency_key="k1")  # fmt: skip
    with pytest.raises(dev_run.RequestNotRetainedError):
        await dev_run.ended(dispatch_sessionmaker, ctx.tenant_id, request.id)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from run_requests"))).scalar() == 1
