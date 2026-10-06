# SPDX-License-Identifier: Apache-2.0
"""Plugin calls in the database (plugins-3 D3): what the API asks a worker, and the answer.

The API asks within its tenant (`ask_options`, `ask_verify`), wakes the workers (`notify`), reads the answer (`read`)
and deletes the call (`forget`). A worker finds calls through `candidates` (queue metadata only), claims one with a
fresh random token and a lease (`claim`, under `SKIP LOCKED`), and answers it (`answer`, `refuse`) only while its
token is the call's, its lease and the call's expiry both hold and the call is still claimed: an earlier execution of
the same worker, a lapsed lease, an expired call or one the API abandoned takes nothing. Callers set the tenant
scope."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.sdk import calls as sdk_calls
from dewpoint.sdk import net as sdk_net

PURPOSE = "plugin.call"  # an answer is sealed under the tenant's data key with this purpose, the call's id as context
CHANNEL = "dewpoint_plugin_calls"  # NOTIFY wakes the workers; it carries nothing
EXPIRES_S = 30.0
LEASE_S = 15.0


# The only failure codes a call shows: the SDK's own transport errors' and the plugin-call codes (the 3a-2 review's
# finding 12). Anything else is shown as `unavailable`.
SDK_CODES = frozenset(
    cls.code for module in (sdk_net, sdk_calls) for cls in vars(module).values()
    if isinstance(cls, type) and issubclass(cls, sdk_net.TransportError)
)  # fmt: skip
CODES = SDK_CODES | frozenset({
    "timeout", "plugin_failed", "connection_changed", "invalid_field", "invalid_result", "result_refused",
    "result_too_large", "unavailable",
})  # fmt: skip


def shown(code: str | None) -> str:
    return code if code in CODES else "unavailable"


@dataclass(frozen=True)
class Answer:
    state: str
    result_ct: bytes | None
    error: str | None


@dataclass(frozen=True)
class Claimed:
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    node_ref: str | None
    field: str | None
    connection_type: str | None
    connection_id: uuid.UUID | None
    revision: int | None
    query: str
    token: uuid.UUID
    lease_until: datetime
    expires_at: datetime


async def ask_options(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    node_ref: str,
    field: str,
    connection_id: uuid.UUID | None,
    revision: int | None,
    query: str,
    type_hash: str | None,
    expires_s: float = EXPIRES_S,
) -> uuid.UUID:
    """`type_hash`: the synced declaration of the connection's type, when a connection is named."""
    found = await s.execute(
        text(
            "insert into plugin_calls (tenant_id, kind, node_ref, field, connection_id, connection_revision, query, "
            "type_hash, expires_at) values (:t, 'options', :ref, :field, :c, :rev, :q, :h, "
            "now() + make_interval(secs => :ttl)) returning id"
        ),
        {"t": tenant_id, "ref": node_ref, "field": field, "c": connection_id, "rev": revision, "q": query,
         "h": type_hash, "ttl": expires_s},
    )  # fmt: skip
    return uuid.UUID(str(found.scalar_one()))


async def ask_verify(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    connection_type: str,
    connection_id: uuid.UUID,
    revision: int,
    type_hash: str,
    expires_s: float = EXPIRES_S,
) -> uuid.UUID:
    found = await s.execute(
        text(
            "insert into plugin_calls (tenant_id, kind, connection_type, connection_id, connection_revision, "
            "type_hash, expires_at) values (:t, 'verify', :type, :c, :rev, :h, now() + make_interval(secs => :ttl)) "
            "returning id"
        ),
        {"t": tenant_id, "type": connection_type, "c": connection_id, "rev": revision, "h": type_hash,
         "ttl": expires_s},
    )  # fmt: skip
    return uuid.UUID(str(found.scalar_one()))


async def notify(s: AsyncSession) -> None:
    """Wakes the workers when the transaction commits. The channel is open to every role, so it carries nothing."""
    await s.execute(text("select pg_notify(:channel, '')"), {"channel": CHANNEL})


async def read(s: AsyncSession, tenant_id: uuid.UUID, call_id: uuid.UUID) -> Answer | None:
    found = await s.execute(
        text("select state, result_ct, error from plugin_calls where id = :i and tenant_id = :t"),
        {"i": call_id, "t": tenant_id},
    )
    row = found.first()
    return Answer(row[0], bytes(row[1]) if row[1] is not None else None, row[2]) if row is not None else None


async def forget(s: AsyncSession, tenant_id: uuid.UUID, call_id: uuid.UUID) -> None:
    await s.execute(text("delete from plugin_calls where id = :i and tenant_id = :t"), {"i": call_id, "t": tenant_id})


