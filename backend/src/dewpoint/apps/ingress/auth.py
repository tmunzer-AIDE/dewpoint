# SPDX-License-Identifier: Apache-2.0
"""A request's authentication (engine 2b spec §8.3; the owner's ruling 2): an HMAC-SHA256, under the endpoint's
secret, of `<timestamp>.` and the exact raw body, its timestamp (Unix seconds) within the endpoint's tolerance either
way; or a bearer token whose SHA-256 is the endpoint's digest. Each is compared in constant time. Anything else, a
secret this process can't open included, is a failure: the caller answers every one with the same 401."""

import hashlib
import hmac

import structlog
from cryptography.exceptions import InvalidTag
from starlette.datastructures import Headers

from dewpoint.apps.ingress.endpoints import Endpoint
from dewpoint.core.crypto.ingress import HMAC_SECRET, IngressKey, UnknownIngressKeyError, bearer_matches

log = structlog.get_logger("dewpoint.ingress")
MAX_TIMESTAMP_DIGITS = 12


def _bearer(endpoint: Endpoint, headers: Headers) -> bool:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or not token.isascii() or endpoint.bearer_digest is None:
        return False
    return bearer_matches(token, endpoint.bearer_digest)


def _signed(endpoint: Endpoint, headers: Headers, body: bytes, now: float, key: IngressKey) -> bool:
    if endpoint.hmac_secret is None or endpoint.timestamp_header is None or endpoint.signature_header is None:
        return False
    stamp = headers.get(endpoint.timestamp_header, "")
    signature = headers.get(endpoint.signature_header, "").strip().lower().removeprefix("sha256=")
    if not (stamp.isascii() and stamp.isdigit() and len(stamp) <= MAX_TIMESTAMP_DIGITS) or not signature.isascii():
        return False
    if abs(now - int(stamp)) > endpoint.tolerance_s:
        return False
    try:
        secret = key.open(HMAC_SECRET, str(endpoint.id), endpoint.hmac_secret)
    except (UnknownIngressKeyError, InvalidTag, ValueError) as e:
        log.warning("ingress_secret_unopenable", endpoint_id=str(endpoint.id), error=type(e).__name__)
        return False
    expected = hmac.new(secret, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def authenticate(endpoint: Endpoint, headers: Headers, body: bytes, now: float, key: IngressKey) -> bool:
    if endpoint.auth_kind == "bearer":
        return _bearer(endpoint, headers)
    if endpoint.auth_kind == "hmac":
        return _signed(endpoint, headers, body, now, key)
    return False
