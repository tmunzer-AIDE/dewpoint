# SPDX-License-Identifier: Apache-2.0
"""What the worker's logs may hold (engine 2b spec §6.7, §12): text proven to be code, never a run's data. A plugin's
log line keeps only its own constants, booleans and null; a bug is logged by its type and place; Temporal's activity
records keep their fixed messages and drop every exception and quoted value."""

import logging
import types

import pytest
import structlog
from temporalio.exceptions import ApplicationError

from dewpoint.apps.worker import logs
from tests.support.plugins import testkit
from tests.support.raising import Declared, raises

KNOWN = logs.literals(testkit.__name__)
COMPUTED = "".join(["q7", "zx-", "issued"])  # in no code: built at run time, as a token an API issues
IDENT = COMPUTED.replace("-", "_")  # the same, shaped as a valid identifier


def test_a_plugins_literals_are_its_source_constants_keyword_names_included() -> None:
    assert {(str, "token_issued"), (str, "bearer"), (str, "detail"), (str, "kind")} <= KNOWN
    assert (str, COMPUTED) not in KNOWN


def test_only_booleans_null_and_the_plugins_own_constants_are_proven() -> None:
    assert logs.proven(True, KNOWN) and logs.proven(None, KNOWN) and logs.proven("bearer", KNOWN)
    assert not logs.proven(COMPUTED, KNOWN)
    assert not logs.proven(123456, KNOWN)  # a number can be a secret too: a PIN
    assert not logs.proven(["bearer"], KNOWN)  # a container: its parts aren't checked
    assert not logs.proven(1, frozenset({(bool, True)}))  # 1 isn't True


def test_a_line_keeps_what_the_plugin_wrote_and_withholds_what_it_computed() -> None:
    with structlog.testing.capture_logs() as seen:
        log = logs.StepLog(KNOWN, run_id="r")
        log.info("token_issued", kind="bearer", ok=True, detail=COMPUTED, token="bearer", **{COMPUTED: 1})
        log.warning(f"issued {COMPUTED}", kind="bearer")
    assert seen == [
        {"event": "token_issued", "kind": "bearer", "ok": True, "detail": "[redacted]", "token": "[redacted]",
         "fields_withheld": 1, "run_id": "r", "log_level": "info"},  # a secret-looking name: redacted even then
        {"event": "step_event_withheld", "kind": "bearer", "run_id": "r", "log_level": "warning"},
    ]  # fmt: skip


def test_a_bug_is_logged_by_its_type_and_place_and_its_text_only_when_a_constant() -> None:
    with pytest.raises(RuntimeError) as computed:
        raises(COMPUTED)
    fields = logs.bug(computed.value, KNOWN)
    assert fields["error_type"] == "RuntimeError" and "error" not in fields
    assert fields["where"][-1].startswith("raising.py:raises:")  # its module was compiled from source
    with pytest.raises(RuntimeError) as constant:
        raises("bearer")
    assert logs.bug(constant.value, KNOWN)["error"] == "bearer"


def test_a_class_name_is_shown_only_when_proven_to_be_code() -> None:
    assert logs.error_class(RuntimeError()) == "RuntimeError"  # a builtin
    assert logs.error_class(Declared()) == "Declared"  # its module's code declares it
    assert logs.error_class(type(IDENT, (Exception,), {})()) == logs.UNNAMED  # named at run time
    forged = type(IDENT, (Exception,), {"__module__": "builtins"})  # claiming to be a builtin
    assert logs.error_class(forged()) == logs.UNNAMED
    with pytest.raises(Exception) as dynamic:
        raise type(IDENT, (Exception,), {})(COMPUTED)
    assert IDENT not in str(logs.bug(dynamic.value, KNOWN)) and COMPUTED not in str(logs.bug(dynamic.value, KNOWN))


def test_a_frame_is_named_only_when_its_code_was_compiled_from_its_modules_source() -> None:
    renamed = types.FunctionType(raises.__code__.replace(co_name=IDENT), raises.__globals__)  # renamed at run time
    with pytest.raises(RuntimeError) as caught:
        renamed("x")
    where = logs.bug(caught.value, KNOWN)["where"]
    assert where[-1] == logs.UNNAMED_FRAME and IDENT not in str(where)
    assert where[0] == logs.UNNAMED_FRAME  # this test's own frame: pytest's loader gives no code to prove it


def test_a_frames_line_is_logged_only_when_its_compiled_function_has_it() -> None:
    with pytest.raises(RuntimeError) as caught:
        raises("x")
    real = caught.value.__traceback__
    assert real is not None and real.tb_next is not None
    frame = real.tb_next.tb_frame  # `raises`, compiled from its module's source
    forged = RuntimeError("x").with_traceback(types.TracebackType(None, frame, 0, 739_184))  # any integer
    assert logs.bug(forged, KNOWN)["where"] == ["raising.py:raises"]
    assert logs.bug(caught.value, KNOWN)["where"][-1] == f"raising.py:raises:{real.tb_next.tb_lineno}"


def test_temporals_activity_records_keep_their_fixed_messages_and_no_error_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logs.withhold_activity_errors()
    activity = logging.getLogger("temporalio.activity")
    caplog.set_level(logging.DEBUG)
    try:
        raise ApplicationError(f"failed holding {COMPUTED}", type="leaky_failed")
    except ApplicationError:
        activity.warning("Completing activity as failed ({'activity_type': 'x'})", exc_info=True)
    try:
        raise ApplicationError("failed", type=IDENT)  # a code shaped like a safe identifier, made at run time
    except ApplicationError:
        activity.warning("Completing activity as failed", exc_info=True)
    activity.warning(f"Completing activity as failed {COMPUTED}")  # a fixed start, a canary after it
    activity.warning(f"Completing as failure during heartbeat with error of type {ValueError}: {COMPUTED}")
    logging.getLogger("temporalio.worker._activity").debug("Recording heartbeat with details %s", [COMPUTED])
    logging.getLogger("temporalio.worker._activity").debug("Running activity %s (token %s)", COMPUTED, b"t")
    activity.debug("Starting activity")
    assert [r.getMessage() for r in caplog.records] == [
        "Completing activity as failed",  # its exact fixed text, nothing more: no code, whatever its shape
        "Completing activity as failed",
        "Completing activity as failed",
        "Activity record withheld",
        "Activity record withheld",
        "Running activity",
        "Starting activity",
    ]
    assert COMPUTED not in caplog.text and IDENT not in caplog.text and "leaky_failed" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_the_filter_is_installed_once() -> None:
    logs.withhold_activity_errors()
    logs.withhold_activity_errors()
    for name in ("temporalio.activity", "temporalio.worker._activity"):
        assert len([f for f in logging.getLogger(name).filters if isinstance(f, logging.Filter)]) == 1
