# SPDX-License-Identifier: Apache-2.0
"""Ingress's app in a test: its settings for the ingress login, endpoints whose secrets are sealed under the test's
ingress key, a client at a chosen address, and a clock the test moves."""

import base64
import hashlib
import hmac
import os
import uuid
from typing import Any

import httpx

from dewpoint.apps.ingress.config import IngressSettings
from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET, IngressKey, bearer_digest
from tests.conftest import _url_for
from tests.core.ingress.support import endpoint

KEY_BYTES = os.urandom(32)
KEY = IngressKey("ingress-1", KEY_BYTES)
SECRET = b"s3cret-of-the-endpoint"
TOKEN = "dwp_token-of-the-endpoint"  # noqa: S105 - a test's token
NOW = 1_800_000_000.0
CLIENT = ("198.51.100.7", 40000)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def settings(pg_url: str, **overrides: Any) -> IngressSettings:
    url, key = _url_for(pg_url, "dewpoint_ingress"), base64.b64encode(KEY_BYTES).decode()
    return IngressSettings(**{"database_url": url, "ingress_key_b64": key} | overrides)


def sealed_dedupe_key(endpoint_id: uuid.UUID, key: bytes | None = None) -> bytes:
    return KEY.seal(DEDUPE_KEY, str(endpoint_id), key or os.urandom(32))


async def hmac_endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
    endpoint_id = uuid.uuid4()
    values = {
        "auth_kind": "hmac", "bearer_digest": None, "hmac_secret": KEY.seal(HMAC_SECRET, str(endpoint_id), SECRET),
        "signature_header": "x-signature", "timestamp_header": "x-timestamp",
        "dedupe_key": sealed_dedupe_key(endpoint_id),
    }  # fmt: skip
    return await endpoint(owner, endpoint_id, **values | columns)


async def bearer_endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
    endpoint_id = uuid.uuid4()
    values = {"auth_kind": "bearer", "bearer_digest": bearer_digest(TOKEN)}
    return await endpoint(owner, endpoint_id, **values | {"dedupe_key": sealed_dedupe_key(endpoint_id)} | columns)


def signed(body: bytes, now: float = NOW, secret: bytes = SECRET) -> dict[str, str]:
    stamp = str(int(now))
    signature = hmac.new(secret, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"x-timestamp": stamp, "x-signature": signature}


def bearer() -> dict[str, str]:
    return {"authorization": f"Bearer {TOKEN}"}


def client(app: Any, address: tuple[str, int] = CLIENT) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=address), base_url="http://ingress")
