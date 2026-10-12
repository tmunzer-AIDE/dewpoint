# SPDX-License-Identifier: Apache-2.0
"""Matching inbound events (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b outline), in every
dispatcher, only while the gate is on.

`event_candidates(n)` picks pending events, ids only and locking nothing, fair across tenants. Each is then matched in
a transaction of its own, under the one lock order: the gate's lock and the tenant's lifecycle lock, both shared (the
gate's disable and 2b-4's erasure take them exclusively), with the gate, the recorded environment and the tenant
rechecked under them; the event's endpoint row; the tenant's counter row; and only then the event row, `FOR UPDATE
SKIP LOCKED`, rechecked still pending and due (another dispatcher may have finished it). Holding the endpoint's row
serializes ingress and matching on one endpoint. The endpoint's and the counter's rows are taken `SKIP LOCKED` too (D9):
one held elsewhere passes the event by, `busy`, never waited on, so a second dispatcher takes other tenants' work. A
pass picks `PAGES` batches' candidates and tries one batch; it probes a busy endpoint or tenant once and passes its
other events by, and the next pass's pick leaves out what the last found busy, so no busy prefix, however long,
starves the events after it (the owner's correction to D9), and every other event keeps its tenant's order, oldest
first (a positional cursor didn't: the fresh M3 review's I2).

The event is opened with the tenant's private key and, for each enabled binding of its endpoint whose filter holds, in
workflow-id order (§7.2), one request is admitted: source `webhook`, key `evt:<event id>:<workflow id>`, the event as
the trigger. Admission freezes it or records it `refused`; either is a request. The event is recorded `matched` with
its request count, or `unmatched`, and its pending counters are released, together. A recheck that fails changes
nothing; more enabled bindings than the cap (refused when they're written) wait, with an alert.

An event is `dead` (audited, alerted on, its counters released) only for a confirmed event-specific failure: its
ciphertext fails under a key version that has opened another event in this process, or its payload isn't a JSON
object; or after `EVENT_ATTEMPTS` unconfirmed failures, backing off from `BACKOFF`, doubling. A platform-wide failure
(a key version missing, the tenant's data key unreadable) waits `WAIT` with an alert, its attempts untouched; the
database itself failing writes nothing (§8.3, §10.5). Any other unexpected failure (a bug) is counted apart from its
attempts (`failures`, D10): it waits 1, 2, 4, 8, 16 then 30 minutes, so it never keeps the events after it out (the
owner's review of the 2b-4b M1 checkpoint 4), and the 7th in a row holds it for an operator."""

import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

import structlog
from cryptography.exceptions import InvalidTag
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from dewpoint.apps import admission
from dewpoint.apps.dispatcher import budget, failures
from dewpoint.apps.dispatcher.dispatch import GATE_LOCK, tenant_lock
from dewpoint.core.audit import service as audit
from dewpoint.core.crypto import events
from dewpoint.core.crypto.keys import KeySource, key_unreadable
from dewpoint.core.db import tenant_scope, unavailable
from dewpoint.core.ingress import keys as event_keys
from dewpoint.core.ingress.counters import release
from dewpoint.core.ingress.filters import MAX_BINDINGS, matches
from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
from dewpoint.core.models.platform import PlatformSettings
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.platform.service import PRODUCTION
from dewpoint.core.plugins import lifecycle
from dewpoint.engine.runtime.activities import LIVE

