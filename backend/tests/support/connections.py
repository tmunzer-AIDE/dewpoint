# SPDX-License-Identifier: Apache-2.0
"""A test-only connection type and the rows a step's connection is read from (plugins-3 D4): a tenant, a version whose
graph names connections in a node's config, a run of it, and connections sealed as the API seals them."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import text

from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.connections.service import PURPOSE
from dewpoint.core.connections.types import ConnectionType, HeaderAuth, VerifyResult
from dewpoint.core.ratelimit.buckets import Scope
from tests.support.keys import FixtureKeys
from tests.support.workflows import PROFILE


class TestkitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    capacity: float = 50
    refill_per_s: float = 50


class TestkitSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


async def _verify(config: BaseModel, secret: BaseModel, http: Any) -> VerifyResult:
    return VerifyResult(True, "ok")


def _scopes(config: BaseModel, credential: Any, secret: BaseModel) -> list[Scope]:
    assert isinstance(config, TestkitConfig) and isinstance(secret, TestkitSecret)
    key = f"testkit.token:{credential(secret.token.get_secret_value())}"
    return [Scope(key, config.capacity, config.refill_per_s)]


TESTKIT_TYPE = ConnectionType(
    "testkit",
    "Testkit",
    TestkitConfig,
    TestkitSecret,
    _verify,  # type: ignore[arg-type]
    base_url=lambda config, secret: config.base_url,  # type: ignore[attr-defined]
    auth=HeaderAuth("Authorization", "Bearer {token}"),
    rate_scopes=_scopes,
)


@dataclass(frozen=True)
class Seeded:
    tenant: uuid.UUID
    run: uuid.UUID
    step: uuid.UUID
    version: uuid.UUID


async def seal(tenant: uuid.UUID, connection_id: uuid.UUID, secret: dict[str, Any]) -> bytes:
    return await ClaimCipher(FixtureKeys(), purpose=PURPOSE).seal(
        str(tenant), str(connection_id), json.dumps(secret).encode()
    )


async def add_connection(
    owner: Any,
    tenant: uuid.UUID,
    *,
    type_key: str = "testkit",
    config: dict[str, Any] | None = None,
    secret: dict[str, Any] | None = None,
) -> uuid.UUID:
    cid = uuid.uuid4()
    blob = await seal(tenant, cid, secret or {"token": "s3cr3t-token-value"})
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into connections (id, tenant_id, type, name, config, secret_ct) "
                "values (:i, :t, :k, :n, cast(:c as jsonb), :b)"
            ),
            {"i": cid, "t": tenant, "k": type_key, "n": f"c-{cid.hex[:8]}", "c": json.dumps(config or {}), "b": blob},
        )
    return cid


async def seed_step(owner: Any, *, named: list[uuid.UUID | None], recorded: list[uuid.UUID] | None = None,
                    tenant: uuid.UUID | None = None, node_type: str = "testkit.http_call@1") -> Seeded:  # fmt: skip
    """A run whose version's node `call` names `named[0]` (and a second node `other` names `named[1]` if given)."""
    tenant = tenant or uuid.uuid4()
    wf, version, run, step, other = (uuid.uuid4() for _ in range(5))
    nodes = [{"id": str(step), "key": "call", "type": node_type,
              "config": {"connection": str(named[0]) if named[0] else None, "path": "/"}}]  # fmt: skip
    if len(named) > 1:
        nodes.append({"id": str(other), "key": "other", "type": "testkit.http_call@1",
                      "config": {"connection": str(named[1]), "path": "/"}})  # fmt: skip
    graph = {"graph_format": 1, "nodes": nodes, "edges": []}
    ids = recorded if recorded is not None else [n for n in named if n is not None]
    async with owner() as s, s.begin():
        exists = (await s.execute(text("select count(*) from tenants where id = :t"), {"t": tenant})).scalar_one()
        if not exists:
            await s.execute(
                text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": tenant.hex[:12]}
            )
        await s.execute(text("insert into cel_profiles(profile) values (:p) on conflict do nothing"), {"p": PROFILE})
        await s.execute(
            text("insert into workflows(id,tenant_id,name,enabled,draft) values (:w,:t,:n,true,'{}')"),
            {"w": wf, "t": tenant, "n": f"W-{wf.hex[:6]}"},
        )
        await s.execute(
            text(
                "insert into workflow_versions(id,tenant_id,workflow_id,number,graph,node_refs,engine_abi,cel_profile,"
                "input_schema,output_schema,vars_schema,closure_version_ids,closure_workflow_ids,closure_node_refs,"
                "closure_cel_profiles,closure_depth,graph_hash,version_hash,connection_ids) "
                "values (:v,:t,:w,1,cast(:g as jsonb),array['testkit.http_call@1'],1,cast(:p as text),"
                "'{}','{}','{}',array[cast(:v as uuid)],array[cast(:w as uuid)],array['testkit.http_call@1'],"
                "array[cast(:p as text)],0,'h','h',cast(:ids as uuid[]))"
            ),
            {"v": version, "t": tenant, "w": wf, "g": json.dumps(graph), "p": PROFILE, "ids": [str(i) for i in ids]},
        )
        await s.execute(
            text(
                "insert into runs(id,tenant_id,workflow_id,workflow_version_id,mode,status) "
                "values (:r,:t,:w,:v,'live','running')"
            ),
            {"r": run, "t": tenant, "w": wf, "v": version},
        )
    return Seeded(tenant, run, step, version)
