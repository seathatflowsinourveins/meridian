"""Offline simulation of the strategy template on the engine's native BacktestEngine.

`uv run python -m meridian.strategy_template.sim [--copies N] [--report]`.
Like `meridian.alpaca_sim` (engine, cash venue, in-process data, strategy, run, dispose: v2.0.0rc9
`examples/backtest/synthetic_data_pnl_test.py:189-253`). No adapter, no lane, no socket.

Everything here is synthetic and uncalibrated: the quote paths are generated in this process
to make each behaviour happen once per scenario, and the parameters are chosen so they do. They
are not observed prices, not a tuned strategy, and not evidence of any edge. The record goes
under `runs/` only.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import nautilus_trader
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OrderType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TimeInForce,
)

from meridian import boundary
from meridian.alpaca.screener_models import parse_screeners
from meridian.alpaca.universe import UniverseParams, UniverseTimeline, select_universe

from .params import TemplateParams
from .report import ReportUnavailable, require_research, write_report
from .strategy import SymbolBook, TrailingTemplate

DATA_SOURCE = "synthetic quotes generated in process; no market or recorded data"
SYNTHETIC = "synthetic, uncalibrated: simulation fixture values, not tuned"
VENUE = "SIM"
START_NS, STEP_NS = 1_794_582_000_000_000_000, 250_000_000  # four quotes a second
TICK, SPREAD, SIZE, CASH = Decimal("0.01"), Decimal("0.01"), 10_000, 10_000_000

# Synthetic, uncalibrated values, chosen so that every scenario below happens.
SIM_PARAMS: dict[str, Any] = {
    "provenance": SYNTHETIC,
    "atr_period": 5,
    "trail_atr_multiple": "3",
    "trail_floor_bps": "10",
    "entry_limit_buffer_bps": "5",
    "exit_limit_buffer_bps": "20",
    "entry_timeout_seconds": "2",
    "base_quantity": 10,
    "reentry_enabled": True,
    "cooldown_seconds": "5",
    "retry_rank_band": 3,
    "reentry_min_confidence": "0.5",
    "confidence_size_floor": "0.5",
    "whipsaw_stopouts_max": 2,
}
BREAKOUT_LOOKBACK = 5  # the simulation's own entry setup, synthetic


def leg(start: Decimal, drift: str, n: int, wiggle: str = "0.02") -> list[Decimal]:
    """n bids from start, drifting each quote, with an alternating wiggle so the ATR is not 0."""
    d, w = Decimal(drift), Decimal(wiggle)
    return [start + i * d + (w if i % 2 else 0) for i in range(1, n + 1)]


def path(start: str, *legs: tuple[str, int] | tuple[str, int, str]) -> list[Decimal]:
    bids = [Decimal(start)]
    for spec in legs:
        drift, n, *wiggle = spec
        bids += leg(bids[-1], drift, n, *wiggle)
    return bids


# Each scenario: (bids, rank, confidence). Rank and confidence are the strategy's inputs for
# re-entry; None means missing, so re-entry waits (R5).
SCENARIOS: dict[str, tuple[list[Decimal], int | None, Decimal | None]] = {
    # Rises the whole time: the trail ratchets up and is never reached.
    "RATCHET": (path("50.00", ("0", 8), ("0.03", 60, "0.01")), None, None),
    # Rises, slides through the trail (fast exit), then rises again with no ranking: waits.
    "BREACH": (
        path("80.00", ("0", 8), ("0.04", 20, "0.01"), ("-0.03", 12, "0.01"), ("0.04", 30, "0")),
        None,
        None,
    ),
    # The same shape with a ranking and a confidence: re-enters once the cooldown has passed.
    "REENTRY": (
        path("60.00", ("0", 8), ("0.04", 20, "0.01"), ("-0.03", 12, "0.01"), ("0.04", 30, "0")),
        1,
        Decimal("0.8"),
    ),
    # Rises, then gaps far under the trail: the released LIMIT is not marketable, so it is
    # cancelled and the remainder re-priced at the bid less the buffer.
    "GAP": (
        path("40.00", ("0", 8), ("0.03", 20, "0.01"), ("-2.00", 1, "0"), ("0", 20)),
        None,
        None,
    ),
    # Drifts down: its setup never fires and it never trades.
    "QUIET": (path("30.00", ("-0.02", 70, "0.01")), 1, Decimal("0.9")),
}


class SyntheticBreakout(TrailingTemplate):
    """The simulation's concrete strategy: buy when the bid clears its last few bids."""

    def __init__(self, params: TemplateParams, ids: list[InstrumentId], inputs: dict[str, Any]):
        super().__init__(params, ids, strategy_id="MERIDIAN-M4SIM")
        self._inputs = inputs
        self.universe = UniverseTimeline(())
        self._windows: dict[InstrumentId, deque[Decimal]] = {}
        self._prior_high: dict[InstrumentId, Decimal | None] = {}

    def observe(self, book: SymbolBook, quote: QuoteTick) -> None:
        window = self._windows.setdefault(book.instrument_id, deque(maxlen=BREAKOUT_LOOKBACK))
        full = len(window) == BREAKOUT_LOOKBACK
        self._prior_high[book.instrument_id] = max(window) if full else None
        window.append(quote.bid_price.as_decimal())

    def entry_signal(self, book: SymbolBook, quote: QuoteTick) -> bool:
        if book.instrument_id.symbol.value not in {
            candidate.symbol for candidate in self.universe.at(quote.ts_event)
        }:
            return False
        high = self._prior_high.get(book.instrument_id)
        return high is not None and quote.bid_price.as_decimal() > high

    def rank(self, book: SymbolBook) -> int | None:
        return self._inputs[book.instrument_id.symbol.value.split("-")[0]][0]

    def confidence(self, book: SymbolBook) -> Decimal | None:
        return self._inputs[book.instrument_id.symbol.value.split("-")[0]][1]


