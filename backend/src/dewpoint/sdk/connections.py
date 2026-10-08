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
# A mail address the runtime and plugins accept (plugins-3 D20): an ASCII dot-atom local part of at most 64 characters
# at a domain of two or more labels, at most 254 characters in all (RFC 5321 §4.5.3.1, RFC 5322 §3.4.1); no quoted
# local part, no address literal, no SMTPUTF8, and no `=?` (a header would decode an RFC 2047 encoded word into names
# the envelope never had: the 3c-2 review's L3). Matched whole (`fullmatch`).
_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
MAIL_ADDRESS = re.compile(  # the 254 bounds the domain too
    rf"(?=[^@]{{1,64}}@)(?=.{{3,254}}\Z)(?![^@]*=\?){_ATEXT}+(?:\.{_ATEXT}+)*@{_LABEL}(?:\.{_LABEL})+"
)
SMTP_SECURITY = ("none", "starttls", "tls")
SMTP_KEYS = frozenset({"host", "port", "security", "sender", "username", "password"})


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
class SecretUrl:
    """The base URL is this secret field's value (plugins-3 D4's `url` auth: an incoming webhook's URL is its
    credential), matched whole by `pattern`, which starts with `https://`, wherever the secret is read; requests go to
    that URL exactly, with no path, query or header of the node's."""

    field: str
    pattern: str


def url_pattern_problem(pattern: Any) -> str | None:
    if not isinstance(pattern, str) or not pattern.startswith("https://"):
        return "secret URL pattern must start with https://"
    try:
        re.compile(pattern)
    except re.error:
        return "secret URL pattern doesn't compile"
    return None


def secret_pattern_problem(pattern: Any) -> str | None:
    """A scope's `secret_pattern`: one capture group, the part of the secret field the scope is keyed by."""
    try:
        groups = re.compile(pattern).groups if isinstance(pattern, str) else 0
    except re.error:
        groups = 0
    return None if groups == 1 else "a secret pattern needs exactly one group"


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
    secret_pattern: str | None = None  # keyed by this group of the secret field, not all of it (a Chat space, D9)


@dataclass(frozen=True)
class StreamEndpoint:
    """The websocket the runtime opens for a connection (plugins-3 D26): `wss://`, the host this config field's value
    maps to, then `path`; the connection's auth header sent with the handshake; and the quota scopes opening a stream
    charges, once a stream (a provider's limit on connections, not on messages). A node can't name another URL."""

    host: HostMap
    path: str
    rate_scopes: tuple[RateScope, ...] = ()


@dataclass(frozen=True)
class SmtpServer:
    """A connection type that sends mail (plugins-3 D4, D20): the runtime speaks SMTP to the host and port these config
    fields hold, secured as the security field says (`starttls`, `tls` or `none`), from the sender field's address,
    and signs in with the username config field and the password secret field when both are named and set. The plugin
    never holds the password, nor names another server or sender."""

    host: str
    port: str
    security: str
    sender: str
    username: str | None = None
    password: str | None = None


def smtp_problems(name: str, smtp: Any, config_schema: Any, secret_schema: Any) -> list[str]:
    """An SMTP server's declaration, as data (the SDK checks its own manifest, the catalog a received one): the host,
    port, security and sender are required config fields, the security field allows only the known modes, and a
    username config field and a password secret field are named together or not at all."""
    if not isinstance(smtp, Mapping) or set(smtp) != SMTP_KEYS:
        return [f"{name}: an smtp server needs exactly {sorted(SMTP_KEYS)}"]
    where = f"{name}: smtp"
    config = config_schema.get("properties", {}) if isinstance(config_schema, Mapping) else {}
    required = config_schema.get("required", []) if isinstance(config_schema, Mapping) else []
    secret = secret_schema.get("properties", {}) if isinstance(secret_schema, Mapping) else {}
    out: list[str] = []
    for role in ("host", "port", "security", "sender"):
        found = smtp[role]
        if not isinstance(found, str) or found not in config or found not in required:
            out.append(f"{where} {role} field {found!r} isn't a required config field")
    security = smtp["security"]
    prop = config.get(security) if isinstance(security, str) else None
    enum = prop.get("enum") if isinstance(prop, Mapping) else None
    known = isinstance(enum, list) and enum and all(isinstance(v, str) and v in SMTP_SECURITY for v in enum)
    if prop is not None and not known:
        out.append(f"{where} security field {security!r} may only allow 'none', 'starttls', 'tls'")
    username, password = smtp["username"], smtp["password"]
    if (username is None) != (password is None):
        out.append(f"{where} username and password are named together")
    if username is not None and (not isinstance(username, str) or username not in config):
        out.append(f"{where} username field {username!r} isn't a config field")
    if password is not None and (not isinstance(password, str) or password not in secret):
        out.append(f"{where} password field {password!r} isn't a secret field")
    return out


