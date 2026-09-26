# SPDX-License-Identifier: Apache-2.0
"""Seed workflows and versions directly (as the table owner), for tests that don't exercise publishing."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

PROFILE = "cel-cpp-0.1.3/fn-1/cls-1"


async def seed_workflow(
    owner_sessionmaker: Any,
    *,
    tenant_id: uuid.UUID | None = None,
    name: str = "W",
    node_refs: Sequence[str] = ("testkit.echo@1",),
    enabled: bool = True,
    active: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant, wf, version = tenant_id or uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        if tenant_id is None:
            await s.execute(
                text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": tenant.hex[:12]}
            )
        await s.execute(text("insert into cel_profiles(profile) values (:p) on conflict do nothing"), {"p": PROFILE})
        await s.execute(
            text("insert into workflows(id,tenant_id,name,enabled,draft) values (:w,:t,:n,:e,'{}')"),
            {"w": wf, "t": tenant, "n": name, "e": enabled},
        )
        await s.execute(
            text(
                "insert into workflow_versions(id,tenant_id,workflow_id,number,graph,node_refs,engine_abi,cel_profile,"
                "input_schema,output_schema,vars_schema,closure_version_ids,closure_workflow_ids,closure_node_refs,"
                "closure_cel_profiles,closure_depth,graph_hash,version_hash) "
                "values (:v,:t,:w,1,'{}',cast(:refs as text[]),1,"
                "cast(:p as text),"
                "'{}','{}','{}',array[cast(:v as uuid)],array[cast(:w as uuid)],cast(:refs as text[]),"
                "array[cast(:p as text)],0,'g','v')"
            ),
            {"v": version, "t": tenant, "w": wf, "p": PROFILE, "refs": list(node_refs)},
        )
        if active:
            await s.execute(text("update workflows set active_version_id = :v where id = :w"), {"v": version, "w": wf})
    return tenant, wf, version
