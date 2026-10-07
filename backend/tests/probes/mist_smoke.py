# SPDX-License-Identifier: Apache-2.0
"""The read-only Mist smoke probe (plugins-3 3b-1; each live run needs the owner's go): every read the Mist plugin's
policy map allows, run through the plugin's own nodes and client over the egress guard against one test org, and each
answer checked against its node's output schema. What it measures: whether real answers carry the shape the OAS
describes (its `required` fields above all), and how large they are. Run by hand, never in CI; from `backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.mist_smoke --cloud global_01 \
        --org <org id> --token-file ~/.config/dewpoint/mist-smoke.token --report <path>

Read-only by construction: its HTTP sends GET without a body and refuses anything else before sending, and it runs
only the curated read nodes, never a write nor the generic nodes. The token is read from a file and only ever applied
as the request's header. Answers stay in memory: the report holds operation names, statuses, sizes and schema
mismatches as declared field names and schema rules (an undeclared key or an index is `*`, a type mismatch names JSON
types), never a value."""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from dewpoint.plugins.mist import PLUGIN
from dewpoint.plugins.mist.connection import MIST_CLOUDS
from dewpoint.plugins.mist.nodes import MistOperation
from dewpoint.sdk import InvalidRequest, NodeError, ReadOnly, TransportError, node_manifest

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
MAX_MISMATCHES = 50  # distinct mismatches kept for one operation
# Path values a list elsewhere gives: (the list's path template, the field of its first result).
SOURCES = {
    "device_id": ("/api/v1/sites/{site_id}/devices", "id"),
    "device_mac": ("/api/v1/sites/{site_id}/devices", "mac"),
    "client_mac": ("/api/v1/sites/{site_id}/clients/search", "mac"),
    "rogue_bssid": ("/api/v1/sites/{site_id}/insights/rogues", "bssid"),
}


class ReadOnlyHttp:
    """The probe's HTTP: GET without a body only, on the cloud's origin only, the token applied here and nowhere
    else. `inner` is the egress guard's client (a fake offline)."""

    def __init__(self, inner: Any, base: str, token: str) -> None:
        self._inner, self._base, self._token = inner, base.rstrip("/"), token

    def _target(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            if f"{parts.scheme}://{parts.netloc}" != self._base:
                raise InvalidRequest()
            return url
        if not url.startswith("/"):
            raise InvalidRequest()
        return self._base + url

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        json: Any = None,
        follow_same_origin: int = 0,
        probe: bool = False,
    ) -> Any:
        if method != "GET" or content is not None or json is not None:
            raise ReadOnly()
        if any(name.lower() == "authorization" for name in headers or {}):
            raise InvalidRequest()
        sent = {**(headers or {}), "Authorization": f"Token {self._token}"}
        return await self._inner.request("GET", self._target(url), headers=sent, params=params)


@dataclass
class ProbeConnection:
    http: ReadOnlyHttp
    config: Mapping[str, Any]
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "mist"


class _Log:
    def info(self, event: str, **fields: object) -> None:
        pass

    def warning(self, event: str, **fields: object) -> None:
        pass


@dataclass
class ProbeStep:
    """A step's context as a curated node sees it: its one connection, attempt 1, nothing else reachable."""

    connection_: ProbeConnection
    attempt: int = 1
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    step_id: uuid.UUID = field(default_factory=uuid.uuid4)
    iteration_key: str = ""
    cancelled: bool = False
    log: _Log = field(default_factory=_Log)

    def idempotency_key(self) -> str:
        return "smoke"

    async def connection(self, connection_id: uuid.UUID) -> ProbeConnection:
        if connection_id != self.connection_.id:
            raise InvalidRequest()
        return self.connection_

    def heartbeat(self, *details: object) -> None:
        pass


def _declared(schema: Any) -> set[str]:
    names: set[str] = set()
    stack = [schema]
    while stack:
        here = stack.pop()
        if isinstance(here, Mapping):
            props = here.get("properties")
            if isinstance(props, Mapping):
                names.update(k for k in props if isinstance(k, str))
            stack.extend(here.values())
        elif isinstance(here, list):
            stack.extend(here)
    return names


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def mismatches(schema: Mapping[str, Any], value: Any) -> list[dict[str, Any]]:
    """Where `value` breaks `schema`: each place as declared field names (`*` for an undeclared key or an index) and
    its rule; a missing field's declared name; a type mismatch's JSON types. Never a value."""
    declared = _declared(schema)
    out: list[dict[str, Any]] = []
    for e in Draft202012Validator(schema).iter_errors(value):
        where = "/".join(p if isinstance(p, str) and p in declared else "*" for p in e.absolute_path)
        entry: dict[str, Any] = {"path": where, "rule": str(e.validator)}
        if e.validator == "required" and isinstance(e.instance, Mapping):
            entry["missing"] = sorted(n for n in e.validator_value if isinstance(n, str) and n not in e.instance)
        if e.validator == "type":
            entry["expected"] = e.validator_value
            entry["found"] = _json_type(e.instance)
        if entry not in out:
            out.append(entry)
        if len(out) >= MAX_MISMATCHES:
            break
    return out


