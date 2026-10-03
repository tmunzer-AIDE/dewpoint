# SPDX-License-Identifier: Apache-2.0
"""A run tree's secret index at the boundaries (engine 2b spec §3.7, the review's I3): its automaton is built once per
index version, off the event loop, and cached with it; a boundary reads the index again only when its version moved.
At the index's bounds a build takes about a second, so building it at every boundary, on the loop, stalled every
activity and workflow task of the worker."""

import asyncio
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.worker import claims
from dewpoint.core.claims.secret_index import Index
from dewpoint.engine import matcher as matcher_module
from tests.apps.worker.harness import TENANT, MemoryStore, run, workers
from tests.support.graphs import G, ref

SECRET = "hunter2-hunter2"


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    claims.SECRETS.clear()
    yield
    claims.SECRETS.clear()


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[tuple[frozenset[str], int]]:
    """Every automaton built: its strings, and the thread that built it."""
    out: list[tuple[frozenset[str], int]] = []
    original = matcher_module.Matcher.__init__

    def counting(self: Any, strings: Any, *args: Any, **kwargs: Any) -> None:
        strings = list(strings)
        out.append((frozenset(strings), threading.get_ident()))
        original(self, strings, *args, **kwargs)

    monkeypatch.setattr(matcher_module.Matcher, "__init__", counting)
    return out


async def test_an_automaton_is_built_once_per_index_version_off_the_event_loop(
    builds: list[tuple[frozenset[str], int]],
) -> None:
    store, root = MemoryStore(), str(uuid.uuid4())
    await store.remember(TENANT, root, [SECRET])
    first = await claims.secrets_of(store, TENANT, root)
    again = await claims.secrets_of(store, TENANT, root)
    assert again.matcher is first.matcher and first.matcher.found(f"a {SECRET} b") and len(builds) == 1
    assert builds[0][1] != threading.get_ident()  # a worker thread's, never the event loop's
    await store.remember(TENANT, root, ["s3cr3t-value"])
    moved = await claims.secrets_of(store, TENANT, root)
    assert (moved.index.version, len(builds)) == (first.index.version + 1, 2) and moved.matcher.found("s3cr3t-value")


async def test_concurrent_boundaries_share_one_build_and_an_older_one_never_replaces_a_newer(
    builds: list[tuple[frozenset[str], int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's review of I3: boundaries that missed the cache while a build ran each built the automaton for the
    same version, and whichever build ended last was cached, an older version included. Every boundary waiting for
    one version shares its one build, and the cache keeps the newest version a boundary has built."""
    release, built = threading.Event(), claims._built

    def slow(index: Index) -> claims.Secrets:  # a build at the index's bounds takes about a second
        release.wait(5)
        return built(index)

    monkeypatch.setattr(claims, "_built", slow)
    root = str(uuid.uuid4())
    older, newer = Index(1, (SECRET,)), Index(2, (SECRET, "s3cr3t-value"))
    waiting = [asyncio.create_task(claims.secrets_for(newer, TENANT, root)) for _ in range(5)]
    await asyncio.sleep(0.05)  # every boundary has missed the cache while the first build runs
    release.set()
    held = await asyncio.gather(*waiting)
    assert len(builds) == 1 and all(h is held[0] for h in held)
    stale = await claims.secrets_for(older, TENANT, root)  # a boundary that read the index just before it moved
    assert stale.index.version == 1 and claims.SECRETS[(TENANT, root)].index.version == 2


async def test_a_runs_boundaries_build_its_automaton_once_per_index_version(
    env: WorkflowEnvironment, builds: list[tuple[frozenset[str], int]]
) -> None:
    """Four steps and their projections all match against the index, which never moves after admission: its
    automaton is built once, in a worker thread. The only other build is admission's splitter matching the trigger's
    own secrets, once, before the run starts."""
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"token": {"type": "string", "x-sensitive": True}},
                         "required": ["token"], "additionalProperties": False},
        "outputs": {"last": ref("steps.d.output.value")},
    }  # fmt: skip
    for key, after in (("a", None), ("b", "a"), ("c", "b"), ("d", "c")):
        g.node(key, "testkit.echo@1", {"value": 1})
        if after:
            g.edge(after, key)
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"token": SECRET}, claimed=True)
    assert result.status == "succeeded", result.error
    loop = threading.get_ident()
    assert [t != loop for s, t in builds if SECRET in s] == [False, True]  # admission's, then the cached one
