# SPDX-License-Identifier: Apache-2.0
"""What a Mist step's failure means, through the activity's own classification (the 3b-1 review's M1 and M2):

- the site check is a probe (a read before the node's effect), so a failure before the write leaves an ambiguous node
  retryable or plainly failed, never `outcome_unknown`; a probe that may have reached Mist and failed is retried;
- after the write was sent, an ambiguous node's failure is still `outcome_unknown`;
- a delete's retry that finds its site gone answers `already_absent`, as one finding the object gone does (D16)."""

import uuid
from typing import Any

from dewpoint.apps.worker import activities
from dewpoint.engine.runtime.activities import StepInput
from dewpoint.plugins.mist import PLUGIN
from dewpoint.sdk import MaybeSent, RateLimited
from tests.plugins.mist.fakes import ORG, SITE, FakeConnection, FakeHttp, Reply, Sent

DEVICE = "00000000-0000-0000-1000-5c5b35000001"


class Network:
    """An attempt's network as the activity sees it: a request it sent leaves it uncertain, a probe doesn't."""

    def __init__(self, script: Any) -> None:
        self.uncertain = False
        outer = self

        class Http(FakeHttp):
            async def request(self, *args: Any, **kwargs: Any) -> Any:
                try:
                    return await super().request(*args, **kwargs)
                finally:
                    if not kwargs.get("probe"):
                        outer.uncertain = True

        self.connection_ = FakeConnection(Http(script))

    async def connection(self, connection_id: uuid.UUID) -> FakeConnection:
        return self.connection_


async def step(type_: str, config: dict[str, Any], script: Any, attempt: int = 1) -> tuple[Any, list[Sent]]:
    network = Network(script)
    node = next(n for n in PLUGIN.nodes if n.type == type_)
    given = StepInput(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), "n", "", f"{type_}@1",
                      {"connection": str(network.connection_.id), **config}, attempt=attempt)  # fmt: skip
    try:
        out, outcome = await activities._call(node, given, node.Config.model_json_schema(), network)  # type: ignore[arg-type]
        found: Any = ("ok", outcome, out.model_dump(mode="json"))
    except activities._StepFailed as f:
        found = ("failed", f.code, f.retryable, f.outcome)
    return found, network.connection_.http.sent


def site(answer: Reply | BaseException) -> Any:
    def script(sent: Sent) -> Reply | BaseException:
        if sent.url == f"/api/v1/sites/{SITE}":
            assert sent.probe, "the site check is a probe"
            return answer
        return Reply(500, {})

    return script


RESTART = ("mist.site_devices.restart", {"site_id": SITE, "device_id": DEVICE})


async def test_a_site_check_that_fails_leaves_an_ambiguous_write_retryable() -> None:
    found, sent = await step(*RESTART, site(Reply(503, {})))
    assert found == ("failed", "mist.server_error", True, None) and len(sent) == 1


async def test_a_site_check_that_may_have_reached_mist_is_retried() -> None:
    for error in (RateLimited(), MaybeSent()):
        found, sent = await step(*RESTART, site(error))
        assert found == ("failed", "mist.site_check_failed", True, None) and len(sent) == 1


async def test_a_site_of_another_org_is_a_plain_failure() -> None:
    found, sent = await step(*RESTART, site(Reply(200, {"org_id": "x"})))
    assert found == ("failed", "mist.site_outside_org", False, None) and len(sent) == 1


async def test_once_the_write_was_sent_an_ambiguous_failure_is_unknown() -> None:
    found, sent = await step(*RESTART, site(Reply(200, {"org_id": ORG})))
    assert found[0] == "failed" and found[3] == "outcome_unknown" and len(sent) == 2


async def test_a_delete_retry_that_finds_its_site_gone_is_already_absent() -> None:
    gone = site(Reply(404, {}))
    assert (await step("mist.site.delete", {"site_id": SITE}, gone, attempt=2))[0] == (
        "ok", "applied", {"already_absent": True}
    )  # fmt: skip
    wlan = {"site_id": SITE, "wlan_id": DEVICE}
    assert (await step("mist.site_wlans.delete", wlan, gone, attempt=2))[0] == (
        "ok",
        "applied",
        {"already_absent": True},
    )
    assert (await step("mist.site.delete", {"site_id": SITE}, gone))[0] == ("failed", "mist.not_found", False, None)
