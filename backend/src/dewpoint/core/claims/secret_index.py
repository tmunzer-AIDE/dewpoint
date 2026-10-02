# SPDX-License-Identifier: Apache-2.0
"""A run tree's secret index (engine 2b spec §3.7): every string of MIN_SECRET characters or more found in any tainted
claim made in the tree, in one encrypted row per root run. Admission seeds it with the trigger's claims; every activity
that makes a tainted claim extends it. The activity boundary claims untainted output that repeats one of them, and
masks every error message against them.

Its version changes with every extension, so a boundary can tell a stale copy. Extensions are serialized on the row,
so concurrent activities never lose one another's strings. Past MAX_STRINGS or MAX_BYTES an extension is refused for
good (`secret_index_limit`) and nothing changes: the step that would add it fails, or admission refuses the run."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.models.claims import SecretIndex

PURPOSE = "secret_index"  # sealed with the root run's id as context
MIN_SECRET = 4  # as engine.sensitive.MIN_SECRET (core doesn't import the engine; a test keeps them equal)
MAX_STRINGS = 100_000  # spec §15: provisional
MAX_BYTES = 8 * 1024 * 1024  # the strings' UTF-8 bytes; spec §15: provisional
SECRET_INDEX_LIMIT = "secret_index_limit"  # noqa: S105 - a code, not a credential
SECRET_INDEX_UNAVAILABLE = "secret_index_unavailable"  # noqa: S105 - a code, not a credential


class SecretIndexLimitError(Exception):
    """An extension past the index's bounds: permanent for the run, never retried. The message is fixed."""


@dataclass(frozen=True)
class Index:
    version: int  # 0: the tree has no index yet
    strings: tuple[str, ...]  # sorted


def check(strings: list[str]) -> None:
    """Raises SecretIndexLimitError when `strings` pass the index's bounds."""
    if len(strings) > MAX_STRINGS or sum(len(x.encode()) for x in strings) > MAX_BYTES:
        raise SecretIndexLimitError(
            "The run's sensitive values are too many to index (over its secret index's bounds)."
        )


def _counts(strings: list[str]) -> dict[str, int]:
    return {"string_count": len(strings), "byte_count": sum(len(x.encode()) for x in strings)}


async def _locked(s: AsyncSession, root_run_id: uuid.UUID) -> Any:
    query = select(SecretIndex.version, SecretIndex.ciphertext).where(SecretIndex.root_run_id == root_run_id)
    return (await s.execute(query.with_for_update())).first()


async def _strings(cipher: ClaimCipher, tenant_id: uuid.UUID, root_run_id: uuid.UUID, blob: bytes) -> list[str]:
    return list(json.loads(await cipher.open(str(tenant_id), str(root_run_id), blob)))


async def read(s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, root_run_id: uuid.UUID) -> Index:
    """The tree's index as it is now; an empty one at version 0 if it has none."""
    query = select(SecretIndex.version, SecretIndex.ciphertext).where(SecretIndex.root_run_id == root_run_id)
    row = (await s.execute(query)).first()
    if row is None:
        return Index(0, ())
    return Index(row.version, tuple(await _strings(cipher, tenant_id, root_run_id, row.ciphertext)))


async def extend(
    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, root_run_id: uuid.UUID, strings: list[str]
) -> Index:
    """The index with `strings` added (those of MIN_SECRET characters or more), as a new version; the same version
    when nothing is new. Raises SecretIndexLimitError past its bounds, having changed nothing."""
    fresh = {x for x in strings if len(x) >= MIN_SECRET}
    row = await _locked(s, root_run_id)
    if row is None:
        if not fresh:
            return Index(0, ())
        merged = sorted(fresh)
        check(merged)
        seal = await cipher.seal(str(tenant_id), str(root_run_id), json.dumps(merged).encode())
        values = {
            "root_run_id": root_run_id,
            "tenant_id": tenant_id,
            "version": 1,
            "ciphertext": seal,
            **_counts(merged),
        }
        inserted = await s.execute(
            insert(SecretIndex)
            .values(values)
            .on_conflict_do_nothing(index_elements=["root_run_id"])
            .returning(SecretIndex.version)
        )
        if inserted.scalar_one_or_none() is not None:
            return Index(1, tuple(merged))
        row = await _locked(s, root_run_id)  # seeded meanwhile by another transaction: extend that one
    current = await _strings(cipher, tenant_id, root_run_id, row.ciphertext)
    merged = sorted(set(current) | fresh)
    if len(merged) == len(current):
        return Index(row.version, tuple(current))
    check(merged)
    seal = await cipher.seal(str(tenant_id), str(root_run_id), json.dumps(merged).encode())
    await s.execute(
        update(SecretIndex)
        .where(SecretIndex.root_run_id == root_run_id)
        .values(version=row.version + 1, ciphertext=seal, **_counts(merged))
    )
    return Index(row.version + 1, tuple(merged))
