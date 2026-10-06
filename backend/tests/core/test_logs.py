# SPDX-License-Identifier: Apache-2.0
"""Every process's log configuration: an exception is logged by its type and the innermost frames it was raised
through, never its text nor a frame's local variables. That holds for structlog's lines, for a standard library
logger's records (uvicorn's, SQLAlchemy's, Temporal's) and for an ASGI app's lifespan failure."""

import json
import logging
import logging.config
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import structlog
import uvicorn.config
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message

from dewpoint.core import logs
from tests.support.logs import records, rendered, stdlib_restored

SECRET = "s3cr3t-value-91be"


def _fails(depth: int) -> None:
    secret = SECRET
    if depth:
        _fails(depth - 1)
    raise KeyError(secret)


def _records(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def test_an_exception_is_logged_by_its_type_and_where_it_was_raised() -> None:
    with rendered() as lines:
        logs.configure()
        try:
            _fails(0)
        except KeyError as e:
            structlog.get_logger("t").error("failed", exc_info=e)
    assert SECRET not in "\n".join(lines())
    [record] = _records(lines())
    assert record["event"] == "failed" and record["level"] == "error"
    assert record["error_type"] == "KeyError" and "exception" not in record and "exc_info" not in record
    assert [frame.rsplit(":", 1)[0] for frame in record["where"]] == [
        "test_logs.py:test_an_exception_is_logged_by_its_type_and_where_it_was_raised",
        "test_logs.py:_fails",
    ]


def test_only_the_innermost_frames_are_named() -> None:
    with rendered() as lines:
        logs.configure()
        try:
            _fails(20)
        except KeyError as e:
            structlog.get_logger("t").error("failed", exc_info=e)
    assert SECRET not in "\n".join(lines())
    [record] = _records(lines())
    assert len(record["where"]) == logs.WHERE_FRAMES
    assert all(frame.startswith("test_logs.py:_fails:") for frame in record["where"])


def test_the_current_exception_is_named_and_none_adds_nothing() -> None:
    log = structlog.get_logger("t")
    with rendered() as lines:
        logs.configure()
        try:
            _fails(0)
        except KeyError:
            log.exception("caught")
            log.error("caught", exc_info=True)
        log.error("calm", exc_info=True)
    assert SECRET not in "\n".join(lines())
    caught, also, calm = _records(lines())
    assert caught["error_type"] == also["error_type"] == "KeyError"
    assert caught["where"][-1].startswith("test_logs.py:_fails:")
    assert not {"error_type", "where", "exception", "exc_info"} & calm.keys()


def _wrapped() -> None:
    try:
        _fails(0)
    except KeyError as e:
        raise RuntimeError(f"refused {SECRET}") from e


def test_a_library_records_exception_is_logged_by_its_type_and_where_never_its_text_nor_its_causes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with stdlib_restored():
        logs.configure()
        try:
            _wrapped()
        except RuntimeError as e:
            logging.getLogger("dewpoint.test.library").error("Exception in a library", exc_info=e)
    err = capsys.readouterr().err
    assert SECRET not in err
    [record] = records(err.splitlines())
    assert {k: record[k] for k in ("event", "logger", "level", "error_type")} == {
        "event": "Exception in a library",
        "logger": "dewpoint.test.library",
        "level": "error",
        "error_type": "RuntimeError",
    }
    assert "exception" not in record and "exc_info" not in record and "timestamp" in record
    assert [frame.rsplit(":", 1)[0] for frame in record["where"]] == [
        "test_logs.py:test_a_library_records_exception_is_logged_by_its_type_and_where_never_its_text_nor_its_causes",
        "test_logs.py:_wrapped",
    ]


@pytest.mark.parametrize(
    ("message", "args", "event"),
    [
        ("Error loading ASGI app factory: %s", (KeyError(SECRET),), "Error loading ASGI app factory: KeyError"),
        (KeyError(SECRET), (), "KeyError"),  # uvicorn's `logger.error(exc)`
        ("%(error)s in %(where)s", ({"error": KeyError(SECRET), "where": "a callback"},), "KeyError in a callback"),
        ("Uvicorn running on %s://%s:%d", ("http", "127.0.0.1", 8000), "Uvicorn running on http://127.0.0.1:8000"),
        ("%d workers", (f"not a number {SECRET}",), "%d workers"),
    ],
    ids=["an-argument", "the-message", "a-mapping-value", "other-values-kept", "arguments-that-dont-fit"],
)
def test_a_library_records_message_names_an_exception_by_its_type(
    capsys: pytest.CaptureFixture[str], message: object, args: tuple[object, ...], event: str
) -> None:
    with stdlib_restored():
        logging.getLogger().handlers.clear()  # as a process starts: pytest's own would fail on a bad record
        logs.configure()
        logging.getLogger("dewpoint.test.library").warning(message, *args)
    err = capsys.readouterr().err
    assert SECRET not in err
    [record] = records(err.splitlines())
    assert record["event"] == event


def test_a_record_is_written_once_however_often_the_process_is_configured(capsys: pytest.CaptureFixture[str]) -> None:
    with stdlib_restored():
        logs.configure()
        logs.configure()
        logging.getLogger("dewpoint.test.library").warning("once")
    assert [r["event"] for r in records(capsys.readouterr().err.splitlines())] == ["once"]


def test_uvicorns_own_logging_configuration_gives_way_to_the_process(capsys: pytest.CaptureFixture[str]) -> None:
    """The API's image runs `uvicorn ... --factory`: uvicorn applies its logging configuration, then calls the factory,
    which configures the process."""
    with stdlib_restored():
        logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
        logs.configure()
        try:
            _wrapped()
        except RuntimeError as e:
            logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=e)
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", "/x", "1.1", 500)
    out, err = capsys.readouterr()
    assert SECRET not in out + err and out == ""
    failure, access = records(err.splitlines())
    assert (failure["logger"], failure["error_type"]) == ("uvicorn.error", "RuntimeError")
    assert (access["logger"], access["event"]) == ("uvicorn.access", '127.0.0.1:50000 - "GET /x HTTP/1.1" 500')


