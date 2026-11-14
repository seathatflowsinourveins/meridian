"""The lead's merge gate (`.agents/skills/lead/scripts/gate.py`) decides right, offline.

A scratch repository with a local bare `origin` stands in for GitHub; a fake `gh` answers the
pull-request calls, and its squash-merge pushes the PR head's tree onto main as GitHub would.
The five checks are replaced by commands that pass or fail on purpose; nothing reaches a network.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
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
        self.empty_checks = 0
        self.existing_pr = False
        self.on_checks: Callable[[], None] = lambda: None  # runs as CI is read
        self.after_merge: Callable[[], None] = lambda: None  # runs right after the merge

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["pr", "list"]:
            return '[{"number": 7}]' if self.existing_pr else "[]"
        if args[:2] == ["pr", "create"]:
            self.branch = args[args.index("--head") + 1]
            return "https://github.invalid/o/r/pull/7"
        if args[:2] == ["pr", "checks"] and "--json" in args:
            self.on_checks()
            if self.empty_checks:
                self.empty_checks -= 1
                return "[]"
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
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
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
    with tempfile.TemporaryDirectory(prefix="gate-") as home:
        monkeypatch.setenv("HOME", home)
        try:
            yield work
        finally:
            g = gate.Gate(work)
            if g.holder():
                g.release()


def wt(repo: Path, branch: str) -> Path:
    return repo.parent / f"{branch}-wt"


def second_branch(repo: Path) -> None:
    sh(repo, "worktree", "add", "-q", "-b", "second", str(wt(repo, "second")), "feature")


def make(
    repo: Path,
    ci: list[str],
    passing: bool = True,
    check: list[str] | None = None,
    builder: str = "codex",
) -> tuple[Any, FakeGh]:
    fake = FakeGh(repo.parent / "origin.git", ci)
    if check is None:
        check = ["test", "-f", "b.txt"] if passing else ["test", "-f", "missing.txt"]
    g = gate.Gate(repo, gh=fake, setup=[], checks=[check])
    g.say = lambda _line: None
    g.check_timeout = 0
    g.check_interval = 0
    g.register("feature", builder, "task-1")
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
    assert g.open("feature", "t", tmp_path / "body.md", review_record(g, tmp_path), wait=False) == 7
    g.land("feature")
    assert [
        "pr",
        "comment",
        "7",
        "--body-file",
        str(g._state_file("feature").with_suffix(".public-review.json")),
    ] in fake.calls
    assert g.holder() is None


def test_refuses_when_main_moved_after_the_trial(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", review_record(g, tmp_path), wait=False)
    move_main(repo)
    with pytest.raises(gate.Refused, match="main moved"):
        g.land("feature")
    assert not any(c[:2] == ["pr", "merge"] for c in fake.calls)


def test_refuses_when_a_check_failed(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"], passing=False)
    assert not g.trial("feature")
    (tmp_path / "b.md").write_text("b\n")
    with pytest.raises(gate.Refused, match="a check failed"):
        g.open("feature", "t", tmp_path / "b.md", review_record(g, tmp_path), wait=False)
    with pytest.raises(gate.Refused, match="the trial failed"):
        g.land("feature")
    assert fake.calls == []


@pytest.mark.parametrize("ci", [["pass", "fail"], ["pending"], []])
def test_refuses_when_ci_is_not_green(repo: Path, tmp_path: Path, ci: list[str]):
    g, fake = make(repo, ci)
    assert g.trial("feature")
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", review_record(g, tmp_path), wait=False)
    with pytest.raises(gate.Refused, match="CI is not green|no CI checks appeared"):
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


def review_record(g: Any, tmp_path: Path) -> Path:
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "builder": "codex",
                "reviewer": "claude",
                "model": "claude-opus-5-5",
                "tested": g.state("feature")["tested"],
                "summary": "No findings.",
                "findings": [],
            }
        )
    )
    return path


def opened(g: Any, tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("b\n")
    g.open("feature", "t", tmp_path / "b.md", review_record(g, tmp_path), wait=False)


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


@pytest.mark.parametrize(
    "edit",
    [["sh", "-c", "echo edited > b.txt"], ["git", "commit", "-q", "--allow-empty", "-m", "x"]],
)
def test_a_worktree_changed_during_the_checks_fails_the_trial(repo: Path, edit: list[str]):
    fake = FakeGh(repo.parent / "origin.git", ["pass"])
    g = gate.Gate(repo, gh=fake, setup=[], checks=[["test", "-f", "b.txt"], edit])
    g.say = lambda _line: None
    assert not g.trial("feature")
    failed = [r for r in g.state("feature")["checks"] if not r["passed"]]
    assert [r["check"] for r in failed] == ["worktree unchanged"]
    assert "changed during the checks" in failed[0]["last"]


def review_output(*summaries: str) -> str:
    return json.dumps(
        {
            "findings": [
                {"file": "file.py", "line": 1, "summary": summary, "failure_scenario": "failure"}
                for summary in summaries
            ]
        }
    )


def fake_reviewer(monkeypatch: pytest.MonkeyPatch, final: str = '{"findings": []}', code: int = 0):
    real_run = subprocess.run
    calls = []

    def run(args, **kwargs):
        if args[0] not in {"codex", "claude"}:
            return real_run(args, **kwargs)
        calls.append((args, kwargs))
        if args[0] == "codex":
            Path(args[args.index("-o") + 1]).write_text(final)
            output = '{"type": "turn.completed"}'
        else:
            envelope = {"subtype": "success", "is_error": False, "result": final}
            with suppress(ValueError):
                envelope["structured_output"] = json.loads(final)
            output = json.dumps(envelope)
        return subprocess.CompletedProcess(args, code, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


@pytest.mark.parametrize(
    "builder,reviewer,model",
    [
        ("codex", "claude", "claude-opus-5-5"),
        ("claude", "codex", "gpt-6-astra"),
    ],
)
def test_review_records_final_message_and_opposite_family(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builder: str,
    reviewer: str,
    model: str,
):
    g, fake = make(repo, ["pass"], builder=builder)
    g.register("feature", builder, "task-1")
    assert g.trial("feature")
    calls = fake_reviewer(monkeypatch)
    path = g.review("feature", builder)
    record = json.loads(path.read_text())
    assert record["reviewer"] == reviewer and record["model"] == model
    assert record["tested"] == sh(wt(repo, "feature"), "rev-parse", "HEAD")
    assert record["findings"] == []
    cmd, options = calls[0]
    assert cmd[0] == reviewer and options["cwd"] == wt(repo, "feature")
    if reviewer == "codex":
        assert cmd[:2] == ["codex", "exec"] and "review" not in cmd
        assert "--ignore-user-config" in cmd and "model_reasoning_effort=high" in cmd
        assert "--ephemeral" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
        schema = Path(cmd[cmd.index("--output-schema") + 1])
        assert json.loads(schema.read_text()) == gate.REVIEW_SCHEMA
        assert options["input"] == sh(wt(repo, "feature"), "diff", "origin/main...HEAD")
        assert "actionable defects the author would fix" in cmd[-1]
    else:
        assert cmd[:2] == ["claude", "-p"]
        assert cmd[2].startswith("Perform a medium-depth code review of branch feature")
        assert "git diff origin/main...HEAD" in cmd[2]
        assert "An empty diff has no findings" in cmd[2]
        assert cmd[cmd.index("--output-format") + 1] == "json"
    (tmp_path / "body.md").write_text("body")
    g.open("feature", "title", tmp_path / "body.md", wait=False)
    assert [
        "pr",
        "comment",
        "7",
        "--body-file",
        str(g._state_file("feature").with_suffix(".public-review.json")),
    ] in fake.calls


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("tested", "0" * 40, "review commit"),
        ("reviewer", "codex", "other model family"),
        ("model", "gpt-6-astra", "review model"),
        ("findings", [{"text": "problem", "status": "open"}], "unresolved"),
        ("findings", [{"text": "problem", "status": "closed: "}], "unresolved"),
    ],
)
def test_open_refuses_invalid_records_before_push(
    repo: Path,
    tmp_path: Path,
    field: str,
    value: Any,
    message: str,
):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(gate.Refused, match=message):
        g.open("feature", "title", tmp_path / "body.md", path, wait=False)
    assert fake.calls == []
    assert sh(repo.parent / "origin.git", "branch", "--list", "feature") == ""


@pytest.mark.parametrize("status", ["closed: already covered by the existing guard"])
def test_manual_review_dispositions_are_accepted(repo: Path, tmp_path: Path, status: str):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["findings"] = [{"text": "a finding", "status": status}]
    path.write_text(json.dumps(record))
    assert g.open("feature", "title", path, path, wait=False) == 7


@pytest.mark.parametrize(
    "builder,final",
    [
        ("codex", review_output("A bug")),
        ("claude", review_output("A bug")),
    ],
)
def test_review_never_silently_closes_findings(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    final: str,
    builder: str,
):
    g, _ = make(repo, ["pass"], builder=builder)
    assert g.trial("feature")
    fake_reviewer(monkeypatch, final)
    with pytest.raises(gate.Refused, match="unresolved"):
        g.review("feature", builder)
    record = json.loads(g.review_file("feature").read_text())
    assert record["summary"] == final
    assert all(item["status"] == "open" for item in record["findings"])


@pytest.mark.parametrize("final,code", [("", 0), ('{"findings": []}', 1)])
def test_failed_review_removes_previous_success(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    final: str,
    code: int,
):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    fake_reviewer(monkeypatch, final, code)
    g.review_file("feature").write_text('{"old": "success"}')
    with pytest.raises(gate.Refused):
        g.review("feature", "codex")
    assert not g.review_file("feature").exists()


@pytest.mark.parametrize("stop", ["trial", "review", "open", "land"])
def test_auto_stops_at_first_failure_and_prints_worker_reply(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
):
    g, _ = make(repo, ["pass"])
    calls, output = [], []
    g.say = output.append

    def step(name):
        def invoke(*_args, **_kwargs):
            calls.append(name)
            if name == stop:
                raise gate.WorkerFailure("specific failure")
            return True

        return invoke

    for name in ("trial", "review", "open", "land"):
        monkeypatch.setattr(g, name, step(name))
    (tmp_path / "body.md").write_text("body")
    assert not g.auto("feature", "codex", "title", tmp_path / "body.md")
    assert calls == ["trial", "review", "open", "land"][: calls.index(stop) + 1]
    assert output == [f"SEND TO WORKER: feature: {stop} failed: specific failure"]


def flock_available(g: Any) -> bool:
    return subprocess.run(["flock", "-n", str(g.lock_path), "true"]).returncode == 0


def test_auto_holds_shared_flock_for_whole_chain_and_releases(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, fake = make(repo, ["pass"])
    fake_reviewer(monkeypatch)
    fake.on_checks = lambda: assert_locked(g)
    (tmp_path / "body.md").write_text("body")
    assert g.auto("feature", "codex", "title", tmp_path / "body.md")
    assert flock_available(g) and g.holder() is None


def assert_locked(g: Any) -> None:
    assert not flock_available(g)


def test_hand_commands_keep_flock_after_client_exits(repo: Path):
    script = str(REPO_ROOT / ".agents/skills/lead/scripts/gate.py")
    # Run a real, separate client with cheap offline checks; its process then exits.
    code = """import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('gate', sys.argv[1])
