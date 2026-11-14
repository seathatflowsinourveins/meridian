"""The lead's merge gate: one landing at a time, a tested tree, a pinned squash-merge (own design).

    gate.py trial BRANCH                 trial-merge origin/main, run the five checks
    gate.py open BRANCH TITLE BODY REVIEW  push the tested commit, open the PR, post the review
                                         record, wait for CI
    gate.py land BRANCH [SQUASH]         squash-merge pinned to the tested head, compare trees
    gate.py release                      drop the landing lock (after an abandoned landing)

It wraps `git`, `gh` (its own sign-in; this script reads no token) and the checks, and prints a
few lines. State and check logs live under the repository's common git directory, in
`meridian-gate/`, never in the tree. The lock is a file there naming the branch that is landing:
`trial` takes it, `land` drops it, and another branch's `trial` refuses while it is held.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

SETUP = [["uv", "sync", "--locked"]]
CHECKS = [
    ["uv", "run", "ruff", "check", "."],
    ["uv", "run", "ruff", "format", "--check", "."],
    ["uv", "run", "pyright"],
    ["uv", "run", "pytest", "-q"],
    ["gitleaks", "git", "--redact", "--no-banner", "."],
]
GREEN = {"pass", "skipping"}  # `gh pr checks --json bucket`; everything else is not green

Gh = Callable[[Sequence[str]], str]


class Refused(Exception):
    """The gate will not go on; the message says why."""


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise Refused(f"git {args[0]} failed: {(out.stderr or out.stdout).strip()[-200:]}")
    return out.stdout.strip()


def real_gh(args: Sequence[str]) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    # `gh pr checks` exits non-zero while a check fails or is pending, and still prints its JSON.
    reported = list(args[:2]) == ["pr", "checks"] and "--json" in args and out.stdout.strip()
    if out.returncode != 0 and not reported:
        raise Refused(f"gh {' '.join(args[:2])} failed: {out.stderr.strip()[-200:]}")
    return out.stdout.strip()


class Gate:
    def __init__(self, repo: Path, gh: Gh = real_gh, setup=SETUP, checks=CHECKS) -> None:
        self.repo = Path(git(repo, "rev-parse", "--show-toplevel"))
        common = Path(git(self.repo, "rev-parse", "--git-common-dir"))
        self.home = (common if common.is_absolute() else self.repo / common) / "meridian-gate"
        self.home.mkdir(exist_ok=True)
        self.gh, self.setup, self.checks = gh, setup, checks
        self.say: Callable[[str], None] = print

    # --- state and lock ------------------------------------------------------------------------
    def _state_file(self, branch: str) -> Path:
        return self.home / (branch.replace("/", "__") + ".json")

    def state(self, branch: str) -> dict:
        f = self._state_file(branch)
        if not f.is_file():
            raise Refused(f"no trial recorded for {branch}; run trial first")
        return json.loads(f.read_text())

    def _save(self, branch: str, state: dict) -> None:
        self._state_file(branch).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    def _lock(self, branch: str) -> None:
        lock = self.home / "lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            os.write(fd, branch.encode())
            os.close(fd)
        except FileExistsError:
            holder = lock.read_text()
            if holder != branch:
                raise Refused(f"{holder} is landing; one landing at a time") from None

    def release(self) -> None:
        (self.home / "lock").unlink(missing_ok=True)

    def _main(self) -> str:
        git(self.repo, "fetch", "-q", "origin")
        return git(self.repo, "rev-parse", "origin/main")

    def _merged_tree(self, main: str, commit: str) -> str:
        return git(self.repo, "merge-tree", "--write-tree", main, commit).splitlines()[0]

    # --- (a) trial ------------------------------------------------------------------------------
    def trial(self, branch: str) -> bool:
        self._lock(branch)
        main = self._main()
        head = git(self.repo, "rev-parse", f"refs/heads/{branch}")
        with tempfile.TemporaryDirectory(prefix="gate-") as tmp:
            wt = Path(tmp) / "tree"
            git(self.repo, "worktree", "add", "-q", "--detach", str(wt), head)
            try:
                tested = head
                if subprocess.run(
                    ["git", "-C", str(wt), "merge-base", "--is-ancestor", main, head]
                ).returncode:
                    merged = subprocess.run(
                        ["git", "-C", str(wt), "merge", "-q", "--no-edit", main],
                        capture_output=True,
                    )
                    if merged.returncode:
                        raise Refused("origin/main does not merge cleanly; merge it on the branch")
                    tested = git(wt, "rev-parse", "HEAD")
                results = self._run_checks(wt, branch)
            finally:
                git(self.repo, "worktree", "remove", "--force", str(wt))
        ok = all(r["passed"] for r in results)
        tree = git(self.repo, "rev-parse", f"{tested}^{{tree}}")
        self._save(
            branch,
            {
                "branch": branch,
                "head": head,
                "main": main,
                "tested": tested,
                "tree": tree,
                "checks": results,
                "passed": ok,
            },
        )
        self.say(f"{'PASS' if ok else 'FAIL'} {branch}: tested {tested[:12]} on main {main[:12]}")
        return ok

    def _run_checks(self, wt: Path, branch: str) -> list[dict]:
        log = self.home / (branch.replace("/", "__") + ".log")
        results = []
        with log.open("w") as out:
            for cmd in [*self.setup, *self.checks]:
                try:
                    run = subprocess.run(cmd, cwd=wt, capture_output=True, text=True)
                    code, text = run.returncode, run.stdout + run.stderr
                except FileNotFoundError:
                    code, text = 127, f"{cmd[0]}: not found"
                out.write(f"$ {' '.join(cmd)}\n{text}\n")
                last = (text.strip().splitlines() or [""])[-1][:120]
                if cmd in self.checks:
                    results.append({"check": " ".join(cmd), "passed": code == 0, "last": last})
                self.say(f"  {'ok  ' if code == 0 else 'FAIL'} {' '.join(cmd)}: {last}")
                if code and cmd in self.setup:
                    return [{"check": " ".join(cmd), "passed": False, "last": last}]
        return results

    # --- (b) open ------------------------------------------------------------------------------
    def open(self, branch: str, title: str, body: Path, review: Path, wait: bool = True) -> int:
        st = self.state(branch)
        if not st["passed"]:
            failed = [r["check"] for r in st["checks"] if not r["passed"]]
            raise Refused(f"a check failed on the trial ({', '.join(failed)}); fix and run trial")
        git(self.repo, "push", "-q", "origin", f"{st['tested']}:refs/heads/{branch}")
        found = json.loads(self.gh(["pr", "list", "--head", branch, "--json", "number"]) or "[]")
        if found:
            pr = int(found[0]["number"])
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
                    str(body),
                ]
            )
            pr = int(url.rstrip("/").rsplit("/", 1)[-1])
        self.gh(["pr", "comment", str(pr), "--body-file", str(review)])
        st["pr"] = pr
        self._save(branch, st)
        self.say(f"PR #{pr} open at {st['tested'][:12]}; review record posted")
        if wait:
            self.gh(["pr", "checks", str(pr), "--watch", "--interval", "30"])
        return pr

    # --- (c) land ------------------------------------------------------------------------------
    def land(self, branch: str, squash: Path | None = None) -> None:
        st = self.state(branch)
        if not st["passed"]:
            raise Refused("the trial failed; nothing lands")
        if "pr" not in st:
            raise Refused("no pull request recorded; run open first")
        main = self._main()
        if self._merged_tree(main, st["tested"]) != st["tree"]:
            raise Refused(
                f"main moved ({st['main'][:12]} -> {main[:12]}) and the merged tree "
                "differs from the tested one; run trial again"
            )
        checks = json.loads(self.gh(["pr", "checks", str(st["pr"]), "--json", "name,bucket"]))
        red = [c["name"] for c in checks if c["bucket"] not in GREEN]
        if not checks or red:
            raise Refused(f"CI is not green ({', '.join(red) or 'no checks reported'})")
        args = ["pr", "merge", str(st["pr"]), "--squash", "--match-head-commit", st["tested"]]
        if squash is not None:
            subject, _, rest = squash.read_text().partition("\n")
            args += ["--subject", subject, "--body", rest.strip()]
        self.gh(args)
        landed = git(self.repo, "rev-parse", f"{self._main()}^{{tree}}")
        self.release()
        if landed != st["tree"]:
            raise Refused(
                f"MISMATCH: main's tree {landed[:12]} is not the tested {st['tree'][:12]}"
            )
        self.say(f"LANDED #{st['pr']}: main's tree equals the tested tree {landed[:12]}")


def main(argv: list[str]) -> int:
    gate = Gate(Path.cwd())
    try:
        match argv:
            case ["trial", branch]:
                return 0 if gate.trial(branch) else 1
            case ["open", branch, title, body, review]:
                gate.open(branch, title, Path(body), Path(review))
            case ["land", branch, *rest] if len(rest) <= 1:
                gate.land(branch, Path(rest[0]) if rest else None)
            case ["release"]:
                gate.release()
            case _:
                print(__doc__.split("\n\n")[1])
                return 2
    except Refused as why:
        print(f"REFUSED: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
