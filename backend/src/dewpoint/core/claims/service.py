# SPDX-License-Identifier: Apache-2.0
"""The claim store (engine 2b spec §3.1, §3.3, §3.4).

A claim is written once. Its id is derived by whoever makes it, so a retried write writes the same row; a row that
already exists must hold the same content (its hash), or the write is refused and nothing changes. Only the claim's
owner, the run that produced it, or a run it was granted to reads it; a run grants only what it owns or holds a grant
on. Every refusal looks the same from outside (`ClaimUnavailableError`): a claim that doesn't exist, belongs to another
tenant (row-level security hides it) or to a run that may not read it.

The caller opens the transaction under the tenant's scope (`tenant_scope`), and checks that the tenant is the one the
activity's server-built workflow id names (§3.3). Pointers and nested handles are the engine's (`engine.handles`):
this module stores and returns whole values."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
from dewpoint.core.models.claims import ClaimGrant, InputClaim, OutputClaim

CLAIM_UNAVAILABLE = "claim_unavailable"


class ClaimUnavailableError(Exception):
    """A claim this run may not read, or that doesn't exist. The message is fixed: it never quotes a value."""


class ClaimConflictError(Exception):
    """A claim written again under its id with other content: nothing was written. A bug, never a value's fault."""


@dataclass(frozen=True)
class NewClaim:
    id: uuid.UUID
    value: Any  # JSON; it may hold handles to claims made before it
    sensitive_pointers: tuple[str, ...]  # the tainted pointers inside the value; "" is all of it
    owner_run_id: uuid.UUID
    root_run_id: uuid.UUID


@dataclass(frozen=True)
class Stored:
    value: Any
    sensitive_pointers: tuple[str, ...]


def _plain(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


async def _write(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, model: Any, new: NewClaim, **extra: Any
) -> None:
    plain = _plain(new.value)
    digest = hashlib.sha256(plain).digest()
    row = {
        "id": new.id,
        "tenant_id": tenant_id,
        "owner_run_id": new.owner_run_id,
        "root_run_id": new.root_run_id,
        "sensitive_pointers": list(new.sensitive_pointers),
        "content_hash": digest,
        "ciphertext": await cipher.seal(str(tenant_id), str(new.id), plain),
        **extra,
    }
    written = await s.execute(
        insert(model).values(row).on_conflict_do_nothing(index_elements=["id"]).returning(model.id)
    )
    if written.scalar_one_or_none() is not None:
        return
    existing = (await s.execute(select(model.content_hash).where(model.id == new.id))).scalar_one_or_none()
    if existing != digest:
        raise ClaimConflictError("A claim was written again with other content.")


async def write_input(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, new: NewClaim, *, pointer: str
) -> None:
    """A claim made before its run starts (`run_inputs`): `pointer` is where in the run's input it came from."""
    await _write(s, cipher, tenant_id, InputClaim, new, pointer=pointer)


async def write_output(
    s: AsyncSession,
    cipher: ClaimCipher,
    tenant_id: uuid.UUID,
    new: NewClaim,
    *,
    kind: str,
    step_id: uuid.UUID | None,
    iteration_key: str | None,
    attempt: int | None,
) -> None:
    """A claim made during a run (`step_outputs`), with its producer, for tracing."""
    await _write(s, cipher, tenant_id, OutputClaim, new, kind=kind, step_id=step_id, iteration_key=iteration_key,
                 attempt=attempt)  # fmt: skip


async def _row(s: AsyncSession, claim_id: uuid.UUID) -> Any:
    for model in (InputClaim, OutputClaim):
        found = (
            await s.execute(
                select(model.owner_run_id, model.sensitive_pointers, model.ciphertext).where(model.id == claim_id)
            )
        ).first()
        if found is not None:
            return found
    return None


async def _may_read(s: AsyncSession, claim_id: uuid.UUID, run_id: uuid.UUID, owner: uuid.UUID) -> bool:
    if owner == run_id:
        return True
    granted = exists().where(ClaimGrant.claim_id == claim_id, ClaimGrant.run_id == run_id)
    return bool((await s.execute(select(granted))).scalar_one())


async def fetch(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, run_id: uuid.UUID, claim_id: uuid.UUID
) -> Stored:
    """A claim's whole value and its sensitive pointers, for `run_id`, its owner or a run it was granted to."""
    row = await _row(s, claim_id)
    if row is None or not await _may_read(s, claim_id, run_id, row.owner_run_id):
        raise ClaimUnavailableError("A claim this run may not read, or that doesn't exist.")
    try:
        plain = await cipher.open(str(tenant_id), str(claim_id), row.ciphertext)
    except ClaimUnreadableError as e:
        raise ClaimUnavailableError("A claim that doesn't open under its tenant.") from e
    return Stored(json.loads(plain), tuple(row.sensitive_pointers))


async def grant(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    granted_by: uuid.UUID,
    to: uuid.UUID,
    claim_ids: list[uuid.UUID],
    root_run_id: uuid.UUID,
) -> None:
    """Grants `to` the claims `granted_by` owns or holds a grant on: a handle crossing between a parent and its child
    (§3.4). Any other claim refuses the whole grant, and nothing is granted."""
    for claim_id in claim_ids:
        row = await _row(s, claim_id)
        if row is None or not await _may_read(s, claim_id, granted_by, row.owner_run_id):
            raise ClaimUnavailableError("A claim this run may not grant.")
    if claim_ids:
        rows = [
            {"claim_id": c, "run_id": to, "tenant_id": tenant_id, "granted_by": granted_by, "root_run_id": root_run_id}
            for c in claim_ids
        ]
        await s.execute(insert(ClaimGrant).values(rows).on_conflict_do_nothing(index_elements=["claim_id", "run_id"]))
