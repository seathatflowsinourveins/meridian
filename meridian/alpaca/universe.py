"""Own-design universe selection from venue screeners, never an entry signal.

Only the intersection has both a price and cumulative daily volume. Volume is
not quote depth or executable liquidity. Owner parameters have no fallback;
nulls in deploy/alpaca-universe.template.json are placeholders, not calibration.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from meridian.alpaca_sessions import session_ns

from .screener_models import Candidate, ScreenerRead, number, symbol


@dataclass(frozen=True, kw_only=True)
class UniverseParams:
    provenance: str
    min_price: Decimal
    min_volume: int
    max_symbols: int
    max_age_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("universe provenance required")
        if (
            not isinstance(self.min_price, Decimal)
            or not self.min_price.is_finite()
            or self.min_price < 0
        ):
            raise ValueError("invalid universe price floor")
        for value in (self.min_volume, self.max_symbols, self.max_age_ns):
            if type(value) is not int or value < 0:
                raise ValueError("invalid universe integer parameter")
        if self.max_symbols < 1 or self.max_age_ns < 1:
            raise ValueError("universe count and age must be positive")

    @classmethod
    def from_file(cls, path: Path) -> UniverseParams:
        """Owner's local JSON; unknown, missing and placeholder values refuse."""
        values = json.loads(path.read_text(encoding="utf-8"))
        names = {"provenance", "min_price", "min_volume", "max_symbols", "max_age_ns"}
        if not isinstance(values, dict) or set(values) != names:
            raise ValueError("universe parameter fields do not match")
        values["min_price"] = number(values["min_price"])
        return cls(**values)


@dataclass(frozen=True)
class Universe:
    read: ScreenerRead
    candidates: tuple[Candidate, ...]
    params: UniverseParams
    calendar: Mapping[date, dict]

    def at(self, decision_ns: int) -> tuple[Candidate, ...]:
        """A list completed at T is usable strictly after T, in that regular session.

        Calendar is supplied by the caller's already-budgeted venue calendar read.
        Empty/missing dates refuse. Extended/overnight screener semantics are not
        established by the endpoint docs, so these lists authorize no entries.
        Age is measured from both computation times and both receipt times.
        """
        read = self.read
        if decision_ns <= read.read_at_ns:
            return ()
        times = (
            read.movers_read_at_ns,
            read.actives_read_at_ns,
            read.movers_updated_ns,
            read.actives_updated_ns,
        )
        if any(decision_ns - t > self.params.max_age_ns for t in times):
            return ()
        session = session_ns(decision_ns, self.calendar)
        if session is None or session.name != "regular":
            return ()
        if any(session_ns(t, self.calendar) != session for t in times):
            return ()
        return self.candidates


def select_universe(
    read: ScreenerRead,
    params: UniverseParams,
    *,
    allowed_symbols: frozenset[str],
    assets: Mapping[str, dict],
    calendar: Mapping[date, dict],
) -> Universe:
    """Caller supplies lane allowlist and already-read asset/calendar rows.

    Assets must explicitly be active, tradable US equities. Screeners alone do
    not confer lane permission; missing metadata excludes. Exits of symbols that
    leave this universe remain the template's responsibility.
    """
    for name in allowed_symbols:
        symbol(name)
    selected = []
    for candidate in read.candidates:
        asset = assets.get(candidate.symbol, {})
        if (
            candidate.symbol in allowed_symbols
            and asset.get("symbol") == candidate.symbol
            and asset.get("class") == "us_equity"
            and asset.get("status") == "active"
            and asset.get("tradable") is True
            and candidate.price >= params.min_price
            and candidate.volume is not None
            and candidate.volume >= params.min_volume
        ):
            selected.append(candidate)
    return Universe(
        read,
        tuple(selected[: params.max_symbols]),
        params,
        {day: dict(row) for day, row in calendar.items()},
    )


class UniverseTimeline:
    """Offline replay: replace, never union, lists in receipt order."""

    def __init__(self, snapshots: tuple[Universe, ...]):
        times = [u.read.read_at_ns for u in snapshots]
        if times != sorted(set(times)):
            raise ValueError("universe receipts must be strictly increasing")
        self.snapshots = snapshots

    def at(self, decision_ns: int) -> tuple[Candidate, ...]:
        for snapshot in reversed(self.snapshots):
            if snapshot.read.read_at_ns < decision_ns:
                return snapshot.at(decision_ns)
        return ()