def _source(node: type[MistOperation], name: str) -> tuple[str, str]:
    if name in SOURCES:
        return SOURCES[name]
    segments = node.path.split("/")
    return "/".join(segments[: segments.index("{" + name + "}")]), ("mac" if name.endswith("_mac") else "id")


def _order(node: type[MistOperation]) -> tuple[int, int, str]:
    first = 0 if node.operation == "listOrgSites" else 1
    return first, len(PLACEHOLDER.findall(node.path)), node.type


async def probe(
    http: ReadOnlyHttp,
    cloud: str,
    org_id: str,
    *,
    site: str | None = None,
    rate: float = 2.0,
    nodes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Every selected curated read, run as a step would run it; the report (see the module)."""
    connection = ProbeConnection(http, {"cloud": cloud, "org_id": org_id})
    reads = sorted(
        (n for n in PLUGIN.nodes if issubclass(n, MistOperation) and n.method == "GET"
         and (nodes is None or n.type in nodes)),
        key=_order,
    )  # fmt: skip
    found: dict[str, list[Any]] = {}
    operations: list[dict[str, Any]] = []
    started = time.monotonic()
    for node in reads:
        entry: dict[str, Any] = {"node": node.type, "operation": node.operation}
        operations.append(entry)
        config_schema = node.Config.model_json_schema()
        if "query" in config_schema.get("required", ()):
            entry |= {"status": "skipped", "detail": "needs_query"}
            continue
        values: dict[str, Any] = {}
        for name in PLACEHOLDER.findall(node.path):
            if name == "org_id":
                continue
            if name == "site_id":
                values[name] = site
            else:
                listed, key = _source(node, name)
                items = found.get(listed) or []
                first = items[0] if items and isinstance(items[0], Mapping) else {}
                values[name] = first.get(key)
        if any(not isinstance(v, str) for v in values.values()):
            entry |= {"status": "skipped", "detail": "unresolved"}
            continue
        try:
            config = node.Config.model_validate({"connection": str(connection.id), **values})
        except ValidationError:
            entry |= {"status": "skipped", "detail": "config_refused"}
            continue
        if rate:
            await asyncio.sleep(1 / rate)
        try:
            data = (await node().run(ProbeStep(connection), config)).model_dump(mode="json")  # type: ignore[arg-type]
        except NodeError as e:
            entry |= {"status": "error", "detail": e.code}
            continue
        except TransportError as e:
            entry |= {"status": "error", "detail": type(e).code}
            continue
        except Exception as e:  # noqa: BLE001 - the probe reports and goes on
            entry |= {"status": "error", "detail": type(e).__name__}
            continue
        results = data.get("results") if isinstance(data, Mapping) else None
        if isinstance(results, list):
            found[node.path] = results
            entry["results"] = len(results)
            if node.operation == "listOrgSites" and site is None and results and isinstance(results[0], Mapping):
                site = results[0].get("id") if isinstance(results[0].get("id"), str) else None
        problems = mismatches(node_manifest(node)["output_schema"], data)
        entry |= {"status": "mismatch" if problems else "ok", "bytes": len(json.dumps(data))}
        if problems:
            entry["mismatches"] = problems
    summary = {s: sum(1 for o in operations if o["status"] == s) for s in ("ok", "mismatch", "error", "skipped")}
    return {
        "cloud": cloud,
        "org_id": org_id,
        "duration_s": round(time.monotonic() - started, 1),
        "summary": summary,
        "operations": operations,
    }


async def _run(args: argparse.Namespace, token: str) -> dict[str, Any]:
    from dewpoint.core.egress.guard import Guard, SystemResolver  # noqa: PLC0415 - the live run's only
    from dewpoint.core.egress.http import GuardedHttp  # noqa: PLC0415

    async def no_entries(tenant_id: uuid.UUID) -> list[Any]:
        return []  # Mist's hosts are public: the guard needs no allowlist entry

    guarded = GuardedHttp(Guard(resolver=SystemResolver(), allowlist=no_entries), uuid.uuid4())
    try:
        return await probe(
            ReadOnlyHttp(guarded, f"https://{MIST_CLOUDS[args.cloud]}", token), args.cloud, args.org,
            site=args.site, rate=args.rate,
        )  # fmt: skip
    finally:
        await guarded.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="The read-only Mist smoke probe (see the module's documentation).")
    parser.add_argument("--cloud", required=True, choices=sorted(MIST_CLOUDS))
    parser.add_argument("--org", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--site", default=None, help="the site to read; the org's first otherwise")
    parser.add_argument("--rate", type=float, default=2.0, help="operations a second, at most")
    args = parser.parse_args()
    token = Path(args.token_file).expanduser().read_text().strip()
    if not token:
        sys.exit("the token file is empty")
    report = asyncio.run(_run(args, token))
    out = Path(args.report).expanduser()
    out.write_text(json.dumps(report, indent=1, sort_keys=True))
    out.chmod(0o600)
    print(json.dumps({"summary": report["summary"], "duration_s": report["duration_s"], "report": str(out)}))


if __name__ == "__main__":
    main()
