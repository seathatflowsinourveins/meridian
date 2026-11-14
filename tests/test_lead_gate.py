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
    sh(work, "worktree", "add", "-q", str(tmp_path / "feature-wt"), "feature")  # the worker's
    return work


def wt(repo: Path, branch: str) -> Path:
    return repo.parent / f"{branch}-wt"


def second_branch(repo: Path) -> None:
    sh(repo, "worktree", "add", "-q", "-b", "second", str(wt(repo, "second")), "feature")


def make(
    repo: Path, ci: list[str], passing: bool = True, check: list[str] | None = None
) -> tuple[Any, FakeGh]:
    fake = FakeGh(repo.parent / "origin.git", ci)
    if check is None:
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
    second_branch(repo)
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    with pytest.raises(gate.Refused, match="feature is landing"):
        g.trial("second")
    g.release()
    assert g.trial("second")


def opened(g: Any, tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", tmp_path / "b.md", wait=False)


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
    second_branch(repo)
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


def test_the_trial_merges_main_on_the_branch_itself(repo: Path):
    g, _ = make(repo, ["pass"])
    move_main(repo)
    assert g.trial("feature")
    head = sh(repo, "rev-parse", "refs/heads/feature")
    assert g.state("feature")["tested"] == head  # a merge commit on the branch, not detached
    assert len(sh(repo, "rev-list", "--parents", "-n", "1", head).split()) == 3
    assert g.state("feature")["tree"] == sh(repo, "rev-parse", f"{head}^{{tree}}")


def test_a_dirty_worktree_or_a_conflict_is_refused(repo: Path):
    g, _ = make(repo, ["pass"])
    (wt(repo, "feature") / "b.txt").write_text("edited\n")
    with pytest.raises(gate.Refused, match="uncommitted changes"):
        g.trial("feature")
    sh(wt(repo, "feature"), "checkout", "-q", "--", "b.txt")
    other = repo.parent / "other-conflict"
    subprocess.run(["git", "clone", "-q", str(repo.parent / "origin.git"), str(other)], check=True)
    commit(other, "b.txt", "main's b\n", "main adds b too")
    sh(other, "push", "-q", "origin", "main")
    with pytest.raises(gate.Refused, match="conflicts with feature"):
        g.trial("feature")
    assert not sh(wt(repo, "feature"), "status", "--porcelain")  # the merge was aborted


def test_a_retried_trial_after_main_moved_fast_forwards_the_remote_branch(
    repo: Path, tmp_path: Path
):
    g, _ = make(repo, ["pass"])
    move_main(repo, "c.txt")
    assert g.trial("feature")
    opened(g, tmp_path)
    move_main(repo, "d.txt")
    assert g.trial("feature")
    opened(g, tmp_path)  # a plain push: it must fast-forward
    origin = repo.parent / "origin.git"
    assert sh(origin, "rev-parse", "feature") == sh(repo, "rev-parse", "refs/heads/feature")
    g.land("feature")


def test_an_amended_branch_after_open_is_refused_at_the_push(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    sh(wt(repo, "feature"), "commit", "-q", "--amend", "-m", "feature, amended")
    assert g.trial("feature")
    calls = len(fake.calls)
    with pytest.raises(gate.Refused, match="was rewritten after an earlier push"):
        opened(g, tmp_path)
    assert len(fake.calls) == calls  # no pull request call after a refused push


def test_a_failed_trial_then_an_amended_fix_lands(repo: Path, tmp_path: Path):
    # Codex's case: open at A; the worker adds B, its trial fails; the worker amends B.
    g, _ = make(repo, ["pass"], check=["test", "!", "-f", "bad.txt"])
    assert g.trial("feature")
    opened(g, tmp_path)
    commit(wt(repo, "feature"), "bad.txt", "x\n", "B")
    assert not g.trial("feature")
    sh(wt(repo, "feature"), "rm", "-q", "bad.txt")
    (wt(repo, "feature") / "good.txt").write_text("y\n")
    sh(wt(repo, "feature"), "add", "good.txt")
    sh(wt(repo, "feature"), "commit", "-q", "--amend", "-m", "B, fixed")
    assert g.trial("feature")
    opened(g, tmp_path)
    g.land("feature")
