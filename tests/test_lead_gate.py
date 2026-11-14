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
    repo: Path, ci: list[str], passing: bool = True, check: list[str] | None = None
) -> tuple[Any, FakeGh]:
    fake = FakeGh(repo.parent / "origin.git", ci)
    if check is None:
        check = ["test", "-f", "b.txt"] if passing else ["test", "-f", "missing.txt"]
    g = gate.Gate(repo, gh=fake, setup=[], checks=[check])
    g.say = lambda _line: None
    g.register("feature", "codex", "task-1")
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
    assert ["pr", "comment", "7", "--body-file", str(tmp_path / "review.json")] in fake.calls
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
            output = json.dumps({"subtype": "success", "is_error": False, "result": final})
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
    g, fake = make(repo, ["pass"])
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
        assert cmd[:5] == ["codex", "exec", "review", "--base", "origin/main"]
        assert "--ignore-user-config" in cmd and "model_reasoning_effort=high" in cmd
        assert "--output-schema" not in cmd
    else:
        assert cmd[:3] == ["claude", "-p", "/code-review high feature"]
        assert cmd[cmd.index("--output-format") + 1] == "json"
    (tmp_path / "body.md").write_text("body")
    g.open("feature", "title", tmp_path / "body.md", wait=False)
    assert ["pr", "comment", "7", "--body-file", str(path)] in fake.calls


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


@pytest.mark.parametrize("status", ["fixed", "closed: already covered by the existing guard"])
def test_manual_review_dispositions_are_accepted(repo: Path, tmp_path: Path, status: str):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    path = review_record(g, tmp_path)
    record = json.loads(path.read_text())
    record["findings"] = [{"text": "a finding", "status": status}]
    path.write_text(json.dumps(record))
    assert g.open("feature", "title", path, path, wait=False) == 7


@pytest.mark.parametrize(
    "final",
    [
        '{"findings": [{"title": "[P1] A bug", "body": "explanation"}]}',
        "- [P1] A bug — file.py:1\n  explanation",
        "I could not complete the review.",
    ],
)
def test_review_never_silently_closes_findings(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    final: str,
):
    g, _ = make(repo, ["pass"])
    assert g.trial("feature")
    fake_reviewer(monkeypatch, final)
    with pytest.raises(gate.Refused, match="unresolved"):
        g.review("feature", "codex")
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
                raise gate.Refused("specific failure")
            return True

        return invoke

    for name in ("trial", "review", "open", "land"):
        monkeypatch.setattr(g, name, step(name))
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
        with pytest.raises(gate.Refused, match="another process holds"):
            g.trial("feature")
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
            data = {"ok": True, "result": {"tasks": [{"id": "task-1", "status": status}]}}
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


def test_claude_prose_with_json_array_keeps_every_finding_separate():
    final = 'Two findings:\n```json\n[{"summary":"one"},{"summary":"two"}]\n```'
    assert len(gate.Gate.findings(final)) == 2
    assert all(f["status"] == "open" for f in gate.Gate.findings(final))
    assert gate.Gate.findings("Review incomplete\n```json\n[]\n```")[0]["status"] == "open"


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
