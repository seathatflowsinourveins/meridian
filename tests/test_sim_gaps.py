"""The simulation's four former gaps to the Alpaca paper venue, each closed and shown here.

Partial fills (`meridian/sim/fills.py`), DAY expiry and the pacer (`meridian/sim/strategies.py`,
`budget.py`), calendar rows (`catalog.py`, `research/xnys_calendar_rows.py`). Offline; every
value is a placeholder.
"""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from nautilus_trader.model import InstrumentId, OrderSide, Price, Quantity, QuoteTick, TimeInForce
from test_sim import BASE, MarketAndLimit, run

from meridian.alpaca.pacing import load_controls
from meridian.alpaca_sessions import NEW_YORK
from meridian.order_budget.pacer import ActionKind
from meridian.sim import budget, catalog, runner
from meridian.sim.fills import ALPACA_PAPER_PARTIAL_RATE, PaperFillModel
from meridian.sim.strategies import GatedBreakout
from meridian.strategy_template.sim import SCENARIOS
from research.xnys_calendar_rows import rows as xnys_rows

ROOT = Path(__file__).resolve().parents[1]


def ny_ns(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=NEW_YORK).timestamp()) * 10**9


def template_orders(seen):
    return [o for o in seen["orders"] if o.strategy_id == seen["template"].strategy_id]


# 1. Random partial fills.


def test_partial_fills_happen_at_alpacas_rate_with_a_fixed_seed():
    assert ALPACA_PAPER_PARTIAL_RATE == 0.1  # the paper page's "10% of the time"
    model, again = PaperFillModel(random_seed=3), PaperFillModel(random_seed=3)
    draws = [model.partial_quantity(10) for _ in range(20_000)]
    assert draws == [again.partial_quantity(10) for _ in range(20_000)]  # the seed repeats
    parts = [d for d in draws if d is not None]
    assert 0.09 < len(parts) / len(draws) < 0.11
    assert model.partial_fills == len(parts) and model.fill_attempts == len(draws)
    assert set(parts) == set(range(1, 10))  # a random size, never all and never none
    assert PaperFillModel(random_seed=3).partial_quantity(1) is None  # one share: whole
    other = PaperFillModel(random_seed=4)
    assert [other.partial_quantity(10) for _ in range(200)] != draws[:200]


def test_the_template_handles_partly_filled_entries_and_exits(tmp_path):
    store = runner.write_catalog(tmp_path)
    data, seen = run(replace(BASE, partial_fill_rate=1.0, random_seed=5), store)
    assert data["problems"] == []
    fills = seen["fills"].reset_index()
    template = {str(o.client_order_id): o for o in template_orders(seen)}
    parts = fills[fills["client_order_id"].isin(template)].groupby("client_order_id").size()
    split = {coid for coid, n in parts.items() if n > 1}
    assert {template[c].side for c in split} == {OrderSide.BUY, OrderSide.SELL}
    # An entry cancelled at its timeout after a part filled: the exit side covers that part
    # (the trailing stop, or after its release a LIMIT; the emulator changes its type).
    cut = [
        o for o in template.values() if o.side == OrderSide.BUY and 0 < o.filled_qty < o.quantity
    ]
    assert cut
    for entry in cut:
        assert any(
            o.side == OrderSide.SELL
            and o.instrument_id == entry.instrument_id
            and o.quantity == entry.filled_qty
            for o in template.values()
        )
    # Exits filled in parts: every symbol the template closed sold exactly what it held.
    closed = [b for b in seen["template"].books.values() if b.exits]
    assert closed and all(b.sold == b.held for b in closed if b.phase.name == "FLAT")
    assert data["orders_partly_filled"] >= len(split)
    # At the paper rate, the same seed gives the same fills.
    first = runner.run_set(BASE, store)
    assert runner.run_set(BASE, store)["statistics"] == first["statistics"]


# 2. DAY orders end at the close.


