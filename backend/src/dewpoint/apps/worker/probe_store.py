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

from dewpoint.engine.runtime import probe as P
from dewpoint.engine.runtime.probe import ITEM, KIND, SPILL, VALUE, SpillInput

SEGMENT_MAX = 1_835_008  # a claim's JSON bytes at most: a size claim may hold up to the payload limit (§3.5)
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
        """A step's input with every handle read, nested handles included (§3.3)."""
        if P.is_handle(value):
            return await self.resolve(await self.open(value))
        if isinstance(value, dict):
            return {k: await self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [await self.resolve(v) for v in value]
        return value

    async def open(self, h: dict[str, Any]) -> Any:
        """What handle `h` addresses, one level: handles inside it stay handles. A missing target raises LookupError."""
        kind = h[KIND]
        if kind == ITEM:
            segment = await self.get(f"{h['id']}/{h['i'] // h['per']}")
            return segment[h["i"] % h["per"]]
        if kind == VALUE:
            return await self.walk(await self.get(h["id"]), P.tokens(h.get("ptr", "")))
        if kind == P.LIST:
            return await self._list(h)
        if kind == P.COLL:
            return await self._coll(h)
        if kind == P.AT:
            return await self.walk(await self.open(h["of"]), P.tokens(h["ptr"]))
        raise LookupError(f"proto: unknown handle kind {kind!r}")

    async def walk(self, value: Any, toks: list[str]) -> Any:
        """Follow a pointer: through chain claims (a key absent from a part is in an older one), and through the
        handles it meets on the way."""
        at = 0
        while at < len(toks):
            if P.is_handle(value):
                value = await self.open(value)
                continue
            tok = toks[at]
            if isinstance(value, dict) and P.CHAIN in value:
                part = value[P.CHAIN]
                if isinstance(part, dict) and tok in part:
                    value, at = part[tok], at + 1
                elif value.get("prev") is not None:
                    value = value["prev"]
                else:
                    raise LookupError(f"`{tok}` has no value here.")
                continue
            if isinstance(value, dict):
                if tok not in value:
                    raise LookupError(f"`{tok}` has no value here.")
                value = value[tok]
            elif isinstance(value, list):
                i = int(tok) if tok.isdigit() else -1
                if not 0 <= i < len(value):
                    raise LookupError(f"`{tok}` has no value here.")
                value = value[i]
            else:
                raise LookupError(f"`{tok}` has no value here.")
            at += 1
        return value

    async def _list(self, h: dict[str, Any]) -> list[Any]:
        first, n, per = int(h.get("from", 0)), int(h["n"]), int(h["per"])
        out = []
        for i in range(first, first + n):
            segment = await self.get(f"{h['id']}/{i // per}")
            out.append(segment[i % per])
        return out

    async def _segs(self, entries: list[Any]) -> list[list[int]]:
        """A collection's segment list: its entries, and the index segments an entry's handle leads to."""
        out: list[list[int]] = []
        for e in entries:
            if isinstance(e, dict):
                claim = await self.open(e) if P.is_handle(e) else e
                while claim is not None:
                    out += await self._segs(claim[P.CHAIN])
                    prev = claim.get("prev")
                    claim = await self.open(prev) if prev is not None else None
            else:
                out.append(e)
        return out

    async def _coll(self, h: dict[str, Any]) -> list[Any]:
        """A collection, as the list its loop collected (positions with nothing read as null)."""
        values: dict[int, Any] = {}
        index = h.get("index") or [None, None, 0]
        entries = list(h["segs"]) + (index[0] or []) + ([index[1]] if index[1] else [])
        for first, _count, _bytes in await self._segs(entries):
            for i, v in await self.get(f"{h['base']}/{first}"):
                values[int(i)] = v
        for _first, pairs in h.get("sealing", []):
            for i, v in pairs:
                values[int(i)] = v
        for i, v in h["tail"]:
            values[int(i)] = v
        offset = int(h["offset"])
        return [values.get(offset + p) for p in range(int(h["n"]))]


STORE: ProbeStore | None = None


@activity.defn(name=SPILL)
async def spill(data: SpillInput) -> int:
    if STORE is None:
        raise ApplicationError("proto: no probe store", non_retryable=True)
    return await STORE.put(data.id, data.value)


@activity.defn(name=P.DERIVE)
async def derive(data: P.DeriveInput) -> int:
    """Proto (§3.2): a reference whose pointer passed POINTER_MAX: copy what it addresses into a claim of its own."""
    if STORE is None:
        raise ApplicationError("proto: no probe store", non_retryable=True)
    try:
        value = await STORE.open(data.handle)
    except LookupError as e:
        raise ApplicationError(str(e), type="evaluation_error", non_retryable=True) from None
    return await STORE.put(data.id, value)


async def claim_envelope(store: ProbeStore, value: Any, base: str, limit: int) -> Any:
    """Proto (§3.5): while the envelope passes `limit`, claim its largest remaining subtree (ties by pointer), down to
    the whole value; each claim holds handles where its claimed descendants were."""
    value = json.loads(json.dumps(value))
    while P.size(value) > limit:
        best: tuple[int, str, list[Any]] | None = None
        stack: list[tuple[Any, list[Any]]] = [(value, [])]
        while stack:
            node, path = stack.pop()
            if P.is_handle(node):
                continue
            if path:
                n = P.size(node)
                ptr = "".join("/" + P.esc(t) for t in path)
                if best is None or n > best[0] or (n == best[0] and ptr < best[1]):
                    best = (n, ptr, path)
            if isinstance(node, dict):
                stack += [(v, [*path, k]) for k, v in node.items()]
            elif isinstance(node, list):
                stack += [(v, [*path, i]) for i, v in enumerate(node)]
        if best is None or best[0] <= P.HANDLE_MAX:
            claim = P.claim_id(f"{base}/")
            await store.put(claim, value)
            return P.handle(claim)
        _, ptr, path = best
        parent = value
        for t in path[:-1]:
            parent = parent[t]
        claim = P.claim_id(f"{base}{ptr}")
        await store.put(claim, parent[path[-1]])
        parent[path[-1]] = P.handle(claim)
    return value


@activity.defn(name=P.CLAIM_INPUT)
async def claim_input(data: P.ClaimInput) -> Any:
    """Proto (§3.5): a sub-flow's input, split to its envelope as its parent starts it."""
    if STORE is None:
        raise ApplicationError("proto: no probe store", non_retryable=True)
    return await claim_envelope(STORE, data.value, data.base, P.TRIGGER_INLINE)
