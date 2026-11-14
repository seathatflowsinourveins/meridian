"""The lead's merge gate: one landing at a time, a tested tree, a pinned squash-merge (own design).

    gate.py register BRANCH --builder codex|claude --task TASK_ID
    gate.py auto BRANCH --builder codex|claude TITLE BODY
    gate.py trial BRANCH [--builder codex|claude]
    gate.py review BRANCH --builder codex|claude
    gate.py close BRANCH NUMBER REASON [--also NUMBER REASON ...]
    gate.py open BRANCH TITLE BODY [REVIEW.json]
    gate.py land BRANCH [SQUASH]
    gate.py release
    gate.py pending [--run RUN_ID]

State and review/check logs live under the common git directory's meridian-gate/.
A local holder retains ~/.cache/meridian/landing.lock with flock through the whole
landing, including gaps between commands. Its adjacent owner record and Unix socket
name the repository and branch; each command holds one socket connection, serializing
commands even for the same branch. land or release ends the holder, without killing a
PID. An interrupted manual client leaves the reservation intact; auto always releases it.
If the holder itself dies,
trial starts a new one and retests; open/land cannot resume an unheld reservation.

`trial` merges origin/main on the branch itself, in the worktree that has it checked out (a
merge commit; never a rebase or a force), and refuses on a dirty worktree or a conflict; the
tested tree is that commit's tree. `open` pushes the branch as it is, a plain push, so a branch
rewritten after an earlier push is refused by git and goes back to the worker.

Remaining window: `land` fetches main and compares the trial-merged tree as the last step before
`gh pr merge`, but GitHub's merge is not conditioned on main's revision, so a push to main in the
seconds between that fetch and the merge lands an untested tree; the post-merge comparison then
FAILs loudly. Only branch protection requiring an up-to-date branch (also for administrators), an
owner's repository setting, closes it.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import select
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path

SETUP = [["uv", "sync", "--locked"]]
CHECKS = [
    ["uv", "run", "ruff", "check", "."],
    ["uv", "run", "ruff", "format", "--check", "."],
    ["uv", "run", "pyright"],
    ["uv", "run", "pytest", "-q"],
    ["gitleaks", "git", "--redact", "--no-banner", "--log-opts=origin/main..HEAD", "."],
]
GREEN = {"pass", "skipping"}  # `gh pr checks --json bucket`; everything else is not green
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "minLength": 1},
                    "line": {"type": "integer", "minimum": 1},
                    "summary": {"type": "string", "minLength": 1},
                    "failure_scenario": {"type": "string", "minLength": 1},
                },
                "required": ["file", "line", "summary", "failure_scenario"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

Gh = Callable[[Sequence[str]], str]


class Refused(Exception):
    """The gate will not go on; the message says why."""


class WorkerFailure(Refused):
    """A concrete code/check defect for the worker to fix."""


class ReviewPending(Refused):
    """Reviewer candidates require the lead's dispositions."""


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise Refused(f"git {args[0]} failed: {(out.stderr or out.stdout).strip()[-200:]}")
    return out.stdout.strip()


def real_gh(args: Sequence[str], timeout: float = 60.0) -> str:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise Refused(f"gh {' '.join(args[:2])} deadline exceeded") from exc
    # `gh pr checks` exits non-zero while a check fails or is pending, and still prints its JSON.
    json_checks = list(args[:2]) == ["pr", "checks"] and "--json" in args
    reported = json_checks and out.stdout.strip()
    if json_checks and out.returncode and "no checks reported" in out.stderr.lower():
        return "[]"
    if out.returncode != 0 and not reported:
        raise Refused(f"gh {' '.join(args[:2])} failed: {out.stderr.strip()[-200:]}")
    return out.stdout.strip()


def guarded(*, create: bool = False):
    """Reserve explicitly; auto owns its one error-handling site."""

    def decorate(method):
        @wraps(method)
        def call(self, branch, *args, **kwargs):
            with self.reservation(branch, create=create):
                return method(self, branch, *args, **kwargs)

        return call

    return decorate


