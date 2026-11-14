"""The end-to-end simulation: each native feature in its loop fails a test when it is not.

Offline: synthetic data in a temporary catalog; the command runs with socket syscalls
blocked (the filter from `test_alpaca_sim.py`). Every value here is a placeholder.
"""

import json
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model import (
    InstrumentId,
    MarketStatusAction,
    Money,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    TimeInForce,
)

from meridian.sim import catalog, runner
from meridian.sim.strategies import GatedBreakout, refusal
from meridian.sim.venue import SETS, VenueModels
from meridian.strategy_template.sim import SCENARIOS, synthetic_universe

ROOT = Path(__file__).resolve().parents[1]
BASE = VenueModels(name="test-base")
AFTER_HOURS_NS = 1_704_317_400_000_000_000  # 2024-01-03 21:30 UTC, 16:30 New York
SATURDAY_NS = 1_704_553_200_000_000_000  # 2024-01-06 15:00 UTC: no Alpaca session


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return runner.write_catalog(tmp_path_factory.mktemp("sim"))


def run(models, store, **kwargs):
    seen = {}

    def inspect(node, run_id, template, bracket):
        seen["fills"] = node.generate_fills_report(run_id)
        seen["orders"] = list(node.get_engine_cache(run_id).orders())
        seen["template"], seen["bracket"] = template, bracket

    data = runner.run_set(models, store, inspect=inspect, **kwargs)
    return data, seen


def first_fill(seen, symbol, side="BUY"):
    fills = seen["fills"]
    rows = fills[(fills["instrument_id"] == symbol) & (fills["order_side"] == side)]
    row = rows.sort_values("ts_event").iloc[0]
    return row["ts_event"].value, Decimal(str(row["last_px"]))


@pytest.fixture(scope="module")
def base(store):
    return run(BASE, store)


def test_every_set_runs_the_template_and_the_bracket(store):
    for models in SETS:
        data = runner.run_set(models, store)
        assert data["problems"] == [], (models.name, data["problems"])
        assert data["statistics"]["total_orders"] == data["orders_total"] > 0


def test_the_template_enters_only_symbols_on_the_mover_list(store, base):
    # BREACH is left off the synthetic screener lists: it never enters, while every
    # scenario on the list behaves as with the full list.
    on_list = [i for i in catalog.instrument_ids(SCENARIOS) if i.symbol.value != "BREACH"]
    data = runner.run_set(BASE, store, universe=synthetic_universe(on_list, catalog.START_NS))
    assert data["symbols"]["BREACH.SIM"]["entries"] == 0
    assert data["symbols"]["BREACH.SIM"]["phase"] == "flat"
    for symbol, report in base[0]["symbols"].items():
        if symbol != "BREACH.SIM":
            assert data["symbols"][symbol]["events"] == report["events"], symbol
    assert base[0]["symbols"]["BREACH.SIM"]["entries"] == 1  # on the full list, it enters


def test_a_list_received_after_the_quotes_authorizes_nothing(store):
    ids = list(catalog.instrument_ids(SCENARIOS))
    late = synthetic_universe(ids, catalog.START_NS + 3_600_000_000_000)
    data = runner.run_set(BASE, store, universe=late)
    assert all(r["entries"] == 0 for r in data["symbols"].values())


def test_latency_moves_the_fill_time(store, base):
    latency = 300_000_000
    late, seen = run(replace(BASE, insert_latency_ns=latency), store)
    t0, _ = first_fill(base[1], "BRACKET.SIM")
    t1, _ = first_fill(seen, "BRACKET.SIM")
    assert t1 >= t0 + latency