class RestingDayAndGtc(GatedBreakout):
    """On its first QUIET quote, one DAY and one GTC buy at half the bid; then nothing."""

    def on_quote(self, quote: QuoteTick) -> None:
        if getattr(self, "_sent", False) or "QUIET" not in str(quote.instrument_id):
            return
        self._sent = True
        price = Price.from_str(format(quote.bid_price.as_decimal() / 2, ".2f"))
        for tif in (TimeInForce.DAY, TimeInForce.GTC):
            self.submit_order(
                self.order_factory.limit(
                    quote.instrument_id, OrderSide.BUY, Quantity.from_int(1), price, tif
                )
            )


def test_a_resting_day_order_expires_at_the_days_end_and_gtc_does_not(tmp_path):
    # Wednesday 19:59:50 New York: the after-hours session ends at 20:00, inside the data.
    deadline = ny_ns("2024-01-03T20:00:00")
    store = runner.write_catalog(tmp_path, start_ns=ny_ns("2024-01-03T19:59:50"))
    data, seen = run(BASE, store, template_type=RestingDayAndGtc)
    by_tif = {o.time_in_force: o for o in template_orders(seen)}
    day, gtc = by_tif[TimeInForce.DAY], by_tif[TimeInForce.GTC]
    assert day.status.name == "EXPIRED" and gtc.status.name == "ACCEPTED"
    assert day.expire_time == deadline and gtc.expire_time is None  # still a DAY order
    assert data["day_expiries"] == [str(day.client_order_id)]
    expired = next(e for e in day.events() if type(e).__name__ == "OrderExpired")
    # The venue expires it at the deadline's quote, before it matches that quote.
    assert deadline <= expired.ts_event <= deadline + catalog.STEP_NS
    # Before the day's end nothing expires: the same orders at 19:00 both rest.
    store = runner.write_catalog(tmp_path / "early", start_ns=ny_ns("2024-01-03T19:00:00"))
    data, seen = run(BASE, store, template_type=RestingDayAndGtc)
    assert {o.status.name for o in template_orders(seen)} == {"ACCEPTED"}
    assert data["day_expiries"] == []


QUIET = catalog.quotes(
    InstrumentId.from_str("QUIET.SIM"), SCENARIOS["QUIET"][0], 0
)  # offsets from the start: the ask path the tests place orders against
NEW_LOW = next(
    i
    for i in range(2, len(QUIET))
    if QUIET[i].ask_price.as_decimal() < min(q.ask_price.as_decimal() for q in QUIET[:i])
)


class DayAtTheNextLow(GatedBreakout):
    """On its first QUIET quote, one DAY buy at the ask of the path's next new low."""

    def on_quote(self, quote: QuoteTick) -> None:
        if getattr(self, "_sent", False) or "QUIET" not in str(quote.instrument_id):
            return
        self._sent = True
        self.submit_order(
            self.order_factory.limit(
                quote.instrument_id,
                OrderSide.BUY,
                Quantity.from_int(1),
                QUIET[NEW_LOW].ask_price,
                TimeInForce.DAY,
            )
        )


def test_day_expiry_does_not_wait_for_the_clients_cancel_latency(tmp_path):
    # The deadline falls between two quotes; the next one is the first that would fill the
    # order. On a weekday the overnight session opens at once, so the market stays open.
    deadline = ny_ns("2024-01-03T20:00:00")
    start = deadline - NEW_LOW * catalog.STEP_NS + catalog.STEP_NS // 2
    store = runner.write_catalog(tmp_path, start_ns=start)
    models = replace(BASE, cancel_latency_ns=1_000_000_000, order_budget=False)
    data, seen = run(models, store, template_type=DayAtTheNextLow)
    (order,) = template_orders(seen)
    assert order.status.name == "EXPIRED" and order.filled_qty == 0
    assert len(seen["fills"]) == 0 or "QUIET.SIM" not in set(seen["fills"]["instrument_id"])
    # Without the deadline it fills at that quote: the test would see a late fill.
    store = runner.write_catalog(tmp_path / "earlier", start_ns=start - 60 * 10**9)
    _, seen = run(models, store, template_type=DayAtTheNextLow)
    assert [o.status.name for o in template_orders(seen)] == ["FILLED"]


# 3. Holidays and early closes from calendar rows.

THANKSGIVING_ROWS = [
    {
        "date": "2026-11-27",
        "open": "09:30",
        "close": "13:00",
        "session_open": "0400",
        "session_close": "1700",
    }
]


