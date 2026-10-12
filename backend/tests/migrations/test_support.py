# SPDX-License-Identifier: Apache-2.0
"""The test helpers' own guarantees. No automatic garbage collection runs while a test's migration runs in this
process: under the parallel suite a long-lived worker's full collection took up to 2 s (a fresh process's, 0.07 s),
freezing every thread, the migrating one mid-step included, past D15's idle bound, and the server ended the step's
session (the disconnect, 2026-10-12). Alembic's command is a probe here: no database."""

import gc
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config

from tests.migrations import support

URL = "postgresql://test@localhost/nothing"


def _garbage() -> None:
    """Cyclic garbage far past every generation's threshold: with collection on, some run."""
    for _ in range(50_000):
        cycle: list[object] = []
        cycle.append(cycle)


@contextmanager
def _collections() -> Iterator[list[int]]:
    """The generation of each collection that starts meanwhile."""
    started: list[int] = []

    def seen(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            started.append(info["generation"])

    gc.callbacks.append(seen)
    try:
        yield started
    finally:
        gc.callbacks.remove(seen)


@pytest.mark.parametrize("helper", [support.upgrade, support.downgrade])
def test_no_automatic_collection_runs_while_a_migration_runs(
    helper: Callable[[str, str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    during: list[int] = []

    def migration(config: Config, target: str) -> None:
        with _collections() as started:
            _garbage()
        during.extend(started)

    monkeypatch.setattr(command, "upgrade", migration)
    monkeypatch.setattr(command, "downgrade", migration)
    with _collections() as outside:
        _garbage()
    assert outside  # the same garbage does start collections outside a migration

    helper(URL, "0052")

    assert during == []
    assert gc.isenabled()


def test_overlapping_migrations_keep_collection_paused_until_the_last_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    inside, release = threading.Event(), threading.Event()

    def held(config: Config, target: str) -> None:
        inside.set()
        release.wait(10)

    monkeypatch.setattr(command, "upgrade", held)
    first = threading.Thread(target=support.upgrade, args=(URL, "0052"))
    first.start()
    assert inside.wait(10)
    monkeypatch.setattr(command, "upgrade", lambda config, target: None)
    support.upgrade(URL, "0052")  # a second one, begun and ended inside the first
    paused = not gc.isenabled()
    release.set()
    first.join(10)

    assert paused
    assert gc.isenabled()


def test_a_process_with_collection_off_keeps_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command, "upgrade", lambda config, target: None)
    gc.disable()
    try:
        support.upgrade(URL, "0052")
        assert not gc.isenabled()
    finally:
        gc.enable()