def lock_server(path: Path, owner: dict) -> int:
    """Retain flock between commands; serve contenders while a command is active."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sock_path = path.with_suffix(".sock")
    record = path.with_suffix(".owner.json")
    active = stream = None
    automatic = False
    released = False
    with path.open("a+") as lock, socket.socket(socket.AF_UNIX) as server:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another process holds landing.lock", flush=True)
            return 1
        sock_path.unlink(missing_ok=True)
        server.bind(str(sock_path))
        os.chmod(sock_path, 0o600)
        server.listen()
        record.write_text(json.dumps(owner) + "\n")
        print("ready", flush=True)
        try:
            while True:
                ready, _, _ = select.select([server, active] if active else [server], [], [])
                if active is not None and active in ready and stream is not None:
                    try:
                        finish = stream.readline(32).strip() == b"release" or automatic
                    except OSError:
                        finish = automatic
                    if finish:
                        record.unlink(missing_ok=True)
                        sock_path.unlink(missing_ok=True)
                        fcntl.flock(lock, fcntl.LOCK_UN)
                        released = True
                        with suppress(OSError):
                            active.sendall(b"released\n")
                        return 0
                    with suppress(OSError):
                        active.sendall(b"done\n")
                    stream.close()
                    active.close()
                    active = stream = None
                if server not in ready:
                    continue
                conn, _ = server.accept()
                # Unbuffered reads prevent a pipelined finish being hidden from select.
                incoming = conn.makefile("rb", buffering=0)
                try:
                    conn.settimeout(1)
                    request = json.loads(incoming.readline(8192))
                    requested_auto = (
                        request.pop("automatic", False) if isinstance(request, dict) else False
                    )
                    if not isinstance(request, dict):
                        error = "landing handshake must be an object"
                    elif request != owner:
                        error = (
                            f"{owner['branch']} is landing; the landing lock does not name "
                            f"{request.get('branch')} in this repository"
                        )
                    elif active is not None:
                        error = f"{owner['branch']} is landing; a command is already running"
                    else:
                        error = None
                    conn.sendall(
                        (json.dumps({"error": error} if error else {"ok": True}) + "\n").encode()
                    )
                    if error is None:
                        conn.settimeout(None)
                        active, stream = conn, incoming
                        automatic = requested_auto
                        continue
                except OSError, ValueError:
                    pass
                incoming.close()
                conn.close()
        finally:
            if not released:
                record.unlink(missing_ok=True)
                sock_path.unlink(missing_ok=True)
            if stream is not None:
                stream.close()
            if active is not None:
                active.close()
    return 0


class Gate:
    def __init__(self, repo: Path, gh: Gh = real_gh, setup=SETUP, checks=CHECKS) -> None:
        self.repo = Path(git(repo, "rev-parse", "--show-toplevel"))
        common = Path(git(self.repo, "rev-parse", "--git-common-dir"))
        self.home = (common if common.is_absolute() else self.repo / common) / "meridian-gate"
        self.home.mkdir(exist_ok=True)
        self.gh, self.setup, self.checks = gh, setup, checks
        self.say: Callable[[str], None] = print
        self.lock_path = Path.home() / ".cache/meridian/landing.lock"
        self._connection: socket.socket | None = None
        self._finish = False
        self._attempt: dict | None = None
        self.check_timeout = 120.0
        self.check_interval = 2.0
        self.review_timeout = 900.0
        self.ci_timeout = 1800.0
        self.review_level = "medium"
        self.retry_limit = 3

    # --- state and lock ------------------------------------------------------------------------
    def _state_file(self, branch: str) -> Path:
        return self.home / (hashlib.sha256(branch.encode()).hexdigest() + ".json")

    def state(self, branch: str) -> dict:
        f = self._state_file(branch)
        if not f.is_file():
            raise Refused(f"no trial recorded for {branch}; run trial first")
        return json.loads(f.read_text())

    def _save(self, branch: str, state: dict) -> None:
        self._state_file(branch).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    def _identity(self, branch: str) -> dict:
        return {"repo": str(self.home.resolve()), "branch": branch}

    def _check_legacy(self) -> None:
        legacy = self.home / "lock"
        if legacy.exists():
            raise Refused(
                f"legacy landing lock {legacy} holds {legacy.read_text().strip()}; "
                "finish or release it with the old gate before upgrading"
            )

    @contextmanager
    def reservation(
        self, branch: str, create: bool = False, automatic: bool = False
    ) -> Iterator[None]:
        self._check_legacy()
        if self._connection is not None:
            yield
            return
        conn = socket.socket(socket.AF_UNIX)
        conn.settimeout(2)
        try:
            try:
                conn.connect(str(self.lock_path.with_suffix(".sock")))
            except FileNotFoundError, ConnectionRefusedError:
                if not create:
                    raise Refused(f"the landing lock does not name {branch}; run trial") from None
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "_hold",
                        str(self.lock_path),
                        json.dumps(self._identity(branch)),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                assert proc.stdout is not None
                ready = proc.stdout.readline().decode().strip()
                proc.stdout.close()
                if ready != "ready":
                    proc.wait()
                    raise Refused(ready or "landing lock holder failed to start") from None
                conn.connect(str(self.lock_path.with_suffix(".sock")))
            with conn.makefile("rb", buffering=0) as stream:
                request = self._identity(branch)
                if automatic:
                    request["automatic"] = True
                conn.sendall((json.dumps(request) + "\n").encode())
                try:
                    reply = json.loads(stream.readline())
                except TimeoutError as exc:
                    raise Refused(f"{self.holder()} is landing; lock handshake timed out") from exc
                if "error" in reply:
                    raise Refused(reply["error"])
                conn.settimeout(None)
                self._connection = conn
                self._finish = False
                try:
                    yield
                finally:
                    primary = sys.exception()
                    try:
                        finish = self._finish or automatic
                        conn.sendall(b"release\n" if finish else b"done\n")
                        expected = b"released\n" if finish else b"done\n"
                        if stream.readline(32) != expected:
                            raise OSError("landing holder disconnected before acknowledging")
                    except OSError as exc:
                        if primary is None:
                            raise Refused(f"landing reservation cleanup failed: {exc}") from exc
                        primary.add_note(f"landing reservation cleanup also failed: {exc}")
                    finally:
                        self._connection = None
        finally:
            conn.close()

    def holder(self) -> str | None:
        record = self.lock_path.with_suffix(".owner.json")
        return json.loads(record.read_text())["branch"] if record.exists() else None

    def _release_stale(self) -> tuple[bool, str | None]:
        """Only the shared flock proves that nobody can still own these leftovers."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False, None
            try:
                holder = self.holder()
            except ValueError, KeyError, TypeError:
                holder = "unreadable owner"
            self.lock_path.with_suffix(".owner.json").unlink(missing_ok=True)
            self.lock_path.with_suffix(".sock").unlink(missing_ok=True)
            return True, holder

    def release(self) -> str | None:
        self._check_legacy()
        stale, holder = self._release_stale()
        if not stale:
            try:
                holder = self.holder()
                if not holder:
                    raise Refused("another process holds landing.lock without a gate owner")
                with self.reservation(holder):
                    self._finish = True
            except Refused, OSError, ValueError:
                # The holder may have died between the flock probe and the handshake.
                stale, holder = self._release_stale()
                if not stale:
                    raise
        self.say(f"released the lock of {holder}" if holder else "no lock was held")
        return holder

    def _main(self) -> str:
        git(self.repo, "fetch", "-q", "origin")
        return git(self.repo, "rev-parse", "origin/main")

    def _merged_tree(self, main: str, commit: str) -> str:
        return git(self.repo, "merge-tree", "--write-tree", main, commit).splitlines()[0]

    # --- (a) trial ------------------------------------------------------------------------------
    def worktree(self, branch: str) -> Path:
        """The worktree that has the branch checked out: the trial merges main there."""
        entries = git(self.repo, "worktree", "list", "--porcelain").split("\n\n")
        for entry in entries:
            lines = entry.splitlines()
            if f"branch refs/heads/{branch}" in lines:
                return Path(lines[0].removeprefix("worktree "))
        raise Refused(f"{branch} is not checked out in any worktree")

    @guarded(create=True)
    def trial(self, branch: str, builder: str | None = None) -> bool:
        builder = self.builder(branch, builder)
        main = self._main()
        wt = self.worktree(branch)
        if git(wt, "status", "--porcelain"):
            raise WorkerFailure(
                f"{branch}'s worktree {wt} has uncommitted changes; the worker commits"
            )
        if subprocess.run(
            ["git", "-C", str(wt), "merge-base", "--is-ancestor", main, "HEAD"]
        ).returncode:
            merge = ["git", "-C", str(wt), "merge", "-q", "--no-edit", main]
            if subprocess.run(merge, capture_output=True).returncode:
                subprocess.run(["git", "-C", str(wt), "merge", "--abort"], capture_output=True)
                raise WorkerFailure(f"origin/main conflicts with {branch}; the worker resolves it")
        tested = git(wt, "rev-parse", "HEAD")
        if self._attempt is not None:
            if self._attempt["commit"] != tested:
                self._attempt["failures"] = 0
            self._attempt["commit"] = tested
            self._save_attempt(branch)
        results = self._run_checks(wt, branch)
        # The checks read the worktree: it must still be exactly the commit being certified.
        moved = git(wt, "rev-parse", "HEAD") != tested
        dirty = git(wt, "status", "--porcelain")
        if moved or dirty:
            why = "HEAD moved" if moved else f"{len(dirty.splitlines())} paths changed"
            self.say(f"  FAIL the worktree changed during the checks ({why})")
            last = f"the worktree changed during the checks ({why})"
            results.append({"check": "worktree unchanged", "passed": False, "last": last})
        ok = all(r["passed"] for r in results)
        tree = git(self.repo, "rev-parse", f"{tested}^{{tree}}")
        state = {
            "main": main,
            "tested": tested,
            "tree": tree,
            "checks": results,
            "passed": ok,
            "builder": builder,
        }
        self._save(branch, state)
        self.say(f"{'PASS' if ok else 'FAIL'} {branch}: tested {tested[:12]} on main {main[:12]}")
        return ok

    @staticmethod
    def plain_text(text: str) -> str:
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)

    def public_value(self, value, worktree: Path | None = None):
        """Sanitize decoded JSON values, never edit serialized JSON escape sequences."""
        if isinstance(value, str):
            return self.public_text(value, worktree)
        if isinstance(value, list):
            return [self.public_value(item, worktree) for item in value]
        if isinstance(value, dict):
            return {
                self.public_text(key, worktree): self.public_value(item, worktree)
                for key, item in value.items()
            }
        return value

    def public_text(self, text: str, worktree: Path | None = None) -> str:
        plain = self.plain_text(text)
        try:
            value = json.loads(plain)
            if isinstance(value, (dict, list)):
                return json.dumps(self.public_value(value, worktree), ensure_ascii=False)
        except ValueError:
            pass
        roots = sorted({str(self.repo), str(worktree or self.repo)}, key=len, reverse=True)
        home = str(Path.home())

        def scrub(match: re.Match) -> str:
            token = match[0]
            if re.match(r"[A-Za-z][\w+.-]*://", token):
                if token.startswith("file://"):
                    return self.public_text(token[7:], worktree)
                return token  # /home/ in an HTTP URL is not a local home directory
            path = token.rstrip(".,;:)]}")
            suffix = token[len(path) :]
            for root in roots:
                if path.startswith(root + "/"):
                    return path[len(root) + 1 :] + suffix
            if (
                path == home
                or path.startswith(home + "/")
                or path.startswith("~/")
                or re.match(r"^/(?:home|Users)/[^/]+(?:/|$)", path)
                or re.match(r"^/mnt/[a-z]/Users/[^/]+(?:/|$)", path, re.I)
                or re.match(r"^[a-z]:[\\/]+Users[\\/]+[^\\/]+(?:[\\/]|$)", path, re.I)
            ):
                return "[local path]" + suffix
            return token

        return re.sub(
            r"[A-Za-z][\w+.-]*://[^\s<>\"'`]+|"
            r"(?<!\w)[A-Za-z]:[\\/][^\s<>\"'`]+|"
            r"(?<![\w/])(?:/|~/)[^\s<>\"'`\\]+",
            scrub,
            plain,
        )

    def _run_checks(self, wt: Path, branch: str) -> list[dict]:
        log = self._state_file(branch).with_suffix(".log")
        results = []
        env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
        env["NO_COLOR"] = "1"
        with log.open("w") as out:
            for cmd in [*self.setup, *self.checks]:
                try:
                    run = subprocess.run(cmd, cwd=wt, capture_output=True, text=True, env=env)
                    code, text = run.returncode, run.stdout + run.stderr
                    summary = run.stdout.strip() or run.stderr.strip()
                    if code:
                        tails = [
                            "\n".join(
                                line[:500]
                                for line in [line for line in part.splitlines() if line.strip()][
                                    -3:
                                ]
                            )
                            for part in (run.stdout, run.stderr)
                        ]
                        summary = "\n".join(tail for tail in tails if tail)
                except FileNotFoundError:
                    code, text = 127, f"{cmd[0]}: not found"
                    summary = text
                out.write(f"$ {' '.join(cmd)}\n{self.plain_text(text)}\n")
                public = self.public_text(summary, wt).strip()
                last = public if code else (public.splitlines() or [""])[-1][:120]
                if cmd in self.checks:
                    results.append({"check": " ".join(cmd), "passed": code == 0, "last": last})
                self.say(f"  {'ok  ' if code == 0 else 'FAIL'} {' '.join(cmd)}: {last}")
                if code and cmd in self.setup:
                    return [{"check": " ".join(cmd), "passed": False, "last": last}]
        return results

    def wait_checks(self, pr: int, deadline: float | None = None) -> list[dict]:
        deadline = min(deadline or float("inf"), time.monotonic() + self.check_timeout)
        while True:
            args = ["pr", "checks", str(pr), "--json", "name,bucket"]
            response = (
                real_gh(args, timeout=max(0.001, deadline - time.monotonic()))
                if self.gh is real_gh
                else self.gh(args)
            )
            checks = json.loads(response)
            if checks:
                return checks
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Refused(
                    f"no CI checks appeared for PR #{pr} within {self.check_timeout:g}s; "
                    "retry open or land after GitHub registers checks"
                )
            self.say(f"waiting for GitHub to register CI checks for PR #{pr}")
            time.sleep(min(self.check_interval, remaining))

    @staticmethod
    def green_checks(checks: list[dict]) -> bool:
        red = [c["name"] for c in checks if c["bucket"] == "fail"]
        if red:
            raise WorkerFailure(f"CI is not green ({', '.join(red)})")
        cancelled = [c["name"] for c in checks if c["bucket"] == "cancel"]
        if cancelled:
            raise Refused(f"CI was cancelled ({', '.join(cancelled)}); re-run CI")
        unknown = [c["name"] for c in checks if c["bucket"] not in GREEN | {"pending"}]
        if unknown:
            raise Refused(f"unknown CI status ({', '.join(unknown)})")
        return bool(checks) and all(c["bucket"] in GREEN for c in checks)

    def watch_checks(self, pr: int) -> None:
        # JSON polling distinguishes a named red check from a transport/gh error.
        deadline = time.monotonic() + self.ci_timeout
        try:
            while True:
                if self.green_checks(self.wait_checks(pr, deadline)):
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Refused(f"CI deadline exceeded after {self.ci_timeout:g}s for PR #{pr}")
                time.sleep(min(30, remaining))
        finally:
            if time.monotonic() >= deadline:
                self._finish = True

    def registration(self, branch: str) -> dict:
        path = self._state_file(branch).with_suffix(".dispatch.json")
        return json.loads(path.read_text()) if path.exists() else {}

    def builder(self, branch: str, requested: str | None) -> str | None:
        registered = self.registration(branch).get("builder")
        if requested not in {None, "codex", "claude"} or registered not in {
            None,
            "codex",
            "claude",
        }:
            raise Refused("builder must be codex or claude")
        if registered and requested not in {None, registered}:
            raise Refused(f"builder differs from dispatch registration: {registered}")
        return registered or requested

    def register(self, branch: str, builder: str, task: str) -> None:
        if builder not in {"codex", "claude"}:
            raise Refused("builder must be codex or claude")
        self.builder(branch, builder)
        git(self.repo, "check-ref-format", "--branch", branch)
        self._state_file(branch).with_suffix(".dispatch.json").write_text(
            json.dumps({"branch": branch, "builder": builder, "task": task}) + "\n"
        )

    def review_file(self, branch: str) -> Path:
        return self._state_file(branch).with_suffix(".review.json")

    def _tested(self, branch: str, builder: str) -> tuple[dict, Path]:
        st = self.state(branch)
        self.builder(branch, builder)
        if st.get("builder") not in {None, builder}:
            raise Refused("builder differs from the recorded builder")
        if not st["passed"]:
            raise Refused("a check failed on the trial; fix and run trial")
        wt = self.worktree(branch)
        self._unchanged(branch, wt, st["tested"])
        return st, wt

    @staticmethod
    def _unchanged(branch: str, wt: Path, tested: str) -> None:
        if git(wt, "rev-parse", "HEAD") != tested or git(wt, "status", "--porcelain"):
            raise Refused(f"{branch} moved or became dirty since its trial; run trial again")

    @staticmethod
    def findings(final: str) -> list[dict]:
        """Codex native priority bullets only; code fences are examples, never records."""
        bullets: list[str] = []
        fence = None
        for line in final.splitlines():
            marker = re.match(r"\s*(`{3,}|~{3,})", line)
            if marker:
                fence = None if fence and marker[1].startswith(fence) else marker[1]
                continue
            if fence:
                continue
            if re.match(r"\s*[-*] \[P[0-3]\]", line):
                if not re.match(r"\s*[-*] \[P[0-3]\] .+ — .+:\d+", line):
                    raise Refused("unclassified Codex priority bullet; see review log")
                bullets.append(line)
            elif bullets:
                bullets[-1] += "\n" + line
        if not bullets:
            raise Refused("unclassified Codex reviewer output; lead must inspect the review log")
        return [{"text": text.strip(), "status": "open"} for text in bullets]

    @staticmethod
    def structured_findings(value) -> list[dict]:
        if not isinstance(value, dict) or not isinstance(value.get("findings"), list):
            raise Refused("unclassified Claude output: missing structured findings; see review log")
        findings = []
        for item in value["findings"]:
            if (
                not isinstance(item, dict)
                or any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("file", "summary", "failure_scenario")
                )
                or type(item.get("line")) is not int
                or item["line"] < 1
            ):
                raise Refused("unclassified Claude finding: schema mismatch; see review log")
            findings.append({"text": json.dumps(item), "status": "open"})
        return findings

    def validate_review(self, st: dict, path: Path) -> dict:
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise Refused(f"readable JSON review record required: {path}") from exc
        return self.validate_record(st, record)

    def validate_record(self, st: dict, record: dict, *, allow_open: bool = False) -> dict:
        if not isinstance(record, dict) or record.get("tested") != st["tested"]:
            raise Refused("review commit is not the tested commit; run review again")
        builder = st.get("builder")
        if builder not in {"codex", "claude"}:
            raise Refused("builder is unknown; register it at dispatch or run review --builder")
        other = "claude" if builder == "codex" else "codex"
        if record.get("reviewer") != other or record.get("builder") != builder:
            raise Refused("reviewer must be from the other model family, not the builder's family")
        model = record.get("model")
        prefix = "claude-" if other == "claude" else "gpt-"
        if not isinstance(model, str) or not model.startswith(prefix):
            raise Refused("review model must name the reviewer's family")
        findings = record.get("findings")
        if not isinstance(findings, list) or not isinstance(record.get("summary"), str):
            raise Refused("review needs a summary and a findings array")
        unresolved = []
        for number, finding in enumerate(findings, 1):
            if not isinstance(finding, dict) or not finding.get("text"):
                raise Refused("each finding needs text and a disposition")
            status = finding.get("status", "")
            if status == "open" and allow_open:
                continue
            if not isinstance(status, str) or not (
                status.startswith("closed:")
                and status[7:].strip()
                and not re.search(
                    r"^(?:(?:this|it|the (?:finding|issue))\s+(?:(?:was|is|has been)\s+)?)?"
                    r"(?:fix(?:ed|es|ing)?|resolved|repaired|corrected|addressed|remediated)(?=\s|[.,;:]|$)"
                    r"|\bfixed\s+in\s+\S+",
                    status[7:].strip(),
                    re.I,
                )
            ):
                unresolved.append(f"{number}. {finding['text']}")
        if unresolved:
            raise ReviewPending(
                "unresolved review findings for lead triage:\n"
                + "\n".join(unresolved)
                + "\nLead: verify candidates; close with a reason or send confirmed defects "
                "to the worker for a new trial and review. "
                "Current-round findings cannot be marked fixed."
            )
        return record

    def close(self, branch: str, dispositions: list[tuple[int, str]]) -> None:
        self._check_legacy()
        fresh, _ = self._release_stale()
        with self.reservation(branch, create=True, automatic=fresh):
            st = self.state(branch)
            self._tested(branch, st["builder"])
            record = json.loads(self.review_file(branch).read_text())
            self.validate_record(st, record, allow_open=True)
            for number, reason in dispositions:
                if not 1 <= number <= len(record["findings"]):
                    raise Refused(f"finding number {number} is outside this review")
                reason = reason.strip().removeprefix("closed:").strip()
                record["findings"][number - 1]["status"] = "closed: " + reason
            self.validate_record(st, record, allow_open=True)
            self.review_file(branch).write_text(
                json.dumps(self.public_value(record), indent=2) + "\n"
            )
            self.say(f"recorded {len(dispositions)} dispositions for {st['tested'][:12]}")

    @guarded()
    def review(self, branch: str, builder: str) -> Path:
        st, wt = self._tested(branch, builder)
        st["builder"] = builder
        self._save(branch, st)
        reviewer = "claude" if builder == "codex" else "codex"
        model = "claude-opus-5-5" if reviewer == "claude" else "gpt-6-astra"
        final_file = self._state_file(branch).with_suffix(".final.txt")
        final_file.unlink(missing_ok=True)
        # Remove any previous successful review before starting a new attempt.
        self.review_file(branch).unlink(missing_ok=True)
        if reviewer == "codex":
            cmd = [
                "codex",
                "exec",
                "review",
                "--base",
                "origin/main",
                "--ignore-user-config",
                "-m",
                model,
                "-c",
                "model_reasoning_effort=high",
                "--json",
                "--ephemeral",
                "-o",
                str(final_file),
            ]
        else:
            cmd = [
                "claude",
                "-p",
                f"Perform a {self.review_level}-depth code review of branch {branch}; "
                "report only high-confidence actionable defects, not a minimum quota.\n"
                "Use origin/main as the base, exactly git diff origin/main...HEAD. "
                "The exact diff is supplied on stdin. "
                "Do not use local main, an upstream branch, or HEAD~1 as a fallback. "
                "An empty diff has no findings.",
                "--model",
                model,
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(REVIEW_SCHEMA),
                "--no-session-persistence",
                "--permission-mode",
                "dontAsk",
                "--tools",
                "Read,Grep,Glob",
                "--allowedTools",
                "Read,Grep,Glob",
                "--disallowedTools",
                "Bash,Edit,Write,Agent,Task,mcp__*",
                "--append-system-prompt",
                "Read-only review of HEAD against origin/main. Do not delegate, edit files, "
                "submit comments, read credentials, or run trading lanes. Return an object "
                "with a findings array of {file, line, summary, failure_scenario}; "
                "use an empty findings array if clean. The schema defines the output contract.",
            ]
        try:
            run = subprocess.run(
                cmd,
                cwd=wt,
                capture_output=True,
                text=True,
                timeout=self.review_timeout,
                input=git(wt, "diff", "origin/main...HEAD") if reviewer == "claude" else None,
            )
        except subprocess.TimeoutExpired as exc:
            self._finish = True
            output = (exc.stdout or b"") + (exc.stderr or b"")
            self._state_file(branch).with_suffix(".review.log").write_bytes(output)
            raise Refused(
                f"{reviewer} review deadline exceeded after {self.review_timeout:g}s"
            ) from exc
        except OSError as exc:
            raise Refused(f"{reviewer} review could not start: {exc}") from exc
        self._state_file(branch).with_suffix(".review.log").write_text(run.stdout + run.stderr)
        if run.returncode:
            raise Refused(f"{reviewer} review failed (exit {run.returncode}); see review log")
        structured = None
        try:
            if reviewer == "codex":
                final = final_file.read_text().strip()
            else:
                envelope = json.loads(run.stdout)
                if envelope.get("is_error") or envelope.get("subtype") != "success":
                    raise ValueError("review did not succeed")
                structured = envelope["structured_output"]
                final = json.dumps(structured)
            if not final:
                raise ValueError("empty final message")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise Refused(
                "unclassified review: no successful structured/final message; see review log"
            ) from exc
        self._unchanged(branch, wt, st["tested"])  # keep the post-model integrity check
        findings = (
            self.findings(final) if reviewer == "codex" else self.structured_findings(structured)
        )
        final = self.public_text(final, wt)
        record = {
            "version": 1,
            "builder": builder,
            "reviewer": reviewer,
            "model": model,
            "tested": st["tested"],
            "summary": final,
            "findings": self.public_value(findings, wt),
        }
        path = self.review_file(branch)
        path.write_text(json.dumps(record, indent=2) + "\n")
        self.say(f"review record: {path}")
        self.validate_review(st, path)
        return path

    def auto(self, branch: str, builder: str, title: str, body: Path) -> bool:
        step = "inputs"
        try:
            body.read_text()  # Validate readability/encoding before checks, models or reservation.
            step = "reservation"
            with self.reservation(branch, create=True, automatic=True):
                try:
                    head = git(self.repo, "rev-parse", f"refs/heads/{branch}")
                    previous = self.attempt(branch)
                    self._attempt = {
                        "commit": head,
                        "failures": previous.get("failures", 0)
                        if previous.get("commit") == head
                        else 0,
                        "outcome": "running",
                        "step": "trial",
                    }
                    self._save_attempt(branch)
                    step = "trial"
                    reusable = False
                    if self._state_file(branch).exists():
                        st = self.state(branch)
                        reusable = (
                            st["passed"] and st["tested"] == head and st["main"] == self._main()
                        )
                        if reusable:
                            self._tested(branch, builder)
                    if not reusable and not self.trial(branch, builder):
                        failures = [
                            r["check"] + ": " + r["last"]
                            for r in self.state(branch)["checks"]
                            if not r["passed"]
                        ]
                        raise WorkerFailure("; ".join(failures))
                    step = "review"
                    review = self.review_file(branch)
                    if (
                        review.exists()
                        and json.loads(review.read_text()).get("tested")
                        == self.state(branch)["tested"]
                    ):
                        self.validate_review(self.state(branch), review)
                    else:
                        self.review(branch, builder)
                    step = "open"
                    self.open(branch, title, body)
                    step = "land"
                    self.land(branch)
                finally:
                    primary = sys.exception()
                    try:
                        if self._attempt is not None:
                            self._attempt.update(
                                step=step,
                                outcome=(
                                    "worker_failure"
                                    if isinstance(primary, WorkerFailure)
                                    else "review_pending"
                                    if isinstance(primary, ReviewPending)
                                    else "lead_action"
                                    if primary
                                    else "landed"
                                ),
                            )
                            if self._attempt["outcome"] == "lead_action":
                                self._attempt["failures"] += 1
                            self._save_attempt(branch)
                    except OSError as exc:
                        if primary is None:
                            raise
                        primary.add_note(f"attempt record also failed: {exc}")
                    finally:
                        self._attempt = None
        except Exception as exc:
            audience = "SEND TO WORKER" if isinstance(exc, WorkerFailure) else "LEAD ACTION"
            detail = str(exc) if isinstance(exc, Refused) else f"{type(exc).__name__}: {exc}"
            self.say(f"{audience}: {branch}: {step} failed: {detail}")
            return False
        return True

    def _save_attempt(self, branch: str) -> None:
        self._state_file(branch).with_suffix(".attempt.json").write_text(
            json.dumps(self._attempt) + "\n"
        )

    def attempt(self, branch: str) -> dict:
        path = self._state_file(branch).with_suffix(".attempt.json")
        return json.loads(path.read_text()) if path.exists() else {}

    def waiting(self, branch: str, head: str) -> str | None:
        review = self.review_file(branch)
        if review.exists():
            record = json.loads(review.read_text())
            if record.get("tested") == head:
                try:
                    self.validate_record(self.state(branch), record)
                except ReviewPending:
                    return "waiting for lead dispositions"
        attempt = self.attempt(branch)
        if attempt.get("commit") != head:
            return None
        if attempt.get("outcome") == "worker_failure":
            return "waiting for worker changes"
        if (
            attempt.get("outcome") == "lead_action"
            and attempt.get("failures", 1) >= self.retry_limit
        ):
            return "waiting for lead: transient retry limit reached; explicit auto retry available"
        if attempt.get("outcome") == "running" and self.lock_path.exists():
            with self.lock_path.open("a+") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return "waiting for active landing to finish"
        return None

    def pending(self, run_id: str | None = None) -> bool:
        cmd = [
            os.environ.get("ORCA_CLI_COMMAND", "orca-ide"),
            "orchestration",
            "task-list",
            "--status",
            "completed",
            "--json",
        ]
        if run_id:
            cmd += ["--run", run_id]
        run = subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True)
        if run.returncode:
            raise Refused(f"task-list failed: {run.stderr.strip()}")
        try:
            listing = json.loads(run.stdout)
            completed = {task["id"] for task in listing["result"]["tasks"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise Refused("task-list did not return a completed-task listing") from exc
        fetched = False
        found = False
        for path in sorted(self.home.glob("*.dispatch.json")):
            task = json.loads(path.read_text())
            if task.get("landed") or task["task"] not in completed:
                continue
            branch = task["branch"]
            # A deleted branch or an ancestor of main has nothing left to publish.
            head = subprocess.run(
                ["git", "-C", str(self.repo), "rev-parse", "--verify", f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
            )
            if head.returncode:
                continue
            waiting = self.waiting(branch, head.stdout.strip())
            if waiting:
                self.say(f"{branch}: {waiting}")
                continue
            if not fetched:
                self._main()
                fetched = True
            ancestor = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "merge-base",
                    "--is-ancestor",
                    head.stdout.strip(),
                    "origin/main",
                ],
                capture_output=True,
            )
            if ancestor.returncode == 0:
                continue
            if ancestor.returncode != 1:
                raise Refused(f"could not check ancestry of {branch}")
            # Squash merges are not ancestors: match GitHub's merged PR head exactly.
            prs = json.loads(
                self.gh(
                    ["pr", "list", "--head", branch, "--state", "merged", "--json", "headRefOid"]
                )
            )
            if any(pr["headRefOid"] == head.stdout.strip() for pr in prs):
                continue
            self.say(json.dumps(task, sort_keys=True))
            found = True
        return found

    # --- (b) open ------------------------------------------------------------------------------
    @guarded()
    def open(
        self, branch: str, title: str, body: Path, review: Path | None = None, wait: bool = True
    ) -> int:
        st = self.state(branch)
        self.builder(branch, st.get("builder"))
        if not st["passed"]:
            failed = [r["check"] for r in st["checks"] if not r["passed"]]
            raise Refused(f"a check failed on the trial ({', '.join(failed)}); fix and run trial")
        if git(self.repo, "rev-parse", f"refs/heads/{branch}") != st["tested"]:
            raise Refused(f"{branch} moved since its trial; run trial again")
        review = review or self.review_file(branch)
        record = self.validate_review(st, review)
        public_body = self._state_file(branch).with_suffix(".body.md")
        public_review = self._state_file(branch).with_suffix(".public-review.json")
        public_body.write_text(self.public_text(body.read_text()))
        public_review.write_text(json.dumps(self.public_value(record), indent=2) + "\n")
        title = self.public_text(title)
        push = subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "origin", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        )
        if push.returncode:
            rejected = re.search(r"\[rejected\]|non-fast-forward|fetch first", push.stderr, re.I)
            if not rejected:
                raise Refused(f"push failed: {self.public_text(push.stderr.strip()[-500:])}")
            error = self.public_text(push.stderr.strip()[-500:])
            raise WorkerFailure(
                f"the push of {branch} was refused ({error}): "
                "the branch "
                "was rewritten after an earlier push and is the worker's to reconcile"
            )
        found = json.loads(self.gh(["pr", "list", "--head", branch, "--json", "number"]) or "[]")
        if found:
            pr = int(found[0]["number"])
            self.gh(["pr", "edit", str(pr), "--title", title, "--body-file", str(public_body)])
        else:
            url = self.gh(
                [
                    "pr",
                    "create",
                    "--base",
                    "main",
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body-file",
                    str(public_body),
                ]
            )
            pr = int(url.rstrip("/").rsplit("/", 1)[-1])
        posted_file = self._state_file(branch).with_suffix(".posted.json")
        posted = json.loads(posted_file.read_text()) if posted_file.exists() else []
        key = {"pr": pr, "tested": st["tested"]}
        if key not in posted:
            self.gh(["pr", "comment", str(pr), "--body-file", str(public_review)])
            posted.append(key)
            posted_file.write_text(json.dumps(posted) + "\n")
        st["review"] = record
        st["pr"] = pr
        self._save(branch, st)
        self.say(f"PR #{pr} open at {st['tested'][:12]}; review record posted")
        if wait:
            self.watch_checks(pr)
        return pr

    # --- (c) land ------------------------------------------------------------------------------
    @guarded()
    def land(self, branch: str, squash: Path | None = None) -> None:
        st = self.state(branch)
        self.builder(branch, st.get("builder"))
        if not st["passed"]:
            raise Refused("the trial failed; nothing lands")
        if "pr" not in st:
            raise Refused("no pull request recorded; run open first")
        if st.get("merged"):
            self._finish = True
            raise Refused(f"PR #{st['pr']} already merged; fetch main and verify tree {st['tree']}")
        if "review" not in st:
            raise Refused("no validated review recorded; run open first")
        self.validate_record(st, st["review"])
        checks = self.wait_checks(st["pr"])
        if not self.green_checks(checks):
            raise Refused("CI is not green (checks are pending)")
        args = ["pr", "merge", str(st["pr"]), "--squash", "--match-head-commit", st["tested"]]
        if squash is not None:
            subject, _, rest = self.public_text(squash.read_text()).partition("\n")
            args += ["--subject", subject, "--body", rest.strip()]
        # Last step before the merge call: main as it is now must still give the tested tree.
        main = self._main()
        if self._merged_tree(main, st["tested"]) != st["tree"]:
            raise Refused(
                f"main moved ({st['main'][:12]} -> {main[:12]}) and the merged tree "
                "differs from the tested one; run trial again"
            )
        self.gh(args)
        # A successful remote merge is irreversible, even if the verification fetch fails.
        self._finish = True
        st["merged"] = True
        self._save(branch, st)
        registration = self.registration(branch)
        if registration:
            registration["landed"] = st["tested"]
            self._state_file(branch).with_suffix(".dispatch.json").write_text(
                json.dumps(registration) + "\n"
            )
        try:
            after = self._main()
            landed = git(self.repo, "rev-parse", f"{after}^{{tree}}")
        except (Refused, OSError, ValueError) as exc:
            raise Refused(
                f"PR #{st['pr']} merged but post-merge verification failed; "
                f"do not merge again; fetch main and verify tree {st['tree']}: {exc}"
            ) from exc
        if landed != st["tree"]:
            raise Refused(
                f"FAIL: main {after[:12]} has tree {landed}, not the tested tree {st['tree']}; "
                "main moved during the merge and holds an untested tree: run the checks on main now"
            )
        self.say(f"LANDED #{st['pr']}: main's tree equals the tested tree {landed[:12]}")


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not 0 < seconds < float("inf"):
        raise argparse.ArgumentTypeError("deadline must be a positive finite number of seconds")
    return seconds


