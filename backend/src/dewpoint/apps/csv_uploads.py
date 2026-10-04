# SPDX-License-Identifier: Apache-2.0
"""A CSV staged for a start (engine 2b spec §8.1): read as data only (`apps.csv_input`), then its own bytes sealed with
the tenant's key under `csv.upload` (the upload's id the context), owned by its uploader and tenant for one hour: what's
stored is bounded by the file's cap, never a parsed form several times larger. A start reads it again under the version
it freezes, and consumes it in its own transaction.

What the uploader is told: the file's headers, the declared columns mapped to them (the workflow's saved default
mapping, else the exact matches), what keeps that mapping from building rows, a preview of the first records' mapped
cells with sensitive columns left out, and each record's errors as its number, the column's name and a code. Nothing
is logged or audited at upload: the start's audit entry keeps the file's tenant-keyed digest and counts.

A workflow's saved default mapping (the owner's ruling 6) is sealed under `csv.mapping`. An upload proposes it when it
fits the active version's declaration; one that no longer does is marked stale and reported with each column's code,
and the exact matches are proposed instead: it's never applied silently, and a start always needs a mapping valid for
its version."""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.csv_input import Table, build_rows, exact_mapping, mapping_problems, read_table
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.models.uploads import CsvMapping, CsvUpload
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.requests import digest as digests
from dewpoint.engine.graph.csv import MAX_BYTES

PURPOSE = "csv.upload"
MAPPING_PURPOSE = "csv.mapping"
TTL = timedelta(hours=1)
PREVIEW_ROWS = 5


def declaration(version: WorkflowVersion) -> dict[str, Any] | None:
    """A version's CSV declaration, as its graph document holds it; None when it declares none."""
    csv = (version.graph.get("settings") or {}).get("csv")
    return dict(csv) if csv else None


def byte_cap(csv: Mapping[str, Any]) -> int:
    """The most an upload may send: the declaration's own cap, never past the platform's."""
    return min(int(csv["max_bytes"]), MAX_BYTES)


def described(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]) -> dict[str, Any]:
    """What `mapping` makes of `table`: its problems, the preview and the records' errors."""
    problems = mapping_problems(columns, mapping, table.headers)
    built = None if problems else build_rows(table, columns, mapping)
    position = {header: i for i, header in enumerate(table.headers)}
    shown = [c["name"] for c in columns if not c.get("sensitive") and c["name"] in mapping and not problems]
    preview = [
        {"row": number, "cells": {name: _cell(record, position[mapping[name]]) for name in shown}}
        for number, record in enumerate(table.rows[:PREVIEW_ROWS], start=1)
    ]
    return {
        "mapping": dict(mapping),
        "problems": problems,
        "masked_columns": [c["name"] for c in columns if c.get("sensitive")],
        "preview": preview,
        "errors": [asdict(e) for e in built.errors] if built else [],
        "error_count": built.error_count if built else 0,
    }


def _cell(record: list[str], index: int) -> str:
    return record[index] if index < len(record) else ""


async def stage(
    s: AsyncSession,
    keys: KeySource,
    *,
    tenant_id: uuid.UUID,
    owner_id: uuid.UUID,
    workflow_id: uuid.UUID,
    csv: Mapping[str, Any],
    data: bytes,
) -> dict[str, Any]:
    """The file staged, and what the uploader is told. Raises CsvFileError for a file that can't be read, having
    staged nothing."""
    table = read_table(data, max_rows=int(csv["max_rows"]), max_bytes=byte_cap(csv))
    upload_id = uuid.uuid4()
    staged = await ClaimCipher(keys, purpose=PURPOSE).seal(str(tenant_id), str(upload_id), data)
    key_version, file_digest = await digests.file_digest(keys, str(tenant_id), data)
    upload = CsvUpload(
        id=upload_id, tenant_id=tenant_id, owner_id=owner_id, workflow_id=workflow_id, staged=staged,
        file_digest=file_digest, digest_key_version=key_version, size_bytes=len(data), row_count=len(table.rows),
        expires_at=func.now() + TTL,
    )  # fmt: skip
    s.add(upload)
    await s.flush()
    await s.refresh(upload)
    columns = csv["columns"]
    mapping, default = await proposed(s, keys, tenant_id=tenant_id, workflow_id=workflow_id, columns=columns,
                                      headers=table.headers)  # fmt: skip
    return {
        "upload_id": str(upload_id),
        "expires_at": upload.expires_at.isoformat(),
        "headers": table.headers,
        "row_count": len(table.rows),
        "default_mapping": default,
        **described(table, columns, mapping),
    }


async def save_default(
    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_id: uuid.UUID,
    user_id: uuid.UUID, mapping: Mapping[str, str],
) -> None:  # fmt: skip
    """`mapping`, checked against the version's declaration by the caller, as the workflow's default; not stale."""
    plaintext = json.dumps(dict(mapping), sort_keys=True, ensure_ascii=False).encode()
    sealed = await ClaimCipher(keys, purpose=MAPPING_PURPOSE).seal(str(tenant_id), str(workflow_id), plaintext)
    values = {"mapping": sealed, "saved_by": user_id, "saved_against": version_id, "saved_at": func.now(),
              "stale_at": None}  # fmt: skip
    await s.execute(
        insert(CsvMapping)
        .values(workflow_id=workflow_id, tenant_id=tenant_id, **values)
        .on_conflict_do_update(index_elements=[CsvMapping.workflow_id], set_=values)
    )


async def proposed(
    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID,
    columns: Sequence[Mapping[str, Any]], headers: Sequence[str],
) -> tuple[dict[str, str], dict[str, Any]]:  # fmt: skip
    """The mapping an upload proposes, and what became of the saved default: none, applied, or stale with its
    problems (marked on its row the first time an upload finds it), the exact matches proposed instead."""
    saved = await s.get(CsvMapping, workflow_id, populate_existing=True)  # row-level security: the tenant's only
    if saved is None:
        return exact_mapping(columns, headers), {"status": "none"}
    plaintext = await ClaimCipher(keys, purpose=MAPPING_PURPOSE).open(str(tenant_id), str(workflow_id), saved.mapping)
    mapping: dict[str, str] = json.loads(plaintext)
    problems = mapping_problems(columns, mapping, None)  # the declaration's: a file's own headers aren't staleness
    if not problems:
        return mapping, {"status": "applied"}
    if saved.stale_at is None:
        await s.execute(update(CsvMapping).where(CsvMapping.workflow_id == workflow_id).values(stale_at=func.now()))
    return exact_mapping(columns, headers), {"status": "stale", "problems": problems}
