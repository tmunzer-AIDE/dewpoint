# SPDX-License-Identifier: Apache-2.0
"""Proto only (2b-1b go/no-go): a stub of the claim store, for size spills and handle-backed loop items. It is not
2b-1b's claim design (no RLS, owners, grants or taint): it only gives the prototype somewhere to put values it takes
out of workflow state, with the properties the spill path relies on:
- durable: a Postgres table, so segments outlive any worker (the harness restarts workers mid-run);
- immutable: a trigger refuses every update and delete;
- idempotent: a second write of an id must carry the same content (its SHA-256), or it fails without writing;
- size-checked: a segment's JSON is at most SEGMENT_MAX bytes, or the write fails.

The harness sets `STORE` before the workers start; the activities below and the step activity's handle resolution
read it."""

import hashlib
import json
from collections import OrderedDict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio import activity
from temporalio.exceptions import ApplicationError

from dewpoint.engine.runtime.probe import ITEM, KIND, SPILL, VALUE, SpillInput

SEGMENT_MAX = 1_048_576  # a segment's JSON bytes at most
DDL = [
    """CREATE TABLE IF NOT EXISTS probe_segments (
         id text PRIMARY KEY, sha256 text NOT NULL, bytes integer NOT NULL, data text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE OR REPLACE FUNCTION probe_segments_immutable() RETURNS trigger LANGUAGE plpgsql AS
         $$ BEGIN RAISE EXCEPTION 'probe segments are immutable'; END $$""",
    "DROP TRIGGER IF EXISTS probe_segments_immutable ON probe_segments",
    """CREATE TRIGGER probe_segments_immutable BEFORE UPDATE OR DELETE ON probe_segments
         FOR EACH ROW EXECUTE FUNCTION probe_segments_immutable()""",
]


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class ProbeStore:
    def __init__(self, url: str, *, cache: int = 64) -> None:
        self.engine = create_async_engine(url, pool_size=20)
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._cache_size = cache
        self.stats = {"writes": 0, "write_bytes": 0, "rewrites": 0, "reads": 0, "read_bytes": 0}

    async def setup(self) -> None:
        async with self.engine.begin() as c:
            for stmt in DDL:
                await c.execute(text(stmt))

    async def put(self, segment_id: str, value: Any) -> int:
        data = _json(value)
        size = len(data.encode())
        if size > SEGMENT_MAX:
            raise ApplicationError(
                f"segment {size} bytes, over {SEGMENT_MAX}", type="segment_too_large", non_retryable=True
            )
        digest = hashlib.sha256(data.encode()).hexdigest()
        async with self.engine.begin() as c:
            inserted = await c.execute(
                text(
                    "INSERT INTO probe_segments (id, sha256, bytes, data) VALUES (:i, :h, :n, :d) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"i": segment_id, "h": digest, "n": size, "d": data},
            )
            stored: str = (
                await c.execute(text("SELECT sha256 FROM probe_segments WHERE id = :i"), {"i": segment_id})
            ).scalar_one()
        if stored != digest:
            raise ApplicationError("another content under this id", type="segment_conflict", non_retryable=True)
        if inserted.rowcount:
            self.stats["writes"] += 1
            self.stats["write_bytes"] += size
        else:
            self.stats["rewrites"] += 1
        return size

    async def get(self, segment_id: str) -> Any:
        if segment_id in self._cache:
            self._cache.move_to_end(segment_id)
            return self._cache[segment_id]
        async with self.engine.connect() as c:
            data: str = (
                await c.execute(text("SELECT data FROM probe_segments WHERE id = :i"), {"i": segment_id})
            ).scalar_one()
        self.stats["reads"] += 1
        self.stats["read_bytes"] += len(data)
        value = json.loads(data)
        self._cache[segment_id] = value
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return value

    async def totals(self) -> dict[str, int]:
        async with self.engine.connect() as c:
            n, size = (await c.execute(text("SELECT count(*), coalesce(sum(bytes), 0) FROM probe_segments"))).one()
        return {"rows": int(n), "bytes": int(size)}

    async def resolve(self, value: Any) -> Any:
        """A step's input with its handles read: an item of a handle-backed list, or a spilled value."""
        if isinstance(value, dict):
            kind = value.get(KIND)
            if kind == ITEM:
                segment = await self.get(f"{value['id']}/{value['i'] // value['per']}")
                return segment[value["i"] % value["per"]]
            if kind == VALUE:
                return await self.get(value["id"])
            return {k: await self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [await self.resolve(v) for v in value]
        return value


STORE: ProbeStore | None = None


@activity.defn(name=SPILL)
async def spill(data: SpillInput) -> int:
    if STORE is None:
        raise ApplicationError("proto: no probe store", non_retryable=True)
    return await STORE.put(data.id, data.value)
