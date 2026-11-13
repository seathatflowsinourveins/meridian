"""
Trade updates from the paper account's websocket, classified before anything acts on them.

Own design. The event list is the earlier line's (`sextant-paper@a991b73a:src/sextant/alpaca/
execution.py`, `_INGRESS`: alpaca-py's `TradeEvent` plus Alpaca's documented status and refusal
events, read by that line on 2026-11-10). alpaca-py 0.45.0 (`alpaca/trading/stream.py`) hands a
handler the raw message when `raw_data=True`; its typed `TradeUpdate` would turn the fill price
and quantities into floats (`alpaca/trading/models.py`), so this module reads the raw text.

An event outside the list ("restated", "trade_bust", "trade_correct" or anything new), a message
with a missing or malformed field, or an order with legs is `UnclassifiedTradeUpdate`: the
client then treats its view of the account as incomplete until a read settles it. Nothing here
emits an engine event.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .reports import decimal_text, timestamp_ns

KNOWN_EVENTS = frozenset(
    {
        "new",
        "accepted",
        "rejected",
        "canceled",
        "expired",
        "done_for_day",
        "replaced",
        "pending_new",
        "stopped",
        "pending_cancel",
        "pending_replace",
        "calculated",
        "suspended",
        "accepted_for_bidding",
        "held",
        "pending_review",
        "fill",
        "partial_fill",
        "order_replace_rejected",
        "order_cancel_rejected",
    }
)
FILL_EVENTS = frozenset({"fill", "partial_fill"})
# After these, no cancel of the order can still act.
TERMINAL_EVENTS = frozenset({"fill", "canceled", "expired", "rejected", "replaced"})
# Replacement belongs to modify, which this lane never sends.
REPLACE_EVENTS = frozenset({"replaced", "pending_replace", "order_replace_rejected"})


class UnclassifiedTradeUpdate(ValueError):
    """A trade update this lane cannot classify exactly: incomplete coverage."""


@dataclass(frozen=True, slots=True)
class TradeUpdate:
    event: str
    venue_order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    ts_event: int
    order: Mapping[str, Any]
    data: Mapping[str, Any]
    execution_id: str | None = None
    price: Decimal | None = None
    qty: Decimal | None = None
    position_qty: Decimal | None = None

    @property
    def is_fill(self) -> bool:
        return self.event in FILL_EVENTS

    @property
    def is_terminal(self) -> bool:
        return self.event in TERMINAL_EVENTS


def is_listening_ack(message: Mapping[str, Any]) -> bool:
    """The venue's confirmation of the subscription: {"stream": "listening", ...}."""
    if message.get("stream") != "listening":
        return False
    data = message.get("data")
    streams = data.get("streams") if isinstance(data, Mapping) else None
    return isinstance(streams, list) and "trade_updates" in streams


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise UnclassifiedTradeUpdate(f"trade update requires {field}")
    return value


def parse_trade_update(message: Mapping[str, Any]) -> TradeUpdate:
    """One raw `trade_updates` message, classified, or `UnclassifiedTradeUpdate`."""
    if not isinstance(message, Mapping) or message.get("stream") != "trade_updates":
        raise UnclassifiedTradeUpdate("not a trade_updates message")
    data = message.get("data")
    if not isinstance(data, Mapping):
        raise UnclassifiedTradeUpdate("trade update requires its data object")
    event = data.get("event")
    if not isinstance(event, str) or event not in KNOWN_EVENTS:
        raise UnclassifiedTradeUpdate("unclassified trade update event")
    order = data.get("order")
    if not isinstance(order, Mapping):
        raise UnclassifiedTradeUpdate("trade update requires its order object")
    if order.get("legs"):
        raise UnclassifiedTradeUpdate("trade update for an order with legs")
    side = order.get("side")
    if side not in ("buy", "sell"):
        raise UnclassifiedTradeUpdate("trade update requires the order side")
    try:
        stamp = data.get("timestamp") or order.get("updated_at")
        ts_event = timestamp_ns(stamp, "trade update timestamp")
        fields: dict[str, Any] = {}
        if event in FILL_EVENTS:
            fields["execution_id"] = _text(data.get("execution_id"), "an execution id")
            fields["price"] = decimal_text(data.get("price"), "fill price")
            fields["qty"] = decimal_text(data.get("qty"), "fill quantity")
            if fields["price"] <= 0 or fields["qty"] <= 0:
                raise UnclassifiedTradeUpdate("fill requires a positive price and quantity")
            if data.get("position_qty") is not None:
                fields["position_qty"] = decimal_text(data.get("position_qty"), "position_qty")
    except UnclassifiedTradeUpdate:
        raise
    except ValueError as exc:
        raise UnclassifiedTradeUpdate(str(exc)) from None
    return TradeUpdate(
        event=event,
        venue_order_id=_text(order.get("id"), "the venue order id"),
        client_order_id=_text(order.get("client_order_id"), "the client order id"),
        symbol=_text(order.get("symbol"), "the symbol"),
        side=side,
        status=_text(order.get("status"), "the order status"),
        ts_event=ts_event,
        order=order,
        data=data,
        **fields,
    )
