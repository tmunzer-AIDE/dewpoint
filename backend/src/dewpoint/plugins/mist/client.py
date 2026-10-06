# SPDX-License-Identifier: Apache-2.0
"""A thin Mist client on a connection's HTTP (plugins-3 D1, D14, D16). The runtime applies the token, keeps the
connection's origin and charges its quota scopes; this client builds paths, reads answers and pages:

- a path's org is always the connection's, and every other placeholder takes a value checked to be one path segment
  of unreserved characters, then encoded, so no value can move the request (`..`, `/`, `?`);
- a site is checked to belong to the connection's org before a node acts on it (one GET per client);
- each status maps to a fixed error, never quoting Mist's answer: 400, 401, 403 and 404 are fatal, 5xx retryable
  (the runtime makes it `outcome_unknown` for an ambiguous node that sent), anything else fatal;
- lists follow `X-Page-*` headers, searches the body's `next`, which must stay on the connection's host and the
  search's own path; both stop at the node's page cap."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from dewpoint.plugins.mist.connection import MIST_CLOUDS
from dewpoint.sdk import Connection, FatalError, RetryableError

ACCEPT = {"Accept": "application/json"}
SEGMENT = re.compile(r"^[A-Za-z0-9_.~-]+$")  # one path segment of unreserved characters (RFC 3986)
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class BadRequest(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.bad_request", "Mist refused the request as written.")


class Unauthorized(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.unauthorized", "Mist refused the connection's token.")


class Forbidden(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.forbidden", "The connection's token may not do this.")


class NotFound(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.not_found", "Mist found no such object.")


class UnexpectedStatus(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.unexpected_status", "Mist answered with a status this node doesn't expect.")


class ServerError(RetryableError):
    def __init__(self) -> None:
        super().__init__("mist.server_error", "Mist failed to answer.")


class InvalidAnswer(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.invalid_answer", "Mist's answer isn't in the form this node reads.")


class InvalidPathValue(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.invalid_path_value", "A value of the request's path isn't a plain identifier.")


class InvalidQueryValue(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.invalid_query_value", "A query value must be text, a number or a boolean.")


class SiteOutsideOrg(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.site_outside_org", "The site isn't in the connection's org.")


class InvalidNext(FatalError):
    def __init__(self) -> None:
        super().__init__("mist.invalid_next", "Mist's next page isn't on the search's own path.")


@dataclass(frozen=True)
class Answer:
    status: int
    body: Any
    headers: Mapping[str, str]


@dataclass(frozen=True)
class Listed:
    results: list[Any]
    total: int | None
    truncated: bool


def _query(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    out: dict[str, Any] = {}
    for name, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[name] = "true" if value else "false"
        elif isinstance(value, str | int | float):
            out[name] = value
        else:
            raise InvalidQueryValue()
    return out


def _int(value: str | None) -> int | None:
    return int(value) if value is not None and value.isascii() and value.isdigit() and len(value) <= 12 else None


class MistClient:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self.org_id = str(connection.config.get("org_id", ""))
        self.host = MIST_CLOUDS.get(str(connection.config.get("cloud", "")))
        self._sites: set[str] = set()

    def path(self, template: str, values: Mapping[str, Any]) -> str:
        """`template` filled: `{org_id}` with the connection's org, every other placeholder with its checked value."""

        def fill(match: re.Match[str]) -> str:
            name = match.group(1)
            value = self.org_id if name == "org_id" else values.get(name)
            if not isinstance(value, str) or not SEGMENT.match(value) or value in (".", ".."):
                raise InvalidPathValue()
            return quote(value, safe="")

        return PLACEHOLDER.sub(fill, template)

    async def call(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> Answer:
        """One request; its answer, or the fixed error its status maps to."""
        params = _query(query)
        sent = await self._connection.http.request(method, path, headers=ACCEPT, params=params, json=body)
        status = sent.status_code
        if 200 <= status < 300:
            try:
                value = json.loads(sent.content) if sent.content.strip() else None
            except ValueError:
                raise InvalidAnswer() from None
            return Answer(status, value, {name.lower(): v for name, v in sent.headers})
        if status == 400:
            raise BadRequest()
        if status == 401:
            raise Unauthorized()
        if status == 403:
            raise Forbidden()
        if status == 404:
            raise NotFound()
        if 500 <= status < 600:
            raise ServerError()
        raise UnexpectedStatus()

    async def check_site(self, site_id: str) -> None:
        """The site belongs to the connection's org (D14): one GET a site per client, the answer's `org_id` exactly
        the connection's."""
        if site_id in self._sites:
            return
        found = await self.call("GET", self.path("/api/v1/sites/{site_id}", {"site_id": site_id}))
        if not isinstance(found.body, Mapping) or found.body.get("org_id") != self.org_id:
            raise SiteOutsideOrg()
        self._sites.add(site_id)

    async def list_pages(self, path: str, query: Mapping[str, Any] | None, *, max_pages: int) -> Listed:
        """A list's pages by their `X-Page-*` headers, at most `max_pages`: until the headers say the last page came,
        or a page is short. A full page without headers may have more (`truncated`)."""
        results: list[Any] = []
        total: int | None = None
        page = 1
        while True:
            found = await self.call("GET", path, query={**(query or {}), "page": page})
            if not isinstance(found.body, list):
                raise InvalidAnswer()
            results.extend(found.body)
            limit = _int(found.headers.get("x-page-limit"))
            at = _int(found.headers.get("x-page-page"))
            total = _int(found.headers.get("x-page-total"))
            asked = (query or {}).get("limit")
            if limit is not None and at is not None and total is not None:
                more = limit * at < total
            else:
                more = isinstance(asked, int) and not isinstance(asked, bool) and len(found.body) >= asked > 0
            if not more:
                return Listed(results, total, False)
            if page >= max_pages:
                return Listed(results, total, True)
            page += 1

    def _next(self, value: Any, path: str) -> str:
        """The next page's URL, once it's on the connection's host and the search's own path."""
        if not isinstance(value, str):
            raise InvalidNext()
        parts = urlsplit(value)
        if parts.fragment or parts.path != path:
            raise InvalidNext()
        if parts.scheme or parts.netloc:
            if parts.scheme != "https" or self.host is None or parts.netloc != self.host:
                raise InvalidNext()
        return value

    async def search_pages(
        self, path: str, query: Mapping[str, Any] | None, *, max_pages: int
    ) -> tuple[dict[str, Any], bool]:
        """A search's pages by the body's `next`, at most `max_pages`: the first page's answer with every page's
        `results`, without `next`; and whether a next page remained."""
        found = await self.call("GET", path, query=query)
        if not isinstance(found.body, dict) or not isinstance(found.body.get("results", []), list):
            raise InvalidAnswer()
        first = dict(found.body)
        results = list(first.get("results", []))
        pages, following = 1, first.pop("next", None)
        while following is not None:
            url = self._next(following, path)
            if pages >= max_pages:
                return {**first, "results": results}, True
            found = await self.call("GET", url)
            if not isinstance(found.body, dict) or not isinstance(found.body.get("results", []), list):
                raise InvalidAnswer()
            results.extend(found.body.get("results", []))
            pages, following = pages + 1, found.body.get("next")
        if "results" in first or results:
            first["results"] = results
        return first, False
