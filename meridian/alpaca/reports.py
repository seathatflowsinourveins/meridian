"""
Alpaca rows as NautilusTrader reconciliation reports.

Own design, ported from `sextant-paper@a991b73a:src/sextant/alpaca/reports.py`. Rows stay the
raw JSON the venue sent (alpaca-py `raw_data=True`): quantities and prices are decimal text,
which this module reads exactly and never through a float. A row this module cannot map
exactly raises `ValueError`; the caller counts it as incomplete coverage, never as absence.

Statuses are Alpaca's order statuses as alpaca-py 0.45.0 lists them
(`alpaca/trading/enums.py`, `OrderStatus`), mapped as the earlier line mapped them.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AccountId,
    AvgPxReconciliation,
    ClientOrderId,
    Equity,
    FillReport,
    LiquiditySide,
    Money,
    OrderSide,
    OrderStatus,
    OrderStatusReport,
    OrderType,
    PositionSide,
    PositionStatusReport,
    Price,
    Quantity,
    TimeInForce,
    TradeId,
    TrailingOffsetType,
    TriggerType,
    VenueOrderId,
)

# Alpaca statuses after which the order can no longer change.
TERMINAL = frozenset({"filled", "canceled", "expired", "rejected", "replaced"})

_STATUS = {
    "new": OrderStatus.ACCEPTED,
    "accepted": OrderStatus.ACCEPTED,
    "pending_new": OrderStatus.ACCEPTED,
    "accepted_for_bidding": OrderStatus.ACCEPTED,
    "held": OrderStatus.ACCEPTED,
    "done_for_day": OrderStatus.ACCEPTED,
    "stopped": OrderStatus.ACCEPTED,
    "suspended": OrderStatus.ACCEPTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
    "pending_cancel": OrderStatus.PENDING_CANCEL,
    "pending_replace": OrderStatus.PENDING_UPDATE,
}
_SIDE = {"buy": OrderSide.BUY, "sell": OrderSide.SELL}
_POSITION_SIDE = {"long": PositionSide.LONG, "short": PositionSide.SHORT}
_TYPE = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP_MARKET,
    "stop_limit": OrderType.STOP_LIMIT,
    "trailing_stop": OrderType.TRAILING_STOP_MARKET,
}
_TIF = {
    "day": TimeInForce.DAY,
    "gtc": TimeInForce.GTC,
    "opg": TimeInForce.AT_THE_OPEN,
    "cls": TimeInForce.AT_THE_CLOSE,
    "ioc": TimeInForce.IOC,
    "fok": TimeInForce.FOK,
}


class UnmappedOrderStatus(ValueError):
    """A venue status this lane has not classified: incomplete coverage, never a guess."""


def decimal_text(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} requires decimal text from the venue")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{field} requires valid decimal text") from None
    if not result.is_finite():
        raise ValueError(f"{field} requires a finite decimal")
    return result


def timestamp_ns(value: object, field: str) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} requires an RFC 3339 timestamp")
    try:
        return dt_to_unix_nanos(value)
    except Exception:
        raise ValueError(f"{field} is not a valid timestamp") from None


def _quantity(value: Decimal, instrument: Equity) -> Quantity:
    quantity = Quantity.from_decimal_dp(value, instrument.size_precision)
    if quantity.as_decimal() != value:
        raise ValueError("venue quantity exceeds instrument size precision")
    return quantity


def _price(value: Decimal, instrument: Equity) -> Price:
    price = Price.from_decimal_dp(value, instrument.price_precision)
    if price.as_decimal() != value:
        raise ValueError("venue price exceeds instrument price precision")
    return price


def _symbol_matches(row: Mapping[str, Any], instrument: Equity) -> None:
    if row.get("symbol") != instrument.raw_symbol.value:
        raise ValueError("Alpaca row does not match the loaded instrument")


def order_status_report(
    row: Mapping[str, Any],
    *,
    account_id: AccountId,
    instrument: Equity,
    ts_init: int,
) -> OrderStatusReport:
    """One simple US-equity order row, mapped exactly, or ValueError."""
    if row.get("asset_class") != "us_equity" or row.get("order_class") not in ("simple", "", None):
        raise ValueError("Alpaca order report requires a simple US-equity order")
    if row.get("legs"):
        raise ValueError("Alpaca order report requires an order without legs")
    _symbol_matches(row, instrument)
    venue_id, client_id = row.get("id"), row.get("client_order_id")
    if not isinstance(venue_id, str) or not venue_id or not isinstance(client_id, str):
        raise ValueError("Alpaca order report requires its venue and client order ids")
    kind, side, tif = row.get("type"), row.get("side"), row.get("time_in_force")
    if kind not in _TYPE or side not in _SIDE or tif not in _TIF:
        raise ValueError("Alpaca order report requires a known type, side and time in force")

    quantity = decimal_text(row.get("qty"), "order quantity")
    filled_qty = decimal_text(row.get("filled_qty"), "filled quantity")
    if quantity <= 0 or not 0 <= filled_qty <= quantity:
        raise ValueError("Alpaca order report has inconsistent share quantities")

    raw_status = row.get("status")
    status = _STATUS.get(raw_status) if isinstance(raw_status, str) else None
    if raw_status == "calculated":
        status = OrderStatus.FILLED if filled_qty == quantity else OrderStatus.ACCEPTED
    if status is None:
        raise UnmappedOrderStatus("Alpaca order status requires classification")
    if status == OrderStatus.ACCEPTED and 0 < filled_qty < quantity:
        status = OrderStatus.PARTIALLY_FILLED

    trailing_offset = trailing_offset_type = None
    if kind == "trailing_stop":
        trail_price, trail_percent = row.get("trail_price"), row.get("trail_percent")
        if (trail_price is None) == (trail_percent is None):
            raise ValueError("Alpaca trailing stop requires exactly one offset")
        if trail_price is not None:
            trailing_offset = decimal_text(trail_price, "trail price")
            trailing_offset_type = TrailingOffsetType.PRICE
        else:
            trailing_offset = decimal_text(trail_percent, "trail percent") * 100
            trailing_offset_type = TrailingOffsetType.BASIS_POINTS
    triggered = kind in ("stop", "stop_limit", "trailing_stop")

    limit_price, stop_price = row.get("limit_price"), row.get("stop_price")
    avg = row.get("filled_avg_price")
    return OrderStatusReport(
        account_id,
        instrument.id,
        VenueOrderId(venue_id),
        _SIDE[side],
        _TYPE[kind],
        _TIF[tif],
        status,
        _quantity(quantity, instrument),
        _quantity(filled_qty, instrument),
        timestamp_ns(row.get("submitted_at"), "submitted_at"),
        timestamp_ns(row.get("updated_at"), "updated_at"),
        ts_init,
        client_order_id=ClientOrderId(client_id),
        expire_time=timestamp_ns(row["expires_at"], "expires_at")
        if row.get("expires_at")
        else None,
        price=_price(decimal_text(limit_price, "limit price"), instrument)
        if limit_price is not None
        else None,
        trigger_price=_price(decimal_text(stop_price, "stop price"), instrument)
        if stop_price is not None
        else None,
        trigger_type=TriggerType.DEFAULT if triggered else None,
        trailing_offset=trailing_offset,
        trailing_offset_type=trailing_offset_type,
        avg_px=decimal_text(avg, "average fill price") if filled_qty and avg is not None else None,
    )


def position_status_report(
    row: Mapping[str, Any],
    *,
    account_id: AccountId,
    instrument: Equity,
    ts_init: int,
) -> PositionStatusReport:
    """One open US-equity position row, or ValueError."""
    if row.get("asset_class") != "us_equity":
        raise ValueError("Alpaca position report requires a US equity")
    _symbol_matches(row, instrument)
    side = _POSITION_SIDE.get(row.get("side"))  # type: ignore[arg-type]
    if side is None:
        raise ValueError("Alpaca position report requires a known side")
    quantity = decimal_text(row.get("qty"), "position quantity")
    if quantity.is_zero() or (side == PositionSide.LONG and quantity < 0):
        raise ValueError("Alpaca position report has an inconsistent share quantity")
    avg_entry = decimal_text(row.get("avg_entry_price"), "average entry price")
    if avg_entry < 0:
        raise ValueError("Alpaca position report has an invalid average entry price")
    # Alpaca's cost basis can change overnight without a fill: compare the opening price only.
    return PositionStatusReport(
        account_id,
        instrument.id,
        side,
        _quantity(quantity.copy_abs(), instrument),
        ts_init,
        ts_init,
        avg_px_open=avg_entry or None,
        avg_px_open_reconciliation=AvgPxReconciliation.OPENING_ONLY,
    )


def fill_report(
    data: Mapping[str, Any],
    *,
    account_id: AccountId,
    instrument: Equity,
    ts_init: int,
    commission: Money,
) -> FillReport:
    """One `fill` or `partial_fill` trade update (its `data` object), or ValueError."""
    if data.get("event") not in ("fill", "partial_fill"):
        raise ValueError("Alpaca fill report requires a fill event")
    order = data.get("order")
    if not isinstance(order, Mapping):
        raise ValueError("Alpaca fill report requires the order object")
    if order.get("asset_class") != "us_equity" or order.get("side") not in _SIDE:
        raise ValueError("Alpaca fill report requires a US equity and a side")
    _symbol_matches(order, instrument)
    execution_id, venue_id = data.get("execution_id"), order.get("id")
    client_id = order.get("client_order_id")
    if not all(isinstance(v, str) and v for v in (execution_id, venue_id, client_id)):
        raise ValueError("Alpaca fill report requires execution, venue and client order ids")
    price = decimal_text(data.get("price"), "fill price")
    quantity = decimal_text(data.get("qty"), "fill quantity")
    if price <= 0 or quantity <= 0:
        raise ValueError("Alpaca fill report requires a positive price and quantity")
    return FillReport(
        account_id,
        instrument.id,
        VenueOrderId(str(venue_id)),
        TradeId(str(execution_id)),
        _SIDE[order["side"]],
        _quantity(quantity, instrument),
        _price(price, instrument),
        commission,
        LiquiditySide.NO_LIQUIDITY_SIDE,
        timestamp_ns(data.get("timestamp"), "fill timestamp"),
        ts_init,
        client_order_id=ClientOrderId(str(client_id)),
    )
