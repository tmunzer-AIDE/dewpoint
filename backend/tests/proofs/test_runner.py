# SPDX-License-Identifier: Apache-2.0
"""A proof's outer runner (tests/proofs/runner.py; the owner's reviews of the start-check run's runner), with fake
processes, a fake clock and a fake cleanup: no Docker, no pytest started. Each invocation keeps files of its own and
never removes another's; a run refuses to start while an earlier one's recorded projects aren't known removed;
SIGTERM and SIGINT are only noted, so neither cuts anything short; pytest is stopped, and every recorded project
removed, whatever stopping met; an interruption inside the cleanup leaves the record and an explicit failure; and the
whole run, cleanup included, stays within its cap."""

import builtins
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.proofs import runner

CAP, RESERVE = 1200.0, 300.0
PROJECT = "dewpoint-m4-0123456789ab"
WALL, RUNNER_PID = 1_000_000.0, 777


@pytest.fixture(autouse=True)
def _no_interruptions_noted() -> None:
    runner.INTERRUPTIONS.noted.clear()  # `main` clears them before it installs its handlers; `run` itself doesn't


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Signal:
    """An answer for a wait: the signal `sig` arrives during it (its handler runs), and the wait goes on to its end."""

    def __init__(self, sig: int) -> None:
        self.sig = sig


class Proc:
    """pytest, faked: each `wait` takes its next answer from `answers` (an exit code; a Signal; an exception to raise);
    with none left, it runs on (TimeoutExpired, the clock moved by the timeout). A signal in `dies_on` ends it."""

    def __init__(self, clock: Clock, answers: list[Any], dies_on: tuple[int, ...]) -> None:
        self.clock, self.answers, self.dies_on = clock, list(answers), dies_on
        self.pid, self.code, self.waits = 4242, None, []

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, int):
            self.clock.now += 1
            self.code = answer
            return answer
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, Signal):
            runner.INTERRUPTIONS(answer.sig, None)
        self.clock.now += timeout or 0
        raise subprocess.TimeoutExpired("pytest", timeout or 0)

    def poll(self) -> int | None:
        return self.code


