# SPDX-License-Identifier: Apache-2.0
"""D12's start check, end to end (2b-4b M4, the start-check slice): the upgrade barrier's revisions 17.2 and 17.3.1, the
configuration-B test design the owner accepted. The dispatcher, sending through its wrapped start call, against a
disposable D12 server whose authorizer asks the run's own Dewpoint database (`dewpoint-db`, the Compose project's
`start-check` profile) whether an eligible request permits each engine-queue start.

Opt-in (`DEWPOINT_PROOF=sc`), and run only when the owner authorizes it, after both images are built from this slice
(test_d12's build step), with `-x` and the run's cap. The run names both images (EXPLICIT_IMAGES): never the shared
`:local` ones, and the server's identity is checked against this tree before anything starts:

    DEWPOINT_M4_IMAGE=<server tag> DEWPOINT_M4_PROOF_CLIENT=<client tag> PYTHONPATH=src .venv/bin/python \\
        -m tests.proofs.runner --proof sc --out <runs directory> --cap 1200 --reserve 300 \\
        tests/proofs/d12/test_start_check.py

The runner (tests/proofs/runner.py) gives the run files of its own (its record, and the projects file the harness
names each project in before its first `up`: OUTER_CLEANUP), refuses to start while an earlier run's projects aren't
known removed, and, in a `finally`, stops pytest and removes every recorded project by its exact name, all within the
one cap.

Configuration B only (the owner's ruling on revision 17.2); configuration A, a persistent target and R4' are separate
decisions. Each case has a tenant and a request of its own, and the dispatcher reads D12's deny reasons as confirmed
(`start_check_reasons_confirmed`, set for this run only, B's first attempt aside):

- A -> C, one request: the check unavailable on a fresh request (its login `NOLOGIN`, its sessions ended); the login
  restored; the next attempt allowed and started, the request's recorded start request id on its started event.
- B: an earlier uncertain attempt (the conservative classification, then the reconciler's absence) stays unproven
  through a later "check unavailable". Nothing about Temporal is asserted.
- D: a cancel committed after the starting commit: the call is denied "not permitted", and the request ends cancelled.
- E: the check waits on a lock until its own deadline, the lock released before the dispatcher settles: as A.

Every wait is bounded (`BOUNDS`); reaching a bound fails the case, never retries. Each case's teardown ends its lock
session, restores the login, and checks the reconnect directly and through D12. A teardown that fails is recorded and
fails the run. A pass shows the denial reasons' end-to-end path and the start check's boundary on this disposable target
only: not configuration A, a persistent target or the owner's deployment, and not R4'."""

import asyncio
import base64
import contextlib
import os
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.common.v1 import WorkflowExecution, WorkflowType
from temporalio.api.enums.v1 import EventType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionRequest, StartWorkflowExecutionRequest
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.cancels import cancel_request
from dewpoint.apps.codec import data_converter
from dewpoint.apps.dispatcher import budget, dispatch, start_call
from dewpoint.apps.dispatcher.main import RETRY
from dewpoint.core import temporal_connect
from dewpoint.core.config import Settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.platform.service import DEVELOPMENT, record_environment
from dewpoint.engine.runtime.activities import ENGINE_QUEUE
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, TOKEN_GRAPH, admit, current
from tests.apps.test_workflow_ops import actor, create, publish
from tests.conftest import TEST_ROLES, _attest_inventory_cutover, _attest_tick_cutover
from tests.proofs import environment
from tests.proofs.conftest import gate, record
from tests.proofs.d12.test_d12 import BACKEND, NAMESPACE, Server, connect, server  # noqa: F401
from tests.support.registry import sync_test_plugins

