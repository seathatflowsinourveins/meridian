"""The Alpaca lane's one-order strategy, also used by offline native simulation.

Moved unchanged from alpaca_node: importing a strategy must not import SDK HTTP
transports (urllib3 probes IPv6 by opening a socket during import).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

from nautilus_trader.model import (
    ClientId,
    ClientOrderId,
    InstrumentId,
    OrderSide,
    Price,
    Quantity,
    StrategyId,
)
from nautilus_trader.trading import Strategy, StrategyConfig

from meridian.alpaca_lane import INSTRUMENT
from meridian.ibkr_node import LIMIT_UNDER_BID, ORDER_QTY, OneDayLimit

INSTRUMENT_ID = InstrumentId.from_str(INSTRUMENT)
CLIENT_ID = ClientId("ALPACA")
HOUSE_PREFIX = "MERIDIAN-M3-"


class OnePaperOrder(OneDayLimit):
    """One own order only, no close-on-stop, and no inherited IB callbacks."""

    def __init__(self) -> None:
        Strategy.__init__(
            self,
            StrategyConfig(
                strategy_id=StrategyId("MERIDIAN-M3"),
                external_order_instrument_ids=[INSTRUMENT_ID],
            ),
        )
        self.instrument_id = INSTRUMENT_ID
        self.instrument = None
        self._bid = None
        self._order_id = None
        self._order: Any = None
        self._hold = None
        self._sent = 0
        self._orders_submitted = False
        self._quotes_subscribed = False
        self._cancel_sent = False
        self._ready = False
        self.quote_usable: Callable[[], bool] = lambda: False
        self.execution_healthy: Callable[[], bool] = lambda: False

    def on_start(self) -> None:
        counts = self._open_counts()
        self._record.trader_started(**counts)
        self.instrument = self.cache.instrument(self.instrument_id)
        if counts["instrument_open_orders"] or counts["instrument_open_positions"]:
            self._hold = "instrument not clean at startup"
            return
        if self.instrument is None or not self.execution_healthy():
            self._hold = "instrument or execution unavailable"
            self._record.engine_error(self._hold)
            return
        self._ready = True
        if self._mode() == "order":
            self._quotes_subscribed = True
            self.subscribe_quotes(self.instrument_id, client_id=CLIENT_ID)

    def on_instrument(self, instrument: Any) -> None:
        # Execution loads the instrument before startup; unsolicited data cannot
        # invoke upstream's environment-controlled subscription/submission path.
        pass

    def on_quote(self, quote: Any) -> None:
        if not self._ready or self._mode() != "order" or not self.quote_usable():
            return
        if quote.instrument_id != self.instrument_id or not quote.bid_price.is_positive():
            return
        # OneDayLimit supplies the bid and calls upstream's once-only quote trigger.
        super().on_quote(quote)

    def submit_example_orders(self) -> None:
        if not self._ready or self._bid is None or self.instrument is None:
            self._record.order_refused("no usable bid")
            return
        # Same 2% band as M1, decimal arithmetic, round down to Alpaca's tick.
        target = self._bid.as_decimal() * (1 - Decimal(str(LIMIT_UNDER_BID)))
        tick = Decimal("0.01") if target >= 1 else Decimal("0.0001")
        price = target.quantize(tick, rounding=ROUND_DOWN)
        if price <= 0:
            self._record.order_refused("no positive limit price")
            return
        self._order_id = ClientOrderId(HOUSE_PREFIX + uuid4().hex)
        self._order = self.limit_order(
            self._order_id, OrderSide.BUY, Quantity.from_str(ORDER_QTY), Price.from_str(str(price))
        )
        self.submit_ib_order(self._order)

    def submit_ib_order(self, order: Any) -> None:
        self.submit_order(order)

    def submit_order(self, order: Any, position_id=None, client_id=None, params=None) -> None:
        if (
            self._mode() != "order"
            or not self._ready
            or self._hold
            or self._sent
            or order is not self._order
            or not self.quote_usable()
        ):
            self._record.order_refused("mode, count, identity or quote refused submission")
            return
        self._sent += 1
        self._record.order_built(type="LIMIT", time_in_force="DAY", side="BUY", quantity="1")
        Strategy.submit_order(self, order, client_id=CLIENT_ID)

    def submit_order_list(
        self, order_list: Any, position_id=None, client_id=None, params=None
    ) -> None:
        self._record.order_refused("order lists are not part of this lane")

    def on_order_accepted(self, event: Any) -> None:
        if (
            self._mode() == "order"
            and event.client_order_id == self._order_id
            and not self._cancel_sent
        ):
            self._cancel_sent = True
            self.cancel_order(self._order_id, client_id=CLIENT_ID)

    def on_order_event(self, event: Any) -> None:
        if event.client_order_id != self._order_id:
            return
        kind = type(event).__name__
        if kind in {
            "OrderInitialized",
            "OrderSubmitted",
            "OrderAccepted",
            "OrderPendingCancel",
            "OrderCanceled",
            "OrderFilled",
            "OrderRejected",
            "OrderDenied",
            "OrderExpired",
            "OrderCancelRejected",
            "OrderCancelDenied",
        }:
            # No ids, prices, quantities, reasons or other broker strings enter evidence.
            self._record.event(kind, event.ts_event)
        if kind == "OrderFilled":
            self._hold = "fill: no further submission"

    def on_position_event(self, event: Any) -> None:
        pass

    def on_stop(self) -> None:
        fields: dict[str, Any] = dict(self._open_counts())
        fields["instrument_inflight_orders"] = len(
            self.cache.orders_inflight(instrument_id=self.instrument_id)
        )
        order = None if self._order_id is None else self.cache.order(self._order_id)
        fields.update(
            order_status=None if order is None else order.status.name,
            filled=False if order is None else order.filled_qty.as_decimal() != 0,
            execution_healthy=self.execution_healthy(),
        )
        self._record.at_stop(**fields)
        # No stop-time cancel or close: an unresolved order fails the run, and the
        # owner inspects it. Restart has no route to submit, modify or cancel.
        if self._quotes_subscribed:
            self.unsubscribe_quotes(self.instrument_id, client_id=CLIENT_ID)
