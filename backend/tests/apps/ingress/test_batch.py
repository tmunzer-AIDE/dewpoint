# SPDX-License-Identifier: Apache-2.0
"""An authenticated body as the batch ingress records (engine 2b spec §8.3; the owner's ruling 4): its events split,
each with a new id, its typed dedupe key and content digest (none for an endpoint whose events carry no id), and its
canonical bytes sealed to the tenant's public key, bound to the tenant, the endpoint and the event's id."""

import json
import os
import uuid
from dataclasses import replace

import pytest
from cryptography.exceptions import InvalidTag

from dewpoint.apps.ingress.batch import prepare
from dewpoint.apps.ingress.endpoints import Endpoint
from dewpoint.core.crypto import events
from dewpoint.core.ingress.identity import canonical, content_digest, dedupe_key
from dewpoint.core.ingress.parsing import MalformedError

PRIVATE, PUBLIC = events.generate_keypair()
SECRET = os.urandom(32)
ENDPOINT = Endpoint(
    id=uuid.uuid4(), tenant_id=uuid.uuid4(), enabled=True, tenant_active=True, auth_kind="bearer", bearer_digest=b"",
    hmac_secret=None, signature_header=None, timestamp_header=None, tolerance_s=300, allowlist=(),
    body_limit=1024 * 1024, id_source="none", id_pointer=None, id_header=None, events_pointer=None, dedupe_key=b"",
    key_version=3, public_key=PUBLIC,
)  # fmt: skip
POINTER = replace(ENDPOINT, id_source="pointer", id_pointer="/id", events_pointer="/events")
HEADER = replace(ENDPOINT, id_source="header", id_header="x-batch-id", events_pointer="/events")


def _opened(endpoint: Endpoint, event_id: uuid.UUID, blob: bytes) -> bytes:
    return events.open_sealed(
        PRIVATE, tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id, event_id=event_id, blob=blob
    )


def test_a_body_without_ids_is_one_event_with_no_dedupe() -> None:
    batch = prepare(ENDPOINT, b'{ "b": 2, "a": [1, 1.0] }', None, None)
    assert (len(batch.ids), batch.versions, batch.dedupe, batch.digests) == (1, [3], [None], [None])
    assert _opened(ENDPOINT, batch.ids[0], batch.sealed[0]) == b'{"a":[1,1.0],"b":2}'  # canonical bytes are sealed
    assert len(batch.sealed[0]) == len(b'{"a":[1,1.0],"b":2}') + events.OVERHEAD


def test_a_sealed_event_opens_only_as_its_own() -> None:
    batch = prepare(ENDPOINT, b'{"a": 1}', None, None)
    with pytest.raises(InvalidTag):
        _opened(replace(ENDPOINT, id=uuid.uuid4()), batch.ids[0], batch.sealed[0])
    with pytest.raises(InvalidTag):
        _opened(ENDPOINT, uuid.uuid4(), batch.sealed[0])


def test_pointer_ids_are_typed_and_identify_content_not_formatting() -> None:
    body = {"events": [{"id": 1, "v": "x"}, {"id": "1", "v": "x"}]}
    batch = prepare(POINTER, json.dumps(body).encode(), None, SECRET)
    assert batch.dedupe == [dedupe_key(SECRET, "pointer", 1, 0), dedupe_key(SECRET, "pointer", "1", 1)]
    assert batch.dedupe[0] != batch.dedupe[1]  # 1 and "1" are two ids
    assert batch.digests == [content_digest(SECRET, canonical(event)) for event in body["events"]]
    again = prepare(POINTER, b'{"events":[{"v":"x","id":1}]}', None, SECRET)  # reformatted, keys reordered
    assert (again.dedupe[0], again.digests[0]) == (batch.dedupe[0], batch.digests[0])
    assert again.ids[0] != batch.ids[0]  # each attempt's events get new internal ids


def test_a_header_id_names_each_event_by_its_index() -> None:
    batch = prepare(HEADER, b'{"events": [{"v": 1}, {"v": 1}]}', "delivery-7", SECRET)
    assert batch.dedupe == [dedupe_key(SECRET, "header", "delivery-7", i) for i in (0, 1)]
    assert batch.dedupe[0] != batch.dedupe[1]


@pytest.mark.parametrize(
    ("endpoint", "body", "header"),
    [
        (POINTER, b'{"events": [{"v": 1}]}', None),  # no id
        (POINTER, b'{"events": [{"id": true}]}', None),
        (POINTER, b'{"events": [{"id": 1.5}]}', None),
        (POINTER, b'{"events": [{"id": {"x": 1}}]}', None),
        (POINTER, b'{"events": [{"id": ""}]}', None),
        (POINTER, b'{"events": [{"id": "' + b"x" * 256 + b'"}]}', None),
        (POINTER, b'{"events": [{"id": 1}, {"id": null}]}', None),  # one bad id refuses all
        (HEADER, b'{"events": [{"v": 1}]}', None),  # no header
        (HEADER, b'{"events": [{"v": 1}]}', ""),
        (ENDPOINT, b'{"a": 1, "a": 2}', None),
        (ENDPOINT, b"[]", None),
        (POINTER, b'{"events": {"id": 1}}', None),
    ],
)
def test_an_event_without_a_valid_id_or_a_malformed_body_refuses_the_whole_body(endpoint, body, header) -> None:
    with pytest.raises(MalformedError):
        prepare(endpoint, body, header, SECRET)
