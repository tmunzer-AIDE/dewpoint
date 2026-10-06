# SPDX-License-Identifier: Apache-2.0
"""The claim store (engine 2b spec §3.1, §3.3, §3.4).

A claim is written once. Its id is derived by whoever makes it, so a retried write writes the same row; a row that
already exists must hold the same value, which is checked by decrypting it, never by a digest of it (#28), or the write
is refused and nothing changes. Only the claim's
owner, the run that produced it, or a run it was granted to reads it; a run grants only what it owns or holds a grant
on. Every refusal looks the same from outside (`ClaimUnavailableError`): a claim that doesn't exist, belongs to another
tenant (row-level security hides it) or to a run that may not read it.

The caller opens the transaction under the tenant's scope (`tenant_scope`), and checks that the tenant is the one the
activity's server-built workflow id names (§3.3). Pointers and nested handles are the engine's (`engine.handles`):
this module stores and returns whole values.

A request's trigger envelope sits in `run_inputs` too (revision 7, §7.1), and is never a claim: no claim read and no
grant ever serves it, and only `read_envelope`, following its request, opens it."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
from dewpoint.core.models.claims import ClaimGrant, InputClaim, OutputClaim
from dewpoint.core.models.requests import RunRequest

CLAIM_UNAVAILABLE = "claim_unavailable"


class ClaimUnavailableError(Exception):
    """A claim this run may not read, or that doesn't exist. The message is fixed: it never quotes a value."""


class EnvelopeUnavailableError(Exception):
    """A request's trigger envelope that isn't there for this tenant: no such request, a refused one, or one retention
    has removed. The message is fixed."""


class EnvelopeUnreadableError(EnvelopeUnavailableError):
    """A request's trigger envelope that is there but broken: its ciphertext doesn't open under its tenant and id, or
    what it opens to isn't JSON. Reading it again never mends it. The message is fixed."""


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
    row = {
        "id": new.id,
        "tenant_id": tenant_id,
        "owner_run_id": new.owner_run_id,
        "root_run_id": new.root_run_id,
        "sensitive_pointers": list(new.sensitive_pointers),
        "ciphertext": await cipher.seal(str(tenant_id), str(new.id), plain),
        **extra,
    }
    written = await s.execute(
        insert(model).values(row).on_conflict_do_nothing(index_elements=["id"]).returning(model.id)
    )
    if written.scalar_one_or_none() is not None:
        return
    # Its id is taken: a retry writes the same value, anything else is a conflict. The existing claim is opened to
    # tell, with the key version its ciphertext names: no digest of a value is kept (#28).
    existing = (await s.execute(select(model.ciphertext).where(model.id == new.id))).scalar_one_or_none()
    if existing is None or await cipher.open(str(tenant_id), str(new.id), existing) != plain:
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
    """A claim's row, never an envelope's: a handle that names an envelope is refused as any unreadable claim is, and
    a grant that reaches one grants nothing (revision 7)."""
    claims = (
        select(InputClaim.owner_run_id, InputClaim.sensitive_pointers, InputClaim.ciphertext).where(
            InputClaim.id == claim_id, InputClaim.role == "claim"
        ),
        select(OutputClaim.owner_run_id, OutputClaim.sensitive_pointers, OutputClaim.ciphertext).where(
            OutputClaim.id == claim_id
        ),
    )
    for query in claims:
        found = (await s.execute(query)).first()
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


GRANTS_PER_STATEMENT = 1_000  # 5 arguments a grant: a loop's 10,000 claimed outputs take 10 statements


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
    rows = [
        {"claim_id": c, "run_id": to, "tenant_id": tenant_id, "granted_by": granted_by, "root_run_id": root_run_id}
        for c in claim_ids
    ]
    for at in range(0, len(rows), GRANTS_PER_STATEMENT):  # the driver's limit: 32,767 arguments a statement
        chunk = rows[at : at + GRANTS_PER_STATEMENT]
        await s.execute(insert(ClaimGrant).values(chunk).on_conflict_do_nothing(index_elements=["claim_id", "run_id"]))


