# SPDX-License-Identifier: Apache-2.0
"""The production gate at the start boundary (engine 2b spec §2.3): every start path comes through `admit`, the dev CLI
included, and in a production deployment it admits nothing while the gate is off. The environment itself:
tests/core/platform/test_service.py."""

from typing import Any

import pytest
from sqlalchemy import func, select, text

from dewpoint.apps.runs import PRODUCTION_RUNS_DISABLED, NotAdmissibleError, start_run
from dewpoint.core.models.runs import Run
from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, record_environment
from dewpoint.engine.runtime.activities import SIMULATE
from tests.apps.test_runs import FakeClient, published


async def refused(dispatch: Any, api_settings: Any, ctx: Any, version: Any) -> tuple[list[str], FakeClient]:
    client = FakeClient()
    with pytest.raises(NotAdmissibleError) as e:
        await start_run(
            dispatch, client, api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=version, trigger={}, mode=SIMULATE,
        )  # fmt: skip
    return e.value.reasons, client


async def run_count(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(select(func.count()).select_from(Run))).scalar_one())


async def test_a_production_deployment_admits_nothing_while_its_gate_is_off(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    reasons, client = await refused(dispatch_sessionmaker, api_settings, ctx, version)
    assert reasons == [PRODUCTION_RUNS_DISABLED]
    assert (client.calls, await run_count(owner_sessionmaker)) == ([], 0)  # nothing started, no run row


async def test_the_gate_is_the_only_thing_between_a_production_deployment_and_its_runs(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """2b-4's audited command turns it on; here the table's owner does."""
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
        await s.execute(text("UPDATE platform_settings SET production_runs = true"))
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient()
    await start_run(
        dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
        tenant_id=ctx.tenant_id, version_id=version, trigger={}, mode=SIMULATE,
    )  # fmt: skip
    assert len(client.started) == 1


async def test_a_deployment_that_never_recorded_its_environment_admits_nothing(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    reasons, client = await refused(dispatch_sessionmaker, api_settings, ctx, version)
    assert reasons == [NOT_RECORDED]
    assert (client.calls, await run_count(owner_sessionmaker)) == ([], 0)
