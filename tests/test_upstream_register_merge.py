"""Two branches that each add a different `UPSTREAM.md` row merge without a conflict.

`.gitattributes` gives `UPSTREAM.md` git's built-in union merge driver (gitattributes(5), "merge",
"union"), so both rows are kept. Checked on a scratch repository holding this repository's
`.gitattributes` and `UPSTREAM.md`, each branch appending its own row at the end of the file.
"""

import shutil
import subprocess
from pathlib import Path

from test_paper_only import REPO_ROOT

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *IDENTITY, "-C", str(repo), *args], capture_output=True, text=True
    )


def add_row(repo: Path, branch: str, row: str) -> None:
    assert git(repo, "checkout", "-q", "-b", branch, "main").returncode == 0
    with (repo / "UPSTREAM.md").open("a", encoding="utf-8") as f:
        f.write(row + "\n")
    assert git(repo, "commit", "-q", "-am", branch).returncode == 0


def test_two_branches_adding_different_rows_merge_cleanly(tmp_path: Path):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for name in (".gitattributes", "UPSTREAM.md"):
        shutil.copyfile(REPO_ROOT / name, repo / name)
    assert git(repo, "add", ".").returncode == 0
    assert git(repo, "commit", "-q", "-m", "base").returncode == 0
    one = "| One | 1.0 | https://example.invalid/one | 2026-11-13 | test row | upstream |"
    two = "| Two | 2.0 | https://example.invalid/two | 2026-11-13 | test row | own design |"
    add_row(repo, "one", one)
    add_row(repo, "two", two)
    merged = git(repo, "merge", "-q", "--no-edit", "one")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    text = (repo / "UPSTREAM.md").read_text(encoding="utf-8")
    assert one in text and two in text and "<<<<<<<" not in text
