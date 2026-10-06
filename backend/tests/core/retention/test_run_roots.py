# SPDX-License-Identifier: Apache-2.0
"""Every run records its tree's root (engine 2b spec §10.1: a run tree's data is due after its root ended): a root run
is its own, a sub-run its parent's, set by the database on insert whatever the writer gives, and never changed."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from tests.support.workflows import seed_workflow

RUN = (
    "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, parent_run_id{root}) "
    "values (:n, :t, :w, :v, 'live', 'running', :kind, :parent{given})"
)


async def _run(maker: Any, tree: dict[str, Any], parent: uuid.UUID | None = None, **given: Any) -> uuid.UUID:
    run = uuid.uuid4()
    sql = RUN.format(root=", root_run_id" if given else "", given=", :root" if given else "")
    async with maker() as s, s.begin():
        await tenant_scope(s, tree["t"])
        await s.execute(text(sql), {"n": run, "t": tree["t"], "w": tree["w"], "v": tree["v"], "parent": parent,
                                    "kind": "subflow" if parent else "run", **given})  # fmt: skip
    return run


async def _root(owner: Any, run: uuid.UUID) -> uuid.UUID:
    async with owner() as s:
        return (await s.execute(text("select root_run_id from runs where id = :r"), {"r": run})).scalar_one()


@pytest.fixture
async def tree(owner_sessionmaker) -> dict[str, Any]:
    t, w, v = await seed_workflow(owner_sessionmaker)
    return {"t": t, "w": w, "v": v}


async def test_a_root_run_is_its_own_root_and_a_sub_run_has_its_parents(tree, owner_sessionmaker,
                                                                        dispatch_sessionmaker,
                                                                        worker_sessionmaker) -> None:  # fmt: skip
    root = await _run(dispatch_sessionmaker, tree)  # the dispatcher writes a root run's row (§7.3)
    child = await _run(worker_sessionmaker, tree, root)  # a sub-run writes its own (§7.8)
    grandchild = await _run(worker_sessionmaker, tree, child)
    assert [await _root(owner_sessionmaker, r) for r in (root, child, grandchild)] == [root, root, root]


async def test_the_database_sets_the_root_whatever_the_writer_gives(tree, owner_sessionmaker,
                                                                    worker_sessionmaker) -> None:  # fmt: skip
    root = await _run(owner_sessionmaker, tree)
    other = await _run(owner_sessionmaker, tree)
    child = await _run(worker_sessionmaker, tree, root, root=other)
    assert await _root(owner_sessionmaker, child) == root


@pytest.mark.parametrize("column", ["root_run_id", "parent_run_id"])
async def test_a_runs_tree_never_changes(tree, owner_sessionmaker, worker_sessionmaker, column: str) -> None:
    """Neither a run's root nor its parent changes once written, not even by the worker, which updates runs."""
    root, other = await _run(owner_sessionmaker, tree), await _run(owner_sessionmaker, tree)
    child = await _run(worker_sessionmaker, tree, root)
    with pytest.raises(DBAPIError, match="a run's tree never changes"):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tree["t"])
            await s.execute(text(f"update runs set {column} = :o where id = :c"), {"o": other, "c": child})  # noqa: S608
    assert await _root(owner_sessionmaker, child) == root
