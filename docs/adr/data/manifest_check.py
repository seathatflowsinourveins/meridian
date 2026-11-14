"""Check the ecosystem manifest's pins, pull requests, commits, branches and ADRs.

    python3 docs/adr/data/manifest_check.py

Every backticked pin in a layer row's Pin cell must be found in one of the files the same row
cites in Where, read from main or from ``branch <name>:<path>``. Every ``PR #N`` in a row must be
a pull request of this repository, every ``commit <sha>`` a commit here, every ``branch <name>``
a local or origin branch, and every ``ADR NNNN`` a docs/adr/NNNN-* file on main or on a branch.
Offline except, for an open pull request not yet in git history, ``gh pr view``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).resolve().with_name("ecosystem-manifest.md")
LAYER = re.compile(r"^### Layer \d")
PIN = re.compile(r"`([^`]+)`")
PR = re.compile(r"PR #(\d+)")
COMMIT = re.compile(r"commit ([0-9a-f]{7,40})")
BRANCH = re.compile(r"branch ([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)")
ADR = re.compile(r"ADR (\d{4})")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )


def git_show(ref: str, path: str) -> str | None:
    out = git("show", f"{ref}:{path}")
    return out.stdout if out.returncode == 0 else None


def branch_ref(name: str) -> str | None:
    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        if git("rev-parse", "--verify", "--quiet", ref).returncode == 0:
            return ref
    return None


def source_text(source: str) -> str | None:
    source = source.strip().strip("`").strip()
    source = re.sub(r" \(in build\)$", "", source)
    branch = re.fullmatch(r"branch ([^:]+):(.+)", source)
    if branch:
        ref = branch_ref(branch[1])
        return None if ref is None else git_show(ref, branch[2].strip())
    if source in {"", "none"}:
        return None
    path = ROOT / source
    return path.read_text(encoding="utf-8") if path.is_file() else None


def rows(text: str):
    in_layer = False
    for number, line in enumerate(text.splitlines(), 1):
        heading = re.match(r"^###\s+(.+)", line)
        if heading:
            in_layer = bool(LAYER.match(line))
            continue
        if not in_layer or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 6 or cells[0] == "Job" or set(cells[0]) <= set("-: "):
            continue
        yield number, cells


def adr_exists(number: str, branches: list[str]) -> bool:
    pattern = f"docs/adr/{number}-"
    if any((ROOT / "docs/adr").glob(f"{number}-*.md")):
        return True
    refs = [ref for name in branches if (ref := branch_ref(name))]
    refs += ["refs/remotes/origin/main"]
    for ref in refs:
        tree = git("ls-tree", "-r", "--name-only", ref, "docs/adr").stdout
        if any(name.startswith(pattern) for name in tree.splitlines()):
            return True
    for ref in git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").stdout.split():
        tree = git("ls-tree", "-r", "--name-only", ref, "docs/adr").stdout
        if any(name.startswith(pattern) for name in tree.splitlines()):
            return True
    return False


def main() -> int:
    text = MANIFEST.read_text(encoding="utf-8")
    problems: list[str] = []
    pins = prs = commits = adrs = branches = row_count = 0
    history = git("log", "--all", "--format=%s").stdout
    known_prs = {int(number) for number in re.findall(r"\(#(\d+)\)", history)}
    gh = subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", "200", "--json", "number"],
        capture_output=True,
        text=True,
        check=False,
    )
    if gh.returncode == 0:
        known_prs |= {int(number) for number in re.findall(r'"number":\s*(\d+)', gh.stdout)}

    for line, (job, _rests, pin, state, where, checked) in rows(text):
        row_count += 1
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", checked):
            problems.append(f"line {line}: checked date is not a date: {checked!r}")
        tokens = PIN.findall(pin)
        sources = [source for source in where.split(";") if source.strip()]
        for token in tokens:
            pins += 1
            found = False
            for source in sources:
                content = source_text(source)
                if content is not None and token in content:
                    found = True
                    break
            if not found:
                problems.append(f"line {line} ({job}): pin {token!r} not in {sources}")

        row_branches = BRANCH.findall(state) + BRANCH.findall(where)
        for name in row_branches:
            branches += 1
            if branch_ref(name) is None:
                problems.append(f"line {line} ({job}): no branch {name}")
        for number in PR.findall(state):
            prs += 1
            if int(number) not in known_prs:
                problems.append(f"line {line} ({job}): no pull request #{number}")
        for commit in COMMIT.findall(state):
            commits += 1
            if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
                problems.append(f"line {line} ({job}): no commit {commit}")
        for number in ADR.findall(state + " " + where):
            adrs += 1
            if not adr_exists(number, row_branches):
                problems.append(f"line {line} ({job}): no ADR {number}")

    summary = (
        f"manifest_check: {row_count} rows, {pins} pins, {prs} pull requests, "
        f"{commits} commits, {branches} branches, {adrs} ADRs, {len(problems)} problems"
    )
    print(summary)
    for problem in problems:
        print(f"- {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
