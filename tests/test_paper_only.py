"""
Paper only: the build fails if a live endpoint, a live port, a live trading mode or a
live key name appears in any file git can see.

"Live" here means real-money trading. NautilusTrader's own names such as ``LiveNode`` and
``Environment.LIVE`` mean "connected to a venue, not a backtest" and are not matched.

This scan is a tripwire, not the boundary. The boundary is ``meridian/boundary.py``.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# This file states the patterns. The lock file holds only package names and hashes.
NOT_SCANNED = {"tests/test_paper_only.py", "uv.lock"}

LIVE_PATTERNS = {
    "live port (IB Gateway live or TWS live)": re.compile(r"(?<![\w.])(?:4001|7496)(?!\w|\.\d)"),
    "live endpoint (Alpaca live trading API)": re.compile(
        r"(?<!paper-)api\.alpaca\.markets", re.IGNORECASE
    ),
    "live trading mode (IB adapter)": re.compile(
        r"TradingMode\s*(?:\.|::)\s*LIVE|trading_mode[\"']?\s*[:=]\s*[\"']?live", re.IGNORECASE
    ),
    # The Gateway's own form in jts.ini: tradingMode=l is a live login (p is paper). Also the
    # ways Python writes it (a configparser subscript, ConfigParser.set). Horizontal space only,
    # so a key on one line never joins a word on the next.
    "live login mode (IB Gateway jts.ini)": re.compile(
        r"tradingMode[\"']?[^\S\r\n]*(?:[:=]|\][^\S\r\n]*=|,)[^\S\r\n]*[\"']?l(?:ive)?\b",
        re.IGNORECASE,
    ),
}
_NAME = re.compile(r"[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*")
_NAME_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_SECRET_WORDS = {"key", "secret", "token", "password"}


def live_key_name(text: str) -> bool:
    """A name with LIVE as one of its parts and a secret word as another."""
    for name in _NAME.findall(text):
        parts = {part.lower() for part in _NAME_PART.findall(name)}
        if "live" in parts and parts & _SECRET_WORDS:
            return True
    return False


def findings(text: str) -> list[str]:
    found = [label for label, pattern in LIVE_PATTERNS.items() if pattern.search(text)]
    if live_key_name(text):
        found.append("live key name")
    return found


def git_files(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", *args], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout
    return [os.fsdecode(name) for name in out.split(b"\0") if name]


def is_link_to_listed_files(name: str, listed: set[str], root: Path = REPO_ROOT) -> bool:
    """True for a symbolic link that only shows again what git already lists.

    Such a link (``.claude/skills/<name>`` pointing at ``.agents/skills/<name>``) is scanned as
    its own text; the files behind it are scanned under their own names. It must be relative,
    not broken, and resolve inside the repository: to a listed file, or to a folder in which
    git lists every file (an ignored file there would reach an agent unscanned). Any other link
    fails the scan, because it could show an agent text that git never lists.
    """
    path = root / name
    if not path.is_symlink():
        return False
    assert not os.path.isabs(os.readlink(path)), f"{name} is an absolute symbolic link"
    assert path.exists(), f"{name} is a broken symbolic link"
    resolved = path.resolve(strict=True)
    assert resolved.is_relative_to(root), f"{name} links outside the repository"
    target = resolved.relative_to(root).as_posix()
    if resolved.is_dir():
        inside = [p.relative_to(root).as_posix() for p in resolved.rglob("*") if not p.is_dir()]
        assert inside and set(inside) <= listed, (
            f"{name} links to {target}, a folder with files git does not list"
        )
    else:
        assert target in listed, f"{name} links to {target}, which git does not list"
    return True


def files_to_scan() -> list[str]:
    """Every name git can see, less NOT_SCANNED and deleted files. Links are checked first."""
    deleted = set(git_files("--deleted"))
    listed = git_files("--cached", "--others", "--exclude-standard")
    seen = set(listed)
    names = [name for name in listed if name not in NOT_SCANNED and name not in deleted]
    for name in names:
        is_link_to_listed_files(name, seen)
    return names


def scan_bytes(name: str, root: Path = REPO_ROOT) -> bytes:
    """What a scan reads: a file's bytes, or a symbolic link's own text (git stores a link as
    the path it points to). The files behind a link are scanned under their own names."""
    path = root / name
    if path.is_symlink():
        return os.fsencode(os.readlink(path))
    # Nothing is skipped quietly: a nested repository or an odd entry fails the scan.
    assert path.is_file(), f"{name} is listed by git but is not a regular file"
    return path.read_bytes()


def test_no_live_endpoint_port_mode_or_key_name_in_the_repo():
    files = files_to_scan()
    assert files, "git reported no files; the scan would pass without looking at anything"
    hits = []
    for name in files:
        data = scan_bytes(name)
        assert b"\0" not in data, f"{name} is not plain text (UTF-16 or binary); cannot scan it"
        hits += [f"{name}: {label}" for label in findings(data.decode("utf-8", errors="replace"))]
    assert hits == []


@pytest.mark.parametrize(
    "text",
    [
        "port = 4001",
        "IB_PORT=7496",
        "connect('127.0.0.1', 4001)",
        "the Gateway live port is 4001.",
        "https://api.alpaca.markets/v2/orders",
        "DockerizedIBGatewayConfig(trading_mode=TradingMode.LIVE)",
        "TradingMode::Live",
        "TRADING_MODE=live",
        'trading_mode: "live"',
        "[Logon]\ntradingMode=l\n",
        "TradingMode = l",
        "tradingMode='l'",
        '"tradingMode": "live"',
        "[Logon]\r\ntradingMode=l\r\n",
        "tradingMode=l ; set by hand",
        "tradingMode=L",
        'parser["Logon"]["tradingMode"] = "l"',
        'parser.set("Logon", "tradingMode", "l")',
        "ALPACA_LIVE_API_KEY",
        "ibkr_live_password",
        "SECRET_KEY_LIVE",
        "liveToken",
        "live-api-key",
        "live.api.key",
    ],
)
def test_the_scan_catches_live_markers(text):
    assert findings(text)


@pytest.mark.parametrize(
    "text",
    [
        "port = 4002",
        "DEFAULT_TWS_PORT = 7497",
        "https://paper-api.alpaca.markets/v2/orders",
        "LiveNode.builder(name, trader, Environment.LIVE)",
        "LiveRiskEngineConfig(bypass=True)",
        "TradingMode.PAPER",
        "TRADING_MODE=paper",
        "[Logon]\ntradingMode=p\n",
        "tradingMode=lane",
        "jts.ini tradingMode is not p",
        "tradingMode=lively",
        "tradingMode:\n  live: false",
        'parser.get("Logon", "tradingMode", fallback=None)',
        "ts = 1794001000000000000",
        "sha256 = 'a40017496b'",
        "version 1.4001.2",
        '"price": "4001.00"',
        "ALPACA_PAPER_API_KEY",
        "delivery_token",
        "alive_key",
        "a live Gateway would be refused; the key is the allowlist",
    ],
)
def test_the_scan_leaves_paper_and_engine_names_alone(text):
    assert findings(text) == []


LISTED = {"a/skill/SKILL.md", "a/mixed/SKILL.md", "b/link"}


@pytest.fixture
def tree(tmp_path):
    root = (tmp_path / "repo").resolve()
    (root / "a" / "skill").mkdir(parents=True)
    (root / "a" / "skill" / "SKILL.md").write_text("text", encoding="utf-8")
    (root / "a" / "mixed").mkdir()
    (root / "a" / "mixed" / "SKILL.md").write_text("text", encoding="utf-8")
    (root / "a" / "mixed" / "ignored.txt").write_text("text", encoding="utf-8")
    (root / "a" / "unlisted").mkdir()
    (root / "b").mkdir()
    (tmp_path / "outside").mkdir()
    return root


@pytest.mark.parametrize("target", ["../a/skill", "../a/skill/SKILL.md"])
def test_a_link_to_listed_files_is_left_to_its_target(tree, target):
    (tree / "b" / "link").symlink_to(target)
    assert is_link_to_listed_files("b/link", LISTED, tree)
    assert scan_bytes("b/link", tree) == target.encode()
    assert not is_link_to_listed_files("a/skill/SKILL.md", LISTED, tree)


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("../../outside", "outside the repository"),
        ("/etc", "absolute"),
        ("IN-TREE", "absolute"),
        ("../a/unlisted", "git does not list"),
        ("../a/mixed", "git does not list"),
        ("..", "git does not list"),
        ("../a/missing", "broken"),
        ("link", "broken"),
        ("../missing/../a/skill", "broken"),
    ],
)
def test_any_other_link_fails_the_scan(tree, target, reason):
    # IN-TREE stands for an absolute link to a listed folder, which is refused all the same.
    (tree / "b" / "link").symlink_to(tree / "a" / "skill" if target == "IN-TREE" else target)
    with pytest.raises(AssertionError, match=reason):
        is_link_to_listed_files("b/link", LISTED, tree)