def smtp_manifest(server: SmtpServer) -> dict[str, Any]:
    return {"host": server.host, "port": server.port, "security": server.security, "sender": server.sender,
            "username": server.username, "password": server.password}  # fmt: skip


type Verify = Callable[[CallContext, Connection], Awaitable[VerifyResult]]


@dataclass(frozen=True)
class ConnectionType:
    key: str
    label: str
    Config: type[BaseModel]
    Secret: type[BaseModel]
    auth: HeaderAuth | None = None
    host: HostMap | UrlField | SecretUrl | None = None
    rate_scopes: tuple[RateScope, ...] = field(default=())
    verify: Verify | None = None
    stream: StreamEndpoint | None = None
    smtp: SmtpServer | None = None

    def problems(self) -> list[str]:
        name = f"connection type {self.key!r}"
        out: list[str] = []
        if not TYPE_KEY_RE.fullmatch(self.key):
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
        out += self._host_problems(name, config_fields, secret_fields)
        for scope in self.rate_scopes:
            out += self._scope_problems(name, scope, config_fields, secret_fields)
        out += self._stream_problems(name, config_fields, secret_fields)
        if self.smtp is not None:
            if self.host is not None or self.auth is not None or self.stream is not None:
                out.append(f"{name}: an SMTP type has no HTTP host, auth header or stream")
            out += smtp_problems(name, smtp_manifest(self.smtp), self.Config.model_json_schema(mode="validation"),
                                 self.Secret.model_json_schema(mode="validation"))  # fmt: skip
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
        secret_host = isinstance(self.host, SecretUrl) and self.host.field in self.Secret.model_fields
        if secret_host and self.host is not None and self.host.field not in secret:
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
        if not HEADER_RE.fullmatch(self.auth.header):
            out.append(f"{name}: auth header {self.auth.header!r} must be a header name")
        try:
            named = [n for _, n in template_parts(self.auth.template) if n is not None]
        except ValueError:
            return [*out, f"{name}: auth template may only name fields ({{field}}), with no format spec or conversion"]
        out += [f"{name}: auth template names {n!r}, not a secret field" for n in named if n not in secret_fields]
        if any(c in self.auth.template for c in "\r\n\0"):
            out.append(f"{name}: auth template must be one line")
        return out

    def _host_problems(self, name: str, config_fields: set[str], secret_fields: set[str]) -> list[str]:
        if self.host is None:
            return []
        if isinstance(self.host, SecretUrl):
            if self.host.field not in secret_fields:
                return [f"{name}: host field {self.host.field!r} isn't a secret field"]
            problem = url_pattern_problem(self.host.pattern)
            return [f"{name}: {problem}"] if problem else []
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
        if not SCOPE_KIND_RE.fullmatch(scope.kind) or not scope.kind.startswith(f"{self.key}."):
            out.append(f"{where} must start with '{self.key}.'")
        out += [f"{where} names {n!r}, not a config field" for n in scope.config if n not in config_fields]
        if scope.secret is not None and scope.secret not in secret_fields:
            out.append(f"{where} names {scope.secret!r}, not a secret field")
        if scope.secret_pattern is not None:
            if scope.secret is None:
                out.append(f"{where}: a secret pattern needs its secret field")
            problem = secret_pattern_problem(scope.secret_pattern)
            if problem:
                out.append(f"{where}: {problem}")
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
        elif isinstance(self.host, SecretUrl):
            host = {"kind": "secret_url", "field": self.host.field, "pattern": self.host.pattern}
        return (
            {
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
            }
            | ({"stream": self._stream_manifest()} if self.stream is not None else {})
            | ({"smtp": smtp_manifest(self.smtp)} if self.smtp is not None else {})
        )

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
    } | ({"secret_pattern": s.secret_pattern} if s.secret_pattern is not None else {})
