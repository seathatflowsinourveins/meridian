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
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from nautilus_trader.model import (
    InstrumentId,
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

from meridian.alpaca_sessions import session_ns
from meridian.strategy_template.sim import SyntheticBreakout

EXTENDED_HOURS_TIF = (TimeInForce.DAY, TimeInForce.GTC)


def refusal(order: Any, ts_ns: int) -> str | None:
    """Why Alpaca would refuse this order now, or None. Emulated orders stay in the engine."""
    if order.emulation_trigger not in (None, TriggerType.NO_TRIGGER):
        return None  # released later as a LIMIT or MARKET, checked by the venue then
    session = session_ns(ts_ns)
    if session is None or session.name == "regular":
        return None  # closed: the venue's CLOSE status rejects it natively
    if order.order_type != OrderType.LIMIT or order.time_in_force not in EXTENDED_HOURS_TIF:
        return f"{session.name}: only LIMIT orders with DAY or GTC"
    return None


class GatedBreakout(SyntheticBreakout):
    """The template's synthetic breakout with the session rule in front of each submit.

    The template sends only DAY LIMIT entries and exits and an emulated trailing stop, so the
    rule never refuses it; a refusal would leave its symbol waiting, and is counted.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.session_refusals: list[tuple[str, str]] = []

    def submit_order(self, order: Any, *args: Any, **kwargs: Any) -> None:
        reason = refusal(order, self.clock.timestamp_ns())
        if reason is None:
            super().submit_order(order, *args, **kwargs)
        else:
            self.session_refusals.append((str(order.client_order_id), reason))


class BracketProbe(Strategy):
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
        self.session_refusals: list[tuple[str, str]] = []

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
        reasons = [r for o in orders if (r := refusal(o, quote.ts_event)) is not None]
        if reasons:
            self.session_refusals.append(("bracket", reasons[0]))
            return
        self.submit_order_list(orders)
