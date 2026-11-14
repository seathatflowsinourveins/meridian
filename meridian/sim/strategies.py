"""The strategies in the loop: the template on several symbols, and one bracket.

Own code, where the engine has no primitive: the engine checks no order type against a
session. Alpaca accepts only LIMIT orders with time in force DAY or GTC as extended-hours
eligible and rejects every other type (https://docs.alpaca.markets/us/docs/orders-at-alpaca,
"Submitting an Extended Hours Eligible Order", read 2026-11-14), and the lane sends every
order extended-hours eligible (`meridian/alpaca/wire.py`, `submit_payload`). `refusal` applies
that rule with `meridian.alpaca_sessions`; the two strategies refuse before submitting. Outside
every session the venue itself rejects, from the `InstrumentStatus` data (`catalog.py`).

The bracket follows `OrderFactory.bracket` (rc9 `docs/concepts/orders/advanced.md:290-342`):
a LIMIT entry whose fill releases a LIMIT take-profit and a STOP_MARKET stop-loss, linked
one-updates-other, all held by the simulated venue. Not emulated: the emulator releases an
emulated LIMIT as a MARKET (rc9 `docs/concepts/orders/emulated.md:37-38`). The paper lanes do
not send a bracket: their wire refuses contingent orders (`meridian/alpaca/wire.py`). It is
here to exercise rc9's contingent path.

`PaperVenue`, mixed into both, adds two own rules where rc9 has none. DAY expiry: rc9's
simulated venue expires only GTD orders (`crates/execution/src/matching_engine/mod.rs:4714`);
Alpaca cancels a DAY order left unfilled after the close, and one marked extended-hours
eligible, as the lane sends them, "remains an active order until it is executed or the market
closes at 8:00 PM ET" (https://docs.alpaca.markets/us/docs/245-trading-for-trading-api, read
2026-11-14; the orders page, "Time in Force", the same day). So each DAY order the venue
accepts gets a time alert at the end of its trade date's last session (20:00 New York, or
the calendar row's `session_close`), which cancels it if it still rests. The order budget:
each venue order passes the lane's account pacer (`budget.py`); emulated orders stay in the
engine, as in the lane, and so does an emulator's release, which this loop does not pace.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import (
    ClientOrderId,
    InstrumentId,
    OrderAccepted,
    OrderSide,
    OrderType,
    Price,
    Quantity,
    QuoteTick,
    StrategyId,
    TimeInForce,
    TriggerType,
)
from nautilus_trader.trading import Strategy, StrategyConfig

from meridian.alpaca_sessions import NEW_YORK, session_ns
from meridian.order_budget.pacer import AccountPacer, ActionKind, PacerRefused
from meridian.strategy_template.sim import SyntheticBreakout

from . import budget

EXTENDED_HOURS_TIF = (TimeInForce.DAY, TimeInForce.GTC)
Calendar = Mapping[date, dict]
DAY_END = time(20)  # the after-hours session's end on a full day (Alpaca's 24/5 FAQ)


def is_emulated(order: Any) -> bool:
    return order.emulation_trigger not in (None, TriggerType.NO_TRIGGER)


def refusal(order: Any, ts_ns: int, calendar: Calendar | None = None) -> str | None:
    """Why Alpaca would refuse this order now, or None. Emulated orders stay in the engine."""
    if is_emulated(order):
        return None  # released later as a LIMIT or MARKET, checked by the venue then
    session = session_ns(ts_ns, calendar)
    if session is None or session.name == "regular":
        return None  # closed: the venue's CLOSE status rejects it natively
    if order.order_type != OrderType.LIMIT or order.time_in_force not in EXTENDED_HOURS_TIF:
        return f"{session.name}: only LIMIT orders with DAY or GTC"
    return None


def day_end_ns(ts_ns: int, calendar: Calendar | None = None) -> int | None:
    """When Alpaca cancels a DAY order placed at `ts_ns`: its trade date's last session end."""
    session = session_ns(ts_ns, calendar)
    if session is None:
        return None
    row = None if calendar is None else calendar.get(session.trade_date)
    end = DAY_END if row is None else datetime.strptime(row["session_close"], "%H%M").time()
    return int(datetime.combine(session.trade_date, end, NEW_YORK).timestamp()) * 1_000_000_000