def test_the_research_script_writes_xnys_rows_for_the_holiday_and_the_half_day(tmp_path):
    from datetime import date

    assert xnys_rows(date(2026, 11, 26), date(2026, 11, 27)) == THANKSGIVING_ROWS
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(THANKSGIVING_ROWS))
    assert list(catalog.load_calendar(path)) == [date(2026, 11, 27)]


def gated(tmp_path, when, calendar):
    store = runner.write_catalog(tmp_path, start_ns=ny_ns(when), calendar=calendar)
    data, seen = run(BASE, store, template_type=MarketAndLimit, calendar=calendar)
    return data, [(o.order_type.name, o.status.name) for o in template_orders(seen)]


def test_the_venue_rejects_on_the_holiday_and_after_the_early_close(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(THANKSGIVING_ROWS))
    rows = catalog.load_calendar(path)
    filled = [("MARKET", "FILLED"), ("LIMIT", "FILLED")]
    rejected = [("MARKET", "REJECTED"), ("LIMIT", "REJECTED")]
    # Thanksgiving, 10:00: open in the weekly window, closed by the rows.
    assert gated(tmp_path / "a", "2026-11-26T10:00:00", None)[1] == filled
    data, orders = gated(tmp_path / "b", "2026-11-26T10:00:00", rows)
    assert orders == rejected and data["bracket"]["entry"] == "REJECTED"
    # The half day, 13:30: after the early close only an extended-hours LIMIT is accepted.
    data, orders = gated(tmp_path / "c", "2026-11-27T13:30:00", rows)
    assert orders == [("LIMIT", "FILLED")]
    assert {r for _, r in data["session_refusals"]} == {
        "after_hours: only LIMIT orders with DAY or GTC"
    }
    assert gated(tmp_path / "d", "2026-11-27T13:30:00", None)[1] == filled
    # 17:30: after the half day's last session the venue rejects both.
    assert gated(tmp_path / "e", "2026-11-27T17:30:00", rows)[1] == rejected


# 4. The lane's order budget in the loop.


class Burst(GatedBreakout):
    """On its first QUIET quote, more resting DAY buys than the pacer's burst; then nothing."""

    count = 20

    def on_quote(self, quote: QuoteTick) -> None:
        if getattr(self, "_sent", False) or "QUIET" not in str(quote.instrument_id):
            return
        self._sent = True
        price = Price.from_str(format(quote.bid_price.as_decimal() / 2, ".2f"))
        for _ in range(self.count):
            self.submit_order(
                self.order_factory.limit(
                    quote.instrument_id, OrderSide.BUY, Quantity.from_int(1), price, TimeInForce.DAY
                )
            )


def test_the_sim_rows_have_the_lanes_shape_and_load_as_paper_defaults(tmp_path):
    template = json.loads((ROOT / "deploy/alpaca-order-budget.template.json").read_text())
    rows = budget.paper_default_rows()
    assert [(r["name"], set(r)) for r in rows] == [(r["name"], set(r)) for r in template]
    loaded = load_controls(str(budget.write_rows(tmp_path)))
    assert loaded.paper_default_rows == len(rows) and loaded.reviewed_rows == 0


