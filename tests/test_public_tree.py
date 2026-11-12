"""
This repository is public. The build fails if an IBKR-style account id appears in any file
git can see, or if CI gains something a fork's pull request could abuse.

Account ids, raw order or fill history, reconciliation fixtures and tuned parameters belong in
the private ``meridian-evidence`` repository. Scrubbed run records in ``evidence/`` may stay.
Like the paper-only scan, this is a tripwire: it catches a pasted id, not a determined one.
Tests that need an id-shaped value build it from parts, so the literal never appears.
"""

import re
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


def tracked_files() -> list[str]:
    deleted = set(git_files("--deleted"))
    listed = git_files("--cached", "--others", "--exclude-standard")
    return [name for name in listed if name not in NOT_SCANNED and name not in deleted]


def read_text(name: str) -> str:
    path = REPO_ROOT / name
    assert path.is_file(), f"{name} is listed by git but is not a regular file"
    data = path.read_bytes()
    assert b"\0" not in data, f"{name} is not plain text (UTF-16 or binary); cannot scan it"
    return data.decode("utf-8", errors="replace")


def test_no_account_id_in_the_public_tree():
    files = tracked_files()
    assert files, "git reported no files; the scan would pass without looking at anything"
    hits = []
    for name in files:
        for line_no, line in enumerate(read_text(name).splitlines(), start=1):
            if ACCOUNT_ID.search(line):
                hits.append(f"{name}:{line_no}")  # the location only, never the value
    assert hits == []


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
