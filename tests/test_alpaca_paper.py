"""
The Alpaca lane is paper only by construction, and its keys arrive only as systemd credentials.

These checks sit beside the tripwire in `test_paper_only.py`, which reads every file git can
see, this package and the unit included. Its exact folded-string allowance names this file's
existing negative fixtures; other recognizable host and switch markers fail the scan.
"""

import re
from pathlib import Path
from typing import Any

import pytest
from test_paper_only import REPO_ROOT, files_to_scan, findings, folded_strings, scan_bytes

from meridian.alpaca import constants
from meridian.alpaca.credentials import (
    CREDENTIAL_NAMES,
    KEY_ID,
    SECRET_KEY,
    PaperKeys,
    PaperKeysUnavailable,
    load_paper_keys,
    main,
)
from meridian.alpaca.factories import paper_stream
from meridian.alpaca.wire import PaperTradingClient

PACKAGE = REPO_ROOT / "meridian" / "alpaca"
UNIT = REPO_ROOT / "deploy" / "systemd" / "meridian-alpaca-paper.service"
HOST = re.compile(r"(?:[a-z0-9-]+\.)*alpaca\.markets")
# The shape Alpaca API key ids are commonly issued in: PK (paper) or AK (live) and 16 to 20
# more capitals or digits. An observed convention, used here only as a tripwire.
KEY_ID_SHAPE = re.compile(r"(?<![A-Za-z0-9])[PA]K[A-Z0-9]{16,20}(?![A-Za-z0-9])")
SYNTHETIC = PaperKeys("synthetic-key-id", "synthetic-secret")


# Each module may name the paper trading host; only these may name extra hosts.
# Documentation hosts, if needed by another module, get their own explicit row.
MODULE_EXTRA_HOSTS = {
    "data.py": {"stream.data.alpaca.markets"},
    "commission.py": {"docs.alpaca.markets", "alpaca.markets"},
}


def assert_package_hosts(package: Path) -> None:
    """Paper trading, quote data and commission citations have distinct host scopes."""
    data_host = "stream.data.alpaca.markets"
    for path in package.glob("*.py"):
        text = path.read_text()
        folded = list(folded_strings(text))
        hosts = set(HOST.findall(text))
        hosts.update(host for value in folded for host in HOST.findall(value))
        allowed = {constants.PAPER_HOST} | MODULE_EXTRA_HOSTS.get(path.name, set())
        assert hosts <= allowed, f"unexpected Alpaca host in {path.name}"
        if path.name == "commission.py":
            for url in (
                "https://docs.alpaca.markets/us/docs/paper-trading",
                "https://alpaca.markets/support/commission-clearing-fees",
            ):
                citation = f'url="{url}"'
                assert text.count(citation) == 1, "missing or repeated commission citation"
                text = text.replace(citation, "")
            # Only the cited URLs belong here, never an API, broker, data or stream host.
            assert not HOST.findall(text), f"unexpected Alpaca host in {path.name}"
            assert not any(HOST.search(value) for value in folded), (
                f"unexpected Alpaca host in {path.name}"
            )
    assert data_host in HOST.findall((package / "data.py").read_text())


def test_the_paper_host_is_the_only_trading_host_this_package_names():
    assert constants.PAPER_TRADING_URL == "https://paper-api.alpaca.markets"
    assert constants.PAPER_TRADE_STREAM_URL == "wss://paper-api.alpaca.markets/stream"
    assert_package_hosts(PACKAGE)


@pytest.mark.parametrize(
    ("module", "host"),
    [
        ("data.py", "stream.data.sandbox.alpaca.markets"),
        ("data.py", "overnight.alpaca.markets"),
        ("data.py", "data.alpaca.markets"),
        ("data.py", "api." + "alpaca.markets"),
        ("wire.py", "stream.data.alpaca.markets"),
        ("wire.py", "https://docs.alpaca.markets/us/docs/paper-trading"),
        ("wire.py", "https://alpaca.markets/support/commission-clearing-fees"),
        ("commission.py", "wss://paper-api.alpaca.markets/stream"),
        ("commission.py", "https://unlisted-docs.alpaca.markets/paper-trading"),
        ("commission.py", "api." + "alpaca.markets"),
        ("commission.py", "https://docs.alpaca.markets/uncited-page"),
    ],
)
def test_package_host_check_rejects_planted_hosts(tmp_path, module, host):
    (tmp_path / "data.py").write_text('HOST = "stream.data.alpaca.markets"')
    (tmp_path / "wire.py").write_text('HOST = "paper-api.alpaca.markets"')
    (tmp_path / "commission.py").write_text((PACKAGE / "commission.py").read_text())
    assert_package_hosts(tmp_path)
    with (tmp_path / module).open("a") as output:
        output.write(f'\nPLANTED = "{host}"')
    with pytest.raises(AssertionError, match="unexpected Alpaca host"):
        assert_package_hosts(tmp_path)