class PaperVenue(Strategy):
    """Mixed in first: calendar rows, DAY expiry and, given budget rows, the pacer."""

    calendar: Calendar | None = None
    budget_rows: Path | None = None

    def paper_venue(self, calendar: Calendar | None, budget_rows: Path | None) -> None:
        self.calendar, self.budget_rows = calendar, budget_rows
        self.session_refusals: list[tuple[str, str]] = []
        self.day_expiries: list[str] = []  # client order ids cancelled at the day's end
        self.pacer: AccountPacer | None = None
        self.paced: list[tuple[str, int, int]] = []  # (client order id, asked ns, sent ns)
        self.budget_refusals: list[tuple[str, str]] = []
        self.budget_anchor_ns: int | None = None  # when the pacer was built (no burst yet)
        self._pending: dict[ClientOrderId, Any] = {}
        self._alerts = 0
        self._drain_at: int | None = None

    # The pacer, as the lane's gateway uses it: request, then drain after one interval.
    def on_start(self) -> None:
        if self.budget_rows is not None:
            self.pacer = budget.pacer(self.budget_rows, self.clock.timestamp_ns)
            self.budget_anchor_ns = self.pacer.bucket.anchor
        super().on_start()

    def submit_paced(self, order: Any, submit: Any) -> None:
        reason = refusal(order, self.clock.timestamp_ns(), self.calendar)
        if reason is not None:
            self.session_refusals.append((str(order.client_order_id), reason))
            return
        if self.pacer is None or is_emulated(order):
            submit()
            return
        coid, asked = order.client_order_id, self.clock.timestamp_ns()
        self._pending[coid] = order

        def send(mark: Any) -> None:
            mark()
            del self._pending[coid]
            self.paced.append((str(coid), asked, self.clock.timestamp_ns()))
            submit()

        def refuse(reason: str) -> None:
            self._pending.pop(coid, None)
            self.budget_refusals.append((str(coid), reason))

        kind = ActionKind.REDUCE if order.side == OrderSide.SELL else ActionKind.SUBMIT
        with suppress(PacerRefused):  # refuse() has recorded it; nothing was sent
            self.pacer.request(kind, send, position_counts=self._position_counts, refuse=refuse)
        self._schedule_drain()

    def _position_counts(self) -> tuple[int, int]:
        """The lane's counts (`AlpacaExecutionClient._position_counts`) from this cache."""
        cache = self.cache
        exiting = {o.instrument_id for o in cache.orders_open() if o.side == OrderSide.SELL}
        return len(cache.positions_open()), len(exiting)

    def _schedule_drain(self) -> None:
        if self.pacer is None or not self.pacer.queue or self._drain_at is not None:
            return
        self._drain_at = self.clock.timestamp_ns() + self.pacer.bucket.interval_ns
        self._alert(self._drain_at, self._drain)

    def _drain(self, _event: Any) -> None:
        self._drain_at = None
        if self.pacer is not None:
            self.pacer.drain()
        self._schedule_drain()

    def _alert(self, at_ns: int, callback: Any) -> None:
        self._alerts += 1
        self.clock.set_time_alert_ns(f"paper-venue-{self._alerts}", at_ns, callback)

    # DAY expiry at the trade date's end.
    def on_order_event(self, event: Any) -> None:
        if isinstance(event, OrderAccepted):
            order = self.cache.order(event.client_order_id)
            end = day_end_ns(event.ts_event, self.calendar)
            if order is not None and order.time_in_force == TimeInForce.DAY and end is not None:
                coid = event.client_order_id
                self._alert(max(end, event.ts_event), lambda _e: self._expire(coid))
        super().on_order_event(event)

    def _expire(self, coid: ClientOrderId) -> None:
        order = self.cache.order(coid)
        if order is not None and order.is_open and not is_emulated(order):
            self.day_expiries.append(str(coid))
            self.cancel_order(coid)


class GatedBreakout(PaperVenue, SyntheticBreakout):
    """The template's synthetic breakout with the session rule and the pacer before a submit.

    The template sends only DAY LIMIT entries and exits and an emulated trailing stop, so the
    rule never refuses it; a refusal would leave its symbol waiting, and is counted. While
    the pacer holds an order, the template sees it as its unresolved order, as in the lane,
    where the order is in flight until the pacer sends it.
    """

    def __init__(
        self,
        *args: Any,
        calendar: Calendar | None = None,
        budget_rows: Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.paper_venue(calendar, budget_rows)

    def submit_order(self, order: Any, *args: Any, **kwargs: Any) -> None:
        submit = SyntheticBreakout.submit_order
        self.submit_paced(order, lambda: submit(self, order, *args, **kwargs))

    def _order(self, book: Any) -> Any:
        pending = self._pending.get(book.order_id) if book.order_id is not None else None
        return pending if pending is not None else super()._order(book)


class BracketProbe(PaperVenue, Strategy):
    """One bracket on one symbol after `wait` quotes; then it only watches."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return super().__new__(cls)  # the native Strategy's __new__ takes only a config

    def __init__(
        self,
        instrument_id: InstrumentId,
        *,
        quantity: int,
        take_profit: Decimal,
        stop_loss: Decimal,
        wait: int,
        strategy_id: str = "MERIDIAN-M5BRACKET",
        calendar: Calendar | None = None,
    ) -> None:
        super().__init__(StrategyConfig(strategy_id=StrategyId(strategy_id)))
        self.instrument_id = instrument_id
        self.quantity, self.take_profit, self.stop_loss, self.wait = (
            quantity,
            take_profit,
            stop_loss,
            wait,
        )
        self.seen = 0
        self.order_ids: dict[str, str] = {}  # leg -> client order id
        # Not paced: the lanes refuse contingent orders, so no lane admission exists for one.
        self.paper_venue(calendar, None)

    def on_start(self) -> None:
        self.subscribe_quotes(self.instrument_id)

    def on_stop(self) -> None:
        self.unsubscribe_quotes(self.instrument_id)

    def on_quote(self, quote: QuoteTick) -> None:
        self.seen += 1
        if self.seen != self.wait:
            return
        ask = quote.ask_price.as_decimal()
        orders = self.order_factory.bracket(
            self.instrument_id,
            OrderSide.BUY,
            Quantity.from_int(self.quantity),
            entry_order_type=OrderType.LIMIT,
            entry_price=Price.from_str(format(ask, "f")),
            time_in_force=TimeInForce.DAY,
            tp_price=Price.from_str(format(ask + self.take_profit, "f")),
            tp_time_in_force=TimeInForce.DAY,
            tp_post_only=False,
            sl_trigger_price=Price.from_str(format(ask - self.stop_loss, "f")),
            sl_trigger_type=TriggerType.BID_ASK,
            sl_time_in_force=TimeInForce.DAY,
        )
        self.order_ids = {
            leg: str(o.client_order_id)
            for leg, o in zip(("entry", "stop_loss", "take_profit"), orders, strict=True)
        }
        reasons = [r for o in orders if (r := refusal(o, quote.ts_event, self.calendar))]
        if reasons:
            self.session_refusals.append(("bracket", reasons[0]))
            return
        self.submit_order_list(orders)
