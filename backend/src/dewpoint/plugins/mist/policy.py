# SPDX-License-Identifier: Apache-2.0
"""The operation-policy map (plugins-3 D28): one generated file, the single source for every node that reaches Mist,
with an entry per operation of the vendored OAS: `allowed` (to the nodes it names, with its capability, scope class
and side effect, and the evidence for it), `held` or `denied` (with the reason). Every Mist node checks it at run
time; a curated node exists only for an allowed operation. The account and authentication routes D14 lists are
refused whatever the map says (`refused`)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from dewpoint.plugins.mist import oas

VERSION = 2  # 2: utility entries carry their review (3b-2)
MAP_FILE = Path(__file__).parent / "data" / "policy.json"
STATES = ("allowed", "held", "denied")
SCOPES = ("org", "site", "metadata")
SIDE_EFFECTS = ("none", "idempotent", "ambiguous")
# The success conditions a utility's node implements (D27): D28's documented REST completion and verified readback have
# no node yet, so a map naming them is refused.
CONTRACTS = ("bounded_collection", "stream_terminal_evidence", "acceptance_only")
DEVICE_TYPES = ("ap", "gateway", "switch")  # the OAS's `device_type`
# Always refused (D14): MSP, the token's own account, login and the other account or authentication routes, installer
# and invite routes, credential tests, and anything outside /api/v1; first segments after /api/v1, then any segment.
REFUSED_ROOTS = frozenset(
    {"msps", "self", "login", "logout", "register", "recover", "invite", "installer", "mobile", "utils"}
)
REFUSED_SEGMENTS = frozenset(
    {
        "admins", "apitokens", "invites", "sdkinvites", "marvisinvites", "ssos", "ssoroles", "cert", "crl",
        "ssl_proxy_cert", "link_accounts", "unlink_account", "mist_scep", "mist_nac_crls", "export_idtokens",
        "register_cmd", "request_ztp_password", "installer",
    }
)  # fmt: skip
# Approved constants and metadata outside an org or a site (D14).
METADATA = frozenset({"/api/v1/const/webhook_topics"})


class PolicyUnreadableError(Exception):
    """The map isn't one this build can trust: another description's, or malformed."""


def refused(path: str) -> bool:
    """Whether `path` (a template or a concrete path) is a route no node may reach, whatever the map says."""
    segments = path.split("/")
    if segments[:3] != ["", "api", "v1"] or len(segments) < 4:
        return True
    if any(s in ("", ".", "..") for s in segments[3:]):
        return True
    return segments[3] in REFUSED_ROOTS or any(s in REFUSED_SEGMENTS for s in segments[3:])


def scope_of(path: str) -> str | None:
    """The scope class of a path template (D14): under the connection's org, under a site, or approved metadata."""
    segments = path.split("/")
    if segments[:3] != ["", "api", "v1"] or len(segments) < 5:
        return None
    if segments[3:5] == ["orgs", "{org_id}"]:
        return "org"
    if segments[3:5] == ["sites", "{site_id}"]:
        return "site"
    return "metadata" if path in METADATA else None


@dataclass(frozen=True)
class UtilityReview:
    """A device utility's review (D27, D28): the success condition its node promises, whether it reads the stream, the
    device types it runs on, the body parameters it may send and their maxima (`max_duration_s` the node's own), and
    what repeating it does."""

    contract: str
    stream: bool
    device_types: tuple[str, ...]
    parameters: tuple[str, ...]
    bounds: Mapping[str, int]
    repeat: str


@dataclass(frozen=True)
class Entry:
    method: str
    path: str
    state: str
    nodes: tuple[str, ...] = ()
    capability: str | None = None
    scope: str | None = None
    side_effect: str | None = None
    evidence: str | None = None
    reason: str | None = None
    reads: tuple[str, ...] = ()  # the other operations its node may read first: a site check, a merge, a picker
    utility: UtilityReview | None = None


_ALLOWED_KEYS = frozenset(
    {"method", "path", "state", "nodes", "capability", "scope", "side_effect", "evidence", "reads"}
)
_OTHER_KEYS = frozenset({"method", "path", "state", "reason"})
_UTILITY_KEYS = frozenset({"contract", "stream", "device_types", "parameters", "bounds", "repeat"})


