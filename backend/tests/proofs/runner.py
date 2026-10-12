# SPDX-License-Identifier: Apache-2.0
"""A proof's outer runner (2b-4b M4; the owner's reviews of the start-check run's runner). One invocation:

- **Files of its own, kept:** a directory created for it alone (`<out>/<proof>-<UTC time>-<random>/`: `run.txt`,
  `record.jsonl`, `projects.txt`, `projects.txt.creates`, `cleanup.txt`, and `cleaned` once its cleanup is confirmed).
  Nothing is removed.
- **Refused while an earlier run's projects aren't known removed:** a `projects.txt` naming any, without `cleaned`.
  Its cleanup is run, or confirmed, by hand first.
- **One cap for the whole run:** pytest gets the cap less `reserve`; the rest is cleanup's.
- **Signals noted, never raised:** while it runs (`main`), SIGTERM, SIGINT, SIGHUP (a closed terminal) and SIGQUIT are
  only noted, and looked at between the short waits on pytest. So nothing the runner does is cut short by one: least
  of all stopping pytest and cleaning up.
- **pytest stops itself if the runner is gone:** it runs in a session of its own, so a runner killed outright (SIGKILL,
  the OOM killer) can't stop it. Told its runner's pid and a deadline (its share of the cap, then GRACE_S), a guard
  in its own process (`guard_from`, started by tests/proofs/conftest.py) interrupts it once its runner is gone or the
  deadline has passed, so its own teardowns run and remove its project; the record stays, unconfirmed.
- **Stop, then clean up, whatever happened:** however pytest ends (its own exit, the cap, an interruption), its process
  group is stopped if it still runs (SIGINT, so its own teardowns run, then SIGKILL after GRACE_S; each wait bounded; a
  process already gone, or one that can't be signalled, is noted and passed over). Then, in a `finally` of its own,
  every project the harness recorded before its first `up` is removed by its exact name
  (`python -m tests.proofs.cleanup`, in a session of its own), within the time left. `cleanup.txt` says "started" before
  it begins and its outcome after; `cleaned` is written only once it's confirmed, which it never is while a compose
  create was in flight when its client stopped (`projects.txt.creates`): that one is checked by hand.

    python -m tests.proofs.runner --proof sc --out <dir> --cap 1200 --reserve 300 tests/proofs/d12/test_start_check.py

The proof's own settings (its images, say) come from the caller's environment. Exit: pytest's code, CAPPED or
INTERRUPTED (an interruption noted at any point), ERROR (the runner's own failure, reported); REFUSED; UNCLEANED
whenever the cleanup isn't confirmed, whatever else happened. None of the runner's own codes is one of pytest's."""

import argparse
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

BACKEND = Path(__file__).resolve().parents[2]
GRACE_S = 30.0  # after each of pytest's signals, before the next step
POLL_S = 1.0  # the longest wait on pytest before the noted interruptions are looked at again
CAPPED, INTERRUPTED, REFUSED, UNCLEANED, ERROR = 124, 130, 20, 21, 22  # pytest's own are 0-5
NOTED_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT)


class Interruptions:
    """NOTED_SIGNALS while a run is on: each noted, never raised (`main` installs this)."""

    def __init__(self) -> None:
        self.noted: list[str] = []

    def __call__(self, signum: int, frame: Any) -> None:
        self.noted.append(signal.Signals(signum).name)


INTERRUPTIONS = Interruptions()


def _cleanup(projects: Path, timeout: float, log: TextIO) -> int:
    done = subprocess.run([sys.executable, "-m", "tests.proofs.cleanup", str(projects)], cwd=BACKEND, stdout=log,
                          stderr=subprocess.STDOUT, timeout=timeout, check=False,
                          start_new_session=True)  # fmt: skip  # a terminal's Ctrl-C never reaches it
    return done.returncode


@dataclass
class Seams:
    """What the runner's tests replace: starting pytest, signalling its group, the clock, and the cleanup."""

    popen: Callable[..., Any] = subprocess.Popen
    killpg: Callable[[int, int], None] = os.killpg
    clock: Callable[[], float] = time.monotonic
    cleanup: Callable[[Path, float, TextIO], int] = field(default=_cleanup)
    wall: Callable[[], float] = time.time  # pytest's deadline, in a clock another process shares
    pid: Callable[[], int] = os.getpid


