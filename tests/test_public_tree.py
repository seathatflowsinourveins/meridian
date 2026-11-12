"""
This repository is public. The build fails if an IBKR-style account id appears in any file
git can see, or if CI gains something a fork's pull request could abuse.

Account ids, raw order or fill history, reconciliation fixtures and tuned parameters belong in
the private ``meridian-evidence`` repository. Scrubbed run records in ``evidence/`` may stay.
Like the paper-only scan, this is a tripwire: it catches a pasted id, not a determined one.
Tests that need an id-shaped value build it from parts, so the literal never appears.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
from test_paper_only import REPO_ROOT, git_files

# Nothing is skipped, this file included: its examples are built from parts.
NOT_SCANNED: set[str] = set()

# A capital D, U, F or I, at most two more capital letters, then 5 to 9 digits, standing alone.
# Covers the shapes in IBKR's and NautilusTrader's documentation examples: U, F and I for
# individual, advisor and institutional accounts; DU, DF and DUD for paper ones; 5 to 7 digits.
ACCOUNT_ID = re.compile(r"(?<![A-Za-z0-9])[DUFI][A-Z]{0,2}[0-9]{5,9}(?![A-Za-z0-9])")

WORKFLOW_HAZARDS = {
    "pull_request_target trigger (runs fork code with this repo's token)": re.compile(
        r"pull_request_target"
    ),
    "self-hosted runner": re.compile(r"self-hosted", re.IGNORECASE),
    "CI secret": re.compile(
        r"secrets\s*[.\[]|tojson\(\s*secrets|secrets\s*:\s*inherit", re.IGNORECASE
    ),
}


# A literal list of hashes under the allowlist's key, as in a copy of the owner's contract.
# The key is built from parts so that this file does not hold it.
ALLOWLIST_KEY = "paper_accounts" + "_sha256"
ALLOWLIST_LITERAL = re.compile(
    re.escape(ALLOWLIST_KEY) + r"""["']?\s*[:=]\s*\[[^\]]*?[0-9a-fA-F]{64}"""
)


def tracked_files() -> list[str]:
    deleted = set(git_files("--deleted"))
    listed = git_files("--cached", "--others", "--exclude-standard")
    return [name for name in listed if name not in NOT_SCANNED and name not in deleted]


def read_text(name: str, root: Path = REPO_ROOT) -> str:
    path = root / name
    assert path.is_file(), f"{name} is listed by git but is not a regular file"
    data = path.read_bytes()
    assert b"\0" not in data, f"{name} is not plain text (UTF-16 or binary); cannot scan it"
    return data.decode("utf-8", errors="replace")


def account_id_hits(names: list[str], root: Path = REPO_ROOT) -> list[str]:
    """file:line for every line holding an account-id shape; the location only, never the value."""
    hits = []
    for name in names:
        for line_no, line in enumerate(read_text(name, root).splitlines(), start=1):
            if ACCOUNT_ID.search(line):
                hits.append(f"{name}:{line_no}")
    return hits


def allowlist_copies(names: list[str], root: Path = REPO_ROOT) -> list[str]:
    """Files holding a literal list of hashes under the allowlist's key; names only."""
    return [name for name in names if ALLOWLIST_LITERAL.search(read_text(name, root))]


def test_no_account_id_in_the_public_tree():
    files = tracked_files()
    assert files, "git reported no files; the scan would pass without looking at anything"
    assert account_id_hits(files) == []


def test_no_copy_of_the_allowlist_in_the_public_tree():
    assert allowlist_copies(tracked_files()) == []


def test_both_scans_find_what_is_planted(tmp_path):
    # The scans themselves, on planted files outside the repository (values built at run time).
    (tmp_path / "clean.md").write_text("nothing here\n", encoding="utf-8")
    (tmp_path / "id.md").write_text("one\naccount " + "DU" + "1234567\n", encoding="utf-8")
    copy = json.dumps({"ibkr": {ALLOWLIST_KEY: ["ab" * 32]}})
    (tmp_path / "copy.json").write_text(copy, encoding="utf-8")
    names = ["clean.md", "id.md", "copy.json"]
    assert account_id_hits(names, tmp_path) == ["id.md:2"]
    assert allowlist_copies(names, tmp_path) == ["copy.json"]


def test_the_allowlist_check_catches_a_copy_of_a_contract():
    copy = json.dumps({"ibkr": {ALLOWLIST_KEY: ["ab" * 32]}}, indent=2)
    assert ALLOWLIST_LITERAL.search(copy)
    assert ALLOWLIST_LITERAL.search(f"{ALLOWLIST_KEY} = ['{'cd' * 32}']")
    assert not ALLOWLIST_LITERAL.search(f'"{ALLOWLIST_KEY}": [account_hash(account_id)]')


@pytest.mark.parametrize(
    "name",
    [
        "risk/boundary.contract.json",
        "risk/boundary.contract.json.bak",
        "risk/boundary.contract.json~",
        "risk/.boundary.contract.json.swp",
        "other.contract.json",
    ],
)
def test_the_allowlist_and_any_copy_of_it_are_ignored_by_git(name):
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", name], cwd=REPO_ROOT, check=False
    )
    assert ignored.returncode == 0, f"git would not ignore {name}"


def test_ci_has_no_fork_reachable_token_secret_or_runner():
    workflows = [n for n in tracked_files() if n.startswith(".github/workflows/")]
    assert workflows, "no workflow files found; the check would pass without looking"
    hits = [
        f"{name}: {label}"
        for name in workflows
        for label, pattern in WORKFLOW_HAZARDS.items()
        if pattern.search(read_text(name))
    ]
    assert hits == []


@pytest.mark.parametrize(
    "parts",
    [
        ("U", "1234567"),
        ("U", "12345678"),
        ("DU", "1234567"),
        ("DF", "1234567"),
        ("F", "1234567"),
        ("I", "1234567"),
        ("DF", "12345"),
        ("DUD", "12345"),
    ],
)
def test_the_scan_catches_account_id_shapes(parts):
    candidate = "".join(parts)
    assert ACCOUNT_ID.search(f"account = '{candidate}'")
    assert ACCOUNT_ID.search(f"{candidate},{candidate}")


@pytest.mark.parametrize(
    "text",
    [
        "DUFAKE0001",  # the fake ids the boundary tests use
        "UTEST00002",
        "port = 4002",
        "sha256 = 'a9b1ea35ebee0b377255f7d069e45ed41c1fe718cb67208c64fffb2179f3a5be'",
        "M1-ibkr-paper-20261112T213000Z-order.json",
        "ts = 1794001000000000000",
        "E501 UP035 SIM105",
        "U+1234",
    ],
)
def test_the_scan_leaves_other_text_alone(text):
    assert ACCOUNT_ID.search(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "on:\n  pull_request_target:\n",
        "runs-on: [self-hosted, linux]",
        "token: ${{ secrets.SOME_TOKEN }}",
        "key: ${{ Secrets . KEY }}",
        "token: ${{ secrets['KEY'] }}",
        "env: ${{ toJSON(secrets) }}",
        "    secrets: inherit",
    ],
)
def test_the_workflow_check_catches_hazards(text):
    assert any(pattern.search(text) for pattern in WORKFLOW_HAZARDS.values())


def test_the_workflow_check_leaves_this_ci_alone():
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert not any(pattern.search(text) for pattern in WORKFLOW_HAZARDS.values())
    assert Path(".github/workflows/ci.yml").as_posix() in tracked_files()