def test_the_fee_model_changes_pnl_by_the_fee(store, base):
    fee = Decimal("1.00")
    charged, _ = run(replace(BASE, commission=Money.from_str(f"{fee} USD")), store)
    assert Decimal(base[0]["commissions_usd"]) == 0
    filled_orders = len({o.client_order_id for o in base[1]["orders"] if o.filled_qty > 0})
    assert Decimal(charged["commissions_usd"]) == fee * filled_orders
    pnl = [d["statistics"]["pnls"]["USD"]["PnL (total)"] for d in (base[0], charged)]
    assert Decimal(str(pnl[0] - pnl[1])).quantize(Decimal("0.01")) == fee * filled_orders


def test_slippage_moves_the_fill_price(store, base):
    slipped, seen = run(replace(BASE, prob_slippage=1.0, random_seed=1), store)
    _, px0 = first_fill(base[1], "BREACH.SIM")
    _, px1 = first_fill(seen, "BREACH.SIM")
    assert px1 == px0 + catalog.TICK  # one tick against the buy, inside its limit


def test_the_trailing_stop_triggers_at_the_emulated_level(base):
    _, seen = base
    book = next(b for i, b in seen["template"].books.items() if str(i) == "BREACH.SIM")
    trigger = Decimal(book.triggers[-1][1])
    release_ns = book.releases[0]
    ticks = catalog.quotes(book.instrument_id, SCENARIOS["BREACH"][0], catalog.START_NS)
    before = [q for q in ticks if q.ts_init < release_ns]
    at = next(q for q in ticks if q.ts_init == release_ns)
    assert all(q.bid_price.as_decimal() > trigger for q in before[-3:])
    assert at.bid_price.as_decimal() <= trigger  # the first quote through the emulated level
    released = next(
        o for o in seen["orders"] if o.instrument_id == book.instrument_id and o.side.name == "SELL"
    )
    assert released.order_type.name == "LIMIT" and released.price.as_decimal() < trigger


class MarketAndLimit(GatedBreakout):
    """Submits one MARKET and one DAY LIMIT buy on its first quote, then nothing."""

    def on_quote(self, quote: QuoteTick) -> None:
        if getattr(self, "_sent", False) or "QUIET" not in str(quote.instrument_id):
            return
        self._sent = True
        qty = Quantity.from_int(1)
        self.submit_order(self.order_factory.market(quote.instrument_id, OrderSide.BUY, qty))
        price = Price.from_str(str(quote.ask_price))
        self.submit_order(
            self.order_factory.limit(
                quote.instrument_id, OrderSide.BUY, qty, price, time_in_force=TimeInForce.DAY
            )
        )


def gated(tmp_path, start_ns):
    store = runner.write_catalog(tmp_path, start_ns=start_ns)
    data, seen = run(BASE, store, template_type=MarketAndLimit, start_ns=start_ns)
    template = [o for o in seen["orders"] if o.strategy_id == seen["template"].strategy_id]
    return data, template


def test_market_refused_outside_regular_hours_where_a_limit_is_accepted(tmp_path):
    data, orders = gated(tmp_path / "after", AFTER_HOURS_NS)
    assert [o.order_type.name for o in orders] == ["LIMIT"]
    assert orders[0].status.name == "FILLED"
    # The MARKET, and the bracket, whose stop-loss is a STOP_MARKET.
    reasons = {r for _, r in data["session_refusals"]}
    assert len(data["session_refusals"]) == 2 and "bracket" in dict(data["session_refusals"])
    assert reasons == {"after_hours: only LIMIT orders with DAY or GTC"}
    data, orders = gated(tmp_path / "regular", catalog.START_NS)
    assert [o.order_type.name for o in orders] == ["MARKET", "LIMIT"]
    assert all(o.status.name == "FILLED" for o in orders) and not data["session_refusals"]


def test_outside_every_session_the_venue_rejects_from_its_status_data(tmp_path):
    data, orders = gated(tmp_path, SATURDAY_NS)
    # No session: the rule leaves both to the venue, whose CLOSE status rejects both.
    assert [o.status.name for o in orders] == ["REJECTED", "REJECTED"]
    assert data["bracket"]["entry"] == "REJECTED" and not data["session_refusals"]