def quotes(iid: InstrumentId, bids: list[Decimal]) -> list[QuoteTick]:
    return [
        QuoteTick(
            instrument_id=iid,
            bid_price=Price.from_str(str(bid)),
            ask_price=Price.from_str(str(bid + SPREAD)),
            bid_size=Quantity.from_int(SIZE),
            ask_size=Quantity.from_int(SIZE),
            ts_event=START_NS + i * STEP_NS,
            ts_init=START_NS + i * STEP_NS,
        )
        for i, bid in enumerate(bids)
    ]


def instrument_ids(scenarios: dict[str, Any], copies: int) -> dict[InstrumentId, str]:
    ids = {}
    for name in scenarios:
        for copy in range(copies):
            symbol = name if copies == 1 else f"{name}-{copy}"
            ids[InstrumentId.from_str(f"{symbol}.{VENUE}")] = name
    return ids


def synthetic_universe(ids: list[InstrumentId]) -> UniverseTimeline:
    """SDK-shaped synthetic lists; the same parser/selector as the read-only client.

    Endpoint bounds permit at most 50 gainers + 50 losers and 100 actives. Both
    directions are candidates; breakout/re-entry inputs remain scenario fixtures.
    """
    if len(ids) > 100:
        raise ValueError("synthetic screener supports at most 100 symbols")
    names = sorted(i.symbol.value for i in ids)
    when = datetime.fromtimestamp(START_NS // 1_000_000_000, UTC)
    movers = {
        "market_type": "stocks",
        "last_updated": when,
        "gainers": [
            {"symbol": s, "price": 10, "change": 1, "percent_change": 10} for s in names[:50]
        ],
        "losers": [
            {"symbol": s, "price": 10, "change": -1, "percent_change": -10} for s in names[50:]
        ],
    }
    actives = {
        "last_updated": when,
        "most_actives": [{"symbol": s, "volume": 1000, "trade_count": 10} for s in names],
    }
    read = parse_screeners(movers, actives, movers_read_at_ns=START_NS, actives_read_at_ns=START_NS)
    # Synthetic policy, not defaults or tuned values; synthetic calendar, no service read.
    params = UniverseParams(
        provenance=SYNTHETIC,
        min_price=Decimal(0),
        min_volume=0,
        max_symbols=len(ids),
        max_age_ns=3_600_000_000_000,
    )
    assets = {
        s: {"symbol": s, "class": "us_equity", "status": "active", "tradable": True} for s in names
    }
    calendar = {
        when.date(): {
            "session_open": "0400",
            "open": "09:30",
            "close": "16:00",
            "session_close": "2000",
        }
    }
    return UniverseTimeline(
        (
            select_universe(
                read, params, allowed_symbols=frozenset(names), assets=assets, calendar=calendar
            ),
        )
    )


def run(
    *,
    params: TemplateParams | None = None,
    scenarios: dict[str, tuple[list[Decimal], int | None, Decimal | None]] | None = None,
    copies: int = 1,
    universe: UniverseTimeline | None = None,
    strategy_type: type[SyntheticBreakout] = SyntheticBreakout,
    inspect: Callable[[BacktestEngine, SyntheticBreakout], None] | None = None,
    report: bool = False,
) -> dict[str, Any]:
    if report:
        require_research()
    params = params or TemplateParams.from_config(SIM_PARAMS)
    scenarios = scenarios or SCENARIOS
    ids = instrument_ids(scenarios, copies)
    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.OFF, bypass_logging=True),
            run_analysis=False,
        )
    )
    data: dict[str, Any] = {}
    try:
        usd = Currency.from_str("USD")
        engine.add_venue(
            venue=next(iter(ids)).venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=usd,
            starting_balances=[Money(CASH, usd)],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        )
        ticks = []
        for iid, name in ids.items():
            engine.add_instrument(
                Equity(
                    instrument_id=iid,
                    raw_symbol=Symbol(iid.symbol.value),
                    currency=usd,
                    price_precision=2,
                    price_increment=Price.from_str(str(TICK)),
                    lot_size=Quantity.from_int(1),
                    ts_event=START_NS,
                    ts_init=START_NS,
                )
            )
            ticks += quotes(iid, scenarios[name][0])
        engine.add_data(sorted(ticks, key=lambda q: q.ts_init))
        inputs = {name: spec[1:] for name, spec in scenarios.items()}
        strategy = strategy_type(params, list(ids), inputs)
        strategy.universe = universe if universe is not None else synthetic_universe(list(ids))
        engine.add_strategy(strategy)
        engine.run()
        venue_orders = [o for o in engine.cache.orders() if not o.is_emulated]
        data = {
            "symbols": {str(i): b.report() for i, b in strategy.books.items()},
            "actions": strategy.actions.summary(),
            "orders_at_venue": len(venue_orders),
            # The engine's RiskEngine denies submits past its own throttle (100 a second by
            # default); a denied exit is re-priced on the symbol's next quote.
            "orders_denied": sum(1 for o in engine.cache.orders() if o.status.name == "DENIED"),
            "orders_not_day_limit": sum(
                1
                for o in venue_orders
                if o.order_type != OrderType.LIMIT or o.time_in_force != TimeInForce.DAY
            ),
        }
        if inspect is not None:
            inspect(engine, strategy)
        if report:
            data["report"] = write_report(engine)
    finally:
        engine.dispose()
    return data