pytestmark = [gate("sc"), pytest.mark.parametrize("server", [environment.JWT], indirect=True)]
START_CHECK = "on"  # the boundary this module proves: D12 asks the run's own database before each engine-queue start
EXPLICIT_IMAGES = True  # its run names both images (the owner's ruling, 2026-10-10): no `:local` fallback
OUTER_CLEANUP = True  # its outer runner removes a killed run's project by the name recorded before its first `up`
LOGIN = environment.START_CHECK_LOGIN
LOCKER = "dewpoint-sc-lock"  # the lock session's application name, so its teardown finds it whatever happened
DATABASE_S = 60.0  # dewpoint-db accepting connections after `up`
OUTAGE_S = 10.0  # the login NOLOGIN and pg_stat_activity showing no session of it
SETTLE_S = 30.0  # the dispatcher's settlement, once its call returned
DUE_S = 30.0  # a request's backoff waited out before its next attempt (5 s after one unavailable send)
CASE_S = 120.0
RECONNECT_S = 10.0  # each teardown check
BOUNDS = {  # revision 17.2's table, recorded with the run
    "outage_s": OUTAGE_S,
    "check": "the authorizer's deadline (compose.yaml: 2 s), well within the call's (test_support pins it)",
    "call_s": dispatch.START_DEADLINE.total_seconds(),
    "settlement_s": SETTLE_S,
    "due_s": DUE_S,
    "case_s": CASE_S,
    "reconnect_s": RECONNECT_S,
    "run": "the run request's cap, with -x",
}


# ---- the run's own Dewpoint database ---------------------------------------------------------------------------------


@dataclass
class Database:
    """`dewpoint-db`, from here on its assigned port: its superuser, the suite's logins (`t_<role>`, this run's
    password), and the authorizer's (`LOGIN`, the password its DSN carries)."""

    run: environment.Run
    password: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    def dsn(self, login: str = environment.DEWPOINT_DB) -> str:
        if login == environment.DEWPOINT_DB:
            password = (self.run.root / "dewpoint_db_password").read_text()
        elif login == LOGIN:
            password = (self.run.root / "start_check_password").read_text()
        else:
            password = self.password
        port = environment.assigned_port(self.run, "dewpoint-db", 5432)
        return f"postgresql://{login}:{password}@127.0.0.1:{port}/{environment.DEWPOINT_DB}"

    def url(self, login: str = environment.DEWPOINT_DB) -> str:
        return self.dsn(login).replace("postgresql://", "postgresql+asyncpg://", 1)


async def _accepting(db: Database) -> None:
    until = time.monotonic() + DATABASE_S
    while True:
        try:
            await (await asyncpg.connect(db.dsn(), timeout=5)).close()
            return
        except Exception as e:  # noqa: BLE001 - not up yet
            if time.monotonic() > until:
                pytest.fail(f"dewpoint-db didn't accept a connection within {DATABASE_S} s ({type(e).__name__})")
            await asyncio.sleep(1)


async def _logins(db: Database) -> None:
    """The suite's logins, each a member of its group role only, and the authorizer's, of `dewpoint_start_check` only:
    in this run's database, nowhere else."""
    c = await asyncpg.connect(db.dsn(), timeout=10)
    try:
        for role in TEST_ROLES:
            await c.execute(f"CREATE ROLE t_{role} LOGIN PASSWORD '{db.password}' IN ROLE {role}")
        authz = (db.run.root / "start_check_password").read_text()
        await c.execute(f"CREATE ROLE {LOGIN} LOGIN PASSWORD '{authz}' IN ROLE dewpoint_start_check")
    finally:
        await c.close()


async def _deployment(db: Database) -> None:
    """A development deployment on the proof's namespace, with the test plugins: what each case's workflow needs."""
    owner, admin = make_engine(db.url()), make_engine(db.url("t_dewpoint_admin"))
    try:
        async with make_sessionmaker(owner)() as s, s.begin():
            await record_environment(s, environment=DEVELOPMENT, namespace=NAMESPACE)
        await sync_test_plugins(make_sessionmaker(admin))
    finally:
        await owner.dispose()
        await admin.dispose()


def _named(url: str) -> str:
    """The database a url names: what migration 0053 expects (DEWPOINT_EXPECTED_DATABASE)."""
    return url.rsplit("/", 1)[1].split("?", 1)[0]