async def write_envelope(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, envelope: Any
) -> uuid.UUID:
    """A request's trigger envelope, encrypted as a claim is and owned by the request (whose id is its run's), and its
    id, for the request row. It holds no tainted pointer: every sensitive value is a claim it holds by handle."""
    envelope_id = uuid.uuid4()
    row = {
        "id": envelope_id,
        "tenant_id": tenant_id,
        "owner_run_id": request_id,
        "root_run_id": request_id,
        "sensitive_pointers": [],
        "ciphertext": await cipher.seal(str(tenant_id), str(envelope_id), _plain(envelope)),
        "role": "envelope",
        "pointer": None,
    }
    await s.execute(insert(InputClaim).values(row))
    return envelope_id


async def read_envelope(s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID) -> Any:
    """A request's trigger envelope: the one its row names and it owns, in the caller's tenant, and nothing else."""
    found = (
        await s.execute(
            select(InputClaim.id, InputClaim.ciphertext)
            .join(RunRequest, RunRequest.envelope_id == InputClaim.id)
            .where(RunRequest.id == request_id, InputClaim.owner_run_id == request_id, InputClaim.role == "envelope")
        )
    ).first()
    if found is None:
        raise EnvelopeUnavailableError("A request whose trigger envelope isn't there.")
    try:
        plain = await cipher.open(str(tenant_id), str(found.id), found.ciphertext)
    except ClaimUnreadableError as e:
        raise EnvelopeUnreadableError("A trigger envelope that doesn't open under its tenant.") from e
    try:
        return json.loads(plain)
    except ValueError:  # not UTF-8, or not JSON
        raise EnvelopeUnreadableError("A trigger envelope that isn't JSON.") from None


async def write_csv_record(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, record: dict[str, Any]
) -> None:
    """A CSV start's record (§8.1): its mapping, the file's header names and its skipped rows, encrypted as a claim is
    and owned by the request. Like the envelope it's never a claim: no claim read or grant serves it."""
    record_id = uuid.uuid4()
    row = {
        "id": record_id,
        "tenant_id": tenant_id,
        "owner_run_id": request_id,
        "root_run_id": request_id,
        "sensitive_pointers": [],
        "ciphertext": await cipher.seal(str(tenant_id), str(record_id), _plain(record)),
        "role": "csv",
        "pointer": None,
    }
    await s.execute(insert(InputClaim).values(row))


async def read_csv_record(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID
) -> dict[str, Any] | None:
    """A request's CSV record, in the caller's tenant; None for a request that took no CSV, or whose record retention
    removed."""
    row = (
        await s.execute(select(InputClaim).where(InputClaim.owner_run_id == request_id, InputClaim.role == "csv"))
    ).scalar_one_or_none()
    if row is None:
        return None
    record: dict[str, Any] = json.loads(await cipher.open(str(tenant_id), str(row.id), row.ciphertext))
    return record


async def read_request_claim(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, claim_id: uuid.UUID
) -> Stored:
    """One of a request's own input claims, for a re-run rebuilding its input (engine 2b spec §7.7): in `run_inputs`,
    owned by the request, never its envelope; nothing else is read. Raises ClaimUnavailableError, as `fetch` does."""
    found = (
        await s.execute(
            select(InputClaim.sensitive_pointers, InputClaim.ciphertext).where(
                InputClaim.id == claim_id, InputClaim.owner_run_id == request_id, InputClaim.role == "claim"
            )
        )
    ).first()
    if found is None:
        raise ClaimUnavailableError("A claim this request doesn't own, or that doesn't exist.")
    try:
        plain = await cipher.open(str(tenant_id), str(claim_id), found.ciphertext)
    except ClaimUnreadableError as e:
        raise ClaimUnavailableError("A claim that doesn't open under its tenant.") from e
    return Stored(json.loads(plain), tuple(found.sensitive_pointers))
