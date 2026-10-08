# SPDX-License-Identifier: Apache-2.0
"""The Mist client (plugins-3 D1, D16, D14): requests through the connection's HTTP, which applies the token and keeps
the origin; path values checked and encoded, the org always the connection's, a site checked to be the org's; status
codes mapped to fixed errors; lists paged by `X-Page-*` headers, searches by the body's `next`, under a page cap."""

from typing import Any

import pytest

from dewpoint.plugins.mist import client as mist
from dewpoint.sdk import FatalError, RetryableError
from tests.plugins.mist.fakes import ORG, OTHER_ORG, SITE, FakeConnection, FakeHttp, Reply, Sent


def make(script: Any) -> tuple[mist.MistClient, FakeHttp]:
    http = FakeHttp(script)
    return mist.MistClient(FakeConnection(http)), http


def test_the_org_is_always_the_connections() -> None:
    client, _ = make({})
    assert client.path("/api/v1/orgs/{org_id}/wlans/{wlan_id}", {"wlan_id": SITE}) == f"/api/v1/orgs/{ORG}/wlans/{SITE}"
    assert client.path("/api/v1/orgs/{org_id}", {"org_id": OTHER_ORG}) == f"/api/v1/orgs/{ORG}"


@pytest.mark.parametrize("value", ["", ".", "..", "a/b", "a?b", "a#b", "a%2Fb", "a b", "é", "a\\b", "a\n", None, 1])
def test_a_path_value_that_could_change_the_path_is_refused_before_sending(value: Any) -> None:
    client, http = make({})
    with pytest.raises(mist.InvalidPathValue) as e:
        client.path("/api/v1/sites/{site_id}/devices/{device_id}", {"site_id": SITE, "device_id": value})
    assert (e.value.code, http.sent) == ("mist.invalid_path_value", [])


def test_a_placeholder_without_a_value_is_refused() -> None:
    client, _ = make({})
    with pytest.raises(mist.InvalidPathValue):
        client.path("/api/v1/sites/{site_id}", {})


async def test_a_call_sends_json_and_reads_json() -> None:
    client, http = make({("POST", f"/api/v1/orgs/{ORG}/wlans"): Reply(200, {"id": "w1"})})
    found = await client.call("POST", f"/api/v1/orgs/{ORG}/wlans", body={"ssid": "corp"})
    assert found.body == {"id": "w1"} and found.status == 200
    assert http.sent[0].json == {"ssid": "corp"} and http.sent[0].headers == {"Accept": "application/json"}


async def test_an_empty_answer_is_none() -> None:
    client, _ = make({("DELETE", f"/api/v1/orgs/{ORG}/wlans/w"): Reply(200)})
    assert (await client.call("DELETE", f"/api/v1/orgs/{ORG}/wlans/w")).body is None


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [
        (400, FatalError, "mist.bad_request"),
        (401, FatalError, "mist.unauthorized"),
        (403, FatalError, "mist.forbidden"),
        (404, FatalError, "mist.not_found"),
        (409, FatalError, "mist.unexpected_status"),
        (302, FatalError, "mist.unexpected_status"),
        (500, RetryableError, "mist.server_error"),
        (503, RetryableError, "mist.server_error"),
    ],
)
async def test_statuses_map_to_fixed_errors(status: int, error: type[Exception], code: str) -> None:
    client, _ = make({("GET", "/api/v1/x"): Reply(status, {"detail": "secret detail"})})
    with pytest.raises(error) as e:
        await client.call("GET", "/api/v1/x")
    assert e.value.code == code and "secret" not in e.value.message  # type: ignore[attr-defined]


async def test_an_answer_that_isnt_json_is_refused() -> None:
    client, _ = make({("GET", "/api/v1/x"): Reply(200, raw=b"<html>")})
    with pytest.raises(FatalError) as e:
        await client.call("GET", "/api/v1/x")
    assert e.value.code == "mist.invalid_answer"


async def test_query_values_are_scalars_and_none_is_left_out() -> None:
    client, http = make({("GET", "/api/v1/x"): Reply(200, {})})
    await client.call("GET", "/api/v1/x", query={"a": "b", "n": 3, "t": True, "f": False, "z": None, "r": 1.5})
    assert http.sent[0].params == {"a": "b", "n": 3, "t": "true", "f": "false", "r": 1.5}
    with pytest.raises(mist.InvalidQueryValue):
        await client.call("GET", "/api/v1/x", query={"l": ["a"]})
    assert len(http.sent) == 1