@pytest.fixture(scope="module")
def database(server: Server) -> Database:  # noqa: F811
    """The run's `dewpoint-db` (its profile is up with the server), migrated to head as the suite's own is, with its
    logins. Nothing outside the run's project is touched."""
    db = Database(server.run)
    asyncio.run(_accepting(db))
    log = server.run.root.parent / "migrate.log"
    with log.open("w") as out:  # its words stay in the run's directory: a connection error can name the database
        done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, stdout=out,
                              stderr=subprocess.STDOUT, env={**os.environ, "DEWPOINT_DATABASE_URL": db.url(),
                                                             "DEWPOINT_EXPECTED_DATABASE": _named(db.url())},
                              timeout=300, check=False)  # fmt: skip
    if done.returncode != 0:
        pytest.fail(f"migrating the run's database failed ({done.returncode}); see migrate.log")
    _attest_tick_cutover(db.url())
    _attest_inventory_cutover(db.url())
    asyncio.run(_logins(db))
    asyncio.run(_deployment(db))
    record({"environment": f"sc-{server.config}", "project": server.run.project, "bounds": BOUNDS})
    return db


@pytest.fixture(autouse=True)
def clean_db() -> None:
    """Not the suite's database (its autouse fixture, replaced here): this proof's is the run's own, each case on a
    tenant of its own, and it goes with the project."""


# ---- one case's processes --------------------------------------------------------------------------------------------


@dataclass
class Send:
    """One start the dispatcher's client sent: the request id it carried, and the error it met (None: accepted)."""

    request_id: str
    error: BaseException | None


@dataclass
class Stack:
    """A case's processes: the owner's, the API's and the dispatcher's sessions on the run's database, and the
    dispatcher's client as its main makes it, each start it sends recorded."""

    owner: async_sessionmaker[AsyncSession]
    api: async_sessionmaker[AsyncSession]
    dispatch: async_sessionmaker[AsyncSession]
    settings: Settings
    client: Client
    admin: Client  # the proof's admin, to read what Temporal holds
    sends: list[Send]


def _recorded(client: Client) -> list[Send]:
    """Each start the client sends, recorded around its start call (`start_call`'s wrapper, which sets the id)."""
    sends: list[Send] = []
    call = client.workflow_service.start_workflow_execution

    async def start_workflow_execution(req: Any, retry: bool = False, metadata: Any = None,
                                       timeout: Any = None) -> Any:  # noqa: ASYNC109  # fmt: skip
        try:
            answer = await call(req, retry=retry, metadata=metadata or {}, timeout=timeout)
        except BaseException as e:
            sends.append(Send(req.request_id, e))
            raise
        sends.append(Send(req.request_id, None))
        return answer

    client.workflow_service.start_workflow_execution = start_workflow_execution  # type: ignore[method-assign]
    return sends


@contextlib.asynccontextmanager
async def stack(server: Server, db: Database) -> AsyncIterator[Stack]:  # noqa: F811
    logins = (environment.DEWPOINT_DB, "t_dewpoint_api", "t_dewpoint_dispatch")
    engines = [make_engine(db.url(login)) for login in logins]
    try:
        settings = Settings(
            database_url=db.url("t_dewpoint_dispatch"), kek_b64=base64.b64encode(b"k" * 32).decode(),
            public_origin="https://testserver", rp_id="testserver", temporal_address=server.grpc,
            temporal_namespace=NAMESPACE, temporal_tls_ca=str(server.run.root / "pki" / "ca.pem"),
            temporal_tls_server_name=environment.SERVER_NAME, temporal_insecure_dev=False,
            temporal_bearer_token_file=str(server.token_file("dewpoint-proof")), start_check_reasons_confirmed=True,
        )  # fmt: skip
        client = await temporal_connect.connect(settings, DEVELOPMENT, data_converter=data_converter(KEYS),
                                                retry_config=RETRY)  # fmt: skip
        budget.instrument(client)  # as the dispatcher's main: timed, then its start call wrapped
        start_call.install(client)
        sends = _recorded(client)
        owner, api, dispatcher = (make_sessionmaker(e) for e in engines)
        yield Stack(owner, api, dispatcher, settings, client, await connect(server), sends)
    finally:
        for engine in engines:
            await engine.dispose()


