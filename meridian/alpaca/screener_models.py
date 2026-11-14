"""Pure screener values/validation, shaped like alpaca-py 0.45.0 models.

Kept separate from SDK imports: alpaca.data imports requests, whose urllib3
probes IPv6 with a socket at import time. The offline simulation opens none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from .reports import timestamp_ns

if TYPE_CHECKING:
    from alpaca.data.models.screener import MostActives, Movers

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]*")


def symbol(value: Any) -> str:
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise ValueError("invalid screener symbol")
    return value


def number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("invalid screener number")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid screener number") from None
    if not result.is_finite():
        raise ValueError("nonfinite screener number")
    return result


def stamp(value: Any) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("screener timestamp needs timezone")
        value = value.astimezone(UTC).isoformat()
    if not isinstance(value, str) or not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
        raise ValueError("screener timestamp needs timezone")
    return timestamp_ns(value, "screener timestamp")


def envelope(value: Any, field: str, read_at_ns: int) -> tuple[dict, int]:
    if not isinstance(value, dict) and callable(getattr(value, "model_dump", None)):
        value = value.model_dump()
    if not isinstance(value, dict) or field not in value:
        raise ValueError("invalid screener envelope")
    if type(read_at_ns) is not int or read_at_ns <= 0:
        raise ValueError("invalid screener receipt time")
    updated = stamp(value.get("last_updated"))
    if not 0 < updated <= read_at_ns:
        raise ValueError("invalid screener computation time")
    return value, updated


def rows(value: Any, limit: int) -> list[dict]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("invalid screener list")
    seen = set()
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid screener row")
        name = symbol(row.get("symbol"))
        if name in seen:
            raise ValueError("duplicate screener symbol")
        seen.add(name)
    return value


@dataclass(frozen=True)
class Candidate:
    symbol: str
    rank: int
    direction: str
    price: Decimal
    change: Decimal
    percent_change: Decimal
    volume: int | None
    trade_count: int | None


@dataclass(frozen=True)
class ScreenerRead:
    """Receipt times are local completion times, never the venue's computation time."""

    candidates: tuple[Candidate, ...]
    movers_read_at_ns: int
    actives_read_at_ns: int
    movers_updated_ns: int
    actives_updated_ns: int

    @property
    def read_at_ns(self) -> int:
        return max(self.movers_read_at_ns, self.actives_read_at_ns)


def parse_screeners(
    movers: Movers | dict,
    actives: MostActives | dict,
    *,
    movers_read_at_ns: int,
    actives_read_at_ns: int,
) -> ScreenerRead:
    """Validate every row, including excluded losers and non-intersecting symbols.

    Order is descending venue percent change, then symbol for ties. No predictive
    score; both directions retained. Missing activity is unknown, never zero.
    """
    movers, mover_time = envelope(movers, "gainers", movers_read_at_ns)
    actives, active_time = envelope(actives, "most_actives", actives_read_at_ns)
    if movers.get("market_type") != "stocks":
        raise ValueError("stock movers required")
    liquidity = {}
    for row in rows(actives.get("most_actives"), 100):
        raw = [row.get(key) for key in ("volume", "trade_count")]
        if any(isinstance(v, float) and abs(v) >= 2**53 for v in raw):
            raise ValueError("inexact SDK activity count")
        values = [number(v) for v in raw]
        if any(v < 0 or v > 2**63 - 1 or v != v.to_integral_value() for v in values):
            raise ValueError("invalid screener activity count")
        liquidity[row["symbol"]] = tuple(int(v) for v in values)
    combined = []
    seen = set()
    for direction in ("gainers", "losers"):
        for row in rows(movers.get(direction), 50):
            name = row["symbol"]
            if name in seen:
                raise ValueError("symbol on both mover lists")
            seen.add(name)
            price, change, percent = [
                number(row.get(key)) for key in ("price", "change", "percent_change")
            ]
            if price <= 0 or price - change <= 0:
                raise ValueError("invalid screener price")
            if (direction == "gainers" and (change < 0 or percent < 0)) or (
                direction == "losers" and (change > 0 or percent > 0)
            ):
                raise ValueError("invalid mover direction")
            volume, trades = liquidity.get(name, (None, None))
            combined.append((name, direction, price, change, percent, volume, trades))
    combined.sort(key=lambda row: (-row[4], row[0]))
    return ScreenerRead(
        tuple(
            Candidate(name, rank, side, price, change, pct, volume, trades)
            for rank, (name, side, price, change, pct, volume, trades) in enumerate(combined, 1)
        ),
        movers_read_at_ns,
        actives_read_at_ns,
        mover_time,
        active_time,
    )
