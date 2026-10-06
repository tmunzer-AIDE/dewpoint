# SPDX-License-Identifier: Apache-2.0
"""Rotating the ingress key (engine 2b spec §8.3), as the key admin, which holds it for this: every endpoint's sealed
secrets (its HMAC secret and its dedupe secret) sealed again under the current key. The command keeps their plaintext
(its behaviour: the key admin's grants allow writing these columns, not only the same secrets), so a sender's
signatures still verify and deduplication carries on. Across every tenant, in batches that each commit, each
write a compare-and-swap on the blob it read: a secret rotated meanwhile (sealed under the current key) is never
overwritten. `usage` counts the sealed secrets by the key id each names, so the previous key retires once none does."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET, IngressKey

BATCH = 100
SEALED = (("hmac_secret", HMAC_SECRET), ("dedupe_key", DEDUPE_KEY))
# A sealed secret's key id: the byte after the format names its length (core/crypto/ingress.py's layout).
_KID = "convert_from(substring({c} from 3 for get_byte({c}, 1)), 'UTF8')"


async def _after_choosing(column: str) -> None:
    """A test's hook: the API may rotate a secret between this batch's read and its write."""


async def usage(s: AsyncSession) -> dict[str, int]:
    """Sealed secrets per ingress key id, every endpoint's."""
    counts: dict[str, int] = {}
    for column, _ in SEALED:
        found = await s.execute(text(f"SELECT {_KID.format(c=column)}, count(*) FROM webhook_endpoints "  # noqa: S608
                                     f"WHERE {column} IS NOT NULL GROUP BY 1"))  # fmt: skip
        for kid, n in found.all():
            counts[str(kid)] = counts.get(str(kid), 0) + int(n)
    return counts


async def reseal(sessionmaker: async_sessionmaker[AsyncSession], key: IngressKey, *,
                 batch: int = BATCH) -> dict[str, int]:  # fmt: skip
    """Every endpoint's secrets sealed under another ingress key sealed again under the current one: how many."""
    counts: dict[str, int] = {}
    for column, purpose in SEALED:
        done, after = 0, None
        while True:
            async with sessionmaker() as s, s.begin():
                later = "AND id > :after " if after else ""
                older = (f"SELECT id, {column} FROM webhook_endpoints WHERE {column} IS NOT NULL AND "  # noqa: S608
                         f"{_KID.format(c=column)} <> :kid {later}ORDER BY id LIMIT :n")  # fmt: skip
                rows = (await s.execute(text(older), {"kid": key.key_id, "after": after, "n": batch})).all()
                if not rows:
                    break
                await _after_choosing(column)
                for endpoint_id, blob in rows:
                    again = key.seal(purpose, str(endpoint_id), key.open(purpose, str(endpoint_id), bytes(blob)))
                    swapped = await s.execute(
                        text(f"UPDATE webhook_endpoints SET {column} = :new WHERE id = :e AND {column} = :old"),  # noqa: S608
                        {"e": endpoint_id, "new": again, "old": bytes(blob)},
                    )
                    done += swapped.rowcount  # type: ignore[attr-defined]
                after = rows[-1][0]
        counts[column] = done
    return counts