@dataclass
class Hooks:
    """The dispatcher's two hooks for a case: what runs after a send's starting commit, and after its call returns (one
    each per send, in order; nothing once they run out); and when the last call returned."""

    committed: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    returned: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    returned_at: float | None = None

    async def after_commit(self, request_id: uuid.UUID) -> None:
        if self.committed:
            await self.committed.pop(0)()

    async def after_call(self, request_id: uuid.UUID) -> None:
        self.returned_at = time.monotonic()
        if self.returned:
            await self.returned.pop(0)()


@pytest.fixture
def hooks(monkeypatch: pytest.MonkeyPatch) -> Hooks:
    installed = Hooks()
    monkeypatch.setattr(dispatch, "_after_starting_commit", installed.after_commit)
    monkeypatch.setattr(dispatch, "_after_start_call", installed.after_call)
    return installed


async def _requested(on: Stack) -> Any:
    """A fresh tenant's workflow, published, and its one admitted request; the current build's workers ready."""
    ctx = await actor(on.owner)
    wf = await create(on.api, ctx, TOKEN_GRAPH)
    assert (await publish(on.api, ctx, wf, on.settings)).version is not None
    await current(on.dispatch)
    await workers(on.owner)
    return ctx, (await admit(on.api, ctx, wf)).request


async def _dispatched(on: Stack, hooks: Hooks, request: Any, settings: Settings | None = None) -> str | None:
    """One candidate begun, started and settled, as a dispatcher pass takes it (`dispatch._dispatch`): the call within
    its own deadline, then its settlement within SETTLE_S."""
    seal = dispatch.sealer(on.client.data_converter, on.client.namespace)
    hooks.returned_at = None
    async with asyncio.timeout(dispatch.START_DEADLINE.total_seconds() + SETTLE_S):
        happened = await dispatch._dispatch(on.dispatch, on.client, seal, KEYS, settings or on.settings, BUILD,
                                            request.tenant_id, request.id)  # fmt: skip
    assert hooks.returned_at is not None, f"no start was sent ({happened})"
    assert time.monotonic() - hooks.returned_at <= SETTLE_S, "settled past its bound"
    return happened


async def _row(on: Stack, request_id: uuid.UUID) -> dict[str, Any]:
    async with on.owner() as s:
        found = await s.execute(
            text("select status, reason, attempts, sends, unavailable_sends, start_request_id, ended_at, "
                 "next_attempt_at, extract(epoch from next_attempt_at - statement_timestamp()) as due_in "
                 "from run_requests where id = :i"),
            {"i": request_id},
        )  # fmt: skip
        return dict(found.mappings().one())


async def _evidence(on: Stack, request: Any) -> dict[str, Any] | None:
    async with on.owner() as s:
        found = await s.execute(
            text("select unproven, read_at, lost_at from execution_evidence where workflow_id = :w and run_id is null"),
            {"w": run_workflow_id(str(request.tenant_id), str(request.id))},
        )
        row = found.mappings().first()
        return dict(row) if row else None


async def _until_due(on: Stack, request_id: uuid.UUID) -> None:
    """Its backoff waited out, as the database's clock measures it: the clock `begin` reads."""
    wait = float((await _row(on, request_id))["due_in"])
    assert wait <= DUE_S, f"due in {wait:.1f} s, past its bound"
    await asyncio.sleep(max(wait, 0.0) + 0.2)


def _backed_off(state: dict[str, Any], before: datetime, after: datetime) -> bool:
    """Its next attempt one unavailable send's backoff after its settlement, by the dispatcher's clock, which sets it
    (Docker's VM clock can drift from this host's: never compared across the two)."""
    wait = dispatch.backoff(1)
    return bool(before + wait <= state["next_attempt_at"] <= after + wait)