gate = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(gate)
g = gate.Gate(pathlib.Path.cwd(), setup=[], checks=[['true']])
assert g.trial('feature', 'codex')
"""
    subprocess.run([sys.executable, "-c", code, script], cwd=repo, check=True)
    g, _ = make(repo, ["pass"])
    assert not flock_available(g)
    second_branch(repo)
    with pytest.raises(gate.Refused, match="feature is landing"):
        g.trial("second")
    g.release()
    assert flock_available(g)


def test_an_external_flock_blocks_the_gate(repo: Path):
    import fcntl

    g, _ = make(repo, ["pass"])
    g.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with g.lock_path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cure = "run the gate without an outer flock; it takes the lock itself"
        with pytest.raises(gate.Refused, match=cure):
            g.trial("feature")
        with pytest.raises(gate.Refused, match=cure):
            g.release()
    assert g.trial("feature")


def test_same_branch_in_another_repository_cannot_take_reservation(repo: Path, tmp_path: Path):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    other = tmp_path / "another"
    subprocess.run(["git", "clone", "-q", str(repo), str(other)], check=True)
    another = gate.Gate(other, setup=[], checks=[["true"]])
    with pytest.raises(gate.Refused, match="feature is landing"):
        another.trial("feature")
    with pytest.raises(gate.Refused):
        another.release()
    assert not flock_available(g)


def test_secret_scan_is_scoped_to_published_commits():
    assert gate.CHECKS[-1] == [
        "gitleaks",
        "git",
        "--redact",
        "--no-banner",
        "--log-opts=origin/main..HEAD",
        ".",
    ]


@pytest.mark.parametrize(
    "status,merged,expected",
    [
        ("completed", False, True),
        ("running", False, False),
        ("completed", True, False),
    ],
)
def test_pending_matches_registered_completed_tasks_and_squash_merge_heads(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    merged: bool,
    expected: bool,
):
    g, _ = make(repo, ["pass"])
    real_run = subprocess.run
    calls = []

    def run(args, **kwargs):
        if args[1:3] == ["orchestration", "task-list"]:
            calls.append(args)
            data = {
                "ok": True,
                "result": {"tasks": [{"id": "task-1"}] if status == "completed" else []},
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    head = sh(repo, "rev-parse", "feature")
    g.gh = lambda _args: json.dumps([{"headRefOid": head}] if merged else [])
    assert g.pending("run-1") is expected
    assert calls[0][-2:] == ["--run", "run-1"]
    assert "--status" in calls[0] and "completed" in calls[0]
    if expected:
        # A merged PR for an earlier head must not hide new commits on the same branch.
        g.gh = lambda _args: json.dumps([{"headRefOid": "0" * 40}])
        assert g.pending()
        sh(repo, "push", "-q", "origin", "feature:main")
        assert not g.pending()


def test_pending_propagates_orca_failure(repo: Path, monkeypatch: pytest.MonkeyPatch):
    g, _ = make(repo, ["pass"])
    with monkeypatch.context() as patch:
        patch.setattr(
            subprocess,
            "run",
            lambda args, **_kwargs: subprocess.CompletedProcess(args, 1, "", "run_required"),
        )
        with pytest.raises(gate.Refused, match="run_required"):
            g.pending()


def test_trigger_detector_missing_package_fails(tmp_path: Path):
    script = REPO_ROOT / ".agents/skills/lead/scripts/trigger_words.py"
    run = subprocess.run(
        [sys.executable, str(script), "-", "--package", str(tmp_path)],
        input="investigate this",
        text=True,
        capture_output=True,
    )
    assert run.returncode == 1 and "oh-my-codex is absent" in run.stderr


def test_trigger_script_uses_package_detector(tmp_path: Path):
    package = tmp_path / "package"
    detector = package / "dist/hooks/keyword-detector.js"
    detector.parent.mkdir(parents=True)
    (package / "package.json").write_text('{"type":"module"}')
    detector.write_text("export function detectKeywords(text) {return [{skill:text, priority:99}]}")
    run = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / ".agents/skills/lead/scripts/trigger_words.py"),
            "-",
            "--package",
            str(package),
        ],
        input="package owns detection",
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(run.stdout)
    assert result["selected"] == {"skill": "package owns detection", "priority": 99}
    assert result["matches"] == [result["selected"]]


@pytest.mark.parametrize("stage", ["open", "land"])
def test_waits_for_github_to_register_checks(repo: Path, tmp_path: Path, stage: str):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    g.check_timeout = 1
    if stage == "land":
        g.open("feature", "title", path, path, wait=False)
    fake.empty_checks = 2
    before = len(fake.calls)
    if stage == "open":
        g.open("feature", "title", path, path)
    else:
        g.land("feature")
    checks = [call for call in fake.calls[before:] if call[:2] == ["pr", "checks"]]
    assert len([call for call in checks if "--json" in call]) == 3
    if stage == "open":
        assert all("--json" in call for call in checks)


@pytest.mark.parametrize("stage", ["open", "land"])
def test_no_checks_timeout_is_clear_and_never_watches_or_merges(
    repo: Path,
    tmp_path: Path,
    stage: str,
):
    g, fake = make(repo, [])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    if stage == "land":
        g.open("feature", "title", path, path, wait=False)
    with pytest.raises(gate.Refused, match="no CI checks appeared.*within 0s"):
        if stage == "open":
            g.open("feature", "title", path, path)
        else:
            g.land("feature")
    assert not any("--watch" in call or call[:2] == ["pr", "merge"] for call in fake.calls)


def test_real_gh_recognizes_only_the_missing_checks_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args, 1, "", "no checks reported on the branch"
        ),
    )
    assert gate.real_gh(["pr", "checks", "7", "--json", "name,bucket"]) == "[]"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 1, "", "authentication failed"),
    )
    with pytest.raises(gate.Refused, match="authentication failed"):
        gate.real_gh(["pr", "checks", "7", "--json", "name,bucket"])


def test_checks_remove_main_venv_and_record_stdout_summary(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("VIRTUAL_ENV", "/home/example/main/.venv")
    g, _ = make(
        repo,
        ["pass"],
        check=[
            sys.executable,
            "-c",
            "import os,sys; assert 'VIRTUAL_ENV' not in os.environ; "
            "print('42 checks passed'); print('a stderr warning',file=sys.stderr)",
        ],
    )
    assert g.trial("feature")
    assert g.state("feature")["checks"][0]["last"] == "42 checks passed"


def test_gitleaks_stderr_summary_is_plain_text(repo: Path):
    g, _ = make(
        repo,
        ["pass"],
        check=[
            sys.executable,
            "-c",
            "import sys; print('\\x1b[32mno leaks found\\x1b[0m',file=sys.stderr)",
        ],
    )
    assert g.trial("feature")
    assert g.state("feature")["checks"][0]["last"] == "no leaks found"
    assert "\x1b" not in g._state_file("feature").with_suffix(".log").read_text()


def test_reopen_updates_existing_pr_title_and_body(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    review = review_record(g, tmp_path)
    body = tmp_path / "body.md"
    body.write_text("old head and tree")
    g.open("feature", "old title", body, review, wait=False)
    fake.existing_pr = True
    body.write_text("new head and tree")
    g.open("feature", "new title", body, review, wait=False)
    edits = [call for call in fake.calls if call[:2] == ["pr", "edit"]]
    assert len(edits) == 1 and edits[0][2:5] == ["7", "--title", "new title"]
    assert Path(edits[0][-1]).read_text() == "new head and tree"
    assert len([call for call in fake.calls if call[:2] == ["pr", "create"]]) == 1


def test_every_posted_text_is_free_of_home_paths(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["summary"] = f"Source {Path.home()}/source.py and /home/example/work/source.py"
    path.write_text(json.dumps(record))
    body = tmp_path / "body.md"
    body.write_text("Built in /home/example/work, /Users/example/work and ~/work.")
    g.open("feature", "Fix /home/example/work/source.py", body, path, wait=False)
    squash = tmp_path / "squash.txt"
    squash.write_text("Source /home/example/work/source.py\n\nBody /Users/example/work/source.py")
    g.land("feature", squash)
    for call in fake.calls:
        for flag in ("--title", "--body", "--subject", "--body-file"):
            if flag not in call:
                continue
            text = call[call.index(flag) + 1]
            if flag == "--body-file":
                text = Path(text).read_text()
            assert "/home/" not in text and "/Users/" not in text and "~/" not in text
            assert str(Path.home()) not in text
    assert json.loads(path.read_text())["summary"] == record["summary"]  # local evidence preserved


@pytest.mark.parametrize("command", ["trial", "auto"])
def test_dispatch_builder_cannot_be_overridden(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
):
    g, _ = make(repo, ["pass"])
    output = []
    g.say = output.append
    monkeypatch.setattr(g, "_main", lambda: pytest.fail("must refuse before merging or checks"))
    if command == "trial":
        with pytest.raises(gate.Refused, match="dispatch registration: codex"):
            g.trial("feature", "claude")
    else:
        (tmp_path / "body").write_text("body")
        assert not g.auto("feature", "claude", "title", tmp_path / "body")
        assert output[0].startswith("LEAD ACTION:")
    assert not g._state_file("feature").exists()
    with pytest.raises(gate.Refused, match="dispatch registration"):
        g.register("feature", "claude", "task-1")


def test_contending_commands_refuse_while_owner_is_running(repo: Path):
    import time

    first, _ = make(repo, ["pass"])
    second, _ = make(repo, ["pass"])
    assert first.trial("feature")
    with first.reservation("feature"):
        started = time.monotonic()
        for invoke in (
            lambda: second.trial("other"),
            lambda: second.trial("feature"),
            second.release,
        ):
            with pytest.raises(gate.Refused, match="feature is landing"):
                invoke()
        assert time.monotonic() - started < 1.5
        assert not flock_available(first)


@pytest.mark.parametrize("payload", ["null", "[]", '"text"', "42", "true"])
@pytest.mark.parametrize("busy", [False, True])
def test_nonobject_handshake_keeps_reservation(repo: Path, payload: str, busy: bool):
    import socket
    from contextlib import nullcontext

    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    with g.reservation("feature") if busy else nullcontext():
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(1)
            conn.connect(str(g.lock_path.with_suffix(".sock")))
            conn.sendall((payload + "\n").encode())
            assert "must be an object" in json.loads(conn.recv(8192))["error"]
        assert not flock_available(g)
    assert g.trial("feature")


def test_fixed_on_current_commit_is_refused_and_new_round_is_required(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["findings"] = [{"text": "a real defect", "status": "fixed"}]
    path.write_text(json.dumps(record))
    with pytest.raises(gate.ReviewPending, match="cannot be marked fixed"):
        g.open("feature", "title", path, path, wait=False)
    assert not fake.calls
    commit(wt(repo, "feature"), "fix.txt", "fixed code", "fix defect")
    assert g.trial("feature")
    with pytest.raises(gate.Refused, match="review commit"):
        g.open("feature", "title", path, path, wait=False)
    fake_reviewer(monkeypatch)
    fresh = g.review("feature", "codex")
    assert json.loads(fresh.read_text())["findings"] == []
    assert g.open("feature", "title", path, wait=False) == 7


def test_post_merge_fetch_failure_releases_and_reports_recovery(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    original = g._main
    calls = []

    def fetch():
        calls.append(True)
        if len(calls) == 2:
            raise gate.Refused("fetch unavailable")
        return original()

    monkeypatch.setattr(g, "_main", fetch)
    with pytest.raises(
        gate.Refused, match="merged but post-merge verification failed.*do not merge again"
    ):
        g.land("feature")
    assert g.state("feature")["merged"]
    assert g.registration("feature")["landed"] == g.state("feature")["tested"]
    assert g.holder() is None and flock_available(g)
    with (
        g.reservation("feature", create=True),
        pytest.raises(gate.Refused, match="already merged"),
    ):
        g.land("feature")
    assert g.holder() is None and flock_available(g)
    assert len([call for call in fake.calls if call[:2] == ["pr", "merge"]]) == 1


@pytest.mark.parametrize(
    "result,code", [(True, 0), (False, 1), ("Orca", 2), ("gh", 2), ("fetch", 2)]
)
def test_pending_cli_distinguishes_idle_from_outage(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: Any,
    code: int,
):
    g, _ = make(repo, ["pass"])

    def pending(_run):
        if isinstance(result, str):
            raise gate.Refused(result + " failed")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(g, "pending", pending)
        patch.setattr(gate, "Gate", lambda _path: g)
        assert gate.main(["pending"]) == code


def test_auto_sends_all_current_review_findings_together(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, fake = make(repo, ["pass"])
    output = []
    g.say = output.append
    fake_reviewer(monkeypatch, review_output("first defect", "second defect", "third defect"))
    (tmp_path / "body").write_text("body")
    assert not g.auto("feature", "codex", "title", tmp_path / "body")
    messages = [text for text in output if text.startswith("LEAD ACTION:")]
    assert len(messages) == 1
    assert all(text in messages[0] for text in ("first defect", "second defect", "third defect"))
    assert not fake.calls


def test_auto_contention_stays_with_lead(repo: Path, tmp_path: Path):
    owner, _ = make(repo, ["pass"])
    contender, _ = make(repo, ["pass"])
    assert owner.trial("feature")
    output = []
    contender.say = output.append
    with owner.reservation("feature"):
        (tmp_path / "body").write_text("body")
        assert not contender.auto("other", "codex", "title", tmp_path / "body")
    assert len(output) == 1 and output[0].startswith("LEAD ACTION:")
    assert "feature is landing" in output[0]


def test_review_citations_are_relative_when_record_is_built(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    final = review_output(f"See {wt(repo, 'feature')}/b.txt:1 and /home/example/private.txt")
    fake_reviewer(monkeypatch, final)
    with pytest.raises(gate.ReviewPending):
        g.review("feature", "codex")
    text = g.review_file("feature").read_text()
    assert "b.txt:1" in text and str(wt(repo, "feature")) not in text
    assert "/home/" not in text and "[local path]" in text


def test_land_revalidates_stored_review_dispositions(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    state = g.state("feature")
    state["review"]["findings"] = [{"text": "still broken", "status": "fixed"}]
    g._save("feature", state)
    with pytest.raises(gate.ReviewPending, match="cannot be marked fixed"):
        g.land("feature")
    assert not any(call[:2] == ["pr", "merge"] for call in fake.calls)


def test_clean_landing_provenance_is_a_runtime_table_row():
    text = (REPO_ROOT / "UPSTREAM.md").read_text()
    runtime = text.split("## Agent runtimes", 1)[1].split("## Assessed", 1)[0]
    row = next(line for line in runtime.splitlines() if line.startswith("| Clean landing"))
    preceding = runtime[: runtime.index(row)].rstrip().splitlines()[-1]
    assert preceding.startswith("| `lead` skill")
    assert len(row.split("|")) == len(preceding.split("|")) == 9
    assert text.count("| Clean landing") == 1


def test_claude_review_base_excludes_commits_on_origin_with_stale_local_main(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import re

    g, _ = make(repo, ["pass"])
    move_main(repo)
    assert g.trial("feature")
    assert sh(repo, "rev-parse", "main") != sh(repo, "rev-parse", "origin/main")
    calls = fake_reviewer(monkeypatch)
    g.review("feature", "codex")
    command, options = calls[0]
    base = re.search(r"git diff (\S+)\.\.\.HEAD", command[2])
    assert base is not None
    assert sh(options["cwd"], "diff", f"{base[1]}...HEAD", "--name-only") == "b.txt"
    assert "c.txt" in sh(options["cwd"], "diff", "main...HEAD", "--name-only")


@pytest.mark.parametrize(
    "final",
    [
        "I found no issues",
        "I found no issues in this diff.",
        "OK\n```JSON\n[]\n```",
        "The review is clean.\n```json\n[]\n```\nNothing to change.",
        'Any surrounding prose\n```json\n{"findings": []}\n```\nDone.',
    ],
)
def test_claude_requires_schema_output_instead_of_clean_prose(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final: str,
):
    g, _ = make(repo, ["pass"])
    body = tmp_path / "body"
    body.write_text("body")
    fake_reviewer(monkeypatch, final)
    assert not g.auto("feature", "codex", "title", body)
    assert not g.review_file("feature").exists()


@pytest.mark.parametrize("final", ["I could not complete the review.", '{"findings": [null]}'])
def test_unknown_review_goes_to_lead_not_worker(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final: str,
):
    g, fake = make(repo, ["pass"])
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    fake_reviewer(monkeypatch, final)
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("LEAD ACTION:") and "unclassified" in output[-1]
    assert not any("SEND TO WORKER" in text for text in output) and not fake.calls
    assert (
        final
        in json.loads(g._state_file("feature").with_suffix(".review.log").read_text())["result"]
    )


@pytest.mark.parametrize(
    "status",
    [
        "closed: fixed",
        "closed: fixed in abc",
        "closed: This was FIXED in abc",
        "closed: repaired by a new commit",
        "closed: resolved",
        "closed: addressed in def",
    ],
)
def test_closure_cannot_claim_a_same_commit_fix(repo: Path, tmp_path: Path, status: str):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["findings"] = [{"text": "the defect", "status": status}]
    path.write_text(json.dumps(record))
    with pytest.raises(gate.ReviewPending, match="cannot be marked fixed"):
        g.open("feature", "title", path, path, wait=False)
    assert not fake.calls


@pytest.mark.parametrize("stage", ["open", "land"])
@pytest.mark.parametrize("outage", [False, True])
def test_auto_routes_red_ci_to_worker_and_transport_errors_to_lead(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    outage: bool,
):
    g, fake = make(repo, ["fail"])
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    fake_reviewer(monkeypatch)
    if stage == "land":
        original = g.open
        monkeypatch.setattr(g, "open", lambda *args: original(*args, wait=False))
    if outage:

        def gh(args):
            if args[:2] == ["pr", "checks"]:
                raise gate.Refused("gh network unavailable")
            return fake(args)

        g.gh = gh
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("LEAD ACTION:" if outage else "SEND TO WORKER:")
    assert ("network unavailable" if outage else "c0") in output[-1]
    assert not any(call[:2] == ["pr", "merge"] for call in fake.calls)


@pytest.mark.parametrize("recovery", ["release", "trial"])
def test_dead_holder_leftovers_can_be_abandoned_or_replaced(repo: Path, recovery: str):
    g, _ = make(repo, ["pass"])
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / ".agents/skills/lead/scripts/gate.py"),
            "_hold",
            str(g.lock_path),
            json.dumps(g._identity("old-branch")),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
        assert not flock_available(g)
    finally:
        proc.kill()  # only this test's own child, never a process discovered by name
        proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
    assert g.holder() == "old-branch" and g.lock_path.with_suffix(".sock").exists()
    if recovery == "release":
        assert g.release() == "old-branch"
        assert g.holder() is None and not g.lock_path.with_suffix(".sock").exists()
    assert g.trial("feature")


def test_stale_release_handles_corrupt_owner_without_erasing_live_lock(repo: Path):
    import fcntl

    g, _ = make(repo, ["pass"])
    g.lock_path.parent.mkdir(parents=True)
    owner = g.lock_path.with_suffix(".owner.json")
    owner.write_text("not JSON")
    assert g.release() == "unreadable owner" and not owner.exists()
    owner.write_text(json.dumps(g._identity("feature")))
    with g.lock_path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(gate.Refused):
            g.release()
        assert owner.exists()
    g.release()


def test_check_failure_keeps_relative_location_and_unscrubbed_local_log(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    branch_wt = Path.home() / "branch-wt"
    sh(repo, "worktree", "move", str(wt(repo, "feature")), str(branch_wt))
    g, _ = make(
        repo,
        ["pass"],
        check=[
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "print(str(Path.cwd()/'b.txt')+':12: error'); sys.exit(1)",
        ],
    )
    output = []
    g.say = output.append
    body = tmp_path / "body"
    body.write_text("body")
    fake_reviewer(monkeypatch)
    assert not g.auto("feature", "codex", "title", body)
    assert "b.txt:12: error" in output[-1] and str(Path.home()) not in output[-1]
    assert g.state("feature")["checks"][0]["last"] == "b.txt:12: error"
    assert str(branch_wt / "b.txt") in g._state_file("feature").with_suffix(".log").read_text()


@pytest.mark.parametrize(
    "error", [KeyError("checks"), TypeError("bad state"), RuntimeError("unexpected")]
)
def test_auto_names_unexpected_errors_for_lead(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
):
    g, _ = make(repo, ["pass"])
    output = []
    g.say = output.append
    body = tmp_path / "body"
    body.write_text("body")

    def fail(*_args):
        raise error

    monkeypatch.setattr(g, "trial", fail)
    assert not g.auto("feature", "codex", "title", body)
    assert len(output) == 1 and output[0].startswith("LEAD ACTION:")
    assert type(error).__name__ in output[0]


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid-utf8"])
def test_auto_validates_body_before_reserving_or_running_work(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
):
    g, _ = make(repo, ["pass"])
    body = tmp_path / "body"
    if kind == "directory":
        body.mkdir()
    elif kind == "invalid-utf8":
        body.write_bytes(b"\xff")
    output = []
    g.say = output.append
    for method in ("reservation", "trial", "review"):
        monkeypatch.setattr(
            g, method, lambda *_args, **_kwargs: pytest.fail("input was not validated")
        )
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("LEAD ACTION: feature: inputs failed:")
    assert g.holder() is None


def test_landed_registration_stops_pending_github_queries(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    opened(g, tmp_path)
    g.land("feature")
    assert g.registration("feature")["landed"] == g.state("feature")["tested"]
    real_run = subprocess.run

    def run(args, **kwargs):
        if args[1:3] == ["orchestration", "task-list"]:
            data = {"result": {"tasks": [{"id": "task-1", "status": "completed"}]}}
            return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    g.gh = lambda _args: pytest.fail("landed registration must not query GitHub")
    assert not g.pending()
    # A fresh dispatch explicitly makes the branch eligible again.
    g.register("feature", "codex", "task-2")
    assert "landed" not in g.registration("feature")


def test_public_text_handles_bare_homes_urls_and_escaped_json(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    url = "https://example.org/docs/home/guide/x"
    assert (
        g.public_text("HOME=/home/example and /Users/example")
        == "HOME=[local path] and [local path]"
    )
    assert g.public_text(url) == url
    assert g.public_text(str(Path.home())) == "[local path]"
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["summary"] = 'quoted /home/example/file\\"suffix and ' + url
    record["findings"] = [
        {"text": 'a quote " and /home/example', "status": "closed: false positive"}
    ]
    path.write_text(json.dumps(record))
    g.open("feature", "title", path, path, wait=False)
    comment = next(call for call in fake.calls if call[:2] == ["pr", "comment"])
    public = json.loads(Path(comment[-1]).read_text())
    assert "/home/example" not in json.dumps(public)
    assert '\\"suffix' in public["summary"] and url in public["summary"]
    encoded = json.dumps(record).replace("/", "\\/")
    decoded = json.loads(g.public_text(encoded))
    assert "/home/example" not in decoded["summary"] and url in decoded["summary"]


def test_review_resolves_worktree_once_and_still_detects_edits(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    calls = []
    original = g.worktree

    def locate(branch):
        calls.append(branch)
        return original(branch)

    monkeypatch.setattr(g, "worktree", locate)
    fake_reviewer(monkeypatch)
    g.review("feature", "codex")
    assert calls == ["feature"]
    real_run = subprocess.run

    def editing(args, **kwargs):
        result = real_run(args, **kwargs)
        if args[0] == "claude":
            (wt(repo, "feature") / "b.txt").write_text("unexpected edit")
        return result

    monkeypatch.setattr(subprocess, "run", editing)
    with pytest.raises(gate.Refused, match="became dirty"):
        g.review("feature", "codex")


@pytest.mark.parametrize("empty", ["[]", '{"findings": []}'])
@pytest.mark.parametrize("first", [True, False])
def test_empty_fixture_cannot_hide_priority_findings(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: str, first: bool
):
    g, fake = make(repo, ["pass"])
    body = tmp_path / "body"
    body.write_text("body")
    parts = [f"Fixture:\n```json\n{empty}\n```", "- [P1] The merge loses data"]
    fake_reviewer(monkeypatch, "\n".join(parts if first else parts[::-1]))
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("LEAD ACTION:") and "unclassified" in output[-1]
    assert not fake.calls and not g.review_file("feature").exists()


@pytest.mark.parametrize("stage", ["trial", "review", "open", "land"])
@pytest.mark.parametrize("worker", [True, False])
def test_auto_releases_on_every_failure_and_records_attempt(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, worker: bool
):
    g, _ = make(repo, ["pass"])
    second_branch(repo)
    body = tmp_path / "body"
    body.write_text("body")

    def fail(*_args):
        assert not flock_available(g)
        raise (gate.WorkerFailure if worker else gate.Refused)("failed")

    for name in ("trial", "review", "open", "land"):
        monkeypatch.setattr(g, name, fail if name == stage else lambda *_args: True)
    assert not g.auto("feature", "codex", "title", body)
    assert g.holder() is None and flock_available(g)
    attempt = json.loads(g._state_file("feature").with_suffix(".attempt.json").read_text())
    assert attempt == {
        "commit": sh(repo, "rev-parse", "feature"),
        "step": stage,
        "outcome": "worker_failure" if worker else "lead_action",
        "failures": 0 if worker else 1,
    }
    other = gate.Gate(repo, setup=[], checks=[["true"]])
    assert other.trial("second")


def test_pending_skips_attempted_trial_merge_until_worker_changes_head(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pass"], passing=False)
    before = sh(repo, "rev-parse", "feature")
    move_main(repo)
    body = tmp_path / "body"
    body.write_text("body")
    assert not g.auto("feature", "codex", "title", body)
    attempt = json.loads(g._state_file("feature").with_suffix(".attempt.json").read_text())
    assert attempt["commit"] == sh(repo, "rev-parse", "feature") != before
    real_run = subprocess.run

    def run(args, **kwargs):
        if args[1:3] == ["orchestration", "task-list"]:
            listing = {"result": {"tasks": [{"id": "task-1", "status": "completed"}]}}
            return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    g.gh = lambda _args: pytest.fail("unchanged attempts must not query GitHub")
    assert not g.pending()
    commit(wt(repo, "feature"), "fix.txt", "fix", "fix")
    g.gh = lambda _args: "[]"
    assert g.pending()


def test_windows_homes_are_scrubbed_in_every_public_channel(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    text = r"/mnt/c/Users/ExampleOwner/project/a.py C:\Users\ExampleOwner\project\b.py"
    text += r" C:/Users/ExampleOwner /mnt/D/users/ExampleOwner"
    fenced = "Example:\n```json\n" + json.dumps({"path": text}) + "\n```"
    assert "ExampleOwner" not in g.public_text(fenced)
    url = "https://example.org/mnt/c/Users/public/docs"
    assert "ExampleOwner" not in g.public_text(text)
    assert g.public_text(url) == url
    assert json.loads(g.public_text(json.dumps({"path": text})))["path"].count("[local path]") == 4
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["summary"] = text
    path.write_text(json.dumps(record))
    body = tmp_path / "body"
    body.write_text(text)
    g.open("feature", text, body, path, wait=False)
    g.land("feature", body)
    for call in fake.calls:
        assert "ExampleOwner" not in " ".join(call)
        if "--body-file" in call:
            posted = Path(call[call.index("--body-file") + 1]).read_text()
            assert "ExampleOwner" not in posted
            if call[:2] == ["pr", "comment"]:
                assert "[local path]" in json.loads(posted)["summary"]


@pytest.mark.parametrize("rejected", [True, False])
def test_auto_routes_rejected_push_to_worker_and_push_outage_to_lead(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rejected: bool
):
    g, fake = make(repo, ["pass"])
    body = tmp_path / "body"
    body.write_text("body")
    if rejected:
        sh(repo, "push", "-q", "origin", "feature")
        sh(wt(repo, "feature"), "commit", "--amend", "-qm", "rewritten")
    fake_reviewer(monkeypatch)
    real_run = subprocess.run

    def run(args, **kwargs):
        if not rejected and args[0] == "git" and "push" in args:
            return subprocess.CompletedProcess(args, 128, "", "Could not resolve host")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("SEND TO WORKER:" if rejected else "LEAD ACTION:")
    assert ("reconcile" if rejected else "resolve host") in output[-1]
    assert not fake.calls


@pytest.mark.parametrize("stage", ["open", "land"])
def test_cancelled_ci_is_a_lead_action(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
):
    g, _ = make(repo, ["cancel"])
    body = tmp_path / "body"
    body.write_text("body")
    fake_reviewer(monkeypatch)
    if stage == "land":
        original = g.open
        monkeypatch.setattr(g, "open", lambda *args: original(*args, wait=False))
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith(f"LEAD ACTION: feature: {stage}")
    assert "c0" in output[-1] and "re-run CI" in output[-1]


def test_failed_check_reports_both_streams_with_relative_locations(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VIRTUAL_ENV", "/home/example/irrelevant")
    script = (
        "import os,sys; from pathlib import Path; assert 'VIRTUAL_ENV' not in os.environ; "
        "print('progress'); print(str(Path.cwd()/'b.txt')+':12: stdout error'); "
        "print(str(Path.cwd()/'b.txt')+':19: fatal stderr error',file=sys.stderr); sys.exit(1)"
    )
    g, _ = make(repo, ["pass"], check=[sys.executable, "-c", script])
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert "b.txt:12: stdout error" in output[-1]
    assert "b.txt:19: fatal stderr error" in output[-1]
    assert str(wt(repo, "feature")) not in output[-1]
    assert str(wt(repo, "feature")) in g._state_file("feature").with_suffix(".log").read_text()


def test_open_posts_review_once_per_commit_even_after_retrial(repo: Path, tmp_path: Path):
    g, fake = make(repo, [])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    with pytest.raises(gate.Refused, match="no CI checks"):
        g.open("feature", "title", path, path)
    fake.existing_pr = True
    fake.ci = ["pass"]
    g.open("feature", "updated title", path, path)
    assert g.trial("feature")
    g.open("feature", "updated again", path, path)

    def comments():
        return [c for c in fake.calls if c[:2] == ["pr", "comment"]]

    assert len(comments()) == 1
    assert len([c for c in fake.calls if c[:2] == ["pr", "edit"]]) == 2
    commit(wt(repo, "feature"), "new.txt", "new", "new")
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    g.open("feature", "new commit", path, path)
    assert len(comments()) == 2


@pytest.mark.parametrize(
    "reason",
    [
        "the fixed-width parser is intentional",
        "fixed-width parsing is intentional",
        "out of scope, not addressed by this PR",
        "the resolved path is deliberately normalized",
    ],
)
def test_non_fix_closures_accept_descriptive_fix_words(repo: Path, tmp_path: Path, reason: str):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["findings"] = [{"text": "not a defect", "status": f"closed: {reason}"}]
    path.write_text(json.dumps(record))
    g.open("feature", "title", path, path, wait=False)


@pytest.mark.parametrize("primary", [True, False])
def test_dead_holder_cleanup_preserves_primary_failure(repo: Path, primary: bool):
    g, _ = make(repo, ["pass"])
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / ".agents/skills/lead/scripts/gate.py"),
            "_hold",
            str(g.lock_path),
            json.dumps(g._identity("feature")),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    original = gate.WorkerFailure("original check failure")
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
        with (
            pytest.raises(
                gate.Refused, match="original check" if primary else "cleanup failed"
            ) as caught,
            g.reservation("feature"),
        ):
            proc.kill()  # this test's own child PID only
            proc.wait(timeout=5)
            if primary:
                raise original
        if primary:
            assert caught.value is original
            assert "cleanup also failed" in original.__notes__[0]
        assert g._connection is None
        g.release()
        assert g.holder() is None and flock_available(g)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


@pytest.mark.parametrize("automatic", [False, True])
def test_disconnected_auto_releases_but_manual_reservation_persists(repo: Path, automatic: bool):
    import socket

    g, _ = make(repo, ["pass"])
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / ".agents/skills/lead/scripts/gate.py"),
            "_hold",
            str(g.lock_path),
            json.dumps(g._identity("feature")),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(g.lock_path.with_suffix(".sock")))
            identity = g._identity("feature")
            if automatic:
                identity["automatic"] = True
            client.sendall((json.dumps(identity) + "\n").encode())
            assert json.loads(client.recv(4096)) == {"ok": True}
            assert not flock_available(g)
        if automatic:
            assert proc.wait(timeout=5) == 0
            assert g.holder() is None and flock_available(g)
        else:
            # Same-connection handshake ensures the server has processed the EOF first.
            with g.reservation("feature"):
                assert not flock_available(g)
            assert proc.poll() is None and g.holder() == "feature"
            g.release()
            assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


def test_interrupted_auto_releases_and_records_outcome(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pass"])
    body = tmp_path / "body"
    body.write_text("body")

    def interrupt(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(g, "trial", interrupt)
    with pytest.raises(KeyboardInterrupt):
        g.auto("feature", "codex", "title", body)
    assert g.holder() is None and flock_available(g)
    attempt = json.loads(g._state_file("feature").with_suffix(".attempt.json").read_text())
    assert attempt["outcome"] == "lead_action"


def completed_listing(monkeypatch: pytest.MonkeyPatch, tasks=None):
    original = subprocess.run

    def run(args, **kwargs):
        if args[1:3] == ["orchestration", "task-list"]:
            data = {"result": {"tasks": [{"id": "task-1"}] if tasks is None else tasks}}
            return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)


def test_lead_closes_numbered_candidates_and_auto_resumes_without_paid_review(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, fake = make(repo, ["pass"])
    calls = fake_reviewer(monkeypatch, review_output("first candidate", "second candidate"))
    completed_listing(monkeypatch)
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("LEAD ACTION:")
    assert "1. " in output[-1] and "2. " in output[-1]
    assert "first candidate" in output[-1] and "second candidate" in output[-1]
    assert g.holder() is None and flock_available(g)
    assert g.attempt("feature")["outcome"] == "review_pending"
    assert not g.pending()
    assert output[-1] == "feature: waiting for lead dispositions"
    monkeypatch.setattr(g, "trial", lambda *_args: pytest.fail("same tested trial must be reused"))
    assert not g.auto("feature", "codex", "title", body)
    assert len(calls) == 1
    with monkeypatch.context() as cli:
        cli.setattr(gate, "Gate", lambda _path: g)
        assert (
            gate.main(
                [
                    "close",
                    "feature",
                    "1",
                    "guard already covers this",
                    "--also",
                    "2",
                    "not reachable",
                ]
            )
            == 0
        )
    assert g.holder() is None
    assert g.pending()
    assert g.auto("feature", "codex", "title", body)
    assert len(calls) == 1
    assert any(call[:2] == ["pr", "merge"] for call in fake.calls)


@pytest.mark.parametrize("reason", ["", "fixed", "closed: fixed in abc", "This was repaired"])
def test_close_rejects_fix_claims_atomically(
    repo: Path, monkeypatch: pytest.MonkeyPatch, reason: str
):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    fake_reviewer(monkeypatch, review_output("one", "two"))
    with pytest.raises(gate.ReviewPending):
        g.review("feature", "codex")
    before = g.review_file("feature").read_text()
    with pytest.raises(gate.Refused):
        g.close("feature", [(1, "false positive"), (2, reason)])
    assert g.review_file("feature").read_text() == before
    with pytest.raises(gate.Refused, match="outside"):
        g.close("feature", [(3, "false positive")])
    assert g.review_file("feature").read_text() == before


def test_new_head_invalidates_closed_review(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pass"])
    calls = fake_reviewer(monkeypatch, review_output("candidate"))
    body = tmp_path / "body"
    body.write_text("body")
    assert not g.auto("feature", "codex", "title", body)
    g.close("feature", [(1, "false positive")])
    commit(wt(repo, "feature"), "new.txt", "new", "new work")
    with pytest.raises(gate.Refused, match="moved"):
        g.close("feature", [(1, "false positive")])
    assert not g.auto("feature", "codex", "title", body)
    assert len(calls) == 2
    assert json.loads(g.review_file("feature").read_text())["findings"][0]["status"] == "open"


@pytest.mark.parametrize("level", ["medium", "high"])
def test_claude_schema_and_read_only_tools(repo: Path, monkeypatch: pytest.MonkeyPatch, level: str):
    g, _ = make(repo, ["pass"])
    g.review_level = level
    assert g.trial("feature")
    calls = fake_reviewer(monkeypatch)
    g.review("feature", "codex")
    args, options = calls[0]
    assert f"{level}-depth" in args[2]
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert schema["properties"]["findings"]["items"]["required"] == [
        "file",
        "line",
        "summary",
        "failure_scenario",
    ]
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob"
    assert "mcp__*" in args[args.index("--disallowedTools") + 1]
    assert options["input"] == sh(wt(repo, "feature"), "diff", "origin/main...HEAD")
    assert options["timeout"] == 900


@pytest.mark.parametrize("builder", ["codex", "claude"])
def test_reviewer_deadline_returns_to_lead_and_releases(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder: str
):
    g, _ = make(repo, ["pass"], builder=builder)
    g.review_timeout = 0.02
    original = subprocess.run

    def run(args, **kwargs):
        if args[0] in {"claude", "codex"}:
            return original(
                [sys.executable, "-c", "import time; print('partial',flush=True); time.sleep(10)"],
                capture_output=True,
                timeout=kwargs["timeout"],
            )
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    assert not g.auto("feature", builder, "title", body)
    assert output[-1].startswith("LEAD ACTION:") and "deadline" in output[-1]
    assert g.holder() is None and flock_available(g)
    assert g._state_file("feature").with_suffix(".review.log").exists()


def test_ci_deadline_returns_to_lead_and_releases(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pending"])
    fake_reviewer(monkeypatch)
    g.ci_timeout = 0.01
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("LEAD ACTION:") and "CI deadline" in output[-1]
    assert g.holder() is None and flock_available(g)


@pytest.mark.parametrize(
    "outcome,failures,expected",
    [
        ("worker_failure", 0, False),
        ("running", 0, True),
        ("lead_action", 1, True),
        ("lead_action", 2, True),
        ("lead_action", 3, False),
    ],
)
def test_pending_retries_dead_or_transient_attempts_with_bound(
    repo: Path, monkeypatch: pytest.MonkeyPatch, outcome: str, failures: int, expected: bool
):
    g, _ = make(repo, ["pass"])
    completed_listing(monkeypatch)
    g._attempt = {
        "commit": sh(repo, "rev-parse", "feature"),
        "outcome": outcome,
        "failures": failures,
    }
    g._save_attempt("feature")
    output = []
    g.say = output.append
    if not expected:
        monkeypatch.setattr(g, "_main", lambda: pytest.fail("waiting branch must not fetch"))
    assert g.pending() is expected
    if not expected:
        assert "waiting for" in output[-1]


def test_transient_failure_count_is_recorded_across_retries(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pending"])
    g.ci_timeout = 0.001
    calls = fake_reviewer(monkeypatch)
    body = tmp_path / "body"
    body.write_text("body")
    for count in range(1, 4):
        assert not g.auto("feature", "codex", "title", body)
        assert g.attempt("feature")["failures"] == count
    assert len(calls) == 1


def test_release_cleans_stale_after_empty_handshake(repo: Path, monkeypatch: pytest.MonkeyPatch):
    g, _ = make(repo, ["pass"])
    probes = iter([(False, "feature"), (True, "feature")])
    monkeypatch.setattr(g, "_release_stale", lambda: next(probes))
    monkeypatch.setattr(g, "holder", lambda: "feature")

    def empty(*_args):
        raise ValueError("empty handshake")

    monkeypatch.setattr(g, "reservation", empty)
    assert g.release() == "feature"


@pytest.mark.parametrize("holder", ["feature", "other"])
def test_legacy_lock_blocks_new_gate_before_trial(
    repo: Path, monkeypatch: pytest.MonkeyPatch, holder: str
):
    g, _ = make(repo, ["pass"])
    legacy = g.home / "lock"
    legacy.write_text(holder)
    monkeypatch.setattr(g, "_main", lambda: pytest.fail("must not fetch past old lock"))
    with pytest.raises(gate.Refused, match=f"legacy landing lock .* holds {holder}"):
        g.trial("feature")
    with pytest.raises(gate.Refused, match="legacy landing lock"):
        g.release()
    assert legacy.read_text() == holder and not g.lock_path.exists()


def test_rejected_push_message_scrubs_home_paths(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pass"])
    fake_reviewer(monkeypatch)
    original = subprocess.run

    def run(args, **kwargs):
        if args[0] == "git" and "push" in args:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "[rejected] /home/private-owner/hooks/reject C:\\Users\\private-owner\\hook",
            )
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    assert not g.auto("feature", "codex", "title", body)
    assert output[-1].startswith("SEND TO WORKER:") and "private-owner" not in output[-1]


def test_pending_without_candidates_never_fetches(repo: Path, monkeypatch: pytest.MonkeyPatch):
    g, _ = make(repo, ["pass"])
    completed_listing(monkeypatch, [])
    monkeypatch.setattr(g, "_main", lambda: pytest.fail("empty queue must not fetch"))
    assert not g.pending()


def test_manual_review_deadline_also_releases(repo: Path, monkeypatch: pytest.MonkeyPatch):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    original = subprocess.run

    def run(args, **kwargs):
        if args[0] == "claude":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=b"partial log")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(gate.Refused, match="deadline"):
        g.review("feature", "codex")
    assert g.holder() is None and flock_available(g)
    assert g._state_file("feature").with_suffix(".review.log").read_text() == "partial log"


def test_manual_ci_deadline_also_releases(repo: Path, tmp_path: Path):
    g, _ = make(repo, ["pending"])
    g.ci_timeout = 0.001
    assert g.trial("feature")
    review = review_record(g, tmp_path)
    with pytest.raises(gate.Refused, match="CI deadline"):
        g.open("feature", "title", review, review)
    assert g.holder() is None and flock_available(g)


def test_ci_query_uses_remaining_deadline(repo: Path, monkeypatch: pytest.MonkeyPatch):
    g, _ = make(repo, ["pass"])
    g.gh = gate.real_gh
    g.check_timeout = 10
    timeouts = []

    def run(args, **kwargs):
        timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        with pytest.raises(gate.Refused, match="deadline"):
            g.wait_checks(7, gate.time.monotonic() + 0.2)
    assert 0 < timeouts[0] <= 0.2


@pytest.mark.parametrize("flag", ["--review-timeout", "--ci-timeout"])
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_cli_refuses_unbounded_or_invalid_deadlines(flag: str, value: str):
    with pytest.raises(SystemExit):
        gate.main(["auto", "branch", "--builder", "codex", "title", "body", flag, value])


def test_clean_structured_codex_review_lands_claude_built_branch(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, fake = make(repo, ["pass"], builder="claude")
    calls = fake_reviewer(monkeypatch)
    body = tmp_path / "body"
    body.write_text("body")
    assert g.auto("feature", "claude", "title", body)
    assert len(calls) == 1 and calls[0][0][:2] == ["codex", "exec"]
    record = json.loads(g.review_file("feature").read_text())
    assert record["findings"] == [] and record["reviewer"] == "codex"
    assert record["tested"] == g.state("feature")["tested"]
    assert any(call[:2] == ["pr", "merge"] for call in fake.calls)
    assert flock_available(g)


@pytest.mark.parametrize(
    "final",
    [
        "",
        "No actionable regressions were identified.",
        "- [P1] A bug — src/file.py:1\nDetails",
        '```json\n{"findings": []}\n```',
        "[]",
        "null",
        "{}",
        '{"findings": null}',
        '{"findings": [], "unexpected": "data"}',
        '{"findings": [{"file":"file.py","line":1,"summary":"bug"}]}',
        '{"findings": [{"file":"file.py","line":true,"summary":"bug","failure_scenario":"case"}]}',
        '{"findings": [{"file":"file.py","line":0,"summary":"bug","failure_scenario":"case"}]}',
        '{"findings": [{"file":"file.py","line":1,"summary":" ","failure_scenario":"case"}]}',
        '{"findings": [{"file":"file.py","line":1,"summary":"bug",'
        '"failure_scenario":"case","extra":1}]}',
    ],
)
def test_unclassified_codex_result_never_records_clean_or_publishes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final: str
):
    g, fake = make(repo, ["pass"], builder="claude")
    fake_reviewer(monkeypatch, final)
    body = tmp_path / "body"
    body.write_text("body")
    output = []
    g.say = output.append
    assert not g.auto("feature", "claude", "title", body)
    assert output[-1].startswith("LEAD ACTION:") and "unclassified" in output[-1]
    assert not g.review_file("feature").exists() and not fake.calls
    assert g._state_file("feature").with_suffix(".final.txt").read_text() == final
    assert g.holder() is None and flock_available(g)


def test_malformed_codex_retry_bound_still_applies(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, _ = make(repo, ["pass"], builder="claude")
    calls = fake_reviewer(monkeypatch, "No actionable regressions were found in the changes.")
    completed_listing(monkeypatch)
    body = tmp_path / "body"
    body.write_text("body")
    for number in range(1, 4):
        assert g.pending()
        assert not g.auto("feature", "claude", "title", body)
        assert g.attempt("feature")["failures"] == number
    output = []
    g.say = output.append
    assert not g.pending()
    assert "retry limit reached" in output[-1]
    assert len(calls) == 3 and not g.review_file("feature").exists()


@pytest.mark.parametrize("builder", ["codex", "claude"])
@pytest.mark.parametrize("result", ["clean", "findings", "malformed", "exit", "timeout"])
def test_rereview_revokes_stored_approval_before_model_and_requires_reopen(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder: str, result: str
):
    g, fake = make(repo, ["pass"], builder=builder)
    assert g.trial("feature")
    fake_reviewer(monkeypatch)
    g.review("feature", builder)
    body = tmp_path / "body"
    body.write_text("body")
    g.open("feature", "title", body, wait=False)
    old = g.state("feature")
    assert "review" in old and old["pr"] == 7
    final = review_output("new candidate") if result == "findings" else review_output()
    if result == "malformed":
        final = "not a schema object"
    fake_reviewer(monkeypatch, final, code=1 if result == "exit" else 0)
    original = subprocess.run

    def run(args, **kwargs):
        if args[0] in {"codex", "claude"}:
            # Inspect durable state during the model call, not merely after it returns.
            assert "review" not in g.state("feature")
            assert not g.review_file("feature").exists()
            if result == "timeout":
                raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=b"partial")
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    if result == "clean":
        g.review("feature", builder)
    else:
        with pytest.raises(gate.Refused):
            g.review("feature", builder)
    state = g.state("feature")
    assert state["tested"] == old["tested"] and state["pr"] == 7
    assert "review" not in state
    # Timeout releases the reservation; reacquiring it alone must not restore approval.
    with (
        g.reservation("feature", create=True),
        pytest.raises(gate.Refused, match="no validated review"),
    ):
        g.land("feature")
    assert not any(call[:2] == ["pr", "merge"] for call in fake.calls)
    if result == "clean":
        fake.existing_pr = True
        body = tmp_path / "body"
        body.write_text("body")
        g.open("feature", "title", body, wait=False)
        assert g.state("feature")["review"] == json.loads(g.review_file("feature").read_text())
        g.land("feature")
        assert g.holder() is None


def test_changed_rereview_posts_closed_findings_once_on_same_commit(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    g, fake = make(repo, ["pass"])
    snapshots = []

    def gh(args):
        if args[:2] == ["pr", "comment"]:
            snapshots.append(json.loads(Path(args[-1]).read_text()))
        return fake(args)

    g.gh = gh
    assert g.trial("feature")
    fake_reviewer(monkeypatch)
    g.review("feature", "codex")
    body = tmp_path / "body"
    body.write_text("body")
    g.open("feature", "title", body, wait=False)
    fake.existing_pr = True
    fake_reviewer(monkeypatch, review_output("candidate from rereview"))
    with pytest.raises(gate.ReviewPending):
        g.review("feature", "codex")
    g.close("feature", [(1, "existing guard excludes the failure scenario")])
    g.open("feature", "title", body, wait=False)
    g.open("feature", "title", body, wait=False)
    assert len(snapshots) == 2
    assert snapshots[0]["tested"] == snapshots[1]["tested"]
    assert snapshots[0]["findings"] == []
    assert "candidate from rereview" in snapshots[1]["findings"][0]["text"]
    assert snapshots[1]["findings"][0]["status"] == (
        "closed: existing guard excludes the failure scenario"
    )
    ledger = json.loads(g._state_file("feature").with_suffix(".posted.json").read_text())
    assert len(ledger) == 2 and ledger[0]["tested"] == ledger[1]["tested"]
    assert ledger[0]["review_sha256"] != ledger[1]["review_sha256"]
    assert g.state("feature")["review"] == snapshots[1]
    g.land("feature")
    assert any(call[:2] == ["pr", "merge"] for call in fake.calls)


def test_review_digest_uses_canonical_public_record(repo: Path, tmp_path: Path):
    g, fake = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["summary"] = "See /home/first-owner/private.txt"
    path.write_text(json.dumps(record))
    g.open("feature", "title", path, path, wait=False)
    fake.existing_pr = True
    record["summary"] = "See /home/second-owner/private.txt"
    path.write_text(json.dumps(dict(reversed(list(record.items())))))
    g.open("feature", "title", path, path, wait=False)
    assert len([c for c in fake.calls if c[:2] == ["pr", "comment"]]) == 1
    # A pre-digest ledger cannot establish which review it published: post once to upgrade it.
    ledger = g._state_file("feature").with_suffix(".posted.json")
    ledger.write_text(json.dumps([{"pr": 7, "tested": g.state("feature")["tested"]}]))
    g.open("feature", "title", path, path, wait=False)
    g.open("feature", "title", path, path, wait=False)
    assert len([c for c in fake.calls if c[:2] == ["pr", "comment"]]) == 2
