# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from dewpoint.apps.cel_evaluator import capacity, config

GIB = 1024**3


def cgroup(tmp_path: Path, memory: str = str(2 * GIB), cpu: str | None = "max 100000", pids: str | None = None) -> Path:
    (tmp_path / "memory.max").write_text(memory + "\n")
    if cpu is not None:
        (tmp_path / "cpu.max").write_text(cpu + "\n")
    if pids is not None:
        (tmp_path / "pids.max").write_text(pids + "\n")
    return tmp_path


def test_six_slots_at_two_gib(tmp_path: Path) -> None:
    assert capacity.derive(cgroup(tmp_path), cpu_count=8, configured=None).slots == 6


def test_the_cpu_quota_and_the_pids_limit_lower_the_slots(tmp_path: Path) -> None:
    assert capacity.derive(cgroup(tmp_path, cpu="200000 100000"), cpu_count=8, configured=None).slots == 2
    assert capacity.derive(cgroup(tmp_path, pids="11"), cpu_count=8, configured=None).slots == 3


def test_configuration_lowers_but_never_raises(tmp_path: Path) -> None:
    assert capacity.derive(cgroup(tmp_path), cpu_count=8, configured=2).slots == 2
    assert capacity.derive(cgroup(tmp_path), cpu_count=8, configured=50).slots == 6


@pytest.mark.parametrize(
    ("memory", "cpu"),
    [("max", "max 100000"), (str(400 * 1024 * 1024), "max 100000"), (str(2 * GIB), "50000 100000")],
)
def test_refuses_to_start_without_a_memory_limit_or_a_slot(tmp_path: Path, memory: str, cpu: str) -> None:
    with pytest.raises(config.StartupError):
        capacity.derive(cgroup(tmp_path, memory, cpu), cpu_count=8, configured=None)


def test_the_environment_is_allow_listed() -> None:
    cfg = config.load({"PATH": "/usr/bin", "DEWPOINT_CEL_SOCKET": "/run/x/cel.sock", "DEWPOINT_CEL_MAX_SLOTS": "2"})
    assert (cfg.socket, cfg.max_slots) == ("/run/x/cel.sock", 2)
    with pytest.raises(config.StartupError, match="DEWPOINT_DATABASE_URL"):
        config.load({"PATH": "/usr/bin", "DEWPOINT_DATABASE_URL": "postgresql://x"})
    with pytest.raises(config.StartupError, match="MAX_SLOTS"):
        config.load({"DEWPOINT_CEL_MAX_SLOTS": "many"})