def _denied(send: Send) -> str | None:
    """The reason D12's denial carries in its details, read as the dispatcher reads it; None for anything else."""
    if isinstance(send.error, RPCError) and send.error.status == RPCStatusCode.PERMISSION_DENIED:
        return dispatch.deny_reason(send.error)
    return None


async def _held(on: Stack, workflow_id: str) -> bool:
    """Whether Temporal holds any execution under `workflow_id`."""
    try:
        await on.admin.workflow_service.describe_workflow_execution(
            DescribeWorkflowExecutionRequest(namespace=NAMESPACE, execution=WorkflowExecution(workflow_id=workflow_id))
        )
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    return True


def _bounded(scenario: Callable[[], Awaitable[None]]) -> None:
    async def case() -> None:
        async with asyncio.timeout(CASE_S):
            await scenario()

    asyncio.run(case())


# ---- what a case does to the authorizer's access, and the teardown that undoes it ----------------------------------


@dataclass
class Levers:
    """The outage and the lock, as the run database's superuser."""

    db: Database
    lock: Any = None  # the lock session, while held

    async def cut(self) -> None:
        """The outage in place: the authorizer's login NOLOGIN, and its sessions ended until none is left."""
        c = await asyncpg.connect(self.db.dsn(), timeout=10)
        try:
            await c.execute(f"ALTER ROLE {LOGIN} NOLOGIN")
            async with asyncio.timeout(OUTAGE_S):
                while await c.fetchval("select count(*) from pg_stat_activity where usename = $1", LOGIN):
                    await c.execute("select pg_terminate_backend(pid) from pg_stat_activity where usename = $1", LOGIN)
                    await asyncio.sleep(0.2)
        finally:
            await c.close()

    async def restore(self) -> None:
        c = await asyncpg.connect(self.db.dsn(), timeout=10)
        try:
            await c.execute(f"ALTER ROLE {LOGIN} LOGIN")
        finally:
            await c.close()

    async def take_lock(self) -> None:
        """What the start check reads, locked by a separate session until `release_lock`."""
        self.lock = await asyncpg.connect(self.db.dsn(), timeout=10, server_settings={"application_name": LOCKER})
        await self.lock.execute("BEGIN")
        await self.lock.execute("LOCK TABLE run_requests IN ACCESS EXCLUSIVE MODE")

    async def release_lock(self) -> None:
        """The lock session ended: its transaction, and its lock, with it."""
        lock, self.lock = self.lock, None
        assert lock is not None, "no lock was held when the call returned"
        await lock.close()


async def _end_lock_sessions(c: Any) -> None:
    async with asyncio.timeout(RECONNECT_S):
        while await c.fetchval("select count(*) from pg_stat_activity where application_name = $1", LOCKER):
            await c.execute("select pg_terminate_backend(pid) from pg_stat_activity where application_name = $1",
                            LOCKER)  # fmt: skip
            await asyncio.sleep(0.2)


async def _restored(server: Server, db: Database) -> None:  # noqa: F811
    """Revision 17.2's teardown, in order: any lock the case holds ended; the login restored; the reconnect checked
    directly (a synthetic root that matches no request is refused) and through D12 (a start for it is denied
    `start-not-permitted`, not `start-check-unavailable`: the authorizer reconnected, and its check runs again)."""
    tenant, run, rid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    workflow_id = run_workflow_id(str(tenant), str(run))
    c = await asyncpg.connect(db.dsn(), timeout=10)
    try:
        try:
            await _end_lock_sessions(c)
        finally:
            await c.execute(f"ALTER ROLE {LOGIN} LOGIN")
    finally:
        await c.close()
    async with asyncio.timeout(RECONNECT_S):
        authz = await asyncpg.connect(db.dsn(LOGIN), timeout=5)
        try:
            assert await authz.fetchval("select start_permitted($1, $2)", workflow_id, str(rid)) is False
        finally:
            await authz.close()
    request = StartWorkflowExecutionRequest(
        namespace=NAMESPACE, workflow_id=workflow_id, workflow_type=WorkflowType(name="RunGraph"),
        task_queue=TaskQueue(name=ENGINE_QUEUE), request_id=str(rid),
    )  # fmt: skip
    client = await connect(server, "dewpoint-proof")
    async with asyncio.timeout(RECONNECT_S):
        with pytest.raises(RPCError) as denied:
            await client.workflow_service.start_workflow_execution(request, retry=False)
    assert denied.value.status == RPCStatusCode.PERMISSION_DENIED
    assert dispatch.deny_reason(denied.value) == dispatch.NOT_PERMITTED, "the authorizer didn't reconnect"