def test_the_throttle_denies_above_its_rate(tmp_path):
    store = runner.write_catalog(tmp_path, copies=3)
    data = runner.run_set(replace(BASE, max_order_submit_rate="2/00:00:01"), store, copies=3)
    assert data["orders_denied"] > 0
    assert runner.run_set(BASE, store, copies=3)["orders_denied"] == 0


def test_same_inputs_same_fills(store, base):
    again, seen = run(BASE, store)
    columns = ["client_order_id", "trade_id", "last_px", "last_qty", "ts_event", "commission"]
    fills = [f.reset_index()[columns] for f in (seen["fills"], base[1]["fills"])]
    assert fills[0].equals(fills[1]) and len(fills[0]) > 0
    assert again["statistics"] == base[0]["statistics"]


def test_session_statuses_follow_alpaca_sessions():
    iid = InstrumentId.from_str("X.SIM")
    friday_close = 1_704_502_800_000_000_000  # 2024-01-05 20:00 New York
    sunday_open = 1_704_675_600_000_000_000  # 2024-01-07 20:00 New York
    events = catalog.status_events(iid, friday_close - 1, sunday_open + 1)
    assert [(e.action, e.ts_event) for e in events] == [
        (MarketStatusAction.TRADING, friday_close - 1),
        (MarketStatusAction.CLOSE, friday_close),
        (MarketStatusAction.TRADING, sunday_open),
    ]


def test_refusal_admits_emulated_and_regular_orders(base):
    _, seen = base
    emulated = next(o for o in seen["orders"] if o.is_emulated)
    assert refusal(emulated, AFTER_HOURS_NS) is None
    limit = next(o for o in seen["orders"] if o.order_type.name == "LIMIT")
    assert refusal(limit, catalog.START_NS) is None
    assert refusal(limit, AFTER_HOURS_NS) is None


# The catalog's tokio runtime opens one AF_UNIX socketpair for its signal driver on first use
# (tokio 1.54.1, src/signal/unix.rs:68), which the suite's filter traps. So: trap socket(2)
# from the start, create that runtime, then add the suite's own filter (socket and
# socketpair). No network socket is ever opened, and nothing at all after the runtime starts.
DRIVER = """
import ctypes, sys, tempfile
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/tests"]
class F(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte),
                ("k", ctypes.c_uint)]
class P(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(F))]
rules = (F * 4)(F(0x20, 0, 0, 0), F(0x15, 0, 1, 41), F(0x06, 0, 0, 0x30000),
                F(0x06, 0, 0, 0x7FFF0000))
libc = ctypes.CDLL(None)
assert libc.prctl(38, 1, 0, 0, 0) == 0 and libc.prctl(22, 2, ctypes.byref(P(4, rules)), 0, 0) == 0
from nautilus_trader.persistence import ParquetDataCatalog
ParquetDataCatalog(tempfile.mkdtemp())
from test_alpaca_sim import block_sockets
block_sockets()
from meridian import boundary
from meridian.sim.runner import main
boundary.REPO_ROOT = Path(sys.argv[2])
raise SystemExit(main([]))
"""


def test_command_without_sockets_writes_engine_reports(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", DRIVER, str(ROOT), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith("SIMULATION; not a lane")
    assert lines[-2] == "PASS"
    record = json.loads((tmp_path / lines[-1].split(": ")[1]).read_text())
    assert [s["set"] for s in record["sets"]] == [m.name for m in SETS]
    for data in record["sets"]:
        folder = tmp_path / data["report"]
        for name in ("tearsheet.html", "orders.csv", "fills.csv", "positions.csv"):
            assert (folder / name).stat().st_size > 0
        assert f"report: {data['report']}/" in result.stdout
    assert "pnls: " in result.stdout and "returns: " in result.stdout
    assert all(p.relative_to(tmp_path).parts[0] == "runs" for p in tmp_path.rglob("*"))
