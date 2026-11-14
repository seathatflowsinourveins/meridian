"""
Paper only: tripwires for recognizable live endpoints, ports, modes and key names
in files git can see. Computed values and indirect calls can escape a source scan.

"Live" here means real-money trading. NautilusTrader's own names such as ``LiveNode`` and
``Environment.LIVE`` mean "connected to a venue, not a backtest" and are not matched.

This scan is a tripwire, not the boundary. The boundaries are ``meridian/boundary.py`` and
the runtime host guards in ``meridian/alpaca/wire.py``. Literal folding never executes code.
"""

import ast
import io
import os
import re
import subprocess
import tokenize
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# This file states the patterns. The lock file holds only package names and hashes.
NOT_SCANNED = {"tests/test_paper_only.py", "uv.lock"}

# Only folded expressions get this allowance; the original text is always scanned.
# Existing negative fixtures, explicitly approved by the lead. No filename-wide exemption.
FOLDED_FIXTURES = {
    "tests/test_alpaca_paper.py": {
        "api.alpaca.markets",
        "TradingClient(key, secret, paper=False)",
        "url_override='https://api.alpaca.markets'",
        "BaseURL.TRADING_LIVE",
        "BaseURL.TRADING_STREAM_LIVE",
    },
}

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
    # alpaca-py 0.45.0 picks its live hosts by `paper=False` or by these BaseURL names.
    "live switch (alpaca-py)": re.compile(r"\bpaper\s*=\s*False\b"),
    "live host name (alpaca-py BaseURL)": re.compile(
        r"\b(?:TRADING_LIVE|TRADING_STREAM_LIVE|BROKER_PRODUCTION)\b"
    ),
}
_NAME = re.compile(r"[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*")
_NAME_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_SECRET_WORDS = {"key", "secret", "token", "password"}
_SECRET_PART = re.compile(r"(?:api)?(?:key|secret|token|password)s?")
_COMPOUND_SECRET = re.compile(
    r"(?:live(?:api)?(?:key|secret|token|password)s?|"
    r"(?:api)?(?:key|secret|token|password)s?live)"
)


def live_key_name(text: str) -> bool:
    """A name with LIVE as one of its parts and a secret word as another."""
    for name in _NAME.findall(text):
        parts = {part.lower() for part in _NAME_PART.findall(name)}
        if "live" in parts and parts & _SECRET_WORDS:
            return True
        if "live" in parts and any(_SECRET_PART.fullmatch(part) for part in parts):
            return True
        if any(_COMPOUND_SECRET.fullmatch(part) for part in parts):
            return True
    return False


def text_findings(text: str) -> list[str]:
    found = [label for label, pattern in LIVE_PATTERNS.items() if pattern.search(text)]
    if live_key_name(text):
        found.append("live key name")
    return found


def python_tree(text: str) -> ast.Module | None:
    try:
        return ast.parse(text)
    except SyntaxError, ValueError:
        return None  # Non-Python files still receive every original text rule.


def literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literal_text(node.left), literal_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def folded_strings(text: str) -> Iterator[str]:
    """Maximal literal additions and adjacent Python string literals, without eval.

    Variables, formatting and function calls are not resolved. Non-Python text is not
    folded. Keep maximal expressions so the allowance matches the entire fixture value.
    """

    def visit(node: ast.AST) -> Iterator[str]:
        if isinstance(node, ast.JoinedStr):
            return  # Formatting is outside literal folding, including its partial constants.
        value = literal_text(node)
        if value is not None:
            segment = ast.get_source_segment(text, node) or ""
            tokens = tokenize.generate_tokens(io.StringIO("(" + segment + ")").readline)
            if sum(token.type == tokenize.STRING for token in tokens) > 1:
                yield value
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    tree = python_tree(text)
    if tree is not None:
        yield from visit(tree)


def python_findings(text: str) -> list[str]:
    tree = python_tree(text)
    if tree is None:
        return []
    # Installed alpaca-py 0.45.0: TradingClient has oauth_token before paper;
    # TradingStream has paper immediately after the two credentials.
    positions = {"TradingClient": 4, "TradingStream": 3}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "alpaca.trading.client",
            "alpaca.trading.stream",
        }:
            for alias in node.names:
                if alias.name in positions:
                    positions[alias.asname or alias.name] = positions[alias.name]
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "paper" for target in node.targets
            )
            and not (isinstance(node.value, ast.Constant) and node.value.value is True)
        ):
            found.append("paper assignment is not literal True")
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "paper" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            ):
                found.append("paper switch is not literal True")
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name in positions and (
            len(node.args) >= positions[name]
            or any(isinstance(arg, ast.Starred) for arg in node.args)
            or any(keyword.arg is None for keyword in node.keywords)
        ):
            found.append("positional or unpacked SDK options outside paper wrappers")
    return found


def findings(text: str, name: str = "") -> list[str]:
    found = text_findings(text) + python_findings(text)
    for value in folded_strings(text):
        if value not in FOLDED_FIXTURES.get(name, set()):
            found.extend(text_findings(value) + python_findings(value))
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
        hits += [
            f"{name}: {label}" for label in findings(data.decode("utf-8", errors="replace"), name)
        ]
    assert hits == []