def main(argv: list[str]) -> int:
    if argv[:1] == ["_hold"]:
        return lock_server(Path(argv[1]), json.loads(argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("trial", "review", "auto", "register", "open", "land", "close"):
        sub = subs.add_parser(name)
        sub.add_argument("branch")
        if name in {"trial", "review", "auto", "register"}:
            sub.add_argument("--builder", choices=["codex", "claude"], required=name != "trial")
        if name in {"review", "auto"}:
            sub.add_argument("--review-level", choices=["medium", "high"], default="medium")
            sub.add_argument("--review-timeout", type=positive_seconds, default=900.0)
        if name in {"open", "auto"}:
            sub.add_argument("--ci-timeout", type=positive_seconds, default=1800.0)
        if name == "close":
            sub.add_argument("number", type=int)
            sub.add_argument("reason")
            sub.add_argument(
                "--also", nargs=2, action="append", default=[], metavar=("NUMBER", "REASON")
            )
        if name == "register":
            sub.add_argument("--task", required=True)
        if name in {"auto", "open"}:
            sub.add_argument("title")
            sub.add_argument("body", type=Path)
        if name == "open":
            sub.add_argument("review", nargs="?", type=Path)
        if name == "land":
            sub.add_argument("squash", nargs="?", type=Path)
    subs.add_parser("release")
    pending = subs.add_parser("pending")
    pending.add_argument("--run")
    pending.add_argument("--retry-limit", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        gate = Gate(Path.cwd())
        for name in ("review_level", "review_timeout", "ci_timeout", "retry_limit"):
            if hasattr(args, name):
                setattr(gate, name, getattr(args, name))
        match args.command:
            case "close":
                gate.close(
                    args.branch, [(args.number, args.reason), *[(int(n), r) for n, r in args.also]]
                )
            case "trial":
                return 0 if gate.trial(args.branch, args.builder) else 1
            case "review":
                gate.review(args.branch, args.builder)
            case "auto":
                return 0 if gate.auto(args.branch, args.builder, args.title, args.body) else 1
            case "register":
                gate.register(args.branch, args.builder, args.task)
            case "pending":
                return 0 if gate.pending(args.run) else 1
            case "open":
                gate.open(args.branch, args.title, args.body, args.review)
            case "land":
                gate.land(args.branch, args.squash)
            case "release":
                gate.release()
    except (Refused, OSError, ValueError, KeyError, TypeError) as why:
        print(f"REFUSED: {why}")
        return 2 if args.command == "pending" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