def _utility(op_id: str, raw: Any) -> UtilityReview:
    if (
        not isinstance(raw, Mapping)
        or set(raw) != _UTILITY_KEYS
        or raw["contract"] not in CONTRACTS
        or raw["stream"] is not (raw["contract"] != "acceptance_only")
        or not isinstance(raw["device_types"], list)
        or not raw["device_types"]
        or not all(t in DEVICE_TYPES for t in raw["device_types"])
        or not isinstance(raw["parameters"], list)
        or not all(isinstance(p, str) and p for p in raw["parameters"])
        or not isinstance(raw["bounds"], Mapping)
        or not all(isinstance(k, str) and type(v) is int and v > 0 for k, v in raw["bounds"].items())
        or not isinstance(raw["repeat"], str)
        or not raw["repeat"]
    ):
        raise PolicyUnreadableError(f"{op_id}: not a utility review")
    return UtilityReview(
        raw["contract"], raw["stream"], tuple(raw["device_types"]), tuple(raw["parameters"]), dict(raw["bounds"]),
        raw["repeat"],
    )  # fmt: skip


def _entry(op_id: str, raw: Any) -> Entry:
    if not isinstance(raw, Mapping) or raw.get("state") not in STATES:
        raise PolicyUnreadableError(f"{op_id}: not an entry")
    if raw["state"] == "allowed":
        nodes, reads = raw.get("nodes"), raw.get("reads")
        if (
            set(raw) not in (_ALLOWED_KEYS, _ALLOWED_KEYS | {"utility"})
            or not isinstance(nodes, list)
            or not nodes
            or not all(isinstance(n, str) for n in nodes)
            or not isinstance(reads, list)
            or not all(isinstance(r, str) for r in reads)
            or raw["scope"] not in SCOPES
            or raw["side_effect"] not in SIDE_EFFECTS
            or not all(isinstance(raw[k], str) and raw[k] for k in ("method", "path", "capability", "evidence"))
        ):
            raise PolicyUnreadableError(f"{op_id}: not an allowed entry")
        values = {k: v for k, v in raw.items() if k not in ("nodes", "reads", "utility")}
        utility = _utility(op_id, raw["utility"]) if "utility" in raw else None
        return Entry(**values, nodes=tuple(nodes), reads=tuple(reads), utility=utility)
    if set(raw) != _OTHER_KEYS or not all(isinstance(raw[k], str) and raw[k] for k in _OTHER_KEYS):
        raise PolicyUnreadableError(f"{op_id}: not a held or denied entry")
    return Entry(**raw)


@dataclass(frozen=True)
class PolicyMap:
    oas_sha256: str
    entries: Mapping[str, Entry] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data: Any) -> "PolicyMap":
        """The map in `data`, once it's this version's and was made from the vendored description."""
        if not isinstance(data, Mapping) or set(data) != {"version", "oas_sha256", "operations"}:
            raise PolicyUnreadableError("not a policy map")
        if data["version"] != VERSION or data["oas_sha256"] != oas.SHA256:
            raise PolicyUnreadableError("a map made for another description")
        ops = data["operations"]
        if not isinstance(ops, Mapping):
            raise PolicyUnreadableError("not a policy map")
        return cls(data["oas_sha256"], {op_id: _entry(op_id, raw) for op_id, raw in ops.items()})

    def allowed(self, operation: str, node: str) -> Entry | None:
        """The operation's entry when the map allows it to `node` and its route isn't always refused; else None."""
        entry = self.entries.get(operation)
        if entry is None or entry.state != "allowed" or node not in entry.nodes or refused(entry.path):
            return None
        return entry

    def read(self, operation: str, node: str, other: str) -> Entry | None:
        """`other`'s entry when `node` may read it before or for `operation` (a site check, a merge, a picker): the map
        allows `operation` to `node`, lists `other` among its reads, and allows `other`; else None. Checked before
        anything is sent (the owner's review of the 3b-1 checkpoint, O2)."""
        own = self.allowed(operation, node)
        found = self.entries.get(other)
        if own is None or other not in own.reads or found is None or found.state != "allowed" or refused(found.path):
            return None
        return found


@cache
def load() -> PolicyMap:
    import json  # noqa: PLC0415 - only when first read

    try:
        return PolicyMap.from_data(json.loads(MAP_FILE.read_text()))
    except (OSError, ValueError) as e:
        raise PolicyUnreadableError("the policy map can't be read") from e
