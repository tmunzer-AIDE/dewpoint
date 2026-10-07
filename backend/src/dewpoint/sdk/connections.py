# SPDX-License-Identifier: Apache-2.0
"""Connection types declared by a plugin (plugins-3 D11). Everything but `verify()` is data, because the API, which
never runs plugin code, validates connections, lists the types and shows each quota scope's cooldown from the synced
manifest alone; the worker computes the same base URL, credentials and scope keys from the same declaration."""

import math
import re
import string
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, SecretStr

from dewpoint.sdk.calls import CallContext
from dewpoint.sdk.fields import SENSITIVE
from dewpoint.sdk.net import Connection

TYPE_KEY_RE = re.compile(r"^(?=.{1,64}$)[a-z][a-z0-9_]{0,40}(\.[a-z][a-z0-9_]{0,40})?$")  # `connections.type`
SCOPE_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
HEADER_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")  # an RFC 9110 token
HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
PATH_RE = re.compile(r"^(/[A-Za-z0-9_~-][A-Za-z0-9._~-]{0,63}){1,16}$")  # segments of unreserved characters, no dots


FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def template_parts(template: str) -> list[tuple[str, str | None]]:
    """An auth template as (literal text, field name or None) pairs. Only plain `{field}` placeholders: a format spec
    or a conversion (`{token:>9}`, `{token!r}`) raises ValueError, so filling a template never formats a secret (the
    3a-2 review's finding 3)."""
    out: list[tuple[str, str | None]] = []
    for literal, name, spec, conversion in string.Formatter().parse(template):
        if name is not None and (spec or conversion is not None):
            raise ValueError("an auth template may only name fields")
        out.append((literal, name))
    return out


def fill(template: str, values: Mapping[str, Any]) -> str:
    """The template with each named field's value substituted, never formatted."""
    return "".join(
        literal + (str(values[name]) if name is not None else "") for literal, name in template_parts(template)
    )


@dataclass(frozen=True)
class VerifyResult:
    """`detail` is a short code (`ok`, `invalid_token`, …, at most 40 characters); `privilege` what the credentials may
    do, when known (at most 40)."""

    ok: bool
    detail: str
    privilege: str | None = None


@dataclass(frozen=True)
class HeaderAuth:
    """Credentials the runtime sends as one header, `template` filled from the secret's fields (plugins-3 D4)."""

    header: str
    template: str


@dataclass(frozen=True)
class HostMap:
    """The base URL is `https://` and the host this config field's value maps to: fixed hosts only."""

    field: str
    hosts: Mapping[str, str]


@dataclass(frozen=True)
class UrlField:
    """The base URL is this config field's value: any host the guard allows (plugins-3 D7, D8)."""

    field: str


@dataclass(frozen=True)
class RateScope:
    """A provider quota scope a request through the connection charges (plugins-3 D9). Its key is `kind`, then each
    named config field's value, then, for `secret`, a MAC of that secret field under the tenant's scope key, never
    the secret itself, joined by `:`."""

    kind: str
    config: tuple[str, ...] = ()
    secret: str | None = None
    capacity: float = 50.0
    refill_per_s: float = 1.25


@dataclass(frozen=True)
class StreamEndpoint:
    """The websocket the runtime opens for a connection (plugins-3 D26): `wss://`, the host this config field's value
    maps to, then `path`; the connection's auth header sent with the handshake; and the quota scopes opening a stream
    charges, once a stream (a provider's limit on connections, not on messages). A node can't name another URL."""

    host: HostMap
    path: str
    rate_scopes: tuple[RateScope, ...] = ()


type Verify = Callable[[CallContext, Connection], Awaitable[VerifyResult]]