log = structlog.get_logger("dewpoint.dispatcher.matching")
BATCH = 50  # events a cycle (§15, provisional)
WAIT = timedelta(minutes=1)  # a wait that's no fault of the event's: retried after it, its attempts untouched
SOURCE = "webhook"
GATE_OFF = "gate_off"
ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
TENANT_ERASING = "tenant_erasing"
SKIPPED = "skipped"
BUSY = "busy"  # its endpoint's row held elsewhere (ingress, another dispatcher): passed by (D9)
BUSY_TENANT = "busy_tenant"  # its tenant's counter row held elsewhere: passed by alike
BACKLOG_FULL = "backlog_full"  # the deployment's budget without room for its new bindings: pending, its tenant passed
# by alike
FAN_OUT_EXCEEDED = "fan_out_exceeded"
KEY_UNAVAILABLE = "key_unavailable"
RETRYING = "retrying"
DEAD = "dead"
EVENT_UNREADABLE = "event_unreadable"
EVENT_NOT_JSON = "event_not_json"
EVENT_NOT_OBJECT = "event_not_object"
EVENT_ATTEMPTS = 5  # event-specific attempts before an unconfirmed failure is dead (§8.3)
BACKOFF = timedelta(seconds=30)  # after the first event-specific failure, doubling (§15, provisional)
PAGES = 4  # a pass picks this many batches' candidates: one busy (D9) gives its place to the next; a batch is still
# all it tries
BUDGET_PAST = "DPB02"  # the database's bound on the ingress budget (0050), refusing a commit adding past the limit
ROLLED_BACK = (GATE_OFF, ENVIRONMENT_NOT_RECORDED, TENANT_ERASING, SKIPPED, BUSY, BUSY_TENANT, BACKLOG_FULL)
ALERTS = "dewpoint.matching.alerts"  # in the session's `info`: alerts logged once its transaction commits


class Verified:
    """The tenants' keypair versions that have opened an event in this process: a version that has is known good."""

    def __init__(self) -> None:
        self._versions: set[tuple[uuid.UUID, int]] = set()

    def add(self, tenant_id: uuid.UUID, version: int) -> None:
        self._versions.add((tenant_id, version))

    def __contains__(self, item: object) -> bool:
        return item in self._versions


async def _after_event_locked() -> None:
    """Runs once a match holds its event's row. A no-op; the race tests hold a match here."""


async def _before_commit() -> None:
    """Runs as a match is about to commit what it decided. A no-op; the tests fail a transaction here."""


def _alert(s: AsyncSession, event: str, **fields: object) -> None:
    """An alert to log once the transaction has committed, never for one rolled back."""
    s.info.setdefault(ALERTS, []).append((event, fields))


def gate_off(platform: PlatformSettings | None) -> str | None:
    """Why nothing is matched now, or None: no recorded environment, or a production deployment's runs off."""
    if platform is None:
        return ENVIRONMENT_NOT_RECORDED
    if platform.environment == PRODUCTION and not platform.production_runs:
        return GATE_OFF
    return None


async def _lock(s: AsyncSession, key: str) -> None:
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})


@dataclass
class Busy:
    """The endpoints and tenants the last pass found busy: the next pass's pick leaves them out, so no busy prefix,
    however long, starves the events after it (the owner's correction to D9), each found busy visited again a pass
    later."""

    endpoints: frozenset[uuid.UUID] = frozenset()
    tenants: frozenset[uuid.UUID] = frozenset()


async def match_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    keys: KeySource,
    verified: Verified,
    *,
    batch: int = BATCH,
    busy: Busy | None = None,
) -> dict[str, int]:
    """One cycle's matching: nothing while the gate is off; otherwise each candidate in turn. What happened, counted.
    A match that fails (a bug, an outage) is logged by type and leaves its event as it was."""
    async with sessionmaker() as s:
        waiting = gate_off(await s.get(PlatformSettings, 1))
        if waiting is not None:
            return {waiting: 1}
        busy = busy if busy is not None else Busy()
        query = text("select tenant_id, event_id, endpoint_id from event_candidates(:n, :e, :t)")
        picked = (await s.execute(query, {"n": batch * PAGES, "e": list(busy.endpoints),
                                          "t": list(busy.tenants)})).all()  # fmt: skip
    counts: Counter[str] = Counter()
    done: list[tuple[uuid.UUID, uuid.UUID]] = []
    endpoints: set[uuid.UUID] = set()  # found busy in this pass: their other events passed by unprobed
    tenants: set[uuid.UUID] = set()
    tried = 0
    with budget.passing("matching") as admitted:
        for tenant_id, event_id, endpoint_id in admitted(picked):  # each tenant's oldest first, fair across tenants
            if tried >= batch:
                break
            if tenant_id in tenants or endpoint_id in endpoints:
                counts[BUSY_TENANT if tenant_id in tenants else BUSY] += 1
                continue
            try:
                outcome = await match_event(sessionmaker, keys, verified, tenant_id=tenant_id, event_id=event_id,
                                            endpoint_id=endpoint_id)  # fmt: skip
                counts[outcome] += 1
            except Exception as e:
                tried += 1
                log.error(
                    "event_match_failed", tenant_id=str(tenant_id), event_id=str(event_id), error=type(e).__name__
                )
                counts["error"] += 1
                # bounded (D10): the database failing counts nothing, its event tried again next pass
                await failures.failed(sessionmaker, tenant_id, failures.MATCH, event_id, e)
                continue
            if outcome == BUSY:
                endpoints.add(endpoint_id)
            elif outcome in (BUSY_TENANT, BACKLOG_FULL):  # its later events wait behind it: its order kept
                tenants.add(tenant_id)
            else:  # tried
                tried += 1
                done.append((tenant_id, event_id))
    busy.endpoints, busy.tenants = frozenset(endpoints), frozenset(tenants)
    await failures.cleared(sessionmaker, [failures.MATCH], done)
    admitted.reported(counts, full=len(picked) >= batch * PAGES)
    return dict(counts)


