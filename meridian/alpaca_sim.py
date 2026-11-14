"""Offline synthetic practice, using the pinned engine's native simulated exchange.

Starting point at NautilusTrader v2.0.0rc9 (da6b57aefdd62b44f675e434ffcfefca7f4025dd):
examples/backtest/synthetic_data_pnl_test.py:189-253: engine, venue, in-process data,
strategy, run, dispose. docs/getting_started/backtest_low_level.py:77-120 supplies
cash/netting setup. Here: synthetic equity quotes and the unmodified OnePaperOrder,
no data provider, adapter, execution algorithm, order budget or live node.

The sandbox alternative (crates/adapters/sandbox/README.md:11-13 and
examples/live/sandbox/exec_tester.py:74-102) uses a live node and data client, as M2
sandbox_node.py does. BacktestEngine needs neither. The same native matching engine
handles commands; docs/concepts/backtesting/execution-flow.md:13-23,97-112 explains
quote-before-callback sequencing and delayed commands. No venue is implemented here.
"""

from __future__ import annotations

import json
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

import nautilus_trader
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    Currency,
    Equity,
    Money,
    OmsType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
)

from meridian import boundary
from meridian.alpaca_strategy import CLIENT_ID, INSTRUMENT_ID, OnePaperOrder
from meridian.ibkr_node import LIMIT_UNDER_BID, ORDER_QTY
from meridian.ibkr_paper import RunRecord

# Synthetic fixture values, not observed prices, balances, liquidity or latency.
# At the tag above, python/tests/unit/backtest/test_backtest_engine_surface.py:
# :1487-1494 bid/ask, :1457 size, :310-311 tick/precision,
# :1683-1696 clock/step, :279-285 balance/zero fees/native latency model.
SYNTHETIC_BID, SYNTHETIC_ASK, SYNTHETIC_SIZE = Decimal("99.99"), Decimal("100.00"), 250
SYNTHETIC_START_NS, SYNTHETIC_STEP_NS = 1_600_000_000_000_000_000, 1_000_000_000
SYNTHETIC_CASH = 1_000_000
TICK = Decimal("0.01")
DATA_SOURCE = "synthetic quotes generated in process; no market or recorded data"
EXERCISES = "Exercises the lane's strategy and engine order flow."
EXCLUDES = "Does not exercise the Alpaca adapter, order budget, credentials, streams or venue."


def synthetic_quotes(*, fill_before_cancel: bool) -> list[QuoteTick]:
    """Initial quote, next quote, final quote; only the failure fixture crosses the buy."""
    limit = (SYNTHETIC_BID * (1 - Decimal(str(LIMIT_UNDER_BID)))).quantize(
        TICK, rounding=ROUND_DOWN
    )
    prices = [(SYNTHETIC_BID, SYNTHETIC_ASK)]
    follow = (limit - TICK, limit) if fill_before_cancel else prices[0]
    prices.extend([follow, follow])
    return [
        QuoteTick(
            instrument_id=INSTRUMENT_ID,
            bid_price=Price.from_str(str(bid)),
            ask_price=Price.from_str(str(ask)),
            bid_size=Quantity.from_int(SYNTHETIC_SIZE),
            ask_size=Quantity.from_int(SYNTHETIC_SIZE),
            ts_event=SYNTHETIC_START_NS + i * SYNTHETIC_STEP_NS,
            ts_init=SYNTHETIC_START_NS + i * SYNTHETIC_STEP_NS,
        )
        for i, (bid, ask) in enumerate(prices)
    ]


