"""Synthetic data through the engine's own catalog: instruments, quotes, session statuses.

Upstream pattern (NautilusTrader v2.0.0rc9, da6b57aefdd62b44f675e434ffcfefca7f4025dd):
`docs/getting_started/backtest_high_level.py:121-136` writes instruments and quotes to a
`ParquetDataCatalog` that `BacktestDataConfig` then reads. The tagged repository bundles no
US-equity quotes, trades or bars (its only AAPL data is an L3 ITCH file fetched from Nasdaq
and a one-row depth fixture), so the quote paths are the template's synthetic scenarios
(`meridian/strategy_template/sim.py`), placed in a New York regular session.

Own code, where the engine has no primitive: the engine has no exchange calendar. Its
`InstrumentStatus` data does open and close a simulated market (the matching engine rejects
an order while the market is not open, `crates/execution/src/matching_engine/mod.rs:3351`), so
`status_events` turns `meridian.alpaca_sessions` windows into those statuses.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model import (
    Currency,
    Equity,
    InstrumentId,
    InstrumentStatus,
    MarketStatusAction,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog

from meridian.alpaca_sessions import NEW_YORK, session_ns
from meridian.strategy_template.sim import SCENARIOS

VENUE = "SIM"
# 2024-01-03 14:30 UTC, 09:30 New York (a Wednesday): a fixed synthetic start, no wall clock.
START_NS = 1_704_292_200_000_000_000
STEP_NS = 250_000_000  # four quotes a second, as the template's own simulation
TICK, SPREAD, SIZE = Decimal("0.01"), Decimal("0.01"), 10_000
DATA_SOURCE = "synthetic quotes and session statuses generated in process; no recorded data"
# The candidate session edges in New York; alpaca_sessions decides which are open.
EDGES = (time(4), time(9, 30), time(16), time(20))

Scenarios = Mapping[str, tuple[list[Decimal], int | None, Decimal | None]]


def equity(iid: InstrumentId, ts_ns: int = START_NS) -> Equity:
    return Equity(
        instrument_id=iid,
        raw_symbol=Symbol(iid.symbol.value),
        currency=Currency.from_str("USD"),
        price_precision=2,
        price_increment=Price.from_str(str(TICK)),
        lot_size=Quantity.from_int(1),
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def quotes(iid: InstrumentId, bids: Iterable[Decimal], start_ns: int) -> list[QuoteTick]:
    return [
        QuoteTick(
            instrument_id=iid,
            bid_price=Price.from_str(str(bid)),
            ask_price=Price.from_str(str(bid + SPREAD)),
            bid_size=Quantity.from_int(SIZE),
            ask_size=Quantity.from_int(SIZE),
            ts_event=start_ns + i * STEP_NS,
            ts_init=start_ns + i * STEP_NS,
        )
        for i, bid in enumerate(bids)
    ]


def _edges(start_ns: int, end_ns: int) -> list[int]:
    day = datetime.fromtimestamp(start_ns // 1_000_000_000, UTC).astimezone(NEW_YORK).date()
    last = datetime.fromtimestamp(end_ns // 1_000_000_000, UTC).astimezone(NEW_YORK).date()
    out = []
    while day <= last:
        for edge in EDGES:
            ns = int(datetime.combine(day, edge, NEW_YORK).timestamp()) * 1_000_000_000
            if start_ns < ns <= end_ns:
                out.append(ns)
        day += timedelta(days=1)
    return out


def status_events(iid: InstrumentId, start_ns: int, end_ns: int) -> list[InstrumentStatus]:
    """TRADING when an Alpaca session (overnight, pre, regular, after) opens, CLOSE when none.

    The weekly window only: without Alpaca's calendar rows (a network read, not done here)
    a holiday or an early close is not known.
    """
    events: list[InstrumentStatus] = []
    was_open: bool | None = None
    for ts in [start_ns, *_edges(start_ns, end_ns)]:
        session = session_ns(ts)
        if (session is not None) is was_open:
            continue
        was_open = session is not None
        events.append(
            InstrumentStatus(
                instrument_id=iid,
                action=MarketStatusAction.TRADING if was_open else MarketStatusAction.CLOSE,
                ts_event=ts,
                ts_init=ts,
                reason=session.name if session else "no Alpaca session",
                is_trading=was_open,
            )
        )
    return events


def instrument_ids(scenarios: Scenarios, copies: int = 1) -> dict[InstrumentId, str]:
    ids = {}
    for name in scenarios:
        for copy in range(copies):
            symbol = name if copies == 1 else f"{name}-{copy}"
            ids[InstrumentId.from_str(f"{symbol}.{VENUE}")] = name
    return ids


def write(
    path: Path,
    scenarios: Scenarios = SCENARIOS,
    *,
    copies: int = 1,
    start_ns: int = START_NS,
    extra: Mapping[InstrumentId, list[QuoteTick]] | None = None,
) -> list[InstrumentId]:
    """Write one catalog: each instrument, its quotes and its session statuses."""
    catalog = ParquetDataCatalog(str(path))
    series = {
        iid: quotes(iid, scenarios[name][0], start_ns)
        for iid, name in instrument_ids(scenarios, copies).items()
    }
    series.update(extra or {})
    catalog.write_instruments([equity(iid, start_ns) for iid in series])
    for iid, ticks in series.items():
        # The catalog takes one instrument per write call.
        catalog.write_quote_ticks(ticks)
        catalog.write_instrument_statuses(status_events(iid, start_ns, ticks[-1].ts_init))
    return list(series)