async def candidates(
    s: AsyncSession, refs: list[str], types: list[str], hashes: list[str], limit: int
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """The due calls of these node refs and connection types, through connection types declared as `hashes` say,
    across tenants, each tenant's oldest first: (tenant, call) only."""
    rows = await s.execute(
        text("select tenant_id, id from plugin_call_candidates(:refs, :types, :hashes, :n)"),
        {"refs": refs, "types": types, "hashes": hashes, "n": limit},
    )
    return [(uuid.UUID(str(t)), uuid.UUID(str(i))) for t, i in rows.all()]


async def claim(
    s: AsyncSession, tenant_id: uuid.UUID, call_id: uuid.UUID, *, lease_s: float = LEASE_S
) -> Claimed | None:
    """The call, claimed with a fresh token, if it's still due and no one else holds its row."""
    locked = await s.execute(
        text(
            "select id from plugin_calls where id = :i and tenant_id = :t and expires_at > now() "
            "and (state = 'pending' or (state = 'claimed' and lease_until <= now())) for update skip locked"
        ),
        {"i": call_id, "t": tenant_id},
    )
    if locked.first() is None:
        return None
    token = uuid.uuid4()
    found = await s.execute(
        text(
            "update plugin_calls set state = 'claimed', claim_token = :token, "
            "lease_until = now() + make_interval(secs => :lease) where id = :i and tenant_id = :t "
            "returning kind, node_ref, field, connection_type, connection_id, connection_revision, query, "
            "lease_until, expires_at"
        ),
        {"i": call_id, "t": tenant_id, "token": token, "lease": lease_s},
    )
    row = found.one()
    return Claimed(
        id=call_id,
        tenant_id=tenant_id,
        kind=row[0],
        node_ref=row[1],
        field=row[2],
        connection_type=row[3],
        connection_id=uuid.UUID(str(row[4])) if row[4] is not None else None,
        revision=row[5],
        query=row[6],
        token=token,
        lease_until=row[7],
        expires_at=row[8],
    )


# Both answers are fenced: this claim's token, still claimed, within its lease and the call's expiry, now. An answer is
# also taken only while the call's connection is still the revision the API read (the owner's review, finding 3).
_ANSWER = text(
    "update plugin_calls set state = 'done', result_ct = :r, claim_token = null, lease_until = null "
    "where id = :i and tenant_id = :t and claim_token = :token and state = 'claimed' "
    "and lease_until > clock_timestamp() and expires_at > clock_timestamp() "
    "and (connection_id is null or exists (select 1 from connections c where c.tenant_id = plugin_calls.tenant_id "
    "and c.id = plugin_calls.connection_id and c.revision = plugin_calls.connection_revision))"
)
_REFUSE = text(
    "update plugin_calls set state = 'failed', error = :e, claim_token = null, lease_until = null "
    "where id = :i and tenant_id = :t and claim_token = :token and state = 'claimed' "
    "and lease_until > clock_timestamp() and expires_at > clock_timestamp()"
)


async def answer(s: AsyncSession, tenant_id: uuid.UUID, call_id: uuid.UUID, token: uuid.UUID, result_ct: bytes) -> bool:
    """Takes the sealed answer only from the current claim, within its lease and the call's expiry."""
    done = await s.execute(_ANSWER, {"i": call_id, "t": tenant_id, "token": token, "r": result_ct})
    return bool(getattr(done, "rowcount", 0) == 1)


async def refuse(s: AsyncSession, tenant_id: uuid.UUID, call_id: uuid.UUID, token: uuid.UUID, error: str) -> bool:
    """Records why the call has no answer, fenced as `answer`."""
    done = await s.execute(_REFUSE, {"i": call_id, "t": tenant_id, "token": token, "e": shown(error)})
    return bool(getattr(done, "rowcount", 0) == 1)


async def connection_changed(s: AsyncSession, tenant_id: uuid.UUID, call_id: uuid.UUID) -> bool:
    """Whether the call's connection is no longer the revision the API read."""
    found = await s.execute(
        text(
            "select 1 from plugin_calls p where p.id = :i and p.tenant_id = :t and p.connection_id is not null "
            "and not exists (select 1 from connections c where c.tenant_id = p.tenant_id and c.id = p.connection_id "
            "and c.revision = p.connection_revision)"
        ),
        {"i": call_id, "t": tenant_id},
    )
    return found.first() is not None


async def sweep(s: AsyncSession) -> int:
    """Deletes calls a minute past their expiry, across tenants."""
    return int((await s.execute(text("select plugin_calls_sweep()"))).scalar_one())
