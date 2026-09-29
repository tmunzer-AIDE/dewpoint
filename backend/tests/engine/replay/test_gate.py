# SPDX-License-Identifier: Apache-2.0
"""The replay gate's history check (spec §7): recorded histories are never changed or removed, and new ones go only
into this build's directory."""

import subprocess
from pathlib import Path

from tests.engine.replay.gate import MAIN, REPLAY, base_for, changes, problems

THIS = "dewpoint-0.1.0+abi3"


def test_a_recorded_history_is_never_changed_or_removed() -> None:
    found = problems([("M", f"{REPLAY}dewpoint-0.1.0+abi2/loops.json"), ("D", f"{REPLAY}{THIS}/drain.json")], THIS)
    assert found == [
        f"{REPLAY}dewpoint-0.1.0+abi2/loops.json: a recorded history is never changed or removed (M)",
        f"{REPLAY}{THIS}/drain.json: a recorded history is never changed or removed (D)",
    ]


def test_new_histories_go_into_this_builds_directory_only() -> None:
    assert problems([("A", f"{REPLAY}{THIS}/grants.json")], THIS) == []
    older, unknown = f"{REPLAY}dewpoint-0.1.0+abi2/new.json", f"{REPLAY}dewpoint-0.1.0+abi9/new.json"
    assert problems([("A", older), ("A", unknown)], THIS) == [
        f"{older}: new histories go into this build's directory, {THIS}",
        f"{unknown}: new histories go into this build's directory, {THIS}",
    ]


def test_the_recorder_and_the_scenarios_may_change() -> None:
    assert (
        problems([("M", f"{REPLAY}scenarios.py"), ("M", f"{REPLAY}test_replay.py"), ("A", f"{REPLAY}x.md")], THIS) == []
    )


def test_changes_are_read_from_git_since_the_base_and_a_rename_is_a_removal(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout

    git("init", "-q", "-b", "main")
    git("config", "user.email", "gate@example.test")
    git("config", "user.name", "gate")
    old = tmp_path / REPLAY / "dewpoint-0.1.0+abi2"
    old.mkdir(parents=True)
    (old / "loops.json").write_text("{}")
    (old / "errors.json").write_text("{}")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD").strip()
    (old / "loops.json").write_text('{"rewritten": true}')
    (old / "errors.json").rename(old / "errors-renamed.json")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert sorted(changes(base, tmp_path)) == [
        ("A", f"{REPLAY}dewpoint-0.1.0+abi2/errors-renamed.json"),
        ("D", f"{REPLAY}dewpoint-0.1.0+abi2/errors.json"),
        ("M", f"{REPLAY}dewpoint-0.1.0+abi2/loops.json"),
    ]


def test_ci_compares_a_pull_request_with_its_base_and_main_with_its_previous_commit() -> None:
    assert base_for("pull_request", "refs/pull/13/merge", pr_base="1a2b3c", before="") == "1a2b3c"
    assert base_for("push", "refs/heads/main", before="4d5e6f") == "4d5e6f"
    assert base_for("push", "refs/heads/main", before="0" * 40) == MAIN  # a first push has no commit before it


def test_ci_compares_a_feature_branch_push_with_its_merge_base_with_main() -> None:
    assert base_for("push", "refs/heads/feat/engine-2a3c", before="4d5e6f") == MAIN


def test_a_rewrite_stays_visible_on_every_later_push_of_the_branch(tmp_path: Path) -> None:
    """The owner's checkpoint-2 review: compared with the previous push, a history rewritten by an earlier push of
    the branch would pass once any unrelated commit is pushed after it."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout

    git("init", "-q", "-b", "main")
    git("config", "user.email", "gate@example.test")
    git("config", "user.name", "gate")
    old = tmp_path / REPLAY / "dewpoint-0.1.0+abi2"
    old.mkdir(parents=True)
    (old / "loops.json").write_text("{}")
    git("add", ".")
    git("commit", "-q", "-m", "main")
    git("switch", "-q", "-c", "feat")
    (old / "loops.json").write_text('{"rewritten": true}')
    git("commit", "-q", "-am", "the first push rewrites a history")
    first_push = git("rev-parse", "HEAD").strip()
    (tmp_path / "README.md").write_text("unrelated")
    git("add", ".")
    git("commit", "-q", "-m", "a later push")
    rewrite = [f"{REPLAY}dewpoint-0.1.0+abi2/loops.json: a recorded history is never changed or removed (M)"]
    assert problems(changes(first_push, tmp_path), THIS) == []  # the previous push misses it
    base = base_for("push", "refs/heads/feat", before=first_push, main="main")
    assert problems(changes(base, tmp_path), THIS) == rewrite
