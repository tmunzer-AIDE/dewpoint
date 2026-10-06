# SPDX-License-Identifier: Apache-2.0
"""Connection types as synced manifests declare them (plugins-3 D11). The API never runs plugin code: it validates a
connection's config and secret against the declared JSON Schemas, lists the types and computes each quota scope from
this data alone; the worker computes base URLs, credentials and scope keys with the same functions from its own
plugins' manifests, so the two always agree."""

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.plugins import PluginManifest
from dewpoint.core.ratelimit.buckets import Scope
from dewpoint.sdk.connections import fill

_FORMATS = FormatChecker(formats=())


@_FORMATS.checks("uuid", raises=ValueError)
def _canonical_uuid(value: object) -> bool:
    """Only the canonical form: a scope key and a lookup made from it must match whoever wrote the value."""
    return not isinstance(value, str) or str(uuid.UUID(value)) == value


class InvalidValueError(ValueError):
    """A config or secret the type's schema refuses. It names fields, never values."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__(f"invalid fields: {', '.join(fields)}")
        self.fields = fields


def _fields(schema: Mapping[str, Any], value: Any) -> list[str]:
    props = schema.get("properties", {})
    found: set[str] = set()
    for error in Draft202012Validator(schema, format_checker=_FORMATS).iter_errors(value):
        if error.path:
            found.add(str(error.path[0]))
        elif error.validator == "required" and isinstance(error.instance, dict):
            found.update(str(r) for r in error.validator_value if r not in error.instance)
        elif error.validator == "additionalProperties" and isinstance(error.instance, dict):
            found.update(str(k) for k in error.instance if k not in props)
        else:
            found.add("")
    return sorted(found)


def declaration_hash(m: Mapping[str, Any]) -> str:
    """The identity of a type's declaration: a worker serves a call through a connection only when its own declaration
    of the type is the synced one (the 3a-2 review's finding 8)."""
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class DeclaredType:
    plugin: str
    key: str
    label: str
    config_schema: Mapping[str, Any]
    secret_schema: Mapping[str, Any]
    auth: Mapping[str, Any] | None
    host: Mapping[str, Any] | None
    rate_scopes: tuple[Mapping[str, Any], ...]
    verify: bool
    hash: str = ""

    @classmethod
    def from_manifest(cls, plugin: str, m: Mapping[str, Any]) -> "DeclaredType":
        return cls(
            plugin=plugin,
            key=m["key"],
            label=m["label"],
            config_schema=m["config_schema"],
            secret_schema=m["secret_schema"],
            auth=m.get("auth"),
            host=m.get("host"),
            rate_scopes=tuple(m.get("rate_scopes", ())),
            verify=bool(m.get("verify")),
            hash=declaration_hash(m),
        )

    def _checked(self, schema: Mapping[str, Any], value: Any) -> dict[str, Any]:
        fields = _fields(schema, value)
        if fields:
            raise InvalidValueError(fields)
        return dict(value)

    def config(self, value: Any) -> dict[str, Any]:
        """The config as written, once the schema accepts it."""
        return self._checked(self.config_schema, value)

    def secret(self, value: Any) -> dict[str, Any]:
        """The secret as written, once the schema accepts it."""
        return self._checked(self.secret_schema, value)

    def base_url(self, config: Mapping[str, Any]) -> str | None:
        if self.host is None:
            return None
        value = config.get(self.host["field"])
        if self.host["kind"] == "map":
            host = self.host["hosts"].get(value) if isinstance(value, str) else None
            return f"https://{host}" if host else None
        return value if isinstance(value, str) else None

    def credentials(self, secret: Mapping[str, Any]) -> dict[str, str]:
        """The header the runtime sends (plugins-3 D4); the plugin never sees it."""
        if self.auth is None:
            return {}
        try:
            return {self.auth["header"]: fill(self.auth["template"], secret)}
        except (KeyError, ValueError):
            raise InvalidValueError(["auth"]) from None

    def scopes(self, config: Mapping[str, Any], secret: Mapping[str, Any], mac: Callable[[str], str]) -> list[Scope]:
        """Each quota scope (plugins-3 D9): its kind, the named config values, then a MAC of the named secret field
        under the tenant's scope key, never the secret itself."""
        out: list[Scope] = []
        for s in self.rate_scopes:
            parts = [s["kind"], *(str(config[name]) for name in s["config"])]
            if s["secret"] is not None:
                parts.append(mac(str(secret[s["secret"]])))
            out.append(Scope(":".join(parts), float(s["capacity"]), float(s["refill_per_s"])))
        return out

    def listing(self) -> dict[str, object]:
        """What `GET /connection-types` shows; a host map on `cloud` is shown as `clouds`, as the web app reads it."""
        out: dict[str, object] = {
            "key": self.key,
            "label": self.label,
            "config_schema": self.config_schema,
            "secret_fields": list(self.secret_schema.get("properties", {})),
        }
        if self.host is not None and self.host["kind"] == "map" and self.host["field"] == "cloud":
            out["clouds"] = dict(self.host["hosts"])
        return out


async def declared_types(s: AsyncSession) -> dict[str, DeclaredType]:
    """Every connection type the synced manifests declare, by key. A type no plugin declares any more is unknown."""
    # Only the declarations, never the whole manifest (every node's schemas): the review's finding 13.
    declared = PluginManifest.manifest["connection_types"]
    rows = await s.execute(select(PluginManifest.name, declared).order_by(PluginManifest.name))
    out: dict[str, DeclaredType] = {}
    for name, kinds in rows.all():
        for m in kinds if isinstance(kinds, list) else []:
            out[m["key"]] = DeclaredType.from_manifest(name, m)
    return out