def unfinished(out: Path) -> list[Path]:
    """Earlier runs whose recorded projects aren't known removed: a `projects.txt` naming any, and no `cleaned`."""
    return sorted(
        p.parent for p in out.glob("*/projects.txt") if p.read_text().split() and not (p.parent / "cleaned").exists()
    )


def run(proof: str, selection: list[str], out: Path, *, cap: float, reserve: float, seams: Seams | None = None) -> int:
    seams = seams or Seams()
    if reserve <= 2 * GRACE_S or cap <= reserve:
        raise ValueError("the cap keeps a reserve for cleanup, longer than the graces pytest gets to stop")
    out = out.resolve()  # pytest runs in backend/: the files it's told of are where they were named
    deadline = seams.clock() + cap
    blocked = unfinished(out)
    if blocked:
        print(f"refused: an earlier run's projects aren't known removed: {', '.join(map(str, blocked))}")
        return REFUSED
    here = out / f"{proof}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    here.mkdir(parents=True, exist_ok=False)  # its own: never another invocation's
    projects = here / "projects.txt"
    alone_after = seams.wall() + (deadline - reserve - seams.clock()) + GRACE_S  # past it, pytest stops itself
    env = {**os.environ, "DEWPOINT_PROOF": proof, "DEWPOINT_PROOF_OUT": str(here / "record.jsonl"),
           "DEWPOINT_PROOF_PROJECTS": str(projects), "DEWPOINT_PROOF_RUNNER_PID": str(seams.pid()),
           "DEWPOINT_PROOF_DEADLINE": repr(alone_after)}  # fmt: skip
    argv = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-n", "0", "-x", *selection]
    proc: Any = None
    code, how, cleaned = INTERRUPTED, "not started", False
    with (here / "run.txt").open("w") as log:
        log.write(f"== {' '.join(argv)}  (cap {cap:.0f} s, of which {reserve:.0f} s kept for cleanup)\n")
        log.flush()
        try:
            proc = seams.popen(argv, cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)  # fmt: skip
            code, how = _wait(proc, deadline - reserve, seams)
        except KeyboardInterrupt:  # a SIGINT with no `Interruptions` installed: the runner used as a library
            code, how = INTERRUPTED, "interrupted (KeyboardInterrupt)"
        except Exception as e:  # noqa: BLE001 - pytest couldn't be started or waited on: reported, then cleaned up
            code, how = ERROR, f"runner error ({type(e).__name__})"
        finally:
            try:
                if proc is not None and proc.poll() is None:
                    log.write(f"== stopping pytest: {_stop(proc, seams)}\n")
            finally:
                cleaned = _clean(here, projects, deadline - seams.clock(), seams, log)
        if INTERRUPTIONS.noted and code != INTERRUPTED:
            how += f"; interrupted meanwhile ({', '.join(INTERRUPTIONS.noted)})"
        summary = f"pytest: {how}; cleanup: {'confirmed' if cleaned else 'NOT confirmed: projects.txt kept'}"
        log.write(f"== {summary}\n")
    try:
        print(f"{here}: {summary}")
    except OSError:  # the terminal is gone (a SIGHUP noted): the result is in run.txt and cleanup.txt
        pass
    if not cleaned:
        return UNCLEANED
    return INTERRUPTED if INTERRUPTIONS.noted else code


def _wait(proc: Any, until: float, seams: Seams) -> tuple[int, str]:
    """pytest's end, its share of the cap, or a noted interruption, whichever comes first."""
    while True:
        if INTERRUPTIONS.noted:
            return INTERRUPTED, f"interrupted ({', '.join(INTERRUPTIONS.noted)})"
        left = until - seams.clock()
        if left <= 0:
            return CAPPED, "stopped at the cap"
        try:
            code = proc.wait(timeout=min(POLL_S, left))
            return code, f"exit {code}"
        except subprocess.TimeoutExpired:
            continue