def test_a_burst_beyond_the_budget_is_deferred_as_the_lane_defers_it(tmp_path):
    store = runner.write_catalog(tmp_path)
    data, seen = run(BASE, store, template_type=Burst)
    burst = seen["template"]
    sent = {coid: (asked, at) for coid, asked, at in burst.paced}
    orders = [o for o in template_orders(seen) if str(o.client_order_id) in sent]
    assert len(orders) == Burst.count and all(o.status.name == "ACCEPTED" for o in orders)
    asked = {a for a, _ in sent.values()}
    assert len(asked) == 1 and data["budget"]["deferred"] == Burst.count
    # The lane's way: M2's pacer from the same rows on the same clock, one request per
    # order at the same time, and a drain after each token interval (`AccountGateway.call`).
    # Its reserve counts the account's positions: the bracket's, open from its entry fill to
    # its take-profit fill, with that take-profit an open sell.
    fills = seen["fills"]
    legs = fills[fills["instrument_id"] == str(runner.BRACKET)]
    held = (
        legs[legs["order_side"] == "BUY"]["ts_event"].min().value,
        legs[legs["order_side"] == "SELL"]["ts_event"].max().value,
    )
    now = [burst.budget_anchor_ns]
    lane = budget.pacer(store.parent / budget.ROWS_FILE, lambda: now[0])
    out: list[int] = []
    (now[0],) = asked
    for _ in range(Burst.count):
        lane.request(
            ActionKind.SUBMIT,
            lambda mark: (mark(), out.append(now[0])),
            position_counts=lambda: (1, 1) if held[0] <= now[0] < held[1] else (0, 0),
        )
    while lane.queue:
        now[0] += lane.bucket.interval_ns
        lane.drain()
    assert sorted(at for _, at in sent.values()) == out
    assert out[0] > min(asked)  # the pacer starts without a burst: nothing goes at once
    # One token an interval from none at the start: 20 sends need at least 20 intervals.
    assert out[-1] - burst.budget_anchor_ns >= Burst.count * lane.bucket.interval_ns
    # Without the order budget every order reaches the venue when it is asked for.
    data, seen = run(replace(BASE, order_budget=False), store, template_type=Burst)
    assert data["budget"] == {"paced": 0, "deferred": 0, "refusals": []}
    assert len({o.ts_init for o in template_orders(seen)}) == 1


class BudgetFullThenFree(GatedBreakout):
    """The template entering QUIET only, while the account looks full for its first seconds:
    17 open positions make an entry's reserve (1 each, plus its own) equal the burst of 18."""

    full_until_ns = catalog.START_NS + 3 * 10**9

    def entry_signal(self, book, quote) -> bool:
        return book.symbol.startswith("QUIET")

    def _position_counts(self) -> tuple[int, int]:
        full = self.clock.timestamp_ns() < self.full_until_ns
        return (17, 0) if full else super()._position_counts()


def test_an_entry_the_budget_refuses_ends_and_the_symbol_enters_when_capacity_returns(
    tmp_path,
):
    data, seen = run(BASE, runner.write_catalog(tmp_path), template_type=BudgetFullThenFree)
    template = seen["template"]
    refused = {coid for coid, reason in data["budget"]["refusals"]}
    assert refused and {r for _, r in data["budget"]["refusals"]} == {"entry-reserve-exceeds-burst"}
    book = next(b for b in template.books.values() if b.symbol.startswith("QUIET"))
    assert book.refusals["refused before the venue"] == len(refused)
    assert "entry-unfilled" in book.events  # the template's own terminal path
    # Capacity returns: a new entry on the same symbol reaches the venue and fills.
    sent = [o for o in template_orders(seen) if o.instrument_id == book.instrument_id]
    assert sent and all(str(o.client_order_id) not in refused for o in sent)
    entry = min((o for o in sent if o.side == OrderSide.BUY), key=lambda o: o.ts_init)
    assert entry.status.name == "FILLED"
    asked = {c: a for c, a, _ in template.paced}
    assert asked[str(entry.client_order_id)] >= BudgetFullThenFree.full_until_ns
    assert book.phase.name != "ENTERING" or template._order(book) is not None


def test_a_queued_market_order_is_refused_once_the_pacer_holds_it_past_the_close(tmp_path):
    # 15:59:59.75: both orders are asked for in the regular session; the pacer, starting
    # without a burst, can send the first only two token intervals later, after 16:00.
    store = runner.write_catalog(tmp_path, start_ns=ny_ns("2024-01-03T15:59:59") + 750 * 10**6)
    data, seen = run(BASE, store, template_type=MarketAndLimit)
    orders = template_orders(seen)
    assert [(o.order_type.name, o.status.name) for o in orders] == [("LIMIT", "FILLED")]
    template = seen["template"]
    (market,) = [c for c, r in template.session_refusals]
    assert dict(template.session_refusals)[market] == (
        "after_hours: only LIMIT orders with DAY or GTC"
    )
    (sent,) = [(c, a, s) for c, a, s in template.paced]
    assert sent[2] >= ny_ns("2024-01-03T16:00:00") and sent[0] != market
