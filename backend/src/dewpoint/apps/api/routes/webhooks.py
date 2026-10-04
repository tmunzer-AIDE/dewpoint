# SPDX-License-Identifier: Apache-2.0
"""Webhook endpoints, bindings and inbound events (engine 2b spec §8.3; the owner's ruling 10 on the 2b-3b outline):
endpoints and bindings written with `trigger.manage` and read with `workflow.view`, a secret shown once; events'
metadata read with `workflow.view`, never a payload, dead ones left out; dead events listed, and pending or dead ones
cancelled, with `tenant.manage`. The endpoints' secrets are sealed under the ingress key, which the API holds beside
ingress: without it, nothing that seals one is written."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import webhooks
from dewpoint.apps.api.routes.run_requests import key_unusable
from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
from dewpoint.core.crypto.ingress import IngressKey
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.ingress import TriggerBinding, WebhookEndpoint

router = APIRouter(prefix="/api/v1", tags=["webhooks"])
STATUSES = Literal["pending", "matched", "unmatched", "cancelled", "dead"]


class EndpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    auth: Literal["bearer", "hmac"] = "bearer"
    signature_header: str | None = Field(default=None, max_length=64)
    timestamp_header: str | None = Field(default=None, max_length=64)
    tolerance_s: int = Field(default=300, ge=60, le=900)
    allowlist: list[str] = Field(default_factory=list)
    body_limit: int = Field(default=webhooks.MIB, ge=1, le=webhooks.MAX_BODY)
    id_source: Literal["pointer", "header", "none"] = "none"
    id_pointer: str | None = None
    id_header: str | None = Field(default=None, max_length=64)
    events_pointer: str | None = None


class EndpointPatch(BaseModel):
    """Only the fields given change, never an endpoint's identity (how it authenticates, where its ids are)."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    signature_header: str | None = Field(default=None, max_length=64)
    timestamp_header: str | None = Field(default=None, max_length=64)
    tolerance_s: int | None = Field(default=None, ge=60, le=900)
    allowlist: list[str] | None = None
    body_limit: int | None = Field(default=None, ge=1, le=webhooks.MAX_BODY)
    events_pointer: str | None = None


class BindingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: uuid.UUID
    filter: list[Any] = Field(default_factory=list)
    enabled: bool = True


class BindingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: list[Any] | None = None
    enabled: bool | None = None


def get_ingress_key(request: Request) -> IngressKey:
    key: IngressKey | None = getattr(request.app.state, "ingress_key", None)
    if key is None:
        raise HTTPException(503, detail={"error": "ingress_key_missing"})
    return key


def get_keyring(request: Request) -> Keyring:
    return request.app.state.keyring  # type: ignore[no-any-return]


def _refused(e: webhooks.WebhookRefusedError) -> HTTPException:
    return HTTPException(e.status, detail=e.detail)


@router.post("/t/{tenant_id}/webhook-endpoints", status_code=201)
async def create_endpoint(
    given: EndpointIn,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    key: IngressKey = Depends(get_ingress_key),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    try:
        endpoint, secret = await webhooks.create_endpoint(db, keyring, key, tenant_id=ctx.tenant_id,
                                                          actor_id=ctx.user.id, given=given.model_dump())  # fmt: skip
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    except Exception as e:
        raise key_unusable(e) from None
    return webhooks.endpoint_body(endpoint) | {"secret": secret}  # shown this once


@router.get("/t/{tenant_id}/webhook-endpoints")
async def list_endpoints(
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at, WebhookEndpoint.id))
    return {"endpoints": [webhooks.endpoint_body(e) for e in found.scalars()]}


@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}")
async def get_endpoint(
    endpoint_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    try:
        return webhooks.endpoint_body(await webhooks.found_endpoint(db, endpoint_id))
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None


@router.patch("/t/{tenant_id}/webhook-endpoints/{endpoint_id}")
async def update_endpoint(
    endpoint_id: uuid.UUID,
    given: EndpointPatch,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    changes = {k: getattr(given, k) for k in given.model_fields_set}
    try:
        endpoint = await webhooks.found_endpoint(db, endpoint_id, lock=True)
        updated = await webhooks.update_endpoint(db, endpoint=endpoint, actor_id=ctx.user.id, changes=changes)
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return webhooks.endpoint_body(updated)


@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/secret")
async def rotate_secret(
    endpoint_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
    key: IngressKey = Depends(get_ingress_key),
) -> dict[str, object]:
    try:
        endpoint = await webhooks.found_endpoint(db, endpoint_id, lock=True)
        secret = await webhooks.rotate_secret(db, key, endpoint=endpoint, actor_id=ctx.user.id)
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return {"id": str(endpoint.id), "secret": secret}  # shown this once


@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", status_code=201)
async def create_binding(
    endpoint_id: uuid.UUID,
    given: BindingIn,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    try:
        binding = await webhooks.create_binding(db, endpoint_id=endpoint_id, actor_id=ctx.user.id,
                                                workflow_id=given.workflow_id, filter=given.filter,
                                                enabled=given.enabled)  # fmt: skip
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return webhooks.binding_body(binding)


@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings")
async def list_bindings(
    endpoint_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    found = await db.execute(select(TriggerBinding).where(TriggerBinding.endpoint_id == endpoint_id)
                             .order_by(TriggerBinding.workflow_id))  # fmt: skip
    return {"bindings": [webhooks.binding_body(b) for b in found.scalars()]}


@router.patch("/t/{tenant_id}/webhook-bindings/{binding_id}")
async def update_binding(
    binding_id: uuid.UUID,
    given: BindingPatch,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    changes = {k: getattr(given, k) for k in given.model_fields_set if getattr(given, k) is not None}
    try:
        binding = await webhooks.found_binding(db, binding_id)
        updated = await webhooks.update_binding(db, binding=binding, actor_id=ctx.user.id, changes=changes)
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return webhooks.binding_body(updated)


@router.delete("/t/{tenant_id}/webhook-bindings/{binding_id}", status_code=204)
async def delete_binding(
    binding_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    try:
        await webhooks.delete_binding(db, binding=await webhooks.found_binding(db, binding_id), actor_id=ctx.user.id)
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return Response(status_code=204)


@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/events")
async def list_events(
    endpoint_id: uuid.UUID,
    status: STATUSES | None = None,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    admin = P.TENANT_MANAGE in ROLE_PERMISSIONS[ctx.role]  # dead events are listed to admins only
    found = await webhooks.events_of(db, endpoint_id, status, dead=admin)
    return {"events": [webhooks.event_body(e) for e in found]}


@router.get("/t/{tenant_id}/inbound-events/dead")
async def list_dead_events(
    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    return {"events": [webhooks.event_body(e) for e in await webhooks.dead_events(db)]}


@router.post("/t/{tenant_id}/inbound-events/{event_id}/cancel")
async def cancel_event(
    event_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    try:
        event = await webhooks.cancel_event(db, tenant_id=ctx.tenant_id, event_id=event_id, actor_id=ctx.user.id)
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return webhooks.event_body(event)


@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/cancel-pending")
async def cancel_pending(
    endpoint_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    try:
        cancelled = await webhooks.cancel_pending(db, tenant_id=ctx.tenant_id, endpoint_id=endpoint_id,
                                                  actor_id=ctx.user.id)  # fmt: skip
    except webhooks.WebhookRefusedError as e:
        raise _refused(e) from None
    return {"cancelled": cancelled}


@router.get("/t/{tenant_id}/inbound-usage")
async def inbound_usage(
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    return dict(await webhooks.usage(db, ctx.tenant_id))
