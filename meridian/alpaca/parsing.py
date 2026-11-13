"""
An Alpaca asset row as a NautilusTrader `Equity`.

Own design, ported from `sextant-paper@a991b73a:src/sextant/alpaca/parsing.py`. Alpaca prices
US equities in cents at or above $1.00 and in hundredths of a cent below (the earlier line's
reading of Alpaca's order rules, 2026-11-10), so every equity gets price precision 4 and a
tiered tick scheme whose ladder switches at $1.00. `TieredTickScheme` and
`register_tick_scheme` are NautilusTrader 2.0.0rc9's (`nautilus_trader.model`).
"""

from collections.abc import Mapping
from typing import Any

from nautilus_trader.model import (
    Currency,
    Equity,
    InstrumentId,
    Price,
    Symbol,
    TieredTickScheme,
    list_tick_schemes,
    register_tick_scheme,
)

from .constants import VENUE

TICK_SCHEME = "ALPACA_US_EQUITY"
_PRICE_PRECISION = 4
_TIERS = ((0.0, 1.0, 0.0001), (1.0, float("inf"), 0.01))
_MAX_TICKS_PER_TIER = 1_000_000
_FLAGS = ("tradable", "shortable", "easy_to_borrow", "marginable", "fractionable")


def register_equity_tick_scheme() -> str:
    if TICK_SCHEME not in list_tick_schemes():
        register_tick_scheme(
            TieredTickScheme(TICK_SCHEME, _TIERS, _PRICE_PRECISION, _MAX_TICKS_PER_TIER)
        )
    return TICK_SCHEME


def instrument_id(symbol: str) -> InstrumentId:
    return InstrumentId(Symbol(symbol), VENUE)


def parse_equity(row: Mapping[str, Any], *, ts_init: int) -> Equity:
    """One US-equity asset row (GET /v2/assets/{symbol}) as an Equity, or ValueError."""
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("Alpaca asset row has no symbol")
    if row.get("class") != "us_equity":
        raise ValueError("Alpaca asset row is not a US equity")
    return Equity(
        instrument_id(symbol),
        Symbol(symbol),
        Currency.from_str("USD"),
        _PRICE_PRECISION,
        Price.from_str("0.0001"),
        ts_init,
        ts_init,
        tick_scheme=register_equity_tick_scheme(),
        info={flag: bool(row.get(flag)) for flag in _FLAGS},
    )