def problems(data: dict[str, Any]) -> list[str]:
    """Order-mode criteria only: no implication that a lane gate or venue was checked."""
    found = []
    if data["engine_error"] or data["orders_refused"]:
        found.append("engine error or strategy refusal")
    if not data["startup_reconciliation"]["trader_started"]:
        found.append("strategy did not start")
    if data["orders_total"] != 1 or data["order"] != dict(
        type="LIMIT", time_in_force="DAY", side="BUY", quantity="1"
    ):
        found.append("expected exactly one DAY LIMIT BUY of one share")
    kinds = [event["type"] for event in data["events"]]
    if not (
        "OrderAccepted" in kinds
        and "OrderCanceled" in kinds
        and kinds.index("OrderAccepted") < kinds.index("OrderCanceled")
    ):
        found.append("expected acceptance followed by cancellation")
    stop = data["at_stop"] or {}
    if "OrderFilled" in kinds or stop.get("filled") is not False:
        found.append("synthetic order filled or fill state missing")
    if stop.get("order_status") != "CANCELED" or any(
        stop.get(key) != 0
        for key in (
            "instrument_open_orders",
            "instrument_inflight_orders",
            "instrument_open_positions",
            "account_open_orders",
            "account_open_positions",
        )
    ):
        found.append("not cancelled and flat with no working order at stop")
    return found


def practice(*, fill_before_cancel: bool = False) -> dict[str, Any]:
    record = RunRecord("order", 0)
    data = record.data
    for name in ("gateway", "boundary", "lane"):
        del data[name]
    data.update(
        schema="meridian.simulation-record/1",
        milestone="M3",
        simulation=True,
        data_source=DATA_SOURCE,
        exercises=EXERCISES,
        excludes=EXCLUDES,
        engine={"name": "NautilusTrader BacktestEngine", "version": nautilus_trader.__version__},
        scenario="synthetic fill before cancel" if fill_before_cancel else "synthetic resting buy",
        orders_total=0,
    )
    data["startup_reconciliation"]["requested"] = False
    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.OFF, bypass_logging=True),
            run_analysis=False,
        )
    )
    try:
        usd = Currency.from_str("USD")
        engine.add_venue(
            venue=INSTRUMENT_ID.venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=usd,
            starting_balances=[Money(SYNTHETIC_CASH, usd)],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
            # Delay through the next synthetic quote, not a calibrated latency.
            latency_model=StaticLatencyModel(
                cancel_latency_nanos=2 * SYNTHETIC_STEP_NS if fill_before_cancel else 0
            ),
        )
        engine.add_instrument(
            Equity(
                instrument_id=INSTRUMENT_ID,
                raw_symbol=Symbol("AAPL"),
                currency=usd,
                price_precision=2,
                price_increment=Price.from_str(str(TICK)),
                lot_size=Quantity.from_str(ORDER_QTY),
                ts_event=SYNTHETIC_START_NS,
                ts_init=SYNTHETIC_START_NS,
            )
        )
        engine.add_data(
            synthetic_quotes(fill_before_cancel=fill_before_cancel), client_id=CLIENT_ID
        )
        strategy = OnePaperOrder()
        strategy._record = record
        # Only wiring changes: synchronous in-process quotes and execution are available.
        # No strategy method, order guard, price rule or cancel callback is overridden.
        strategy.quote_usable = lambda: True
        strategy.execution_healthy = lambda: True
        engine.add_strategy(strategy)
        engine.run()
        data["orders_total"] = len(engine.cache.orders())
    except Exception as exc:
        record.engine_error(type(exc).__name__)
    finally:
        engine.dispose()
    data["problems"] = problems(data)
    data["passed"] = not data["problems"]
    return data


def main(*, fill_before_cancel: bool = False) -> int:
    print("SIMULATION; not a lane; no typed word; synthetic quotes only.", flush=True)
    print(EXERCISES, flush=True)
    print(EXCLUDES, flush=True)
    data = practice(fill_before_cancel=fill_before_cancel)
    # Deliberately never call the lane's RunRecord.write (which can publish evidence).
    folder = boundary.REPO_ROOT / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"M3-alpaca-{uuid4().hex}-simulation.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PASS" if data["passed"] else "FAIL: " + "; ".join(data["problems"]))
    print(f"Simulation record: runs/{path.name}")
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
