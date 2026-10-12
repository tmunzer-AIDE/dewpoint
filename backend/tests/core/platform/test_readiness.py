# SPDX-License-Identifier: Apache-2.0
"""Production readiness's check of the ingress capacity (the owner's ruling on 2b-4b's M3 checkpoint 3): M6's enable
command and D14's ingress switch refuse while any of its three values is unset."""

from types import SimpleNamespace

from dewpoint.core.platform import readiness


def test_the_capacity_is_ready_only_whole() -> None:
    def platform(s: float | None, h: float | None, w: int | None) -> object:
        return SimpleNamespace(ingress_starts_per_s=s, ingress_headroom=h, ingress_queue_wait_s=w)

    assert readiness.ingress_capacity(platform(8.0, 0.5, 300)) == []
    assert readiness.ingress_capacity(platform(8.0, None, 300)) == ["headroom"]
    assert readiness.ingress_capacity(platform(None, None, None)) == ["starts_per_s", "headroom", "queue_wait_s"]