@dataclass(frozen=True)
class ConnectionType:
    key: str
    label: str
    Config: type[BaseModel]
    Secret: type[BaseModel]
    auth: HeaderAuth | None = None
    host: HostMap | UrlField | None = None
    rate_scopes: tuple[RateScope, ...] = field(default=())
    verify: Verify | None = None
    stream: StreamEndpoint | None = None

    def problems(self) -> list[str]:
        name = f"connection type {self.key!r}"
        out: list[str] = []
        if not TYPE_KEY_RE.match(self.key):
            out.append(f"{name}: key must be a lowercase identifier")
        if not isinstance(self.label, str) or not 0 < len(self.label) <= 100:
            out.append(f"{name}: label must be 1-100 characters")
        for label, model in (("config", self.Config), ("secret", self.Secret)):
            if model.model_config.get("extra") != "forbid":
                out.append(f"{name}: the {label} model must forbid extra fields")
        config_fields, secret_fields = set(self.Config.model_fields), set(self.Secret.model_fields)
        out += self._required_problems(name)
        for prop, info in self.Secret.model_fields.items():
            if info.annotation is not SecretStr:
                out.append(f"{name}: secret field {prop!r} must be a SecretStr")
        out += self._auth_problems(name, secret_fields)
        out += self._host_problems(name, config_fields)
        for scope in self.rate_scopes:
            out += self._scope_problems(name, scope, config_fields, secret_fields)
        out += self._stream_problems(name, config_fields, secret_fields)
        return out

    def _stream_problems(self, name: str, config_fields: set[str], secret_fields: set[str]) -> list[str]:
        if self.stream is None:
            return []
        where = f"{name}: stream"
        host = self.stream.host
        out: list[str] = []
        if host.field not in config_fields:
            out.append(f"{where} host field {host.field!r} isn't a config field")
        else:
            if not self.Config.model_fields[host.field].is_required():
                out.append(f"{where} host field {host.field!r} must be required")
            out += [f"{where} host {h!r} must be a host name" for h in host.hosts.values() if not HOST_RE.fullmatch(h)]
            prop = self.Config.model_json_schema(mode="validation").get("properties", {}).get(host.field, {})
            if sorted(map(str, prop.get("enum", []))) != sorted(host.hosts):
                out.append(f"{where} host field {host.field!r} must allow exactly the host map's keys")
        path = self.stream.path
        if not isinstance(path, str) or not PATH_RE.fullmatch(path):
            out.append(f"{where} path must be one or more /segments of unreserved characters")
        for scope in self.stream.rate_scopes:
            out += self._scope_problems(name, scope, config_fields, secret_fields)
            out += [f"{name}: rate scope {scope.kind!r} names {n!r}, which must be required" for n in scope.config
                    if n in self.Config.model_fields and not self.Config.model_fields[n].is_required()]  # fmt: skip
            if scope.secret in self.Secret.model_fields and not self.Secret.model_fields[scope.secret].is_required():
                out.append(f"{name}: rate scope {scope.kind!r} names {scope.secret!r}, which must be required")
        return out

    def _required_problems(self, name: str) -> list[str]:
        """Every field the host, the auth template or a rate scope reads is required: the API computes them from the
        stored config as written, the worker from the validated one, and a default would make the two differ."""
        config = {f for f, info in self.Config.model_fields.items() if info.is_required()}
        secret = {f for f, info in self.Secret.model_fields.items() if info.is_required()}
        out: list[str] = []
        if self.host is not None and self.host.field in self.Config.model_fields and self.host.field not in config:
            out.append(f"{name}: host field {self.host.field!r} must be required")
        if self.auth is not None:
            try:
                named = [n for _, n in template_parts(self.auth.template) if n is not None]
            except ValueError:
                named = []
            out += [f"{name}: auth template names {n!r}, which must be required" for n in named
                    if n in self.Secret.model_fields and n not in secret]  # fmt: skip
        for scope in self.rate_scopes:
            out += [f"{name}: rate scope {scope.kind!r} names {n!r}, which must be required" for n in scope.config
                    if n in self.Config.model_fields and n not in config]  # fmt: skip
            if scope.secret in self.Secret.model_fields and scope.secret not in secret:
                out.append(f"{name}: rate scope {scope.kind!r} names {scope.secret!r}, which must be required")
        return out

    def _auth_problems(self, name: str, secret_fields: set[str]) -> list[str]:
        if self.auth is None:
            return []
        out: list[str] = []
        if not HEADER_RE.match(self.auth.header):
            out.append(f"{name}: auth header {self.auth.header!r} must be a header name")
        try:
            named = [n for _, n in template_parts(self.auth.template) if n is not None]
        except ValueError:
            return [*out, f"{name}: auth template may only name fields ({{field}}), with no format spec or conversion"]
        out += [f"{name}: auth template names {n!r}, not a secret field" for n in named if n not in secret_fields]
        if any(c in self.auth.template for c in "\r\n\0"):
            out.append(f"{name}: auth template must be one line")
        return out

    def _host_problems(self, name: str, config_fields: set[str]) -> list[str]:
        if self.host is None:
            return []
        if self.host.field not in config_fields:
            return [f"{name}: host field {self.host.field!r} isn't a config field"]
        if isinstance(self.host, UrlField):
            return []
        out = [f"{name}: host {h!r} must be a host name" for h in self.host.hosts.values() if not HOST_RE.fullmatch(h)]
        prop = self.Config.model_json_schema(mode="validation").get("properties", {}).get(self.host.field, {})
        if sorted(map(str, prop.get("enum", []))) != sorted(self.host.hosts):
            out.append(f"{name}: host field {self.host.field!r} must allow exactly the host map's keys")
        return out

    def _scope_problems(
        self, name: str, scope: RateScope, config_fields: set[str], secret_fields: set[str]
    ) -> list[str]:
        where = f"{name}: rate scope {scope.kind!r}"
        out: list[str] = []
        if not SCOPE_KIND_RE.match(scope.kind) or not scope.kind.startswith(f"{self.key}."):
            out.append(f"{where} must start with '{self.key}.'")
        out += [f"{where} names {n!r}, not a config field" for n in scope.config if n not in config_fields]
        if scope.secret is not None and scope.secret not in secret_fields:
            out.append(f"{where} names {scope.secret!r}, not a secret field")
        budget = (scope.capacity, scope.refill_per_s)
        if not all(isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v > 0
                   for v in budget):  # fmt: skip
            out.append(f"{where} needs a positive capacity and refill")
        return out

    def manifest(self) -> dict[str, Any]:
        secret_schema = self.Secret.model_json_schema(mode="validation")
        secret_schema["properties"] = {
            prop: {**sub, SENSITIVE: True} for prop, sub in secret_schema.get("properties", {}).items()
        }
        host: dict[str, Any] | None = None
        if isinstance(self.host, HostMap):
            host = {"kind": "map", "field": self.host.field, "hosts": dict(self.host.hosts)}
        elif isinstance(self.host, UrlField):
            host = {"kind": "url_field", "field": self.host.field}
        return {
            "key": self.key,
            "label": self.label,
            "config_schema": self.Config.model_json_schema(mode="validation"),
            "secret_schema": secret_schema,
            "auth": (
                {"kind": "header", "header": self.auth.header, "template": self.auth.template}
                if self.auth is not None
                else None
            ),
            "host": host,
            "rate_scopes": [_scope_manifest(s) for s in self.rate_scopes],
            "verify": self.verify is not None,
        } | ({"stream": self._stream_manifest()} if self.stream is not None else {})

    def _stream_manifest(self) -> dict[str, Any]:
        assert self.stream is not None  # noqa: S101 - only when set
        return {
            "kind": "map",
            "field": self.stream.host.field,
            "hosts": dict(self.stream.host.hosts),
            "path": self.stream.path,
            "rate_scopes": [_scope_manifest(s) for s in self.stream.rate_scopes],
        }


def _scope_manifest(s: RateScope) -> dict[str, Any]:
    return {
        "kind": s.kind,
        "config": list(s.config),
        "secret": s.secret,
        "capacity": float(s.capacity),
        "refill_per_s": float(s.refill_per_s),
    }