# The deployment's budget (the owner's ruling on the 2b-4b M3 checkpoint 4): an event's new queued requests, counted as
# they're inserted, take its credit (released as its transaction commits); only past it, bindings added since it was
# accepted, do they need the limit's room. Last in its transaction: then it holds the budget's row to the commit
MATCHED = text("SELECT ingress_matched(:credit, :k)")


async def match_event(
    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, verified: Verified, *, tenant_id: uuid.UUID,
    event_id: uuid.UUID, endpoint_id: uuid.UUID,
) -> str:  # fmt: skip
    """One event's matching transaction: `matched`, `unmatched`, or why it waits or was passed by. Its alerts are
    logged once it has committed: a transaction rolled back alerts on nothing (the owner's M3 review)."""
    async with sessionmaker() as s:
        try:
            async with s.begin():
                outcome = await _match(s, keys, verified, tenant_id, event_id, endpoint_id)
                if outcome in ROLLED_BACK:
                    await s.rollback()
                else:
                    await _before_commit()
        except DBAPIError as e:
            # The budget's bound refusing the commit (0050's `ingress_budget_bounded`, SQLSTATE DPB02): a full backlog,
            # rolled back, its tenant passed by so its later events keep their order (2b-4b M4: tolerant code, run in
            # a release before the migration that brings a refusal)
            if getattr(e.orig, "sqlstate", None) == BUDGET_PAST:
                return BACKLOG_FULL
            raise
        for event, fields in s.info.pop(ALERTS, []):  # committed
            log.error(event, **fields)
        return outcome