@pytest.mark.parametrize(
    "text",
    [
        "port = 4001",
        "IB_PORT=7496",
        "connect('127.0.0.1', 4001)",
        "the Gateway live port is 4001.",
        "https://api.alpaca.markets/v2/orders",
        "wss://api.alpaca.markets/stream",
        "https://broker-api.alpaca.markets",
        "TradingClient(key, secret, paper=False)",
        "TradingStream(key, secret, paper = False)",
        "BaseURL.TRADING_LIVE",
        "BaseURL.TRADING_STREAM_LIVE",
        "BaseURL.BROKER_PRODUCTION",
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
        "wss://paper-api.alpaca.markets/stream",
        "TradingClient(key, secret, paper=True, url_override=PAPER_TRADING_URL)",
        "BaseURL.TRADING_PAPER",
        "https://data.alpaca.markets/v2/stocks/quotes",
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


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "0.0",
        "-0.0",
        "+0",
        "0e0",
        "0j",
        "0x0",
        "0o0",
        "0b0",
        "None",
        "''",
        '""',
        "b''",
        "[]",
        "{}",
        "()",
        "set()",
        "(False)",
        "not True",
        "bool()",
        "bool(0)",
        "settings.paper",
    ],
)
def test_nonliteral_true_paper_switches_are_refused(value):
    assert findings(f"TradingClient(key, secret, paper={value})")
    assert findings(f"paper={value}")


@pytest.mark.parametrize(
    "text",
    [
        "TradingClient(key, secret, None, False)",
        "TradingClient(key, secret, None, True)",
        "TradingStream(key, secret, False)",
        "TradingStream(key, secret, True)",
        "alpaca.trading.stream.TradingStream(key, secret, 0)",
        "from alpaca.trading.client import TradingClient as Client\nClient(k, s, None, False)",
        "TradingClient(*args)",
        "TradingStream(**options)",
    ],
)
def test_sdk_positional_switches_and_unpacked_options_are_refused(text):
    assert findings(text)


@pytest.mark.parametrize(
    "name",
    [
        "LIVE_KEYS",
        "ALPACA_LIVE_APIKEY",
        "livekey",
        "livekeys",
        "liveapikey",
        "liveSecrets",
        "LIVE_TOKENS",
        "LIVE_PASSWORDS",
        "KEYSLIVE",
    ],
)
def test_plural_and_compound_secret_names_are_refused(name):
    assert live_key_name(name)


@pytest.mark.parametrize(
    "source",
    [
        'HOST = "api." + "alpaca.markets"',
        'HOST = "api." "alpaca.markets"',
        'HOST = ("api."\n "alpaca.markets")',
        'HOST = ("api." + ("alpaca." + "markets"))',
        'HOST = "api\\x2e" + "alpaca.markets"',
        'HOST = "https://api." + "alpaca.markets/v2/orders"',
    ],
)
def test_literal_concatenated_hosts_are_refused(source):
    assert findings(source)


@pytest.mark.parametrize("name", ["tests/test_alpaca_paper.py", "meridian/alpaca/planted.py"])
def test_unlisted_folded_host_fails_even_in_the_fixture_file(monkeypatch, name):
    source = 'HOST = "https://api." + "alpaca.markets/planted"'
    # Exercise the repository scanner, including its filename-aware fixture allowance.
    monkeypatch.setattr(__import__(__name__), "files_to_scan", lambda: [name])
    monkeypatch.setattr(__import__(__name__), "scan_bytes", lambda _: source.encode())
    with pytest.raises(AssertionError):
        test_no_live_endpoint_port_mode_or_key_name_in_the_repo()
    # The approved value is allowed only as a fold in the named fixture file.
    source = 'HOST = "api." + "alpaca.markets"'
    if name == "tests/test_alpaca_paper.py":
        test_no_live_endpoint_port_mode_or_key_name_in_the_repo()
    else:
        with pytest.raises(AssertionError):
            test_no_live_endpoint_port_mode_or_key_name_in_the_repo()
    source = 'HOST = "api.alpaca.markets"'
    with pytest.raises(AssertionError):
        test_no_live_endpoint_port_mode_or_key_name_in_the_repo()


@pytest.mark.parametrize(
    ("module", "parts"),
    [
        ("wire.py", ("api.alpaca.", "markets")),
        ("data.py", ("api.alpaca.", "markets")),
        ("commission.py", ("api.alpaca.", "markets")),
        ("commission.py", ("docs.alpaca.", "markets/uncited")),
    ],
)
@pytest.mark.parametrize("join", [" + ", " "])
def test_package_scope_refuses_split_hosts(tmp_path, module, parts, join):
    from test_alpaca_paper import PACKAGE, assert_package_hosts

    (tmp_path / "data.py").write_text('HOST = "stream.data.alpaca.markets"')
    (tmp_path / "commission.py").write_text((PACKAGE / "commission.py").read_text())
    with (tmp_path / module).open("a") as output:
        output.write("\nPLANTED = " + repr(parts[0]) + join + repr(parts[1]))
    with pytest.raises(AssertionError, match="unexpected Alpaca host"):
        assert_package_hosts(tmp_path)