async def test_a_site_of_the_connections_org_passes_once() -> None:
    client, http = make({("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"id": SITE, "org_id": ORG})})
    await client.check_site(SITE)
    await client.check_site(SITE)
    assert [s.url for s in http.sent] == [f"/api/v1/sites/{SITE}"]


@pytest.mark.parametrize("answer", [{"id": SITE, "org_id": OTHER_ORG}, {"id": SITE}, [], {"org_id": ORG.upper()}])
async def test_a_site_of_another_org_is_refused(answer: Any) -> None:
    client, _ = make({("GET", f"/api/v1/sites/{SITE}"): Reply(200, answer)})
    with pytest.raises(FatalError) as e:
        await client.check_site(SITE)
    assert e.value.code == "mist.site_outside_org"


def pages(total: int, limit: int) -> Any:
    def script(sent: Sent) -> Reply:
        assert sent.params is not None
        page, size = int(sent.params["page"]), int(sent.params["limit"])
        items = [{"n": i} for i in range((page - 1) * size, min(page * size, total))]
        return Reply(200, items, {"X-Page-Limit": str(size), "X-Page-Page": str(page), "X-Page-Total": str(total)})

    return script


async def test_a_list_follows_its_page_headers_to_the_end() -> None:
    client, http = make(pages(5, 2))
    found = await client.list_pages("/api/v1/x", {"limit": 2}, max_pages=10)
    assert found == mist.Listed([{"n": i} for i in range(5)], total=5, truncated=False)
    assert [s.params for s in http.sent] == [{"limit": 2, "page": p} for p in (1, 2, 3)]


async def test_a_list_stops_at_its_page_cap() -> None:
    client, http = make(pages(5, 2))
    found = await client.list_pages("/api/v1/x", {"limit": 2}, max_pages=2)
    assert found == mist.Listed([{"n": i} for i in range(4)], total=5, truncated=True)
    assert len(http.sent) == 2


async def test_a_full_page_without_headers_may_have_more() -> None:
    client, _ = make({("GET", "/api/v1/x"): Reply(200, [{"n": 1}, {"n": 2}])})
    assert await client.list_pages("/api/v1/x", {"limit": 2}, max_pages=1) == mist.Listed(
        [{"n": 1}, {"n": 2}], total=None, truncated=True
    )


async def test_a_list_answer_that_isnt_an_array_is_refused() -> None:
    client, _ = make({("GET", "/api/v1/x"): Reply(200, {"results": []})})
    with pytest.raises(FatalError) as e:
        await client.list_pages("/api/v1/x", {}, max_pages=1)
    assert e.value.code == "mist.invalid_answer"


def searches(*bodies: dict[str, Any]) -> Any:
    queue = list(bodies)

    def script(sent: Sent) -> Reply:
        return Reply(200, queue.pop(0))

    return script


async def test_a_search_follows_next_on_its_own_path() -> None:
    path = f"/api/v1/orgs/{ORG}/alarms/search"
    client, http = make(
        searches(
            {"results": [1, 2], "total": 3, "limit": 2, "next": f"{path}?limit=2&search_after=x"},
            {"results": [3], "total": 3, "limit": 2},
        )
    )
    found = await client.search_pages(path, {"limit": 2, "duration": "1d"}, max_pages=5)
    assert found == ({"results": [1, 2, 3], "total": 3, "limit": 2}, False)
    assert [s.url for s in http.sent] == [path, f"{path}?limit=2&search_after=x"]
    assert http.sent[1].params is None


async def test_a_search_stops_at_its_page_cap() -> None:
    path = "/api/v1/x/search"
    client, _ = make(searches({"results": [1], "next": f"{path}?p=2"}, {"results": [2], "next": f"{path}?p=3"}))
    assert await client.search_pages(path, {}, max_pages=2) == ({"results": [1, 2]}, True)


@pytest.mark.parametrize(
    "next_url",
    [
        "/api/v1/self?x=1", "/api/v1/x/search/../../self", "/api/v1/x/searchy?x=1", "//evil.example/api/v1/x/search",
        "https://evil.example/api/v1/x/search?x", "/api/v1/x/search#frag", 3,
    ],
)  # fmt: skip
async def test_a_next_off_the_search_path_is_refused(next_url: Any) -> None:
    client, http = make(searches({"results": [1], "next": next_url}))
    with pytest.raises(FatalError) as e:
        await client.search_pages("/api/v1/x/search", {}, max_pages=3)
    assert e.value.code == "mist.invalid_next" and len(http.sent) == 1


async def test_an_absolute_next_on_the_same_path_goes_to_the_connection() -> None:
    path = "/api/v1/x/search"
    client, http = make(searches({"results": [1], "next": f"https://api.mist.com{path}?p=2"}, {"results": [2]}))
    assert await client.search_pages(path, {}, max_pages=3) == ({"results": [1, 2]}, False)
    assert http.sent[1].url == f"https://api.mist.com{path}?p=2"  # the connection's HTTP refuses another origin


async def test_a_full_default_page_without_headers_may_have_more() -> None:
    """The review's L3: without a `limit`, Mist answers its documented default of 100."""
    client, _ = make({("GET", "/api/v1/x"): Reply(200, [{}] * 100)})
    assert (await client.list_pages("/api/v1/x", {}, max_pages=1)).truncated


async def test_a_next_never_followed_isnt_judged() -> None:
    """The review's L8: at its cap, a search reports it was cut, whatever the next page's URL."""
    client, http = make(searches({"results": [1], "next": "/api/v1/elsewhere"}))
    assert await client.search_pages("/api/v1/x/search", {}, max_pages=1) == ({"results": [1]}, True)
    assert len(http.sent) == 1
