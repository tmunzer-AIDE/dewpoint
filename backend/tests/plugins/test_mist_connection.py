# SPDX-License-Identifier: Apache-2.0
"""The `mist` connection type, now declared by the mist plugin (plugins-3 D11), keeps the shape it had in `core`: the
same schemas, header and scope keys (the values below are `core`'s, from origin/main 15084df), and the same verify
answers, now read through the connection's read-only HTTP."""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError

from dewpoint.apps.plugin_loader import installed_plugins
from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.mist import PLUGIN
from dewpoint.plugins.mist.connection import MIST, MistConfig
from dewpoint.sdk import MaybeSent, NotSent, VerifyResult

ORG = uuid.UUID("6a1d6e2f-3c4b-4a5d-9e8f-0123456789ab")
CLOUDS = {
    "global_01": "api.mist.com",
    "global_02": "api.gc1.mist.com",
    "global_03": "api.ac2.mist.com",
    "global_04": "api.gc2.mist.com",
    "global_05": "api.gc4.mist.com",
    "emea_01": "api.eu.mist.com",
    "emea_02": "api.gc3.mist.com",
    "emea_03": "api.ac6.mist.com",
    "emea_04": "api.gc6.mist.com",
    "apac_01": "api.ac5.mist.com",
    "apac_02": "api.gc5.mist.com",
    "apac_03": "api.gc7.mist.com",
}
CONFIG_SCHEMA = {
    "additionalProperties": False,
    "properties": {
        "cloud": {"enum": list(CLOUDS), "title": "Cloud", "type": "string"},
        "org_id": {"format": "uuid", "title": "Org Id", "type": "string"},
    },
    "required": ["cloud", "org_id"],
    "title": "MistConfig",
    "type": "object",
}
SECRET_SCHEMA = {
    "additionalProperties": False,
    "properties": {
        "api_token": {"format": "password", "maxLength": 200, "minLength": 20, "title": "Api Token", "type": "string",
                      "writeOnly": True, "x-sensitive": True},
    },
    "required": ["api_token"],
    "title": "MistSecret",
    "type": "object",
}  # fmt: skip


def test_the_mist_type_keeps_its_shape() -> None:
    (m,) = PLUGIN.manifest()["connection_types"]
    assert m == {
        "key": "mist",
        "label": "Juniper Mist",
        "config_schema": CONFIG_SCHEMA,
        "secret_schema": SECRET_SCHEMA,
        "auth": {"kind": "header", "header": "Authorization", "template": "Token {api_token}"},
        "host": {"kind": "map", "field": "cloud", "hosts": CLOUDS},
        "rate_scopes": [
            {"kind": "mist.org", "config": ["cloud", "org_id"], "secret": None, "capacity": 50.0,
             "refill_per_s": 1.25},
            {"kind": "mist.token", "config": [], "secret": "api_token", "capacity": 50.0, "refill_per_s": 1.25},
        ],
        "verify": True,
    }  # fmt: skip


def test_the_mist_plugin_validates_and_is_installed() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert "mist" in {p.name for p in installed_plugins()}


def test_an_unknown_cloud_is_refused() -> None:
    with pytest.raises(ValidationError):
        MistConfig.model_validate({"cloud": "evil.example.com", "org_id": str(ORG)})


@dataclass
class _Answer:
    status_code: int
    body: Any = None
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def content(self) -> bytes:
        return json.dumps(self.body).encode() if self.body is not None else b"{"

    def header(self, name: str) -> str | None:
        return None

    def json(self) -> Any:
        return json.loads(self.content)


@dataclass
class _Http:
    answers: Mapping[str, _Answer | Exception]
    sent: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)

    async def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None, **_: Any) -> _Answer:
        self.sent.append((method, url, dict(headers or {})))
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class _Connection:
    http: _Http
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    type: str = "mist"
    config: Mapping[str, Any] = field(default_factory=lambda: {"cloud": "emea_01", "org_id": str(ORG)})


async def _verify(answers: Mapping[str, _Answer | Exception]) -> tuple[VerifyResult, _Http]:
    http = _Http(answers)
    assert MIST.verify is not None
    return await MIST.verify(None, _Connection(http)), http  # type: ignore[arg-type]


async def test_an_org_privilege_verifies_with_its_role() -> None:
    result, http = await _verify(
        {"/api/v1/self": _Answer(200, {"privileges": [{"scope": "org", "org_id": str(ORG), "role": "write"}]})}
    )
    assert result == VerifyResult(True, "ok", "write")
    assert http.sent == [("GET", "/api/v1/self", {"Accept": "application/json"})]


async def test_msp_access_is_confirmed_through_the_org() -> None:
    result, http = await _verify(
        {
            "/api/v1/self": _Answer(200, {"privileges": [{"scope": "msp", "role": "admin"}]}),
            f"/api/v1/orgs/{ORG}": _Answer(200, {"id": str(ORG)}),
        }
    )
    assert result == VerifyResult(True, "ok", "msp")
    assert [url for _, url, _ in http.sent] == ["/api/v1/self", f"/api/v1/orgs/{ORG}"]


@pytest.mark.parametrize(
    ("answers", "detail"),
    [
        ({"/api/v1/self": _Answer(401)}, "invalid_token"),
        ({"/api/v1/self": _Answer(403)}, "invalid_token"),
        ({"/api/v1/self": _Answer(500)}, "unexpected_status"),
        ({"/api/v1/self": _Answer(200, {"privileges": [{"scope": "org", "org_id": str(uuid.uuid4())}]})},
         "no_org_access"),
        ({"/api/v1/self": _Answer(200, ["not", "an", "object"])}, "no_org_access"),
        ({"/api/v1/self": _Answer(200, {"privileges": [{"scope": "msp"}]}), f"/api/v1/orgs/{ORG}": _Answer(404)},
         "no_org_access"),
        ({"/api/v1/self": _Answer(200)}, "unreachable"),
        ({"/api/v1/self": NotSent()}, "unreachable"),
        ({"/api/v1/self": MaybeSent()}, "unreachable"),
    ],
)  # fmt: skip
async def test_verify_answers(answers: Mapping[str, _Answer | Exception], detail: str) -> None:
    result, _ = await _verify(answers)
    assert not result.ok and result.detail == detail