@pytest.fixture
def levers(server: Server, database: Database) -> Iterator[Levers]:  # noqa: F811
    """A case's levers; whatever the case did, its teardown restores the authorizer's access and checks it reconnects.
    A failure here fails the teardown, which the proof's record keeps."""
    try:
        yield Levers(database)
    finally:
        asyncio.run(_restored(server, database))


# ---- the cases ------------------------------------------------------------------------------------------------------


def test_sc_a_to_c_check_unavailable_on_a_fresh_request_then_a_fresh_check_starts_it(
    server: Server,  # noqa: F811
    database: Database,
    levers: Levers,
    hooks: Hooks,
) -> None:
    async def scenario() -> None:
        async with stack(server, database) as on:
            _, request = await _requested(on)
            workflow_id = run_workflow_id(str(request.tenant_id), str(request.id))
            assert (await _row(on, request.id))["sends"] == 0
            hooks.committed.append(levers.cut)  # A: the outage, once the intent is committed
            try:
                before = datetime.now(UTC)
                happened = await _dispatched(on, hooks, request)
                after, state = datetime.now(UTC), await _row(on, request.id)
                [send] = on.sends
                record({"environment": f"sc-{server.config}", "case": "A", "classified": happened,
                        "reason": _denied(send), "sends": state["sends"]})  # fmt: skip
                assert _denied(send) == dispatch.CHECK_UNAVAILABLE, send.error
                assert send.request_id == str(state["start_request_id"])
                assert happened == "check_unavailable"
                assert (state["status"], state["attempts"], state["sends"], state["unavailable_sends"]) == (
                    "queued", 0, 1, 1,
                )  # fmt: skip
                assert state["ended_at"] is None and _backed_off(state, before, after)
                assert not await _held(on, workflow_id)
            finally:
                await levers.restore()  # the login restored within the scenario (the teardown restores it again)
            await _until_due(on, request.id)
            happened = await _dispatched(on, hooks, request)
            state = await _row(on, request.id)
            [_, send] = on.sends
            execution = WorkflowExecution(workflow_id=workflow_id)
            described = await on.admin.workflow_service.describe_workflow_execution(
                DescribeWorkflowExecutionRequest(namespace=NAMESPACE, execution=execution)
            )
            info = described.workflow_extended_info.request_id_infos.get(str(state["start_request_id"]))
            on_started = info is not None and info.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
            record({"environment": f"sc-{server.config}", "case": "C", "classified": happened, "sends": state["sends"],
                    "recorded_id_on_the_started_event": on_started})  # fmt: skip
            assert send.error is None and send.request_id == str(state["start_request_id"])
            assert happened == "started" and (state["status"], state["sends"]) == ("started", 2)
            assert on_started, info
            assert await dispatch.started_by(on.client, workflow_id, state["start_request_id"]) is not None

    _bounded(scenario)


