# SPDX-License-Identifier: Apache-2.0
"""The Mist device-utility probe (plugins-3 3b-2; each live run needs the owner's go): the diagnostic utilities a
device's type supports, run through the plugin's own nodes, client and stream reader, over the egress guard, against
devices of one test org the owner chose. Run by hand, never in CI; from `backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.mist_utilities list --cloud global_01 \
        --org <org id> --token-file ~/.config/dewpoint/mist-smoke.token
    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.mist_utilities run --cloud global_01 \
        --org <org id> --token-file ~/.config/dewpoint/mist-smoke.token --device <site id>:<device id> \
        --report <path>

`list` sends GETs only: the org's sites and inventory, printed as a table to choose from. `run` sends GETs, and a POST
only to a diagnostic utility (a ping, a traceroute to 8.8.8.8, an ARP, a show command) of a chosen device: its HTTP
refuses any other request before sending, so no disruptive utility can be sent. The token is read from a file and only
ever applied as a header. The report holds each run's outcome, its counts and the shapes the 3b-2 ledger left
unverified (whether a table came with text after it), never a line of output."""

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from dewpoint.plugins.mist import PLUGIN, stream
from dewpoint.plugins.mist.client import MistClient
from dewpoint.plugins.mist.connection import MIST_CLOUDS, MIST_STREAM_CLOUDS, MIST_STREAM_PATH
from dewpoint.plugins.mist.utilities import MistUtility
from dewpoint.sdk import InvalidRequest, NodeError, ReadOnly, SideEffect, TransportError
from tests.probes.mist_smoke import ProbeStep

PING_TARGET = "8.8.8.8"
BODIES: dict[str, dict[str, Any]] = {
    "mist.site_devices.ping": {"host": PING_TARGET, "count": 3},
    "mist.site_devices.traceroute": {"host": PING_TARGET},
}
NEEDS = {  # diagnostics whose required parameter names something of the org's: not guessed
    "mist.site_devices.service_ping": "needs_service",
    "mist.site_devices.show_dhcp_leases": "needs_network",
}
type Opener = Callable[[], Awaitable[Any]]


def diagnostics(device_type: str) -> list[type[MistUtility]]:
    """The diagnostic utilities (`mist.diagnose`, repeatable, streaming) a device of `device_type` supports."""
    return [
        n for n in PLUGIN.nodes
        if issubclass(n, MistUtility) and "mist.diagnose" in n.capabilities and n.side_effect == SideEffect.IDEMPOTENT
        and n.review.stream and device_type in n.review.device_types
    ]  # fmt: skip


def _filled(template: str, site_id: str, device_id: str) -> str:
    return template.replace("{site_id}", site_id).replace("{device_id}", device_id)


