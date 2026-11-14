"""Calendar rows for the simulation from `exchange-calendars`, offline; research side only.

`uv run python research/xnys_calendar_rows.py START END [OUT.json]` writes one row per XNYS
session from START to END (ISO dates, inclusive), in the shape of Alpaca's calendar
(https://docs.alpaca.markets/us/reference/legacycalendar: `date`, `open`, `close`,
`session_open`, `session_close`), which `meridian.sim.catalog.load_calendar` reads and
`python -m meridian.sim --calendar OUT.json` takes. A holiday has no row (closed).

Sources. The regular open and close, holidays and early closes: `exchange-calendars`
(research dependency group, pinned in uv.lock; UPSTREAM.md), whose XNYS calendar has them
offline. The extended sessions are Alpaca's, not the exchange's: pre-market from 04:00 and
after-hours to 20:00 New York (https://docs.alpaca.markets/us/docs/orders-at-alpaca, "Extended
Hours Trading", read 2026-11-14). `exchange-calendars` does not know Alpaca's after-hours end
on an early close; this script takes the close plus the full day's four hours (17:00 after a
13:00 close), the half-day row already used in `tests/test_alpaca_sessions.py`. That one value
is an assumption to compare with Alpaca's own calendar rows when a lane reads them.

Kept outside `meridian/`: no production module imports a research library
(`tests/test_dependency_boundary.py`).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SESSION_OPEN, SESSION_CLOSE = "0400", "2000"  # Alpaca's pre-market start, after-hours end
AFTER_HOURS = timedelta(hours=4)  # 16:00 to 20:00 on a full day


def rows(start: date, end: date) -> list[dict[str, str]]:
    import exchange_calendars as xcals

    # The calendar's own bounds must be sessions; a week either side covers any holiday.
    week = timedelta(days=7)
    calendar = xcals.get_calendar("XNYS", start=str(start - week), end=str(end + week))
    out = []
    for session in calendar.sessions_in_range(start.isoformat(), end.isoformat()):
        opened = calendar.session_open(session).tz_convert(NEW_YORK).to_pydatetime()
        closed = calendar.session_close(session).tz_convert(NEW_YORK).to_pydatetime()
        full_day = closed.time() == datetime.strptime("1600", "%H%M").time()
        after = SESSION_CLOSE if full_day else (closed + AFTER_HOURS).strftime("%H%M")
        out.append(
            {
                "date": session.date().isoformat(),
                "open": opened.strftime("%H:%M"),
                "close": closed.strftime("%H:%M"),
                "session_open": SESSION_OPEN,
                "session_close": after,
            }
        )
    return out


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: xnys_calendar_rows.py START END [OUT.json]", file=sys.stderr)
        return 2
    found = rows(date.fromisoformat(argv[0]), date.fromisoformat(argv[1]))
    text = json.dumps(found, indent=1) + "\n"
    if len(argv) == 3:
        Path(argv[2]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