class World:
    """The seams: one fake pytest, its signals, the clock and the cleanup, each call recorded. `kill_error` is what
    signalling pytest raises (it ended meanwhile, say); `during_cleanup` runs inside the cleanup, before its answer."""

    def __init__(self, answers: list[Any], *, dies_on: tuple[int, ...] = (signal.SIGINT, signal.SIGKILL),
                 kill_error: BaseException | None = None, cleanup: Any = 0, during_cleanup: Any = None,
                 records: bool = False) -> None:  # fmt: skip
        self.clock = Clock()
        self.proc = Proc(self.clock, answers, dies_on)
        self.kill_error, self.cleanup_answer, self.during_cleanup, self.records = (
            kill_error, cleanup, during_cleanup, records,
        )  # fmt: skip
        self.started: list[dict[str, Any]] = []
        self.signals: list[tuple[int, int]] = []
        self.cleanups: list[tuple[Path, float]] = []

    def popen(self, argv: list[str], **kwargs: Any) -> Proc:
        self.started.append({"argv": argv, **kwargs})
        if self.records:  # the harness recording its project before its first `up`
            Path(kwargs["env"]["DEWPOINT_PROOF_PROJECTS"]).write_text(f"{PROJECT}\n")
        return self.proc

    def killpg(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        if self.kill_error is not None:
            raise self.kill_error
        if sig in self.proc.dies_on:
            self.proc.code, self.proc.answers = -sig, [-sig]

    def cleanup(self, projects: Path, timeout: float, log: Any) -> int:
        self.cleanups.append((projects, timeout))
        if self.during_cleanup is not None:
            self.during_cleanup()
        if isinstance(self.cleanup_answer, BaseException):
            self.clock.now += timeout if isinstance(self.cleanup_answer, subprocess.TimeoutExpired) else 0
            raise self.cleanup_answer
        return int(self.cleanup_answer)

    def seams(self) -> runner.Seams:
        return runner.Seams(popen=self.popen, killpg=self.killpg, clock=self.clock, cleanup=self.cleanup,
                            wall=lambda: WALL, pid=lambda: RUNNER_PID)  # fmt: skip

    def here(self) -> Path:
        return Path(self.started[0]["env"]["DEWPOINT_PROOF_PROJECTS"]).parent


def _run(world: World, out: Path) -> int:
    return runner.run("sc", ["tests/proofs/d12/test_start_check.py"], out, cap=CAP, reserve=RESERVE,
                      seams=world.seams())  # fmt: skip


def _dirs(out: Path) -> list[Path]:
    return sorted(p for p in out.iterdir() if p.is_dir())


# --- files, and the refusal


def test_each_invocation_keeps_files_of_its_own_and_never_removes_another(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    first, second = World([0]), World([0])
    assert _run(first, out) == 0 and _run(second, out) == 0
    heres = [first.here(), second.here()]
    assert heres[0] != heres[1] and sorted(heres) == _dirs(out)  # one each, and nothing else made or removed
    for world, here in zip((first, second), heres, strict=True):
        assert (here / "run.txt").exists() and (here / "cleaned").exists()
        assert (here / "cleanup.txt").read_text() == "confirmed\n"
        env = world.started[0]["env"]
        assert env["DEWPOINT_PROOF"] == "sc" and env["DEWPOINT_PROOF_OUT"] == str(here / "record.jsonl")
        assert world.cleanups == [(here / "projects.txt", world.cleanups[0][1])]
        assert world.started[0]["start_new_session"] is True and "-x" in world.started[0]["argv"]


def test_a_run_refuses_to_start_while_an_earlier_runs_projects_arent_known_removed(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    earlier = out / "sc-earlier"
    earlier.mkdir(parents=True)
    (earlier / "projects.txt").write_text(f"{PROJECT}\n")  # an interrupted run's: never cleaned
    world = World([0])
    assert _run(world, out) == runner.REFUSED
    assert world.started == [] and world.cleanups == [] and _dirs(out) == [earlier]  # nothing started, nothing touched
    assert (earlier / "projects.txt").read_text() == f"{PROJECT}\n"
    (earlier / "cleaned").write_text("by hand\n")  # its cleanup confirmed: the next run may start
    assert _run(World([0]), out) == 0
    empty = out / "sc-nothing-up"
    empty.mkdir()
    (empty / "projects.txt").write_text("")  # a run that brought nothing up holds nothing back
    assert _run(World([0]), out) == 0


def test_a_failed_proof_is_still_cleaned_up_and_its_code_kept(tmp_path: Path) -> None:
    world = World([1])
    assert _run(world, tmp_path / "runs") == 1
    assert len(world.cleanups) == 1 and world.signals == []  # it had ended: nothing to stop


# --- interruptions: noted, never raised


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_an_interruption_stops_pytest_then_cleans_up(tmp_path: Path, sig: int) -> None:
    world = World([Signal(sig)])
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED
    assert world.signals == [(world.proc.pid, signal.SIGINT)]  # pytest's own teardowns run first
    [(projects, timeout)] = world.cleanups
    assert projects.name == "projects.txt" and 0 < timeout <= CAP


def test_a_keyboard_interrupt_with_no_handler_installed_still_stops_and_cleans_up(tmp_path: Path) -> None:
    world = World([KeyboardInterrupt()])  # the runner used as a library: SIGINT raised, not noted
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED
    assert world.signals == [(world.proc.pid, signal.SIGINT)] and len(world.cleanups) == 1


def test_pytest_ending_between_poll_and_kill_never_skips_the_cleanup(tmp_path: Path) -> None:
    """The owner's first timing: pytest still running at `poll()`, gone by `killpg()` (ProcessLookupError)."""
    world = World([Signal(signal.SIGTERM)], kill_error=ProcessLookupError())
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED
    assert world.signals == [(world.proc.pid, signal.SIGINT)] and len(world.cleanups) == 1
    assert (world.here() / "cleaned").exists()
    assert "stopping pytest: it had already ended" in (world.here() / "run.txt").read_text()


def test_pytest_that_cant_be_signalled_never_skips_the_cleanup(tmp_path: Path) -> None:
    world = World([Signal(signal.SIGTERM)], kill_error=PermissionError())
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED and len(world.cleanups) == 1


def test_a_sigterm_during_the_cleanup_is_noted_and_the_cleanup_finishes(tmp_path: Path) -> None:
    """The owner's second timing: a SIGTERM while the cleanup runs. Noted, not raised: the cleanup finishes and is
    confirmed, and the run reports the interruption."""
    world = World([0], during_cleanup=lambda: runner.INTERRUPTIONS(signal.SIGTERM, None))
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED
    assert (world.here() / "cleaned").exists() and (world.here() / "cleanup.txt").read_text() == "confirmed\n"
    assert "interrupted meanwhile (SIGTERM)" in (world.here() / "run.txt").read_text()


def test_an_interruption_raised_inside_the_cleanup_keeps_the_record_and_an_explicit_failure(tmp_path: Path) -> None:
    """With no handler installed, a SIGINT inside the cleanup raises: the run ends UNCLEANED, `cleanup.txt` says so, no
    `cleaned` is written, and the record holds the next run back until it's cleaned by hand."""
    out = tmp_path / "runs"
    during: list[str] = []
    world = World([0], cleanup=KeyboardInterrupt(), records=True,
                  during_cleanup=lambda: during.append((world.here() / "cleanup.txt").read_text()))  # fmt: skip
    assert _run(world, out) == runner.UNCLEANED
    assert during == ["started: not confirmed\n"]  # had the runner itself died here, that's what would stay
    here = world.here()
    assert (here / "cleanup.txt").read_text().startswith("interrupted (KeyboardInterrupt): not confirmed")
    assert not (here / "cleaned").exists() and (here / "projects.txt").read_text() == f"{PROJECT}\n"
    assert runner.unfinished(out) == [here]


NOTED = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT)


def test_the_runner_notes_every_stopping_signal_while_it_runs_and_restores_them_after(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """SIGHUP (a closed terminal) and SIGQUIT too, as SIGTERM and SIGINT: noted, never the runner's death (the final
    review's I1). Anything noted before `main` installs them is cleared first, never after (so none is dropped)."""
    before = {sig: signal.getsignal(sig) for sig in NOTED}
    seen: dict[str, Any] = {}

    def fake_run(proof: str, selection: list[str], out: Path, **kwargs: Any) -> int:
        handlers = {sig: signal.getsignal(sig) for sig in NOTED}
        seen.update({"handlers": handlers, "noted": list(runner.INTERRUPTIONS.noted), "out": out})
        return 0

    monkeypatch.setattr(runner, "run", fake_run)
    runner.INTERRUPTIONS.noted.append("SIGTERM")  # an earlier run's, stale
    assert runner.main(["--proof", "sc", "--out", "relative/runs", "--cap", "1200", "--reserve", "300", "x.py"]) == 0
    assert seen["handlers"] == dict.fromkeys(NOTED, runner.INTERRUPTIONS) and seen["noted"] == []
    assert seen["out"].is_absolute()  # wherever pytest runs, its record and projects files are where they were named
    assert {sig: signal.getsignal(sig) for sig in before} == before
    runner.INTERRUPTIONS(signal.SIGHUP, None)  # a handler that returns: nothing is raised where it lands
    assert runner.INTERRUPTIONS.noted[-1] == "SIGHUP"


# --- the runner gone: pytest stops itself (the final review's I1)


def test_pytest_is_told_who_its_runner_is_and_when_to_stop_itself(tmp_path: Path) -> None:
    world = World([0])
    assert _run(world, tmp_path / "runs") == 0
    env = world.started[0]["env"]
    assert env["DEWPOINT_PROOF_RUNNER_PID"] == str(RUNNER_PID)
    # its share of the cap, then the grace the runner itself would give it: past that, it's on its own
    assert float(env["DEWPOINT_PROOF_DEADLINE"]) == pytest.approx(WALL + CAP - RESERVE + runner.GRACE_S)


def _watched(parents: list[int], times: list[float]) -> tuple[str | None, list[str]]:
    interrupted: list[str] = []
    ppid, now = iter(parents), iter(times)
    why = runner.watch(RUNNER_PID, WALL + 100, stop=threading.Event(), poll=0.0, getppid=lambda: next(ppid),
                       now=lambda: next(now), interrupt=lambda: interrupted.append("SIGINT"))  # fmt: skip
    return why, interrupted


def test_pytest_interrupts_itself_once_when_its_runner_is_gone() -> None:
    why, interrupted = _watched([RUNNER_PID, RUNNER_PID, 1], [WALL, WALL + 1, WALL + 2])  # reparented: it died
    assert why == "the runner is gone" and interrupted == ["SIGINT"]


def test_pytest_interrupts_itself_once_its_deadline_has_passed() -> None:
    why, interrupted = _watched([RUNNER_PID] * 3, [WALL, WALL + 50, WALL + 100])
    assert why == "its deadline passed" and interrupted == ["SIGINT"]


def test_the_guard_does_nothing_while_its_runner_lives_and_stops_when_asked() -> None:
    stop, interrupted = threading.Event(), []
    stop.set()
    assert runner.watch(RUNNER_PID, WALL + 100, stop=stop, poll=0.0, getppid=lambda: RUNNER_PID, now=lambda: WALL,
                        interrupt=lambda: interrupted.append("x")) is None  # fmt: skip
    assert interrupted == []


def test_the_guard_starts_in_pytest_only_under_a_runner(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert runner.guard_from({}) is None  # an ordinary run of the suite: no guard
    under = {"DEWPOINT_PROOF_RUNNER_PID": "1", "DEWPOINT_PROOF_DEADLINE": "0"}  # past due, and not its parent
    assert runner.guard_from({**under, "PYTEST_XDIST_WORKER": "gw0"}) is None  # a worker's parent is the controller
    guard = runner.guard_from(
        {"DEWPOINT_PROOF_RUNNER_PID": str(runner.os.getppid()), "DEWPOINT_PROOF_DEADLINE": "9e18"}
    )
    assert guard is not None
    thread, stop = guard
    assert thread.daemon and thread.is_alive()
    stop.set()
    thread.join(5)
    assert not thread.is_alive()  # its runner (this process's parent) is there and its deadline far off: no interrupt


# --- stopping, the cap, and the cleanup's own failures


def test_pytest_ignoring_its_interrupt_is_killed_before_cleanup(tmp_path: Path) -> None:
    world = World([Signal(signal.SIGTERM)], dies_on=(signal.SIGKILL,))
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED
    assert world.signals == [(world.proc.pid, signal.SIGINT), (world.proc.pid, signal.SIGKILL)]
    assert len(world.cleanups) == 1


def test_a_pytest_that_outlives_its_kill_never_holds_the_cleanup_back(tmp_path: Path) -> None:
    world = World([Signal(signal.SIGTERM)], dies_on=())  # it never ends, not even on SIGKILL
    started = world.clock.now
    assert _run(world, tmp_path / "runs") == runner.INTERRUPTED
    assert world.signals == [(world.proc.pid, signal.SIGINT), (world.proc.pid, signal.SIGKILL)]
    [(_, timeout)] = world.cleanups
    assert world.clock.now - started + timeout <= CAP + 1e-6
    assert world.proc.waits[-2:] == [runner.GRACE_S, runner.GRACE_S]  # each stop's wait bounded


def test_the_whole_run_stays_within_its_cap_with_time_kept_for_cleanup(tmp_path: Path) -> None:
    world = World([], dies_on=(signal.SIGKILL,))  # pytest never ends, and ignores its interrupt
    started = world.clock.now
    assert _run(world, tmp_path / "runs") == runner.CAPPED
    pytest_waits = world.proc.waits[:-2]
    assert all(w <= runner.POLL_S for w in pytest_waits) and sum(pytest_waits) == pytest.approx(CAP - RESERVE)
    [(_, timeout)] = world.cleanups
    assert RESERVE - 2 * runner.GRACE_S <= timeout <= RESERVE  # two graces at most to stop it
    assert world.clock.now - started + timeout <= CAP + 1e-6


def test_a_cleanup_that_overruns_or_fails_is_reported_and_its_record_kept(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    overrun = World([0], cleanup=subprocess.TimeoutExpired("cleanup", RESERVE), records=True)
    assert _run(overrun, out) == runner.UNCLEANED
    here = overrun.here()
    assert (here / "cleanup.txt").read_text().startswith("overran the cap: not confirmed")
    assert not (here / "cleaned").exists() and runner.unfinished(out) == [here]
    failing = World([0], cleanup=1)
    assert _run(failing, tmp_path / "other") == runner.UNCLEANED
    assert (failing.here() / "cleanup.txt").read_text().startswith("failed (exit 1): not confirmed")


# --- the runner's own results: distinct, and reported whatever fails


def test_the_runners_own_exit_codes_never_collide_with_pytests() -> None:
    ours = [runner.CAPPED, runner.INTERRUPTED, runner.REFUSED, runner.UNCLEANED, runner.ERROR]
    assert len(set(ours)) == len(ours) and not set(ours) & {int(code) for code in pytest.ExitCode}


def test_a_pytest_that_cant_be_started_still_gets_the_cleanup_and_a_result(tmp_path: Path) -> None:
    world = World([0])

    def broken(argv: list[str], **kwargs: Any) -> Any:
        raise OSError("no such interpreter")

    world.popen = broken  # type: ignore[method-assign]
    assert runner.run("sc", ["x.py"], tmp_path / "runs", cap=CAP, reserve=RESERVE, seams=world.seams()) == runner.ERROR
    [here] = _dirs(tmp_path / "runs")
    assert "runner error (OSError)" in (here / "run.txt").read_text() and (here / "cleaned").exists()


def test_a_cleanup_that_cant_be_started_is_an_explicit_failure(tmp_path: Path) -> None:
    world = World([0], cleanup=OSError("no python"), records=True)
    assert _run(world, tmp_path / "runs") == runner.UNCLEANED
    assert (world.here() / "cleanup.txt").read_text().startswith("failed (OSError): not confirmed")


def test_a_status_that_cant_be_written_is_never_taken_for_a_confirmed_cleanup(tmp_path: Path) -> None:
    world = World([0], records=True)
    real_popen = world.popen

    def locking(argv: list[str], **kwargs: Any) -> Any:
        proc = real_popen(argv, **kwargs)
        world.here().chmod(0o500)  # its directory read-only from here on: cleanup.txt and `cleaned` can't be written
        return proc

    world.popen = locking  # type: ignore[method-assign]
    try:
        assert _run(world, tmp_path / "runs") == runner.UNCLEANED
    finally:
        world.here().chmod(0o700)
    assert len(world.cleanups) == 1 and not (world.here() / "cleaned").exists()
    assert "couldn't be written" in (world.here() / "run.txt").read_text()


def test_a_terminal_gone_by_the_end_never_turns_a_result_into_an_error(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def gone(*args: Any, **kwargs: Any) -> None:
        raise OSError(5, "Input/output error")  # stdout's terminal closed (SIGHUP noted, the run went on)

    monkeypatch.setattr(builtins, "print", gone)
    assert _run(World([0]), tmp_path / "runs") == 0


def test_a_cap_without_room_for_cleanup_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reserve"):
        runner.run("sc", [], tmp_path, cap=1000, reserve=2 * runner.GRACE_S, seams=World([0]).seams())
    with pytest.raises(ValueError, match="reserve"):
        runner.run("sc", [], tmp_path, cap=RESERVE, reserve=RESERVE, seams=World([0]).seams())