class ProbeHttp:
    """The probe's HTTP: a GET without a body, or a POST to a diagnostic utility of a chosen device, on the cloud's
    origin only, the token applied here and nowhere else; anything else is refused before sending. `inner` is the
    egress guard's client (a fake offline)."""

    def __init__(self, inner: Any, base: str, token: str, devices: Sequence[tuple[str, str]]) -> None:
        self._inner, self._base, self._token = inner, base.rstrip("/"), token
        self._posts = {
            _filled(n.path, site, device)
            for site, device in devices
            for kind in ("ap", "gateway", "switch")
            for n in diagnostics(kind)
        }

    def _target(self, url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        if (parts.scheme or parts.netloc) and f"{parts.scheme}://{parts.netloc}" != self._base:
            raise InvalidRequest()
        if not parts.path.startswith("/") or parts.fragment:
            raise InvalidRequest()
        return parts.path, (url if parts.scheme else self._base + url)

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
        path, target = self._target(url)
        if content is not None:
            raise ReadOnly()
        if method == "GET":
            if json is not None:
                raise ReadOnly()
        elif method != "POST" or path not in self._posts or "?" in url:
            raise ReadOnly()  # a POST only to a chosen device's diagnostic, never another utility nor request
        if any(name.lower() == "authorization" for name in headers or {}):
            raise InvalidRequest()
        sent = {**(headers or {}), "Authorization": f"Token {self._token}"}
        try:
            return await self._inner.request(method, target, headers=sent, params=params, json=json)
        except Exception as e:
            raise _mapped(e) from None


def _mapped(error: Exception) -> Exception:
    from dewpoint.apps.worker.network import CORE_ERRORS, mapped  # noqa: PLC0415 - the runtime's own mapping

    return mapped(error) if isinstance(error, CORE_ERRORS) else error


class ProbeSocket:
    """A guarded stream as a node holds it: the runtime's failures as the SDK names them."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def send(self, text: str, *, probe: bool = False) -> None:
        try:
            await self._inner.send(text)
        except Exception as e:
            raise _mapped(e) from None

    async def receive(self, timeout_s: float) -> str | None:
        try:
            text: str | None = await self._inner.receive(timeout_s)
        except Exception as e:
            raise _mapped(e) from None
        return text

    async def close(self) -> None:
        await self._inner.close()


@dataclass
class ProbeWs:
    opener: Opener

    async def connect(self) -> Any:
        return await self.opener()


@dataclass
class ProbeConnection:
    http: Any
    ws: ProbeWs
    config: Mapping[str, Any]
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "mist"


@dataclass
class Tables:
    """What the reader's terminal-evidence check saw: tables with `finished`, and those with text after them."""

    seen: int = 0
    trailing: int = 0


def _watched(tables: Tables) -> Callable[[str], bool]:
    original = stream._finished

    def watched(raw: str) -> bool:
        text = raw.lstrip()
        if text.startswith("{"):
            try:
                table, end = json.JSONDecoder().raw_decode(text)
            except (ValueError, RecursionError):
                table, end = None, 0
            if isinstance(table, dict) and "finished" in table:
                tables.seen += 1
                tables.trailing += bool(text[end:].strip())
        return original(raw)

    return watched


async def probe(
    http: Any,
    opener: Opener,
    cloud: str,
    org_id: str,
    devices: Sequence[tuple[str, str, str]],
    *,
    rate: float = 1.0,
    nodes: Sequence[str] | None = None,
    max_duration_s: int = 30,
) -> dict[str, Any]:
    """Each chosen device's diagnostics, run as a step would run them; the report (see the module)."""
    connection = ProbeConnection(http, ProbeWs(opener), {"cloud": cloud, "org_id": org_id})
    operations: list[dict[str, Any]] = []
    started = time.monotonic()
    original = stream._finished
    try:
        for index, (site_id, device_id, device_type) in enumerate(devices):
            for node in diagnostics(device_type):
                if nodes is not None and node.type not in nodes:
                    continue
                entry: dict[str, Any] = {"node": node.type, "device": index, "device_type": device_type}
                operations.append(entry)
                if node.type in NEEDS:
                    entry |= {"status": "skipped", "detail": NEEDS[node.type]}
                    continue
                body = BODIES.get(node.type)
                config = {"connection": str(connection.id), "site_id": site_id, "device_id": device_id,
                          "max_duration_s": max_duration_s, **({"body": body} if body is not None else {})}  # fmt: skip
                try:
                    value = node.Config.model_validate(config)
                except (ValidationError, ValueError):
                    entry |= {"status": "skipped", "detail": "config_refused"}
                    continue
                if rate:
                    await asyncio.sleep(1 / rate)
                tables = Tables()
                stream._finished = _watched(tables)  # type: ignore[assignment]
                began = time.monotonic()
                try:
                    out = (await node().run(ProbeStep(connection), value)).model_dump(mode="json")  # type: ignore[arg-type]
                    entry |= {
                        "status": "ok", "ended_by": out["ended_by"], "completion_known": out["completion_known"],
                        "received": out["received"], "lines": len(out["lines"]), "truncated": out["truncated"],
                    }  # fmt: skip
                except NodeError as e:
                    entry |= {"status": "error", "detail": e.code}
                except TransportError as e:
                    entry |= {"status": "error", "detail": type(e).code}
                except Exception as e:  # noqa: BLE001 - the probe reports and goes on
                    entry |= {"status": "error", "detail": type(e).__name__}
                finally:
                    stream._finished = original  # type: ignore[assignment]
                entry |= {"seconds": round(time.monotonic() - began, 1), "tables": tables.seen,
                          "trailing_after_table": tables.trailing}  # fmt: skip
    finally:
        stream._finished = original  # type: ignore[assignment]
    summary = {s: sum(1 for o in operations if o["status"] == s) for s in ("ok", "error", "skipped")}
    return {"cloud": cloud, "duration_s": round(time.monotonic() - started, 1), "summary": summary,
            "operations": operations}  # fmt: skip


async def inventory(http: Any, org_id: str) -> list[dict[str, Any]]:
    """The org's devices (GETs only): site, name, type, model, connected and ids, to choose from."""
    client = MistClient(ProbeConnection(http, ProbeWs(_no_stream), {"cloud": "", "org_id": org_id}))  # type: ignore[arg-type]
    sites = await client.call("GET", f"/api/v1/orgs/{org_id}/sites", query={"limit": 1000})
    listed = sites.body if isinstance(sites.body, list) else []
    names = {s.get("id"): s.get("name") for s in listed if isinstance(s, dict)}
    found = await client.call("GET", f"/api/v1/orgs/{org_id}/inventory", query={"limit": 1000})
    rows = found.body if isinstance(found.body, list) else []
    return [
        {"site": names.get(d.get("site_id"), "-"), "name": d.get("name") or "-", "type": d.get("type"),
         "model": d.get("model"), "connected": d.get("connected"), "site_id": d.get("site_id"),
         "device_id": d.get("id")}
        for d in rows if isinstance(d, dict) and d.get("site_id")
    ]  # fmt: skip


async def _no_stream() -> Any:
    raise ReadOnly()


async def _live(args: argparse.Namespace, token: str) -> Any:
    from dewpoint.core.egress.guard import Guard, SystemResolver  # noqa: PLC0415 - the live run's only
    from dewpoint.core.egress.http import GuardedHttp  # noqa: PLC0415
    from dewpoint.core.egress.ws import GuardedWebsocket  # noqa: PLC0415

    async def no_entries(tenant_id: uuid.UUID) -> list[Any]:
        return []  # Mist's hosts are public: the guard needs no allowlist entry

    guard, tenant = Guard(resolver=SystemResolver(), allowlist=no_entries), uuid.uuid4()
    guarded, sockets = GuardedHttp(guard, tenant), GuardedWebsocket(guard, tenant)
    base = f"https://{MIST_CLOUDS[args.cloud]}"
    chosen = [tuple(d.split(":", 1)) for d in args.device or []]
    http = ProbeHttp(guarded, base, token, chosen)  # type: ignore[arg-type]
    try:
        listed = await inventory(http, args.org)
        if args.command == "list":
            return listed
        types = {d["device_id"]: d["type"] for d in listed}
        devices = [(site, device, types.get(device, "")) for site, device in chosen]
        if any(not kind for _, _, kind in devices):
            sys.exit("a chosen device isn't in the org's inventory")
        url = f"wss://{MIST_STREAM_CLOUDS[args.cloud]}{MIST_STREAM_PATH}"

        async def opener() -> ProbeSocket:
            try:
                return ProbeSocket(await sockets.open(url, {"Authorization": f"Token {token}"}))
            except Exception as e:
                raise _mapped(e) from None

        return await probe(http, opener, args.cloud, args.org, devices, rate=args.rate,
                           max_duration_s=args.max_duration)  # fmt: skip
    finally:
        await sockets.aclose()
        await guarded.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="The Mist device-utility probe (see the module's documentation).")
    parser.add_argument("command", choices=("list", "run"))
    parser.add_argument("--cloud", required=True, choices=sorted(MIST_CLOUDS))
    parser.add_argument("--org", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--device", action="append", help="<site id>:<device id>, for `run`; repeat for several")
    parser.add_argument("--report", help="where `run` writes its report")
    parser.add_argument("--rate", type=float, default=1.0, help="utilities a second, at most")
    parser.add_argument("--max-duration", type=int, default=30, help="seconds a collection may take, at most")
    args = parser.parse_args()
    if args.command == "run" and (not args.device or not args.report):
        sys.exit("run needs --device and --report")
    token = Path(args.token_file).expanduser().read_text().strip()
    if not token:
        sys.exit("the token file is empty")
    found = asyncio.run(_live(args, token))
    if args.command == "list":
        for i, d in enumerate(found):
            print(f"{i:3} {d['site'][:24]:24} {d['name'][:28]:28} {d['type'] or '-':8} {d['model'] or '-':14} "
                  f"{'up' if d['connected'] else 'down':4} {d['site_id']}:{d['device_id']}")  # fmt: skip
        return
    out = Path(args.report).expanduser()
    out.write_text(json.dumps(found, indent=1, sort_keys=True))
    out.chmod(0o600)
    print(json.dumps({"summary": found["summary"], "duration_s": found["duration_s"], "report": str(out)}))


if __name__ == "__main__":
    main()
