# SPDX-License-Identifier: Apache-2.0
"""Uploading a CSV for a start (engine 2b spec §8.1): `POST /t/{tid}/workflows/{wid}/csv-uploads`, `run.start`, a raw
`text/csv` body. The API's middleware buffers a body before the app runs, so this one route is passed through unread
(`STREAMED`): it authorizes the caller and loads the active version's declaration first, then reads the body as it
arrives, up to the declaration's cap (never past the platform's 5 MiB), and stops one byte past it with 413, never
reading or buffering the rest."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import admission
from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
from dewpoint.apps.csv_input import CsvFileError
from dewpoint.apps.csv_uploads import byte_cap, declaration, stage
from dewpoint.core.authz.permissions import P
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.workflows import Workflow, WorkflowVersion

router = APIRouter(prefix="/api/v1", tags=["runs"])
STREAMED = re.compile(r"/api/v1/t/[^/]+/workflows/[^/]+/csv-uploads")  # matched whole, for POST
TOO_LARGE = {"error": "too_large"}


class _TooLargeError(Exception):
    pass


async def _read(request: Request, cap: int) -> bytes:
    """The body as it arrives, stopping at its first byte past `cap`: the rest is never read."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise _TooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/t/{tenant_id}/workflows/{workflow_id}/csv-uploads", status_code=201)
async def upload_csv(
    workflow_id: uuid.UUID,
    request: Request,
    ctx: TenantContext = Depends(require(P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """201 with the staged upload's id, its mapping, preview and errors."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
        raise HTTPException(415, detail={"error": "unsupported_media_type"})
    workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
    if workflow is None:
        raise HTTPException(404, detail={"error": "not_found"})
    version = await db.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
    if version is None:
        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
    csv = declaration(version)
    if csv is None:
        raise HTTPException(409, detail={"error": "csv_not_declared"})
    cap = byte_cap(csv)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise HTTPException(413, detail=TOO_LARGE)
    try:
        data = await _read(request, cap)
    except _TooLargeError:
        raise HTTPException(413, detail=TOO_LARGE) from None
    try:
        return await stage(db, keys, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=workflow_id, csv=csv,
                           data=data)  # fmt: skip
    except CsvFileError as e:
        raise HTTPException(422, detail={"error": e.code}) from None
    except Exception as e:
        raise key_unusable(e) from None
