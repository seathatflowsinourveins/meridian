"""The lead's merge gate (`.agents/skills/lead/scripts/gate.py`) decides right, offline.

A scratch repository with a local bare `origin` stands in for GitHub; a fake `gh` answers the
pull-request calls, and its squash-merge pushes the PR head's tree onto main as GitHub would.
The five checks are replaced by commands that pass or fail on purpose; nothing reaches a network.
"""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from test_paper_only import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "gate", REPO_ROOT / ".agents" / "skills" / "lead" / "scripts" / "gate.py"
)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
# No __pycache__ beside the skill: the paper-only scan requires git to list every file there.
sys.dont_write_bytecode, _was = True, sys.dont_write_bytecode
SPEC.loader.exec_module(gate)
sys.dont_write_bytecode = _was

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, name: str, text: str, message: str) -> None:
    (repo / name).write_text(text)
    sh(repo, "add", name)
    sh(repo, "commit", "-q", "-m", message)


class FakeGh:
    """The calls the gate makes, answered as GitHub would; `ci` is each check's bucket."""

    def __init__(self, origin: Path, ci: list[str]) -> None:
        self.origin, self.ci, self.calls, self.branch = origin, ci, [], ""
        self.on_checks: Callable[[], None] = lambda: None  # runs as CI is read
        self.after_merge: Callable[[], None] = lambda: None  # runs right after the merge

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["pr", "list"]:
            return "[]"
        if args[:2] == ["pr", "create"]:
            self.branch = args[args.index("--head") + 1]
            return "https://github.invalid/o/r/pull/7"
        if args[:2] == ["pr", "checks"] and "--json" in args:
            self.on_checks()
            return json.dumps([{"name": f"c{i}", "bucket": b} for i, b in enumerate(self.ci)])
        if args[:2] == ["pr", "merge"]:
            head = sh(self.origin, "rev-parse", f"refs/heads/{self.branch}")
            assert args[args.index("--match-head-commit") + 1] == head
            tree = sh(self.origin, "rev-parse", f"{head}^{{tree}}")
            new = sh(self.origin, "commit-tree", tree, "-p", "main", "-m", "squash")
            sh(self.origin, "update-ref", "refs/heads/main", new)
            self.after_merge()
        return ""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    sh(work, "checkout", "-q", "-b", "main")
    commit(work, "a.txt", "a\n", "base")
    sh(work, "push", "-q", "origin", "main")
    sh(work, "checkout", "-q", "-b", "feature")
    commit(work, "b.txt", "b\n", "feature")
    sh(work, "checkout", "-q", "main")
    return work


def make(repo: Path, ci: list[str], passing: bool = True) -> tuple[Any, FakeGh]:
    fake = FakeGh(repo.parent / "origin.git", ci)
    check = ["test", "-f", "b.txt"] if passing else ["test", "-f", "missing.txt"]
    g = gate.Gate(repo, gh=fake, setup=[], checks=[check])
    g.say = lambda _line: None
    return g, fake


def move_main(repo: Path, name: str = "c.txt") -> None:
    other = repo.parent / f"other-{name}"
    subprocess.run(["git", "clone", "-q", str(repo.parent / "origin.git"), str(other)], check=True)
    commit(other, name, "c\n", "main moved")
    sh(other, "push", "-q", "origin", "main")


def test_a_tested_tree_lands_and_main_equals_it(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass", "skipping"])
    move_main(repo)  # before the trial: the trial merges it in
    assert g.trial("feature")
    (tmp_path / "body.md").write_text("body\n")
    assert g.open("feature", "t", tmp_path / "body.md", tmp_path / "body.md", wait=False) == 7
    g.land("feature")
    assert ["pr", "comment", "7", "--body-file", str(tmp_path / "body.md")] in fake.calls
    assert not (g.home / "lock").exists()


def test_refuses_when_main_moved_after_the_trial(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", tmp_path / "b.md", wait=False)
    move_main(repo)
    with pytest.raises(gate.Refused, match="main moved"):
        g.land("feature")
    assert not any(c[:2] == ["pr", "merge"] for c in fake.calls)


def test_refuses_when_a_check_failed(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"], passing=False)
    assert not g.trial("feature")
    (tmp_path / "b.md").write_text("b\n")
    with pytest.raises(gate.Refused, match="a check failed"):
        g.open("feature", "t", tmp_path / "b.md", tmp_path / "b.md", wait=False)
    with pytest.raises(gate.Refused, match="the trial failed"):
        g.land("feature")
    assert fake.calls == []


@pytest.mark.parametrize("ci", [["pass", "fail"], ["pending"], []])
def test_refuses_when_ci_is_not_green(repo: Path, tmp_path: Path, ci: list[str]):
    g, fake = make(repo, ci)
    assert g.trial("feature")
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", tmp_path / "b.md", wait=False)
    with pytest.raises(gate.Refused, match="CI is not green"):
        g.land("feature")
    assert not any(c[:2] == ["pr", "merge"] for c in fake.calls)


def test_one_landing_at_a_time(repo: Path):
    sh(repo, "branch", "second", "feature")
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    with pytest.raises(gate.Refused, match="feature is landing"):
        g.trial("second")
    g.release()
    assert g.trial("second")


def opened(g: Any, tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", tmp_path / "b.md", wait=False)


@pytest.mark.parametrize("fix", [False, True])
def test_a_retried_trial_keeps_the_pushed_merge_so_its_push_fast_forwards(
    repo: Path, tmp_path: Path, fix: bool
):
    g, _ = make(repo, ["pass"])
    move_main(repo, "c.txt")
    assert g.trial("feature")  # merges main in a detached tree; the local branch stays put
    opened(g, tmp_path)
    move_main(repo, "d.txt")  # main moves again
    if fix:  # and the worker commits a fix on its local branch, which lacks the pushed merge
        sh(repo, "checkout", "-q", "feature")
        commit(repo, "e.txt", "e\n", "fix")
        sh(repo, "checkout", "-q", "main")
    assert g.trial("feature")
    opened(g, tmp_path)  # a non-fast-forward push would raise here
    g.land("feature")


def test_main_is_compared_as_the_last_step_before_the_merge(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    fake.on_checks = lambda: move_main(repo)  # main moves while CI is read
    with pytest.raises(gate.Refused, match="main moved"):
        g.land("feature")
    assert not any(c[:2] == ["pr", "merge"] for c in fake.calls)


def test_main_moving_during_the_merge_is_a_loud_fail(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    fake.after_merge = lambda: move_main(repo)
    tested = g.state("feature")["tree"]
    with pytest.raises(gate.Refused, match="run the checks on main") as failed:
        g.land("feature")
    assert str(failed.value).startswith("FAIL") and tested in str(failed.value)


def test_open_and_land_need_their_own_lock(repo: Path, tmp_path: Path):
    sh(repo, "branch", "second", "feature")
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    assert g.release() == "feature"
    assert g.trial("second")
    with pytest.raises(gate.Refused, match="does not name feature"):
        g.land("feature")
    with pytest.raises(gate.Refused, match="does not name feature"):
        opened(g, tmp_path)
    assert g.holder() == "second"  # the other landing's lock is untouched
    assert not any(c[:2] == ["pr", "merge"] for c in fake.calls)
