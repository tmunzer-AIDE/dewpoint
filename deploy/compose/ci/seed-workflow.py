# SPDX-License-Identifier: Apache-2.0
"""CI's synthetic data for the Compose proof (engine 2b spec §12): a tenant with its data key, its owner, and a
published workflow of the shipped `flow` plugin's nodes only. Nothing here is real data. Run in the API's image, as
the API's database login, after `dewpoint plugins sync`:

    docker compose run --rm -T api python - < ci/seed-workflow.py

It prints the tenant's id and the workflow's, on its last line."""

import asyncio
import secrets
import uuid
from typing import Any

from dewpoint.apps import workflow_ops
from dewpoint.core.auth.users import create_user
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.tenancy.service import create_tenant
from dewpoint.core.workflows import service as workflows

GRAPH: dict[str, Any] = {
    "graph_format": 1,
    "nodes": [
        {
            "id": "5f0c6e2a-2b2b-4e2b-9c2b-2b2b2b2b2b2b",
            "key": "t",
            "type": "flow.transform@1",
            "config": {"fields": {"answer": {"$value": {"kind": "cel", "expr": "1 + 1"}}}},
            "options": {"on_error": "fail"},
        }
    ],
    "edges": [],
    "settings": {
        "input_schema": {"type": "object"},
        "outputs": {"answer": {"$value": {"kind": "cel", "expr": "steps.t.output.answer"}}},
    },
}


async def seed(settings: Settings) -> tuple[uuid.UUID, uuid.UUID]:
    """The synthetic tenant's id and its published workflow's."""
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        mark = uuid.uuid4().hex[:8]
        async with sessionmaker() as s, s.begin():
            # A synthetic owner no one signs in as: a random password, never written down.
            user = await create_user(s, email=f"ci-{mark}@example.com", password=secrets.token_urlsafe(24))
            tenant = await create_tenant(s, Keyring(KekSet.from_settings(settings)), name="CI proof", slug=f"ci-{mark}",
                                         owner_id=user.id)  # fmt: skip
        ctx = TenantContext(tenant_id=tenant.id, user=user, role="owner", session=None)  # type: ignore[arg-type]
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant.id)
            workflow_id = (await workflows.create_workflow(s, ctx, name="CI proof", draft=GRAPH)).id
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant.id)
            workflow = await workflows.get_workflow(s, tenant.id, workflow_id, for_update=True)
            if workflow is None:
                raise SystemExit("the workflow just created isn't there")
            published = await workflow_ops.publish(s, ctx, workflow, expected_revision=workflow.draft_revision,
                                                   settings=settings)  # fmt: skip
            if published.version is None:
                raise SystemExit(f"publish refused: {[d.code for d in published.errors]}")
        return tenant.id, workflow_id
    finally:
        await engine.dispose()


if __name__ == "__main__":
    tenant_id, workflow_id = asyncio.run(seed(get_settings()))
    print(tenant_id, workflow_id)