def test_both_sdk_clients_are_built_on_the_paper_host():
    client = PaperTradingClient(SYNTHETIC.key_id, SYNTHETIC.secret_key, timeout_secs=5)
    assert client._base_url == constants.PAPER_TRADING_URL
    stream = paper_stream(SYNTHETIC)  # constructing it opens no socket
    assert stream._endpoint == constants.PAPER_TRADE_STREAM_URL
    assert stream._raw_data is True


def test_the_build_failing_scan_reads_this_package_and_the_unit():
    scanned = set(files_to_scan())
    package = {str(path.relative_to(REPO_ROOT)) for path in PACKAGE.glob("*.py")}
    assert package and package <= scanned
    assert str(UNIT.relative_to(REPO_ROOT)) in scanned
    for name in sorted(package) + [str(UNIT.relative_to(REPO_ROOT))]:
        assert findings((REPO_ROOT / name).read_text()) == [], name


@pytest.mark.parametrize(
    "text",
    [
        "TradingClient(key, secret, " + "paper=" + "False)",
        "url_override='https://" + "api." + "alpaca.markets'",
        "BaseURL." + "TRADING_" + "LIVE",
        "BaseURL." + "TRADING_STREAM_" + "LIVE",
    ],
)
def test_the_scan_catches_the_sdks_live_switches_in_this_packages_terms(text):
    assert findings(text)


def test_no_alpaca_key_shaped_value_is_anywhere_in_the_repository():
    hits = []
    for name in files_to_scan():
        data = scan_bytes(name)  # a symbolic link is read as its own text, never followed
        if b"\0" in data:
            continue
        if KEY_ID_SHAPE.search(data.decode("utf-8", errors="replace")):
            hits.append(name)  # the file only, never the value
    assert hits == []
    assert KEY_ID_SHAPE.search("PK" + "A1B2C3D4E5F6G7H8I9")  # the tripwire itself works


def write(directory: Path, name: str, data: bytes) -> None:
    (directory / name).write_bytes(data)


def test_the_keys_come_from_the_credentials_directory_only(tmp_path):
    write(tmp_path, KEY_ID, b"synthetic-key-id\n")
    write(tmp_path, SECRET_KEY, b"synthetic-secret")
    keys = load_paper_keys({"CREDENTIALS_DIRECTORY": str(tmp_path)})
    assert (keys.key_id, keys.secret_key) == ("synthetic-key-id", "synthetic-secret")
    assert "synthetic" not in repr(keys) and "synthetic" not in str(keys)
    with pytest.raises(PaperKeysUnavailable, match="CREDENTIALS_DIRECTORY"):
        load_paper_keys({})
    with pytest.raises(PaperKeysUnavailable, match="CREDENTIALS_DIRECTORY"):
        load_paper_keys({"ALPACA_PAPER_API_KEY": "anything"})  # the environment is never read


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (None, "is missing"),
        (b"", "empty or not one printable token"),
        (b"\n", "empty or not one printable token"),
        (b"two words", "empty or not one printable token"),
        (b"tab\tinside", "empty or not one printable token"),
        ("café".encode(), "empty or not one printable token"),
        (b"x" * 300, "longer than"),
    ],
)
def test_a_missing_or_malformed_credential_refuses_by_name_never_by_value(tmp_path, data, why):
    write(tmp_path, KEY_ID, b"synthetic-key-id")
    if data is not None:
        write(tmp_path, SECRET_KEY, data)
    with pytest.raises(PaperKeysUnavailable, match=why) as info:
        load_paper_keys({"CREDENTIALS_DIRECTORY": str(tmp_path)})
    assert SECRET_KEY in str(info.value)
    assert "synthetic" not in str(info.value)


