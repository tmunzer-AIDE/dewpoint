# SPDX-License-Identifier: Apache-2.0
"""A CSV staged for a start (engine 2b spec §8.1): read as data only (`apps.csv_input`), its headers and cells sealed
with the tenant's key under `csv.upload` (the upload's id the context), owned by its uploader and tenant for one hour.
A start consumes it in its own transaction.

What the uploader is told: the file's headers, the declared columns mapped to them (exact matches), what keeps that
mapping from building rows, a preview of the first records' mapped cells with sensitive columns left out, and each
record's errors as its number, the column's name and a code. Nothing is logged or audited at upload: the start's audit
entry keeps the file's tenant-keyed digest and counts."""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.csv_input import Table, build_rows, exact_mapping, mapping_problems, read_table
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.models.uploads import CsvUpload
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.requests import digest as digests
from dewpoint.engine.graph.csv import MAX_BYTES

PURPOSE = "csv.upload"
TTL = timedelta(hours=1)
PREVIEW_ROWS = 5
LISTED_ERRORS = 100  # the response lists this many; its count is every one


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
    errors = [] if problems else build_rows(table, columns, mapping)[1]
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
        "errors": [asdict(e) for e in errors[:LISTED_ERRORS]],
        "error_count": len(errors),
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
    plaintext = json.dumps({"headers": table.headers, "rows": table.rows}, ensure_ascii=False).encode()
    staged = await ClaimCipher(keys, purpose=PURPOSE).seal(str(tenant_id), str(upload_id), plaintext)
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
    return {
        "upload_id": str(upload_id),
        "expires_at": upload.expires_at.isoformat(),
        "headers": table.headers,
        "row_count": len(table.rows),
        **described(table, columns, exact_mapping(columns, table.headers)),
    }
