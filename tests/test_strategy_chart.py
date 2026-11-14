"""The chart page of a fixed synthetic run: its data equals the run's reports; offline, verbatim."""

import csv
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from meridian import boundary
from meridian.strategy_template import chart, sim

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "upstream/lightweight-charts/v5.2.1/lightweight-charts.standalone.production.js"
# The only URLs in the verbatim library: its licence comment, the SVG namespace of its logo, and
# the attribution link the logo opens on a click (README "License and attribution"). None loads.
LIBRARY_URLS = {
    "https://www.apache.org/licenses/LICENSE-2.0",
    "http://www.w3.org/2000/svg",
    "https://www.tradingview.com/?utm_medium=lwc-link&utm_campaign=lwc-chart",
}


def generate(root, monkeypatch):
    monkeypatch.setattr(boundary, "REPO_ROOT", root)
    books = {}
    data = sim.run(chart=True, inspect=lambda engine, strategy: books.update(strategy.books))
    folder = root / data["report"]["directory"]
    return folder, (root / data["report"]["chart"]).read_bytes(), books


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        return generate(tmp_path_factory.mktemp("chart"), monkeypatch)


def split(page: bytes) -> tuple[bytes, bytes]:
    """(the page without the library, the embedded library)."""
    start = page.index(chart.LIBRARY_TAG) + len(chart.LIBRARY_TAG)
    end = page.index(b"</script>", start)
    return page[:start] + page[end:], page[start:end]


def embedded(page: bytes) -> dict:
    match = re.search(rb'<script id="run-data" type="application/json">(.*?)</script>', page, re.S)
    assert match
    return json.loads(match.group(1))


def bids_by_symbol() -> dict[str, dict[int, Decimal]]:
    return {
        f"{name}.{sim.VENUE}": {sim.START_NS + i * sim.STEP_NS: b for i, b in enumerate(bids)}
        for name, (bids, *_inputs) in sim.SCENARIOS.items()
    }


def test_the_embedded_library_is_byte_identical_to_the_upstream_copy(generated):
    _folder, page, _books = generated
    assert page.count(chart.LIBRARY_TAG) == 1
    assert split(page)[1] == LIBRARY.read_bytes()


def test_no_url_in_the_page_points_outside_the_file(generated):
    _folder, page, _books = generated
    own, library = split(page)
    text = own.decode()
    assert not re.search(r"[a-z][a-z0-9+.-]*://|//[a-z0-9]", text, re.I)
    for loader in ("src=", "href=", "url(", "@import", "<link", "<iframe", "<img", "fetch("):
        assert loader not in text.lower()
    found = set(re.findall(rb"https?://[^\s\"'`)$]+", library))
    assert {u.decode() for u in found} == LIBRARY_URLS


def test_one_fill_marker_per_fill_with_the_reports_prices_and_times(generated):
    folder, page, _books = generated
    with (folder / "fills.csv").open(newline="") as stream:
        fills = list(csv.DictReader(stream))
    symbols = embedded(page)["symbols"]
    assert sum(len(s["markers"]) for s in symbols) == len(fills) > 0
    for s in symbols:
        rows = sorted(
            (r for r in fills if r["instrument_id"] == s["symbol"]),
            key=lambda r: pd.Timestamp(r["ts_event"]).value,
        )
        assert len(rows) == len(s["markers"])
        for row, m in zip(rows, s["markers"], strict=True):
            ts = pd.Timestamp(row["ts_event"]).value
            assert (m["ts"], m["side"], m["qty"], m["px"]) == (
                ts,
                row["order_side"],
                row["last_qty"],
                row["last_px"],
            )
            assert m["time"] == ts // chart.NS and m["price"] == float(row["last_px"])
            entry = row["order_side"] == "BUY"
            assert m["shape"] == ("arrowUp" if entry else "arrowDown")
            assert m["text"].startswith("entry BUY" if entry else "exit SELL")
            assert f"{row['last_qty']} @ {row['last_px']}" in m["text"]


def test_candles_are_the_run_quotes_bids_per_second(generated):
    symbols = embedded(generated[1])["symbols"]
    bids = bids_by_symbol()
    assert [s["symbol"] for s in symbols] == list(bids)
    for s in symbols:
        seconds: dict[int, list[float]] = {}
        for ts, bid in bids[s["symbol"]].items():
            seconds.setdefault(ts // chart.NS, []).append(float(bid))
        expected = [
            {"time": t, "open": v[0], "high": max(v), "low": min(v), "close": v[-1]}
            for t, v in seconds.items()
        ]
        assert s["bars"] == expected


def test_the_trail_is_the_recorded_trigger_and_never_above_the_bid(generated):
    _folder, page, books = generated
    bids = bids_by_symbol()
    for s in embedded(page)["symbols"]:
        recorded = books[next(i for i in books if str(i) == s["symbol"])].triggers
        holdings = s["summary"]["entries"]
        assert len(s["trail"]) == holdings
        for segment in s["trail"]:
            times = [p["time"] for p in segment]
            assert times == sorted(set(times)) and segment
            for p in segment:
                level = max((t, lv) for t, lv in recorded if t <= p["ts"])[1]
                assert p["level"] == level and p["value"] == float(level)
                assert Decimal(p["level"]) < bids[s["symbol"]][p["ts"]]  # long only
        held = s["summary"]["phase"] == "holding"
        assert (s["open_trail"] is not None) == held


def test_the_statistics_table_is_the_engines(generated):
    folder, page, _books = generated
    stats = json.loads((folder / "statistics.json").read_text())["statistics"]
    text = page.decode()
    rows = chart.statistics_rows(stats)
    assert len(rows) == text.count("<tr><td>") > 10
    for group, name, value in rows:
        assert f"<tr><td>{group}</td><td>{name}</td><td>{value}</td></tr>" in text
    assert "<td>Win Rate</td><td>0.4</td>" in text and "<td>undefined</td>" in text


def test_the_page_is_deterministic(generated, tmp_path, monkeypatch):
    assert generate(tmp_path, monkeypatch)[1] == generated[1]


def test_chart_command_is_socket_free_and_writes_only_under_runs(tmp_path):
    code = f"""
import sys
sys.path.insert(0, {str(ROOT / "tests")!r})
from test_alpaca_sim import block_sockets
block_sockets()
from pathlib import Path
from meridian import boundary
from meridian.strategy_template import sim
boundary.REPO_ROOT = Path({str(tmp_path)!r})
raise SystemExit(sim.main(['--chart']))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Chart (opens offline): runs/" in result.stdout
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 7 and all(p.is_relative_to(tmp_path / "runs") for p in files)
    assert sum(p.name == "chart.html" for p in files) == 1