def _stop(proc: Any, seams: Seams) -> str:
    """pytest's group interrupted, so its own teardowns run, then killed: each wait bounded. A process already gone, or
    one that can't be signalled, is reported, never raised: the cleanup that follows doesn't depend on it."""
    for sig in (signal.SIGINT, signal.SIGKILL):
        try:
            seams.killpg(proc.pid, sig)
        except ProcessLookupError:
            return "it had already ended"
        except OSError as e:
            return f"it couldn't be signalled ({type(e).__name__})"
        try:
            proc.wait(timeout=GRACE_S)
            return f"stopped ({sig.name})"
        except subprocess.TimeoutExpired:
            continue
    return f"still running {GRACE_S:.0f} s after SIGKILL"


def _written(path: Path, content: str, log: TextIO) -> bool:
    try:
        path.write_text(content)
        return True
    except OSError as e:
        log.write(f"== {path.name} couldn't be written ({type(e).__name__})\n")
        return False


def _clean(here: Path, projects: Path, left: float, seams: Seams, log: TextIO) -> bool:
    """Every recorded project removed by its exact name, within the time left. `cleanup.txt` says "started" first and
    its outcome after; `cleaned` only once it's confirmed, and confirmed only once both are written. Never raises."""
    status = here / "cleanup.txt"
    _written(status, "started: not confirmed\n", log)
    if left <= 0:
        confirmed, result = False, "no time left"
    else:
        log.write(f"== cleanup of the recorded projects ({left:.0f} s left)\n")
        log.flush()
        try:
            code = seams.cleanup(projects, left, log)
            confirmed, result = code == 0, ("confirmed" if code == 0 else f"failed (exit {code})")
        except subprocess.TimeoutExpired:
            confirmed, result = False, "overran the cap"
        except KeyboardInterrupt:
            confirmed, result = False, "interrupted (KeyboardInterrupt)"
        except Exception as e:  # noqa: BLE001 - it couldn't be started, say: an explicit failure, never a raise
            confirmed, result = False, f"failed ({type(e).__name__})"
    outcome = f"{result}\n" if confirmed else f"{result}: not confirmed; projects.txt kept, clean it by hand\n"
    confirmed = _written(status, outcome, log) and confirmed
    confirmed = confirmed and _written(here / "cleaned", "cleanup confirmed\n", log)
    log.write(f"== cleanup: {result}{'' if confirmed else ' (not confirmed)'}\n")
    return confirmed


def watch(runner_pid: int, deadline: float, *, stop: threading.Event, poll: float = POLL_S,
          getppid: Callable[[], int] = os.getppid, now: Callable[[], float] = time.time,
          interrupt: Callable[[], None] | None = None) -> str | None:  # fmt: skip
    """pytest's own guard (`guard_from`): it interrupts pytest once (SIGINT to itself, so its teardowns run, a blocked
    call included) when its runner is gone (it was re-parented) or `deadline` has passed; None once `stop` is set."""
    interrupt = interrupt or (lambda: os.kill(os.getpid(), signal.SIGINT))
    while True:
        if getppid() != runner_pid:
            interrupt()
            return "the runner is gone"
        if now() >= deadline:
            interrupt()
            return "its deadline passed"
        if stop.wait(poll):
            return None


def guard_from(environ: Mapping[str, str]) -> tuple[threading.Thread, threading.Event] | None:
    """In pytest under the runner (its pid and pytest's deadline in `environ`), the guard, started: never otherwise,
    and never in an xdist worker, whose parent is pytest's controller (the runner runs `-n 0`)."""
    pid, deadline = environ.get("DEWPOINT_PROOF_RUNNER_PID"), environ.get("DEWPOINT_PROOF_DEADLINE")
    if not pid or not deadline or environ.get("PYTEST_XDIST_WORKER"):
        return None
    stop = threading.Event()
    thread = threading.Thread(target=watch, args=(int(pid), float(deadline)), kwargs={"stop": stop}, daemon=True,
                              name="dewpoint-proof-guard")  # fmt: skip
    thread.start()
    return thread, stop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A proof's outer runner")
    parser.add_argument("--proof", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cap", required=True, type=float)
    parser.add_argument("--reserve", required=True, type=float)
    parser.add_argument("selection", nargs="+")
    args = parser.parse_args(argv)
    INTERRUPTIONS.noted.clear()  # before the handlers: whatever is noted from now on is this run's
    previous = {sig: signal.signal(sig, INTERRUPTIONS) for sig in NOTED_SIGNALS}
    try:
        return run(args.proof, args.selection, args.out.resolve(), cap=args.cap, reserve=args.reserve)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
