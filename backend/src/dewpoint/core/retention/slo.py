# SPDX-License-Identifier: Apache-2.0
"""Retention's SLO (engine 2b spec §10.3): a successful sweep within the last 24 hours, whose lag is under 24 hours. A
breach pauses new production starts (a dispatch-time critical check, §2.3) until retention recovers. Reckoned on the
database's clock."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WITHIN_S = 24 * 3600
LAG_S = 24 * 3600
_HEALTHY = text(
    "SELECT coalesce((SELECT lag_s < :lag FROM retention_sweeps WHERE succeeded "
    "AND ended_at >= statement_timestamp() - make_interval(secs => :within) ORDER BY ended_at DESC LIMIT 1), false)"
)


async def healthy(s: AsyncSession) -> bool:
    """The latest successful sweep within the window left nothing a day past its cutoff."""
    return bool((await s.execute(_HEALTHY, {"lag": LAG_S, "within": WITHIN_S})).scalar_one())
