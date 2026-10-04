# SPDX-License-Identifier: Apache-2.0
"""An authenticated body as the batch ingress records (engine 2b spec §8.3; the owner's ruling 4). Its events are split
from the strictly parsed body; each gets a new id, its dedupe key from the id its sender gave it (typed, at the
endpoint's pointer) or from the request's header id and its index, its content digest, and its canonical bytes sealed
to the tenant's newest public key, bound to the tenant, the endpoint and the event's id. Any event without a valid id
refuses the whole body."""

import uuid
from dataclasses import dataclass
from typing import cast

from dewpoint.apps.ingress.endpoints import Endpoint
from dewpoint.core.crypto import events
from dewpoint.core.ingress.identity import IdSource, InvalidEventIdError, canonical, content_digest, dedupe_key
from dewpoint.core.ingress.parsing import MalformedError, events_of, parse
from dewpoint.core.ingress.pointer import PointerError, resolve


@dataclass(frozen=True)
class Batch:
    ids: list[uuid.UUID]
    sealed: list[bytes]
    versions: list[int]
    dedupe: list[bytes | None]
    digests: list[bytes | None]


def _given_id(endpoint: Endpoint, event: dict[str, object], header_id: str | None) -> str | int | None:
    if endpoint.id_source == "pointer" and endpoint.id_pointer is not None:
        try:
            found = resolve(event, endpoint.id_pointer)
        except PointerError:
            raise MalformedError from None
        return found if isinstance(found, (str, int)) else None  # dedupe_key refuses None and a bool
    if endpoint.id_source == "header":
        if header_id is None:
            raise MalformedError
        return header_id
    return None


def prepare(endpoint: Endpoint, body: bytes, header_id: str | None, dedupe_secret: bytes | None) -> Batch:
    """Raises MalformedError. `dedupe_secret` is the endpoint's opened dedupe key: None only when its events carry no
    id."""
    if endpoint.public_key is None or endpoint.key_version is None:
        raise ValueError("the tenant has no inbound key")  # the caller fails closed first
    if endpoint.id_source not in ("pointer", "header", "none"):
        raise ValueError("an id source the schema doesn't allow")
    source = cast(IdSource, endpoint.id_source)
    if source != "none" and dedupe_secret is None:
        raise ValueError("an endpoint with ids needs its dedupe key")
    batch = Batch([], [], [], [], [])
    for index, event in enumerate(events_of(parse(body), endpoint.events_pointer)):
        try:
            key = dedupe_key(dedupe_secret or b"", source, _given_id(endpoint, event, header_id), index)
        except InvalidEventIdError:
            raise MalformedError from None
        content = canonical(event)
        event_id = uuid.uuid4()
        batch.ids.append(event_id)
        batch.sealed.append(
            events.seal(
                endpoint.public_key, endpoint.key_version, tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id,
                event_id=event_id, plaintext=content,
            )
        )  # fmt: skip
        batch.versions.append(endpoint.key_version)
        batch.dedupe.append(key)
        batch.digests.append(content_digest(dedupe_secret, content) if key is not None and dedupe_secret else None)
    return batch
