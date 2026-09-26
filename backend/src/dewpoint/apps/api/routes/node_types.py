# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.http import active_session, get_db
from dewpoint.core.plugins import registry

router = APIRouter(prefix="/api/v1", tags=["node-types"])


@router.get("/node-types", dependencies=[Depends(active_session)])
async def node_types(db: AsyncSession = Depends(get_db, scope="function")) -> list[dict[str, object]]:
    """The editor's palette: node types that new versions may use (active) or still carry (deprecated)."""
    return [
        {
            "ref": row.ref,
            "type": row.type,
            "version": row.version,
            "kind": row.kind,
            "state": row.state,
            "title": row.manifest.get("title"),
            "description": row.manifest.get("description", ""),
            "ports": row.manifest.get("ports", []),
            "dynamic_ports": row.manifest.get("dynamic_ports"),
            "config_schema": row.manifest.get("config_schema"),
            "output_schema": row.manifest.get("output_schema"),
        }
        for row in await registry.list_node_types(db)
    ]