LIFESPAN: dict[str, Any] = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": {}}
STARTUP_FAILED, SHUTDOWN_FAILED = {"type": "lifespan.startup.failed"}, {"type": "lifespan.shutdown.failed"}
STARTED, STOPPED = {"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}


def _quiet() -> None:
    pass


def _raising(error: BaseException) -> Callable[[], None]:
    def hook() -> None:
        raise error from KeyError(SECRET)

    return hook


async def _ok(request: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _app(startup: Callable[[], None] = _quiet, shutdown: Callable[[], None] = _quiet) -> ASGIApp:
    """A Starlette app, as both the API's and ingress's are, behind the middleware."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        startup()
        yield
        shutdown()

    return logs.LifespanFailures(Starlette(routes=[Route("/", _ok)], lifespan=lifespan))


async def _lifespan(app: ASGIApp) -> tuple[list[Message], BaseException | None]:
    """The app's lifespan as a server runs it, startup then shutdown: the messages the app sent, and what it raised."""
    events: list[Message] = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent: list[Message] = []

    async def receive() -> Message:
        return events.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    try:
        await app(dict(LIFESPAN), receive, send)
    except BaseException as e:  # what the app raised, compared by identity
        return sent, e
    return sent, None


class _Stop(BaseException):
    """Not an Exception: what a cancelled or interrupted lifespan raises is a BaseException."""


@pytest.mark.parametrize("kind", [RuntimeError, _Stop], ids=lambda kind: kind.__name__)
@pytest.mark.parametrize(
    ("phase", "sent"),
    [("startup", [STARTUP_FAILED]), ("shutdown", [STARTED, SHUTDOWN_FAILED])],
    ids=["startup", "shutdown"],
)
async def test_a_lifespan_failure_is_sent_without_its_text_logged_by_its_type_and_raised_unchanged(
    phase: str, sent: list[Message], kind: type[BaseException]
) -> None:
    """Starlette sends the server the formatted traceback as the failure's message, the exception's text and its
    cause's included, and uvicorn logs that message as it is."""
    error = kind(f"refused {SECRET}")
    with rendered() as lines:
        logs.configure()
        messages, raised = await _lifespan(_app(**{phase: _raising(error)}))
    assert messages == sent and raised is error
    assert SECRET not in "\n".join(lines())
    [record] = records(lines())
    assert {k: record[k] for k in ("event", "level", "phase", "error_type")} == {
        "event": "lifespan_failed",
        "level": "error",
        "phase": phase,
        "error_type": kind.__name__,
    }
    assert record["where"][-1].startswith("test_logs.py:hook:")


async def test_a_lifespan_that_succeeds_is_sent_unchanged_and_logs_nothing() -> None:
    with rendered() as lines:
        logs.configure()
        messages, raised = await _lifespan(_app())
    assert (messages, raised, lines()) == ([STARTED, STOPPED], None, [])


async def test_each_lifespan_reports_its_own_phase() -> None:
    """A failure is named by the phase of the lifespan it ends, whatever a lifespan before it reached."""
    startups = [_quiet, _raising(RuntimeError(f"refused {SECRET}"))]
    app = _app(startup=lambda: startups.pop(0)())
    with rendered() as lines:
        logs.configure()
        first, _ = await _lifespan(app)
        second, raised = await _lifespan(app)
    assert (first, second, type(raised)) == ([STARTED, STOPPED], [STARTUP_FAILED], RuntimeError)
    assert [r["phase"] for r in records(lines())] == ["startup"]


async def test_a_request_passes_through_the_lifespan_middleware() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/")
    assert (r.status_code, r.text) == (200, "ok")
