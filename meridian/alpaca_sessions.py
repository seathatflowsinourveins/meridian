"""Alpaca's New York sessions; no network, account data, or local timezone assumptions.

Times/holiday rule: https://docs.alpaca.markets/us/docs/245-trading-for-trading-api
Calendar fields: https://docs.alpaca.markets/us/reference/legacycalendar
Feeds: https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data
All read 2026-11-13; entitlement evidence is in UPSTREAM.md.
Without calendar rows this is the weekly window only, suitable for scheduling a
preflight. Order admission must supply calendar rows (empty means closed).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SIP_DELAY_NS = 15 * 60 * 1_000_000_000


@dataclass(frozen=True)
class Session:
    name: str
    feed: str
    trade_date: date
    start: datetime


def session_at(when: datetime, calendar: Mapping[date, dict] | None = None) -> Session | None:
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("session time must be timezone aware")
    local = when.astimezone(NEW_YORK)
    day, wall = local.date(), local.time()
    trade_date = day + timedelta(days=wall >= time(20))
    if trade_date.weekday() >= 5 or (calendar is not None and trade_date not in calendar):
        return None
    if wall >= time(20) or wall < time(4):
        start_day = trade_date - timedelta(days=1)
        return Session(
            "overnight", "overnight", trade_date, datetime.combine(start_day, time(20), NEW_YORK)
        )
    row = None if calendar is None else calendar[trade_date]
    pre, opened, closed, end = (
        (time(4), time(9, 30), time(16), time(20))
        if row is None
        else (
            datetime.strptime(row["session_open"], "%H%M").time(),
            time.fromisoformat(row["open"]),
            time.fromisoformat(row["close"]),
            datetime.strptime(row["session_close"], "%H%M").time(),
        )
    )
    if not time(4) <= pre < opened < closed < end <= time(20):
        raise ValueError("invalid market calendar session times")
    for name, feed, start, stop in (
        ("pre_market", "delayed_sip", pre, opened),
        ("regular", "iex", opened, closed),
        ("after_hours", "delayed_sip", closed, end),
    ):
        if start <= wall < stop:
            return Session(name, feed, trade_date, datetime.combine(day, start, NEW_YORK))
    return None


def session_ns(timestamp_ns: int, calendar: Mapping[date, dict] | None = None) -> Session | None:
    return session_at(datetime.fromtimestamp(timestamp_ns // 1_000_000_000, UTC), calendar)
