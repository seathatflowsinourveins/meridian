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


def files_to_scan() -> list[str]:
    deleted = set(git_files("--deleted"))
    listed = git_files("--cached", "--others", "--exclude-standard")
    return [name for name in listed if name not in NOT_SCANNED and name not in deleted]


def test_no_live_endpoint_port_mode_or_key_name_in_the_repo():
    files = files_to_scan()
    assert files, "git reported no files; the scan would pass without looking at anything"
    hits = []
    for name in files:
        path = REPO_ROOT / name
        # Nothing is skipped quietly: a nested repository or an odd entry fails the scan.
        assert path.is_file(), f"{name} is listed by git but is not a regular file"
        data = path.read_bytes()
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