def test_sc_b_an_earlier_uncertain_attempt_stays_unproven_through_check_unavailable(
    server: Server,  # noqa: F811
    database: Database,
    levers: Levers,
    hooks: Hooks,
) -> None:
    async def scenario() -> None:
        async with stack(server, database) as on:
            _, request = await _requested(on)
            hooks.committed.append(levers.cut)  # the outage from the first send on
            unconfirmed = on.settings.model_copy(update={"start_check_reasons_confirmed": False})
            assert await _dispatched(on, hooks, request, unconfirmed) == "uncertain"  # the conservative default
            # the reconciler, having seen it absent once: back in the queue, its attempt unproven (§7.6)
            ref = dispatch.Ref(request.id, request.tenant_id)
            assert await dispatch.settle(on.dispatch, ref, dispatch.Outcome("absent"), audited=True) == "absent"
            assert (await _evidence(on, request) or {}).get("unproven") is True
            happened = await _dispatched(on, hooks, request)
            state, evidence = await _row(on, request.id), await _evidence(on, request)
            reasons = [_denied(sent) for sent in on.sends]
            record({"environment": f"sc-{server.config}", "case": "B", "classified": happened, "reasons": reasons,
                    "unproven": evidence is not None and evidence["unproven"]})  # fmt: skip
            assert reasons == [dispatch.CHECK_UNAVAILABLE] * 2
            assert happened == "check_unavailable"
            # the earlier attempt stays unproven, and stays for the evidence cadence to observe; the start unresolved
            assert evidence == {"unproven": True, "read_at": None, "lost_at": None}
            assert (state["status"], state["sends"], state["unavailable_sends"], state["ended_at"]) == (
                "queued", 2, 1, None,
            )  # fmt: skip

    _bounded(scenario)


def test_sc_d_a_cancel_committed_after_the_intent_is_denied_not_permitted_and_ends_cancelled(
    server: Server,  # noqa: F811
    database: Database,
    levers: Levers,
    hooks: Hooks,
) -> None:
    async def scenario() -> None:
        async with stack(server, database) as on:
            ctx, request = await _requested(on)
            workflow_id = run_workflow_id(str(request.tenant_id), str(request.id))
            answered: list[str] = []

            async def cancel() -> None:  # the API's cancel, committed between the intent and the call
                async with on.api() as s, s.begin():
                    answered.append(await cancel_request(s, tenant_id=ctx.tenant_id, request_id=request.id,
                                                         actor_id=ctx.user.id))  # fmt: skip

            hooks.committed.append(cancel)
            happened = await _dispatched(on, hooks, request)
            state = await _row(on, request.id)
            [send] = on.sends
            record({"environment": f"sc-{server.config}", "case": "D", "classified": happened,
                    "reason": _denied(send), "status": state["status"]})  # fmt: skip
            assert answered == ["requested"]  # it was starting: recorded for the dispatcher
            assert _denied(send) == dispatch.NOT_PERMITTED, send.error
            assert happened == "cancelled"
            assert state["status"] == "cancelled" and state["ended_at"] is not None
            assert not await _held(on, workflow_id)

    _bounded(scenario)


def test_sc_e_a_lock_the_check_waits_on_is_check_unavailable_released_before_settling(
    server: Server,  # noqa: F811
    database: Database,
    levers: Levers,
    hooks: Hooks,
) -> None:
    async def scenario() -> None:
        async with stack(server, database) as on:
            _, request = await _requested(on)
            workflow_id = run_workflow_id(str(request.tenant_id), str(request.id))
            began: list[float] = []

            async def lock() -> None:
                await levers.take_lock()
                began.append(time.monotonic())

            hooks.committed.append(lock)
            hooks.returned.append(levers.release_lock)  # before the dispatcher settles: its writes would wait on it
            before = datetime.now(UTC)
            happened = await _dispatched(on, hooks, request)
            after, state = datetime.now(UTC), await _row(on, request.id)
            [send] = on.sends
            record({"environment": f"sc-{server.config}", "case": "E", "classified": happened,
                    "reason": _denied(send), "call_s": round((hooks.returned_at or 0) - began[0], 2)})  # fmt: skip
            assert _denied(send) == dispatch.CHECK_UNAVAILABLE, send.error
            assert happened == "check_unavailable"
            assert (state["status"], state["attempts"], state["sends"], state["unavailable_sends"]) == (
                "queued", 0, 1, 1,
            )  # fmt: skip
            assert state["ended_at"] is None and _backed_off(state, before, after)
            assert not await _held(on, workflow_id)

    _bounded(scenario)
