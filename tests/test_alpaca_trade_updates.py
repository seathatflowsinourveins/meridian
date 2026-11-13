"""
The trade-update stream's parsing: every message is classified exactly, or refused as
incomplete coverage. Messages are synthetic, shaped as alpaca-py 0.45.0 hands them to a
handler with `raw_data=True` (`alpaca/trading/stream.py`, `_dispatch` and `_cast`).
"""

from decimal import Decimal

import pytest
from alpaca_fakes import order_row, update

from meridian.alpaca.trade_updates import (
    KNOWN_EVENTS,
    TERMINAL_EVENTS,
    UnclassifiedTradeUpdate,
    is_listening_ack,
    parse_trade_update,
)


def test_a_fill_keeps_its_decimal_text_exact():
    row = order_row(status="filled", qty="3", limit_price="187.2501")
    message = update("fill", row, price="187.2501", qty="3", position_qty="3")
    parsed = parse_trade_update(message)
    assert parsed.is_fill and parsed.is_terminal
    assert parsed.price == Decimal("187.2501") and parsed.qty == Decimal("3")
    assert parsed.position_qty == Decimal("3")
    assert parsed.venue_order_id == row["id"] and parsed.client_order_id == row["client_order_id"]
    assert parsed.execution_id and parsed.symbol == "AAPL" and parsed.side == "buy"


def test_a_partial_fill_is_a_fill_but_not_terminal():
    row = order_row(status="partially_filled", qty="5", filled_qty="2")
    parsed = parse_trade_update(update("partial_fill", row, qty="2"))
    assert parsed.is_fill and not parsed.is_terminal and parsed.qty == Decimal("2")


@pytest.mark.parametrize("event", sorted(KNOWN_EVENTS - {"fill", "partial_fill"}))
def test_every_classified_status_event_parses(event):
    parsed = parse_trade_update(update(event, order_row(status="new", filled_qty="0")))
    assert parsed.event == event and not parsed.is_fill
    assert parsed.is_terminal == (event in TERMINAL_EVENTS)


def test_the_event_timestamp_wins_over_the_orders_update_time():
    row = order_row(status="canceled", filled_qty="0")
    message = update("canceled", row, timestamp="2026-11-02T14:30:00.123456789Z")
    assert parse_trade_update(message).ts_event % 1_000_000_000 == 123_456_789


@pytest.mark.parametrize("event", ["restated", "trade_bust", "trade_correct", "", "NEW", "fills"])
def test_an_unknown_or_correcting_event_is_incomplete_coverage(event):
    with pytest.raises(UnclassifiedTradeUpdate):
        parse_trade_update(update(event, order_row()))


def drop(message, *path):
    target = message["data"]
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return message


@pytest.mark.parametrize(
    "broken",
    [
        lambda m: {**m, "stream": "listening"},
        lambda m: {"stream": "trade_updates"},
        lambda m: {"stream": "trade_updates", "data": "fill"},
        lambda m: drop(m, "order"),
        lambda m: drop(m, "execution_id"),
        lambda m: drop(m, "price"),
        lambda m: drop(m, "order", "id"),
        lambda m: drop(m, "order", "client_order_id"),
        lambda m: drop(m, "order", "symbol"),
        lambda m: drop(m, "order", "status"),
        lambda m: {**m, "data": {**m["data"], "price": 187.25}},  # a float, not decimal text
        lambda m: {**m, "data": {**m["data"], "qty": "0"}},
        lambda m: {**m, "data": {**m["data"], "price": "-1"}},
        lambda m: {**m, "data": {**m["data"], "price": "NaN"}},
        lambda m: {**m, "data": {**m["data"], "timestamp": "yesterday"}},
        lambda m: {**m, "data": {**m["data"], "order": {**m["data"]["order"], "side": "short"}}},
        lambda m: {**m, "data": {**m["data"], "order": {**m["data"]["order"], "legs": [{}]}}},
    ],
)
def test_a_malformed_fill_is_incomplete_coverage(broken):
    with pytest.raises(UnclassifiedTradeUpdate):
        parse_trade_update(broken(update("fill", order_row())))


def test_the_listening_acknowledgement_is_recognised_and_nothing_else_is():
    assert is_listening_ack({"stream": "listening", "data": {"streams": ["trade_updates"]}})
    assert not is_listening_ack({"stream": "listening", "data": {"streams": []}})
    assert not is_listening_ack({"stream": "authorization", "data": {"status": "authorized"}})
    assert not is_listening_ack(update("new", order_row()))
