# SPDX-License-Identifier: Apache-2.0
"""Sealing stored records again under the active data-key version (engine 2b spec §6.4), so an older version can retire:
`dewpoint keys reencrypt`, as the key admin. This command keeps each record's plaintext, purpose and context, and
changes only its blob, and so the version its header names. That is the command's behaviour, not a privilege
guarantee: the key admin's grants let it write these columns, and no grant can check what it writes (the owner's M3
review). A tenant at a time under its scope (or the platform's records), in batches
that each commit, each under the scope's key lifecycle lock from reading the active version to committing (no
rotation or retirement interleaves: the owner's M3 review), each write a compare-and-swap on the blob it read: a
record the application rewrote meanwhile (already under the active version) is never overwritten. A schedule whose
Temporal action, as its sync last read it back, still names a version (synced before the tick contract, carrying the
schedule's id sealed) has its generation raised: its next sync writes the action without it."""

import os
import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.crypto.keyring import FORMAT_V1, Keyring, NoKeyError, lock_scope
from dewpoint.core.db import tenant_scope

BATCH = 100


@dataclass(frozen=True)
class Field:
    """A sealed column: its table, the column that keys a row (within its tenant), the purpose, and its context."""

    table: str
    key: str
    column: str
    purpose: str
    context: Callable[[object], str] = str


TENANT_FIELDS = (
    Field("run_inputs", "id", "ciphertext", "claim"),  # claims, envelopes and CSV records: the row's id
    Field("step_outputs", "id", "ciphertext", "claim"),
    Field("run_secret_index", "root_run_id", "ciphertext", "secret_index"),
    Field("csv_uploads", "id", "staged", "csv.upload"),
    Field("csv_mappings", "workflow_id", "mapping", "csv.mapping"),
    Field("schedules", "id", "input", "schedule.input"),
    Field("connections", "id", "secret_ct", "connection.secret"),
    Field("tenant_event_keys", "version", "private_sealed", "event.private"),  # its keypair version
    # the tenant's credential scope key (plugins-3 D9): the same key sealed again, never a new one, so no credential's
    # budget or cooldown splits; its context is the tenant's id
    Field("rate_scope_keys", "tenant_id", "sealed", "rate.scope"),
    # a plugin call's answer (plugins-3a-2), its id as context: a call can outlive its expiry without a sweeper
    Field("plugin_calls", "id", "result_ct", "plugin.call"),
)
PLATFORM_FIELDS = (
    Field("user_mfa", "user_id", "totp_secret_ct", "user.totp"),
    Field("user_mfa", "user_id", "totp_pending_ct", "user.totp", lambda user: f"{user}:pending"),
)


async def _after_choosing(table: str) -> None:
    """A test's hook: the application may write a record between this batch's read and its write."""


def _version(blob: bytes) -> int:
    if blob[:1] != FORMAT_V1 or len(blob) < 17:
        raise ValueError("a sealed record in an unknown format")
    return int(struct.unpack(">I", blob[1:5])[0])


def reseal(ciphers: dict[int, AESGCM], active: int, aad: bytes, blob: bytes) -> bytes:
    """`blob` opened under the version its header names and sealed under `active`, with the same associated data."""
    plaintext = ciphers[_version(blob)].decrypt(blob[5:17], blob[17:], aad)
    nonce = os.urandom(12)
    return FORMAT_V1 + struct.pack(">I", active) + nonce + ciphers[active].encrypt(nonce, plaintext, aad)


async def _field(sessionmaker: async_sessionmaker[AsyncSession], keyring: Keyring, tenant_id: uuid.UUID | None,
                 field: Field, batch: int) -> int:  # fmt: skip
    """One field's records under an older version sealed again, batch by batch, in key order: how many. A scope with
    no data key has sealed nothing."""
    scope = str(tenant_id) if tenant_id else "platform"
    owned = "tenant_id = :t AND " if tenant_id else ""
    done, after = 0, None
    while True:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            # From reading the active version to committing what it sealed under it: no rotation or retirement.
            await lock_scope(s, tenant_id)
            try:
                active, ciphers = await keyring.versions(s, tenant_id)
            except NoKeyError:
                return done
            older = (f"SELECT {field.key}, {field.column} FROM {field.table} WHERE {owned}{field.column} IS NOT NULL "  # noqa: S608
                     f"AND substring({field.column} from 2 for 4) <> :v "
                     f"{'AND ' + field.key + ' > :after ' if after is not None else ''}"
                     f"ORDER BY {field.key} LIMIT :n")  # fmt: skip
            rows = (await s.execute(text(older), {"t": tenant_id, "v": struct.pack(">I", active), "after": after,
                                                  "n": batch})).all()  # fmt: skip
            if not rows:
                return done
            await _after_choosing(field.table)
            for key, blob in rows:
                aad = f"dewpoint|{scope}|{field.purpose}|{field.context(key)}".encode()
                again = reseal(ciphers, active, aad, bytes(blob))
                swapped = await s.execute(
                    text(f"UPDATE {field.table} SET {field.column} = :new WHERE {owned}{field.key} = :k "  # noqa: S608
                         f"AND {field.column} = :old"), {"t": tenant_id, "k": key, "new": again, "old": bytes(blob)},
                )  # fmt: skip
                done += swapped.rowcount  # type: ignore[attr-defined]
            after = rows[-1][0]


async def tenant(sessionmaker: async_sessionmaker[AsyncSession], keyring: Keyring, tenant_id: uuid.UUID, *,
                 batch: int = BATCH) -> dict[str, int]:  # fmt: skip
    """A tenant's records sealed again under its active version, and its schedules whose Temporal action still names a
    version queued for their sync: how many of each."""
    counts = {field.table: await _field(sessionmaker, keyring, tenant_id, field, batch) for field in TENANT_FIELDS}
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await lock_scope(s, tenant_id)
        # Only once the sync caught up: a schedule queued already isn't queued again.
        queued = await s.execute(text(
            "UPDATE schedules SET generation = generation + 1 WHERE tenant_id = :t AND deleted_at IS NULL "
            "AND synced_generation = generation AND action_key_version IS NOT NULL"), {"t": tenant_id})  # fmt: skip
    counts["schedule_actions"] = queued.rowcount  # type: ignore[attr-defined]
    return counts


async def platform(sessionmaker: async_sessionmaker[AsyncSession], keyring: Keyring, *,
                   batch: int = BATCH) -> dict[str, int]:  # fmt: skip
    """The platform key's records (users' TOTP secrets) sealed again under its active version: how many."""
    counts: dict[str, int] = {}
    for field in PLATFORM_FIELDS:
        counts[field.table] = counts.get(field.table, 0) + await _field(sessionmaker, keyring, None, field, batch)
    return counts
