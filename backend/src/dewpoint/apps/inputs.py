# SPDX-License-Identifier: Apache-2.0
"""Claiming a run's input before it starts (engine 2b spec §3.5). One function validates the input against the
version's input schema, then splits it: its sensitive and undeclared values, text repeating them, and what's too large
become claims owned by the run (§3.4), and the strings of the tainted ones seed the run tree's secret index (§3.7).
What's left is the envelope the start carries, with handles in place of claims.

An input that doesn't match its schema is refused with the places and rules it breaks, never a value nor a key the data
supplied (a map's key can be a secret, and a sub-flow's refusal is an activity result: history); one that holds the
handle marker is refused: data from outside never crosses into a run as a handle (§3.2)."""

import asyncio
import math
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
from dewpoint.engine.graph.model import MAX_DEPTH
from dewpoint.engine.handles import ClaimRef, contains_marker
from dewpoint.engine.runtime.projection import location
from dewpoint.engine.split import Split, split

FORGED = "The run's input holds the reserved key `$claim`, which only Dewpoint writes."
RESERVED_INPUT = "The run's input holds `rows` or `row_count`, which only a CSV upload supplies."
_REASONS = 5  # an input that breaks more rules is told about the first ones
TOO_DEEP = f"The run's input nests deeper than {MAX_DEPTH} levels."
TOO_DEEP_TO_CHECK = "The run's input is nested too deeply to check against the workflow's input schema."
NOT_FINITE = "The run's input holds a number that isn't finite: NaN and infinity aren't valid JSON."


def nests_too_deep(value: Any, *, handles: bool = False) -> bool:
    """Whether `value` nests objects and arrays deeper than the engine's limit for a document (`MAX_DEPTH`), its own
    value the first level, as a workflow document and a webhook body are counted (issue #88). Iterative: no recursion
    limit decides, so it runs before anything that recurses through the input. `handles`: a run's value, whose handles
    count as the leaves they stand for (what one expands to is bounded where it's resolved); an input from outside
    holds none (the marker is refused), and a handle there counts as an object."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if handles and ClaimRef.of(current) is not None:
            continue
        if isinstance(current, Mapping):
            children: Any = current.values()
        elif isinstance(current, list | tuple):
            children = current
        else:
            continue
        if depth > MAX_DEPTH:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def holds_non_finite(value: Any) -> bool:
    """Whether `value` holds NaN or an infinity, which Python's JSON parser, and so a request's body, accepts (`NaN`,
    `Infinity`, or a number past a float's range) and JSON can't hold: the idempotency digest's canonical JSON, the
    claims and Postgres JSONB refuse it. Iterative, like `nests_too_deep`."""
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, float):
            if not math.isfinite(current):
                return True
        elif isinstance(current, Mapping):
            stack.extend(current.values())
        elif isinstance(current, list | tuple):
            stack.extend(current)
    return False


INPUT_INVALID = "input_invalid"


class InputRefusedError(Exception):
    """`reasons`: what to tell the caller, places and rules only; `reason`: its code (engine 2b spec §9)."""

    def __init__(self, reasons: list[str], reason: str = INPUT_INVALID) -> None:
        super().__init__("; ".join(reasons))
        self.reasons, self.reason = reasons, reason


def reasons(schema: Mapping[str, Any], value: Any) -> list[str]:
    """Why `value` doesn't match `schema`: each place, as far as the schema declares it (`projection.location`: a key
    the data supplied shows as `*`), and the rule it breaks; never what's there. Ordered by that text, not by the
    data, and each told once: jsonschema reports `required` once per missing property (`dependentRequired` per
    missing dependency, `propertyNames` per refused name), and keys breaking one rule show as one `*`."""
    try:
        found = sorted(
            {
                (location(list(e.absolute_path), schema), str(e.validator))
                for e in Draft202012Validator(schema).iter_errors(value)
            }
        )
    except RecursionError:  # jsonschema descends a call a level: told, never raised (issue #88)
        return [TOO_DEEP_TO_CHECK]
    return [
        f"The run's input doesn't match the workflow's input schema at "
        f"{'its root' if where == '(root)' else where}: it breaks `{rule}`."
        for where, rule in found[:_REASONS]
    ]


def checked(schema: Mapping[str, Any], value: dict[str, Any], *, against_schema: bool = True) -> Split:
    """`value` checked against `schema`, then split: CPU only. Raises InputRefusedError. Its depth first: nothing
    recursive reads an input deeper than the limit (issue #88). `against_schema` False: the caller checked it by rules
    of its own (a step's seeds, S2), and the schema only says what's sensitive."""
    if nests_too_deep(value):
        raise InputRefusedError([TOO_DEEP])
    refused = reasons(schema, value) if against_schema else []
    if refused:
        raise InputRefusedError(refused)
    if contains_marker(value):
        raise InputRefusedError([FORGED])
    return split(value, schema, lambda pointer: str(uuid.uuid4()))


async def claim_input(
    s: AsyncSession,
    keys: KeySource,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    root_run_id: uuid.UUID,
    schema: Mapping[str, Any],
    value: dict[str, Any],
    off_loop: bool = False,
    against_schema: bool = True,
) -> Any:
    """The envelope of `value`, its claims written (`run_inputs`) and its secrets indexed, inside the caller's
    transaction. Raises InputRefusedError, having written nothing that commits. `off_loop`: the check and the split in a
    thread, for the work a CSV slot bounds (seconds of CPU for a CSV's rows at the caps; the owner's ruling 2 on 2b-4b's
    M3 checkpoint); the session stays on the event loop."""
    if off_loop:
        done = await asyncio.to_thread(checked, schema, value, against_schema=against_schema)
    else:
        done = checked(schema, value, against_schema=against_schema)
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
