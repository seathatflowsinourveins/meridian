"""Engine reports on synthetic fills only; no broker or research imports in Meridian."""

import csv
import json
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from html.parser import HTMLParser
from importlib.util import find_spec
from pathlib import Path

import pytest

from meridian import boundary
from meridian.strategy_template import report, sim

ROOT = Path(__file__).resolve().parents[1]
HAS_RESEARCH = all(find_spec(name) is not None for name in ("plotly", "pandas"))
research = pytest.mark.skipif(not HAS_RESEARCH, reason="requires uv sync --group research")


def rows(folder, name):
    with (folder / name).open(newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture(params=[("BREACH", "GAP"), tuple(sim.SCENARIOS)])
def generated(request, tmp_path, monkeypatch):
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    data = sim.run(scenarios={name: sim.SCENARIOS[name] for name in request.param}, report=True)
    folder = tmp_path / data["report"]["directory"]
    return folder, data["report"]["statistics"]


@research
def test_engine_statistics_against_fill_cashflows_and_position_lifecycles(generated):
    folder, stats = generated
    fills = sorted(rows(folder, "fills.csv"), key=lambda r: r["ts_event"])
    quantities = defaultdict(Decimal)
    cashflows = defaultdict(Decimal)
    realized = []
    count = 0
    cash = Decimal(0)
    for fill in fills:
        symbol = fill["instrument_id"]
        qty, price = Decimal(fill["last_qty"]), Decimal(fill["last_px"])
        fee = Decimal(fill["commission"].split()[0])
        if quantities[symbol] == 0:
            count += 1
        signed = qty if fill["order_side"] == "BUY" else -qty
        flow = -signed * price - fee
        quantities[symbol] += signed
        cashflows[symbol] += flow
        cash += flow
        if quantities[symbol] == 0:
            realized.append(cashflows.pop(symbol))
    # rc9 snapshot PnL is ending cash minus starting cash (open principal is still spent).
    assert stats["pnls"]["USD"]["PnL (total)"] == pytest.approx(float(cash), abs=1e-8)
    # Include a new lifecycle after netting re-entry, even if the position ID is reused.
    assert stats["total_positions"] == count == len(rows(folder, "positions.csv"))
    # rc9 includes zero realized-PnL open positions in this denominator.
    assert stats["pnls"]["USD"]["Win Rate"] == pytest.approx(
        sum(pnl > 0 for pnl in realized) / count
    )
    assert stats["returns"]["Sharpe Ratio (252 days)"] is None  # only one synthetic day
    stored = json.loads((folder / "statistics.json").read_text())
    assert stored["statistics"] == stats
    assert "NaN" not in (folder / "statistics.json").read_text()


@research
def test_engine_report_columns_and_snapshot_history(generated):
    folder, stats = generated
    orders, fills, positions = (
        rows(folder, f"{name}.csv") for name in ("orders", "fills", "positions")
    )
    assert {"client_order_id", "instrument_id", "side", "type", "status", "filled_qty"} <= orders[
        0
    ].keys()
    assert {"client_order_id", "order_side", "last_qty", "last_px", "ts_event"} <= fills[0].keys()
    assert {"position_id", "realized_pnl", "ts_opened", "ts_closed", "is_snapshot"} <= positions[
        0
    ].keys()
    assert len(orders) == stats["total_orders"]
    if stats["total_positions"] == 5:
        assert sum(p["is_snapshot"] == "True" for p in positions) == 1
        assert sum(p["side"] == "LONG" for p in positions) == 2


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        self.scripts += tag == "script"
        for key, value in attrs:
            if key == "src" or (tag == "link" and key == "href"):
                self.external.append(value)


@research
def test_report_command_is_socket_free_and_html_is_self_contained(tmp_path):
    code = f"""
import sys
sys.path.insert(0, {str(ROOT / "tests")!r})
from test_alpaca_sim import block_sockets
block_sockets()
from pathlib import Path
from meridian import boundary
from meridian.strategy_template import sim
boundary.REPO_ROOT = Path({str(tmp_path)!r})
raise SystemExit(sim.main(['--report']))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Engine statistics (null = undefined):" in result.stdout
    assert '"Win Rate":' in result.stdout and "Tearsheet: runs/" in result.stdout
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 6 and all(p.is_relative_to(tmp_path / "runs") for p in files)
    html = next(p for p in files if p.suffix == ".html").read_text()
    resources = Resources()
    resources.feed(html)
    assert not resources.external  # No CDN script, stylesheet, font, or image fetch.
    assert resources.scripts >= 2 and "plotly.js v" in html and "Plotly.newPlot(" in html
    for section in (
        "Run Information",
        "Performance Statistics",
        "Equity Curve",
        "Drawdown",
        "Monthly Returns",
        "Returns Distribution",
        "Rolling Sharpe",
        "Yearly Returns",
    ):
        assert section in html
    assert "synthetic, uncalibrated simulation" in html


@research
def test_no_trades_retains_engine_undefined_values(tmp_path, monkeypatch):
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    data = sim.run(scenarios={"QUIET": sim.SCENARIOS["QUIET"]}, report=True)["report"]
    assert data["statistics"]["total_positions"] == 0
    assert data["statistics"]["pnls"]["USD"]["Win Rate"] is None
    folder = tmp_path / data["directory"]
    assert (folder / "tearsheet.html").is_file()
    assert rows(folder, "fills.csv") == []  # rc9 empty report has no columns.


@pytest.mark.parametrize("missing", ["plotly", "pandas"])
def test_missing_group_is_actionable_and_writes_nothing(tmp_path, monkeypatch, capsys, missing):
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(report, "find_spec", lambda name: None if name == missing else object())
    assert sim.main(["--report"]) == 2
    output = capsys.readouterr().out
    assert missing in output and "uv sync --locked --group research" in output
    assert not list(tmp_path.iterdir())