async def _match(
    s: AsyncSession, keys: KeySource, verified: Verified, tenant_id: uuid.UUID, event_id: uuid.UUID,
    endpoint_id: uuid.UUID,
) -> str:  # fmt: skip
    await lifecycle.assert_read_committed(s)
    await tenant_scope(s, tenant_id)
    await _lock(s, GATE_LOCK)
    await _lock(s, tenant_lock(tenant_id))
    platform = await s.get(PlatformSettings, 1, populate_existing=True)
    waiting = gate_off(platform)
    if waiting is not None or platform is None:
        return waiting or ENVIRONMENT_NOT_RECORDED
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None or tenant.status != "active":
        return TENANT_ERASING
    # D9: the endpoint's row, then the tenant's counter row, `SKIP LOCKED`: one held elsewhere (ingress recording an
    # event, another dispatcher matching one) is passed by, `busy`, never waited on, so dispatchers scale
    endpoint = (
        await s.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()  # fmt: skip
    if endpoint is None:
        there = await s.execute(select(WebhookEndpoint.id).where(WebhookEndpoint.id == endpoint_id))
        return BUSY if there.first() is not None else SKIPPED
    counter = select(TenantEventCounters.tenant_id).where(TenantEventCounters.tenant_id == tenant_id)
    if (await s.execute(counter.with_for_update(skip_locked=True))).first() is None:
        if (await s.execute(counter)).first() is not None:
            return BUSY_TENANT
    event = (
        await s.execute(
            select(InboundEvent)
            .where(
                InboundEvent.id == event_id,
                InboundEvent.endpoint_id == endpoint_id,
                InboundEvent.status == "pending",
                or_(InboundEvent.next_attempt_at.is_(None), InboundEvent.next_attempt_at <= func.statement_timestamp()),
            )
            .options(undefer(InboundEvent.sealed))
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if event is None:
        return SKIPPED
    await _after_event_locked()
    try:
        private = await event_keys.private_key(s, keys, tenant_id, event.key_version)
    except Exception as e:  # no fault of the event's: a version missing, or the tenant's data key unreadable
        if unavailable(e) or not (isinstance(e, event_keys.NoEventKeyError) or key_unreadable(e)):
            raise  # the database itself, or a bug: nothing written, the event as it was
        _alert(s, "event_key_unavailable", tenant_id=str(tenant_id), version=event.key_version,
               error=type(e).__name__)  # fmt: skip
        event.next_attempt_at = func.statement_timestamp() + WAIT
        await s.flush()
        return KEY_UNAVAILABLE
    try:
        plaintext = events.open_sealed(private, tenant_id=tenant_id, endpoint_id=endpoint_id, event_id=event.id,
                                       blob=event.sealed)  # fmt: skip
    except (InvalidTag, ValueError):
        if (tenant_id, event.key_version) in verified:  # confirmed: the key is good, the event isn't
            return await _dead(s, event, EVENT_UNREADABLE)
        return await _retry(s, event, EVENT_UNREADABLE)
    verified.add(tenant_id, event.key_version)
    try:
        payload = json.loads(plaintext)
    except ValueError:
        return await _dead(s, event, EVENT_NOT_JSON)
    if not isinstance(payload, dict):
        return await _dead(s, event, EVENT_NOT_OBJECT)
    bindings = (
        await s.execute(
            select(TriggerBinding)
            .where(TriggerBinding.endpoint_id == endpoint_id, TriggerBinding.enabled.is_(True))
            .order_by(TriggerBinding.workflow_id)
            .limit(MAX_BINDINGS + 1)
        )
    ).scalars().all()  # fmt: skip
    if len(bindings) > MAX_BINDINGS:
        _alert(s, "event_fan_out_exceeded", endpoint_id=str(endpoint_id), event_id=str(event.id))
        event.next_attempt_at = func.statement_timestamp() + WAIT
        await s.flush()
        return FAN_OUT_EXCEEDED
    admitting = [binding for binding in bindings if matches(binding.filter, payload)]
    admitted = queued = 0
    for binding in admitting:
        request = await admission.admit_request(
            s, keys, tenant_id=tenant_id, workflow_id=binding.workflow_id, source=SOURCE, actor_id=None, mode=LIVE,
            idempotency_key=f"evt:{event.id}:{binding.workflow_id}", input=payload,
            details={"endpoint_id": str(endpoint_id), "event_id": str(event.id), "binding_id": str(binding.id)},
        )  # fmt: skip
        admitted += 1
        queued += request.new and request.request.status == "queued"
    event.status = "matched" if admitted else "unmatched"
    event.request_count = admitted
    event.ended_at = func.statement_timestamp()
    await release(s, tenant_id, endpoint_id, event.size_bytes)
    await s.flush()
    if queued:
        credited = await s.execute(MATCHED, {"credit": event.credit or 0, "k": queued})
        if not credited.scalar_one():
            return BACKLOG_FULL  # rolled back: the event pending as it was
    return event.status


async def _retry(s: AsyncSession, event: InboundEvent, reason: str) -> str:
    """An event-specific failure not yet confirmed: another attempt later, backing off, dead after the last."""
    event.attempts += 1
    if event.attempts >= EVENT_ATTEMPTS:
        return await _dead(s, event, reason)
    event.next_attempt_at = func.statement_timestamp() + BACKOFF * 2 ** (event.attempts - 1)
    await s.flush()
    return RETRYING


async def _dead(s: AsyncSession, event: InboundEvent, reason: str) -> str:
    """An event that will never match: dead, its pending counters released, audited and alerted on."""
    event.status, event.reason, event.ended_at = DEAD, reason, func.statement_timestamp()
    await release(s, event.tenant_id, event.endpoint_id, event.size_bytes)
    details: dict[str, object] = {"endpoint_id": str(event.endpoint_id), "reason": reason, "attempts": event.attempts}
    await audit.record(s, tenant_id=event.tenant_id, actor_id=None, action="inbound_event.dead",
                       target_type="inbound_event", target_id=str(event.id), details=details)  # fmt: skip
    _alert(s, "inbound_event_dead", tenant_id=str(event.tenant_id), event_id=str(event.id), reason=reason)
    await s.flush()
    return DEAD