def problems(data: dict[str, Any], copies: int = 1) -> list[str]:
    """Each scenario's behaviour happened, and nothing the template forbids did."""
    found = []
    for symbol, r in data["symbols"].items():
        name = symbol.split(".")[0].split("-")[0]
        if r["trail_loosened"] or r["refusals"].get("one unresolved order"):
            found.append(f"{symbol}: the trail loosened or a second order was attempted")
        expect = {
            "RATCHET": r["trail_ratchets"] > 0 and r["exits"] == 0 and r["phase"] == "holding",
            "BREACH": r["exits"] == 1
            and r["entries"] == 1
            and r["refusals"].get("no ranking", 0) > 0,
            "REENTRY": r["exits"] >= 1 and r["entries"] == 2 and "reentry" in r["events"],
            "GAP": r["exits"] == 1 and "reprice" in r["events"] and r["phase"] == "flat",
            "QUIET": r["entries"] == 0 and r["phase"] == "flat",
        }[name]
        if not expect:
            found.append(f"{symbol}: the {name} scenario did not happen as designed")
    if data["orders_denied"]:
        found.append(f"the engine's risk throttle denied {data['orders_denied']} orders")
    if data["orders_not_day_limit"]:
        found.append("an order at the venue was not a DAY LIMIT")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline simulation of the strategy template.")
    parser.add_argument("--copies", type=int, default=1, help="copies of each scenario")
    parser.add_argument("--report", action="store_true", help="engine statistics, CSVs and HTML")
    args = parser.parse_args(argv)
    copies = max(args.copies, 1)
    print("SIMULATION; not a lane; synthetic quotes and uncalibrated parameters only.")
    try:
        data = run(copies=copies, report=args.report)
    except ReportUnavailable as exc:
        print(str(exc))
        return 2
    found = problems(data, copies)
    record = {
        "schema": "meridian.simulation-record/1",
        "milestone": "M4",
        "simulation": True,
        "data_source": DATA_SOURCE,
        "parameters": {k: str(v) for k, v in SIM_PARAMS.items()},
        "engine": {"name": "NautilusTrader BacktestEngine", "version": nautilus_trader.__version__},
        "copies": copies,
        **data,
        "problems": found,
        "passed": not found,
    }
    for symbol, r in data["symbols"].items():
        if copies == 1 or symbol.split(".")[0].endswith("-0"):
            print(
                f"{symbol:12} {r['phase']:8} entries {r['entries']} exits {r['exits']}"
                f" ratchets {r['trail_ratchets']:3}  {' > '.join(r['events']) or '-'}"
                + (f"  refused: {r['refusals']}" if r["refusals"] else "")
            )
    a = data["actions"]
    print(
        f"order actions {a['counts']}; at the venue {a['venue_actions']}:"
        f" at most {a['max_venue_actions_per_second']} in any second,"
        f" {a['max_venue_actions_per_minute']} in any minute (simulated time);"
        f" denied by the engine's risk throttle: {data['orders_denied']}"
    )
    folder = boundary.REPO_ROOT / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"M4-template-{uuid4().hex}-simulation.json"
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PASS" if not found else "FAIL: " + "; ".join(found))
    print(f"Simulation record: runs/{out.name}")
    if args.report:
        print("Engine statistics (null = undefined):")
        print(json.dumps(data["report"]["statistics"], indent=2, sort_keys=True, allow_nan=False))
        print(f"Engine reports: {data['report']['directory']}/")
        print(f"Tearsheet: {data['report']['directory']}/tearsheet.html")
    return 0 if not found else 1


if __name__ == "__main__":
    raise SystemExit(main())