def test_the_offline_check_reports_presence_and_no_value(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    assert main() == 1
    assert "refused" in capsys.readouterr().err
    write(tmp_path, KEY_ID, b"synthetic-key-id")
    write(tmp_path, SECRET_KEY, b"synthetic-secret")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert main() == 0
    out = capsys.readouterr()
    assert "present" in out.out and "synthetic" not in out.out + out.err


def unit_lines() -> list[tuple[str, str, str]]:
    """(section, key, value) for every setting in the unit; repeated keys are kept."""
    section, rows = "", []
    for raw in UNIT.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line
            continue
        key, _, value = line.partition("=")
        rows.append((section, key, value))
    return rows


def test_the_unit_runs_as_paper_and_reads_both_keys_as_encrypted_credentials():
    rows = unit_lines()
    settings = {(section, key): value for section, key, value in rows}
    assert settings[("[Service]", "User")] == "paper"
    assert settings[("[Service]", "Group")] == "paper"
    loaded = [value for _, key, value in rows if key == "LoadCredentialEncrypted"]
    assert sorted(loaded) == sorted(
        f"{name}:/etc/credstore.encrypted/{name}" for name in CREDENTIAL_NAMES
    )
    assert settings[("[Service]", "ExecStart")].endswith("-m meridian.alpaca.credentials")


def test_the_unit_holds_no_value_and_cannot_be_enabled():
    rows = unit_lines()
    keys = {key for _, key, _ in rows}
    # No value can travel in the unit: no environment, no inline or imported credential.
    assert not keys & {"Environment", "EnvironmentFile", "SetCredential", "SetCredentialEncrypted"}
    assert "ImportCredential" not in keys and "LoadCredential" not in keys
    # Prepared, not enabled: without an [Install] section `systemctl enable` has nothing to do.
    assert "[Install]" not in {section for section, _, _ in rows}
    text = UNIT.read_text()
    assert HOST.search(text) is None
    assert not KEY_ID_SHAPE.search(text)


def test_the_stream_refuses_a_redirect_to_another_host_before_any_key_is_sent():
    """websockets 17.4 follows redirects; with an explicit host and port it refuses a
    cross-origin one (`asyncio/client.py`, `process_redirect`). alpaca-py's default would
    follow it and then authenticate there. Checked offline, on the connect object only."""
    from websockets.asyncio.client import connect
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    stream = paper_stream(SYNTHETIC)
    params: dict[str, Any] = dict(stream._websocket_params)
    assert params["host"] == constants.PAPER_HOST and params["port"] == 443
    assert params["proxy"] is None
    elsewhere = Response(302, "Found", Headers({"Location": "wss://api.example.invalid/stream"}))
    pinned = connect(constants.PAPER_TRADE_STREAM_URL, **params)
    assert isinstance(pinned.process_redirect(InvalidStatus(elsewhere)), ValueError)
    unpinned = connect(constants.PAPER_TRADE_STREAM_URL)  # what alpaca-py would do by default
    assert unpinned.process_redirect(InvalidStatus(elsewhere)) == "wss://api.example.invalid/stream"


@pytest.mark.parametrize(
    ("secure", "host", "port", "refused"),
    [
        (True, "paper-api.alpaca.markets", 443, False),
        (True, "api.example.invalid", 443, True),
        (False, "paper-api.alpaca.markets", 80, True),
        (True, "paper-api.alpaca.markets", 8443, True),
    ],
)
def test_the_stream_checks_where_its_socket_landed_before_signing_in(
    monkeypatch, secure, host, port, refused
):
    import asyncio
    from types import SimpleNamespace

    from alpaca.trading.stream import TradingStream

    closed = []

    async def fake_connect(self):  # stands in for alpaca-py's websockets.connect call
        uri = SimpleNamespace(secure=secure, host=host, port=port)
        self._ws = SimpleNamespace(protocol=SimpleNamespace(uri=uri))

    async def fake_close(self):
        closed.append(True)
        self._ws = None

    monkeypatch.setattr(TradingStream, "_connect", fake_connect)
    monkeypatch.setattr(TradingStream, "close", fake_close)
    stream = paper_stream(SYNTHETIC)
    if refused:
        with pytest.raises(ConnectionError, match="not on the paper host"):
            asyncio.run(stream._connect())
        assert closed == [True]
    else:
        asyncio.run(stream._connect())
        assert closed == []


@pytest.mark.parametrize("key_id", [b"AK-synthetic-one", b"AK", b"AK" + b"0" * 20])
@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_credential_loader_refuses_live_shaped_ids_without_disclosure(tmp_path, key_id, ending):
    # The documented hint is about the id, not the secret; no real keys are used.
    write(tmp_path, KEY_ID, b"PK-synthetic-paper" + ending)
    write(tmp_path, SECRET_KEY, b"AK-synthetic-secret")
    assert load_paper_keys({"CREDENTIALS_DIRECTORY": str(tmp_path)}).key_id == "PK-synthetic-paper"
    write(tmp_path, KEY_ID, key_id + ending)
    write(tmp_path, SECRET_KEY, b"synthetic-secret")
    with pytest.raises(PaperKeysUnavailable) as info:
        load_paper_keys({"CREDENTIALS_DIRECTORY": str(tmp_path)})
    assert str(info.value) == "credential alpaca-paper-key-id has a refused key-id shape"


def test_offline_credential_check_hides_refused_key_shape(tmp_path, monkeypatch, capsys):
    write(tmp_path, KEY_ID, b"AK-synthetic-private")
    write(tmp_path, SECRET_KEY, b"synthetic-secret")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "refused: credential alpaca-paper-key-id has a refused key-id shape\n"
