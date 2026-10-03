# SPDX-License-Identifier: Apache-2.0
"""Claiming a run's input before it starts (engine 2b spec §3.5). One function validates the input against the
version's input schema, then splits it: its sensitive and undeclared values, text repeating them, and what's too large
become claims owned by the run (§3.4), and the strings of the tainted ones seed the run tree's secret index (§3.7).
What's left is the envelope the start carries, with handles in place of claims.

An input that doesn't match its schema is refused with the places and rules it breaks, never a value nor a key the data
supplied (a map's key can be a secret, and a sub-flow's refusal is an activity result: history); one that holds the
handle marker is refused: data from outside never crosses into a run as a handle (§3.2)."""

import uuid
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.claims import secret_index
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
from dewpoint.core.crypto.keys import KeySource
from dewpoint.engine.handles import contains_marker
from dewpoint.engine.runtime.projection import location
from dewpoint.engine.split import split

FORGED = "The run's input holds the reserved key `$claim`, which only Dewpoint writes."
_REASONS = 5  # an input that breaks more rules is told about the first ones


INPUT_INVALID = "input_invalid"


class InputRefusedError(Exception):
    """`reasons`: what to tell the caller, places and rules only; `reason`: its code (engine 2b spec §9)."""

    def __init__(self, reasons: list[str], reason: str = INPUT_INVALID) -> None:
        super().__init__("; ".join(reasons))
        self.reasons, self.reason = reasons, reason


def reasons(schema: Mapping[str, Any], value: Any) -> list[str]:
    """Why `value` doesn't match `schema`: each place, as far as the schema declares it (`projection.location`: a key
    the data supplied shows as `*`), and the rule it breaks; never what's there. Ordered by that text, not by the
    data."""
    found = sorted(
        (location(list(e.absolute_path), schema), str(e.validator))
        for e in Draft202012Validator(schema).iter_errors(value)
    )
    return [
        f"The run's input doesn't match the workflow's input schema at "
        f"{'its root' if where == '(root)' else where}: it breaks `{rule}`."
        for where, rule in found[:_REASONS]
    ]


async def claim_input(
    s: AsyncSession,
    keys: KeySource,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    root_run_id: uuid.UUID,
    schema: Mapping[str, Any],
    value: dict[str, Any],
) -> Any:
    """The envelope of `value`, its claims written (`run_inputs`) and its secrets indexed, inside the caller's
    transaction. Raises InputRefusedError, having written nothing that commits."""
    refused = reasons(schema, value)
    if refused:
        raise InputRefusedError(refused)
    if contains_marker(value):
        raise InputRefusedError([FORGED])
    done = split(value, schema, lambda pointer: str(uuid.uuid4()))
    if done.claims:
        cipher = ClaimCipher(keys)
        for c in done.claims:
            new = claims.NewClaim(uuid.UUID(c.id), c.value, ("",) if c.tainted else (), run_id, root_run_id)
            await claims.write_input(s, cipher, tenant_id, new, pointer=c.pointer)
    if done.secrets:
        index = ClaimCipher(keys, purpose=secret_index.PURPOSE)
        try:
            await secret_index.extend(s, index, tenant_id, root_run_id, list(done.secrets))
        except secret_index.SecretIndexLimitError as e:
            raise InputRefusedError([str(e)], SECRET_INDEX_LIMIT) from None
    return done.envelope
