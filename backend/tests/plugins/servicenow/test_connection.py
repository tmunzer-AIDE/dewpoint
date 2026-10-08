# SPDX-License-Identifier: Apache-2.0
"""ServiceNow's connection type (plugins-3 3d-2, D22): the instance's https URL (its default domain or a custom URL),
a REST API key the runtime sends as `x-sn-apikey` (the plugin never holds it), one quota scope a key on an instance,
and a verify hook that reads one incident."""

from typing import Any

import pytest
from pydantic import ValidationError

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.servicenow import PLUGIN, SERVICENOW, TABLE
from dewpoint.sdk import TransportError
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, Reply

KEY = "k" * 40


def test_the_plugin_validates_and_the_key_is_a_header() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    m = SERVICENOW.manifest()
    assert m["auth"] == {"kind": "header", "header": "x-sn-apikey", "template": "{api_key}"}
    assert m["host"] == {"kind": "url_field", "field": "instance_url"}
    assert m["verify"] is True
    assert TABLE == "/api/now/v2/table/incident"  # v2: a query matching nothing answers 200 and []


@pytest.mark.parametrize("url", ["https://acme.service-now.com", "https://itsm.example.com"])
def test_an_instance_is_an_https_host(url: str) -> None:
    assert SERVICENOW.Config.model_validate({"instance_url": url}).model_dump() == {"instance_url": url}


@pytest.mark.parametrize(
    "url",
    [
        "http://acme.service-now.com",
        "https://acme.service-now.com/",
        "https://acme.service-now.com/api",
        "https://acme.service-now.com:8443",
        "https://ACME.service-now.com",
        "https://acme.service-now.com\n",
        "https://localhost",
        "https://user@acme.service-now.com",
        "https://10.0.0.1",
        "acme.service-now.com",
    ],
)
def test_an_instance_of_another_form_is_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        SERVICENOW.Config.model_validate({"instance_url": url})


@pytest.mark.parametrize("key", ["k" * 16, "k" * 1024, "Ab0!~" * 4])
def test_a_key_is_printable_ascii(key: str) -> None:
    assert SERVICENOW.Secret.model_validate({"api_key": key}).model_dump(mode="json")["api_key"] == "**********"


@pytest.mark.parametrize("key", ["k" * 15, "k" * 1025, "k" * 16 + " ", "k" * 16 + "\n", "k" * 16 + "é", ""])
def test_a_key_of_another_form_is_refused(key: str) -> None:
    with pytest.raises(ValidationError):
        SERVICENOW.Secret.model_validate({"api_key": key})


def test_one_scope_a_key_on_an_instance() -> None:
    [scope] = SERVICENOW.rate_scopes
    assert (scope.kind, tuple(scope.config), scope.secret, scope.capacity, scope.refill_per_s) == (
        "servicenow.key", ("instance_url",), "api_key", 10, 2)  # fmt: skip


async def verify(reply: Reply | Exception) -> tuple[Any, FakeHttp]:
    http = FakeHttp(lambda sent: reply)
    assert SERVICENOW.verify is not None
    connection = FakeConnection(http, config={"instance_url": "https://acme.service-now.com"}, type="servicenow")
    return await SERVICENOW.verify(None, connection), http  # type: ignore[arg-type]


async def test_verify_reads_one_incident() -> None:
    result, http = await verify(Reply(200, {"result": [{"sys_id": "a" * 32}]}))
    assert (result.ok, result.detail) == (True, "ok")
    [sent] = http.sent
    assert (sent.method, sent.url, sent.json) == ("GET", TABLE, None)
    assert sent.params == {"sysparm_limit": "1", "sysparm_fields": "sys_id"}


@pytest.mark.parametrize(
    ("reply", "detail"),
    [(Reply(401), "invalid_key"), (Reply(403), "no_table_access"), (Reply(404), "unexpected_status"),
     (Reply(500), "unexpected_status"), (TransportError(), "unreachable")],
)  # fmt: skip
async def test_verify_says_what_failed(reply: Reply | Exception, detail: str) -> None:
    result, _ = await verify(reply)
    assert (result.ok, result.detail) == (False, detail)
