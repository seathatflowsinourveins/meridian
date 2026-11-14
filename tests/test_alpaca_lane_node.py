"""Alpaca lane wiring and lifecycle against synthetic venue and quote streams."""

import asyncio
import importlib
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast

import pytest
from alpaca_fakes import Rig, fill_activity, order_row, position_row, run, update
from nautilus_trader.core import unix_nanos_to_iso8601
from nautilus_trader.model import ClientOrderId, OrderSide, Price, Quantity
from node_lifetime import live_nodes as live_nodes


@pytest.fixture
def node_module(monkeypatch, live_nodes):
    module = importlib.import_module("meridian.alpaca_node")
    real_config = module.LiveNodeConfig
    monkeypatch.setattr(
        module, "LiveNodeConfig", lambda **kw: real_config(**kw, delay_post_stop_secs=0)
    )
    # Never construct a real credential reader or network transport in these tests.
    monkeypatch.setattr(module, "production_wiring", lambda *_: pytest.fail("production wiring"))

    yield module


def state():
    from meridian.alpaca.credentials import PaperKeys
    from meridian.alpaca_lane import BudgetAuthority, Preflight, Settings

    return Preflight(
        Settings("unused-fake-path", 10**9),
        BudgetAuthority("fake", 3, 13),
        PaperKeys("fake-id", "fake-secret"),
    )


class Quotes:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.subscriptions = []

    def select_feed(self, feed):
        self.feed = feed

    async def _start_ws(self):
        pass

    async def close(self):
        pass

    async def subscribe(self, handler, symbols):
        self.handler = handler
        self.subscriptions.append(symbols)
        self.queue.put_nowait([{"T": "subscription", "quotes": symbols}])

    async def unsubscribe(self, symbols):
        pass

    async def receive(self):
        return await self.queue.get()

    async def _dispatch(self, row):
        await self.handler(row)


def build(module, monkeypatch, mode="order", rig=None, when=None, lane_state=None):
    from meridian.alpaca.data import AlpacaQuoteClient
    from meridian.alpaca_lane import RunRecord

    rig = rig or Rig()
    rig.venue.accept_status = "new"
    lane_state = lane_state or state()

    def test_clock(clock):
        from meridian.alpaca.reports import timestamp_ns
        from meridian.alpaca_sessions import session_ns

        monkeypatch.setattr(module, "session_ns", session_ns)
        fixed = when or "2026-11-02T15:00:00+00:00"
        offset = timestamp_ns(fixed, "synthetic") - clock.timestamp_ns()
        return SimpleNamespace(timestamp_ns=lambda: clock.timestamp_ns() + offset)

    quotes, captured = Quotes(), {}
    original = module.build_client
    strategy_type = module.OnePaperOrder

    def strategy():
        result = strategy_type()
        captured["strategy"] = result
        return result

    monkeypatch.setattr(module, "OnePaperOrder", strategy)

    def execution(**kwargs):
        kwargs["wiring"] = rig.wiring()
        kwargs["clock"] = test_clock(kwargs["clock"])
        client = original(**kwargs)
        captured["exec"] = client
        return client

    monkeypatch.setattr(module, "build_client", execution)
    monkeypatch.setattr(module, "production_wiring", lambda *_: None)

    def quote_factory(*, name, config, cache, clock):
        client = AlpacaQuoteClient(
            name=name,
            quote_config=config,
            cache=cache,
            clock=test_clock(clock),
            stream=cast(Any, quotes),
        )
        captured["quote"] = client
        return client

    monkeypatch.setattr(module.AlpacaQuoteFactory, "create", quote_factory)
    record = RunRecord(mode, lane_state)
    node = module.build(lane_state, record)
    return node, record, rig, quotes, captured


async def wait_until(condition):
    for _ in range(2000):
        if condition():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("fake engine did not reach expected state")


def quote(client, age=0):
    return [
        {
            "T": "q",
            "S": "AAPL",
            "bp": "100.1234",
            "ap": "100.1235",
            "bs": "2",
            "as": "3",
            "t": unix_nanos_to_iso8601(client.clock.timestamp_ns() - age),
        }
    ]


@pytest.mark.parametrize("mode", ["restart", "order"])
def test_modes_reconcile_and_only_order_accepts_then_cancels(node_module, monkeypatch, mode):
    node, record, rig, quotes, clients = build(node_module, monkeypatch, mode)

    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: record.data["startup_reconciliation"]["trader_started"])
        if mode == "order":
            await wait_until(lambda: bool(quotes.subscriptions))
            quotes.queue.put_nowait(quote(clients["quote"]))
            await wait_until(lambda: getattr(rig.venue, "last_post", None) is not None)
            await wait_until(lambda: any(method == "delete" for method, _ in rig.venue.calls))
            order = rig.venue.orders[-1]
            order["status"] = "canceled"
            rig.stream.push(update("canceled", order))
            await wait_until(
                lambda: any(e["type"] == "OrderCanceled" for e in record.data["events"])
            )
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    record.data["checks_unchanged_after_run"] = True
    assert record.problems() == []
    assert clients["exec"].coverage_complete is False  # disconnected now, stop captured before
    if mode == "order":
        assert rig.venue.last_post["limit_price"] == "98.12"
        assert rig.venue.last_post["qty"] == "1"
        assert sum(m == "post" for m, _ in rig.venue.calls) == 1
        assert sum(m == "delete" for m, _ in rig.venue.calls) == 1
    else:
        assert not quotes.subscriptions
        assert all(m == "get" for m, _ in rig.venue.calls)


@pytest.mark.parametrize("age", [None, 10**9, 10**9 + 1])
def test_missing_or_stale_quotes_place_nothing(node_module, monkeypatch, age):
    node, record, rig, quotes, clients = build(node_module, monkeypatch)

    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        if age is not None:
            quotes.queue.put_nowait(quote(clients["quote"], age))
        for _ in range(20):
            await asyncio.sleep(0.001)
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    assert getattr(rig.venue, "last_post", None) is None
    assert record.problems()


@pytest.mark.parametrize("mode", ["restart", "order"])
@pytest.mark.parametrize("holding", ["order", "position"])
def test_clean_instrument_required(node_module, monkeypatch, mode, holding):
    rig = Rig()
    earlier = order_row(client_order_id=node_module.HOUSE_PREFIX + "earlier", status="new")
    if holding == "position":
        earlier = order_row(client_order_id=node_module.HOUSE_PREFIX + "earlier")
        rig.venue.fills.append(fill_activity(earlier))
        rig.venue.positions.append(position_row(qty="1"))
    rig.venue.orders.append(earlier)
    node, record, rig, quotes, _ = build(node_module, monkeypatch, mode, rig)

    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: record.data["startup_reconciliation"]["trader_started"])
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    assert all(m == "get" for m, _ in rig.venue.calls)
    assert not quotes.subscriptions
    assert record.problems()


def test_fill_fails_and_sends_no_second_order(node_module, monkeypatch):
    node, record, rig, quotes, clients = build(node_module, monkeypatch)

    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: getattr(rig.venue, "last_post", None) is not None)
        order = rig.venue.orders[-1]
        order.update(status="filled", filled_qty="1", filled_avg_price="98.12")
        rig.stream.push(update("fill", order, qty="1", price="98.12", execution_id="fake-fill"))
        await wait_until(lambda: any(e["type"] == "OrderFilled" for e in record.data["events"]))
        quotes.queue.put_nowait(quote(clients["quote"]))
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    assert sum(m == "post" for m, _ in rig.venue.calls) == 1
    assert record.problems()
    assert any("filled" in p for p in record.problems())


def test_restart_guard_at_execution_send(node_module, monkeypatch):
    node, record, rig, _, clients = build(node_module, monkeypatch, "restart")

    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: record.data["startup_reconciliation"]["trader_started"])
        assert not clients["exec"]._submit_admitted()
        strategy = clients["strategy"]
        order = strategy.limit_order(
            ClientOrderId(node_module.HOUSE_PREFIX + "fake"),
            OrderSide.BUY,
            Quantity.from_str("1"),
            Price.from_str("98.00"),
        )
        strategy._order = order
        strategy.submit_order(order)
        strategy.submit_order_list(SimpleNamespace(orders=[order]))
        await clients["exec"]._submit_order(SimpleNamespace(order=order))
        await clients["exec"]._cancel_order(SimpleNamespace())
        for _ in range(5):
            await asyncio.sleep(0)
        assert record.data["orders_refused"] == 4
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    assert all(m == "get" for m, _ in rig.venue.calls)


def test_quote_expiring_at_pacer_admission_is_refused(node_module, monkeypatch):
    node, record, rig, quotes, clients = build(node_module, monkeypatch)

    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        # Delay SUBMIT in the fake pacer, then make the quote client unusable.
        assert rig.pacer is not None
        original = rig.pacer.request

        def delayed(kind, send, **kwargs):
            if kind.name == "SUBMIT":
                clients["quote"]._fail("synthetic loss while queued")
            return original(kind, send, **kwargs)

        rig.pacer.request = delayed
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: any(e["type"] == "OrderRejected" for e in record.data["events"]))
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    assert getattr(rig.venue, "last_post", None) is None


def test_node_configuration_and_strategy_claim(node_module, monkeypatch):
    captured = {}

    class Builder:
        @staticmethod
        def build(name, config, **factories):
            captured.update(config=config, **factories)
            return SimpleNamespace(add_strategy=lambda strategy: captured.update(strategy=strategy))

    monkeypatch.setattr(node_module, "LiveNode", Builder)
    from meridian.alpaca_lane import RunRecord

    node_module.build(state(), RunRecord("restart", state()))
    config = captured["config"]
    assert list(config.exec_clients) == ["ALPACA"]
    assert list(config.data_clients) == ["ALPACA"]
    assert config.exec_clients["ALPACA"].order_budget_rows_path == "unused-fake-path"
    assert config.exec_clients["ALPACA"].commission_source
    engine = config.exec_engine
    assert engine.reconciliation and not engine.generate_missing_orders
    assert engine.reconciliation_lookback_mins is None
    assert engine.inflight_check_interval_ms == 0
    assert engine.open_check_interval_secs > 0
    assert str(captured["strategy"].instrument_id) == "AAPL.ALPACA"
    assert captured["strategy"].config.external_order_instrument_ids == [node_module.INSTRUMENT_ID]


def test_strategy_prices_without_reading_any_quote_size(node_module, monkeypatch):
    node, record, rig, quotes, clients = build(node_module, monkeypatch)
    handle = node.handle()

    class PriceOnly:
        instrument_id = node_module.INSTRUMENT_ID
        bid_price = Price.from_str("100.1234")

        @property
        def bid_size(self):
            pytest.fail("lane read bid size")

        @property
        def ask_size(self):
            pytest.fail("lane read ask size")

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        clients["strategy"].quote_usable = lambda: True
        clients["exec"].quote_usable = lambda: True
        clients["strategy"].on_quote(PriceOnly())
        await wait_until(lambda: getattr(rig.venue, "last_post", None) is not None)
        handle.stop()
        assert await task is None

    asyncio.run(drive())
    assert rig.venue.last_post["limit_price"] == "98.12"
    assert rig.venue.last_post["qty"] == "1"


SESSIONS = [
    ("2026-11-16T02:00:00-05:00", "overnight", "overnight"),
    ("2026-11-16T08:00:00-05:00", "pre_market", "delayed_sip"),
    ("2026-11-16T12:00:00-05:00", "regular", "iex"),
    ("2026-11-16T18:00:00-05:00", "after_hours", "delayed_sip"),
]


def session_build(module, monkeypatch, when, *, eligible=True, halted=False):
    from dataclasses import replace

    from meridian.alpaca_lane import Settings
    from meridian.alpaca_sessions import SIP_DELAY_NS

    rig = Rig()
    get = rig.venue.get

    def asset_flags(path, *args, **kwargs):
        row = get(path, *args, **kwargs)
        if path.startswith("/assets/"):
            row.update(overnight_tradable=eligible, overnight_halted=halted)
        return row

    rig.venue.get = asset_flags
    # Synthetic test limit permits the documented delayed feed; never a production default.
    settings = Settings("unused-fake-path", SIP_DELAY_NS + 10**9)
    return build(
        module, monkeypatch, rig=rig, when=when, lane_state=replace(state(), settings=settings)
    )


@pytest.mark.parametrize("when,session,feed", SESSIONS)
@pytest.mark.parametrize("age_kind", ["fresh", "missing", "stale"])
def test_each_session_engine_quote_order_fields_and_freshness(
    node_module, monkeypatch, when, session, feed, age_kind
):
    from meridian.alpaca_sessions import SIP_DELAY_NS

    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, when)
    handle, cache = node.handle(), node.cache

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        assert quotes.feed == feed
        if age_kind != "missing":
            age = (
                SIP_DELAY_NS + 10**9
                if age_kind == "stale"
                else (SIP_DELAY_NS if feed == "delayed_sip" else 1)
            )
            quotes.queue.put_nowait(quote(clients["quote"], age))
            await wait_until(lambda: cache.quote(node_module.INSTRUMENT_ID) is not None)
        if age_kind == "fresh":
            await wait_until(lambda: any(method == "delete" for method, _ in rig.venue.calls))
            order = rig.venue.orders[-1]
            order["status"] = "canceled"
            rig.stream.push(update("canceled", order))
            await wait_until(
                lambda: any(e["type"] == "OrderCanceled" for e in record.data["events"])
            )
        else:
            for _ in range(20):
                await asyncio.sleep(0.001)
        handle.stop()
        await task

    asyncio.run(drive())
    assert record.data["session"] == session and record.data["feed"] == feed
    record.data["checks_unchanged_after_run"] = True
    if age_kind == "fresh":
        assert record.problems() == []
        assert rig.venue.last_post["type"] == "limit"
        assert rig.venue.last_post["time_in_force"] == "day"
        assert rig.venue.last_post["extended_hours"] is True
    else:
        assert getattr(rig.venue, "last_post", None) is None
        assert record.problems()


@pytest.mark.parametrize(
    "eligible,halted", [(False, False), (True, True), ("true", False), (True, None)]
)
def test_overnight_ineligible_asset_refused_unsent(node_module, monkeypatch, eligible, halted):
    node, record, rig, quotes, clients = session_build(
        node_module, monkeypatch, SESSIONS[0][0], eligible=eligible, halted=halted
    )
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: any(e["type"] == "OrderDenied" for e in record.data["events"]))
        handle.stop()
        await task

    asyncio.run(drive())
    assert all(method == "get" for method, _ in rig.venue.calls)
    assert record.problems()


@pytest.mark.parametrize("when", ["2026-11-13T20:00:00-05:00", "2026-11-15T19:59:00-05:00"])
def test_lane_closed_window_has_no_order_or_quote_connection(node_module, monkeypatch, when):
    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, when)
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: record.data["startup_reconciliation"]["trader_started"])
        assert not clients["exec"]._submit_admitted()
        handle.stop()
        await task

    asyncio.run(drive())
    assert all(method == "get" for method, _ in rig.venue.calls)
    assert not quotes.subscriptions
    assert record.data["session"] == "closed"


@pytest.mark.parametrize(
    "status",
    [
        "accepted",
        "pending_new",
        "held",
        "suspended",
        "done_for_day",
        "pending_review",
        "accepted_for_bidding",
        "calculated",
        "stopped",
    ],
)
def test_queued_or_inactive_acceptance_never_passes(node_module, monkeypatch, status):
    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, SESSIONS[0][0])
    rig.venue.accept_status = status
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: any(e["type"] == "OrderAccepted" for e in record.data["events"]))
        assert all(method != "delete" for method, _ in rig.venue.calls)
        order = rig.venue.orders[-1]
        order["status"] = "canceled"
        rig.stream.push(update("canceled", order))
        await wait_until(lambda: any(e["type"] == "OrderCanceled" for e in record.data["events"]))
        handle.stop()
        await task

    asyncio.run(drive())
    record.data["checks_unchanged_after_run"] = True
    assert not record.data["venue_working_seen"]
    assert any("working in this session" in problem for problem in record.problems())


def test_queued_order_waits_for_new_before_cancel(node_module, monkeypatch):
    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, SESSIONS[0][0])
    rig.venue.accept_status = "accepted"
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: any(e["type"] == "OrderAccepted" for e in record.data["events"]))
        assert not record.data["venue_working_seen"]
        assert all(method != "delete" for method, _ in rig.venue.calls)
        order = rig.venue.orders[-1]
        order["status"] = "new"
        rig.stream.push(update("new", order))
        await wait_until(lambda: any(method == "delete" for method, _ in rig.venue.calls))
        order["status"] = "canceled"
        rig.stream.push(update("canceled", order))
        await wait_until(lambda: any(e["type"] == "OrderCanceled" for e in record.data["events"]))
        handle.stop()
        await task

    asyncio.run(drive())
    record.data["checks_unchanged_after_run"] = True
    assert record.problems() == []


def test_holiday_calendar_keeps_lane_closed(node_module, monkeypatch):
    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, SESSIONS[0][0])
    get = rig.venue.get
    rig.venue.get = lambda path, *a, **kw: [] if path == "/calendar" else get(path, *a, **kw)
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: record.data["startup_reconciliation"]["trader_started"])
        assert not clients["exec"]._submit_admitted()
        handle.stop()
        await task

    asyncio.run(drive())
    assert not quotes.subscriptions
    assert all(method == "get" for method, _ in rig.venue.calls)
    assert record.data["session"] == "closed"


def test_overnight_asset_permission_rechecked_at_pacer(node_module, monkeypatch):
    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, SESSIONS[0][0])
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        assert rig.pacer is not None
        original = rig.pacer.request

        def delayed(kind, send, **kwargs):
            if kind.name == "SUBMIT":
                monkeypatch.setattr(clients["exec"], "_asset_admitted", lambda _: False)
            return original(kind, send, **kwargs)

        rig.pacer.request = delayed
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: any(e["type"] == "OrderRejected" for e in record.data["events"]))
        handle.stop()
        await task

    asyncio.run(drive())
    assert getattr(rig.venue, "last_post", None) is None


def test_queued_price_cannot_cross_session_at_pacer(node_module, monkeypatch):
    from meridian.alpaca_sessions import session_at

    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, SESSIONS[2][0])
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: bool(quotes.subscriptions))
        assert rig.pacer is not None
        original = rig.pacer.request

        def delayed(kind, send, **kwargs):
            if kind.name == "SUBMIT":
                from datetime import datetime

                later = session_at(datetime.fromisoformat(SESSIONS[3][0]))
                monkeypatch.setattr(clients["exec"], "current_session", lambda: later)
                # Even a refreshed quote does not make the earlier session's price valid.
                monkeypatch.setattr(clients["exec"], "quote_usable", lambda: True)
            return original(kind, send, **kwargs)

        rig.pacer.request = delayed
        quotes.queue.put_nowait(quote(clients["quote"]))
        await wait_until(lambda: any(e["type"] == "OrderRejected" for e in record.data["events"]))
        handle.stop()
        await task

    asyncio.run(drive())
    assert getattr(rig.venue, "last_post", None) is None
    assert record.data["session"] == "regular" and record.data["feed"] == "iex"


# The unattended lane skips, not fails, a run the venue's calendar says is closed; it needs the
# node's `venue_closed`, set only after the calendar was read.
CLOSED_DAYS = [
    # A full holiday: the venue returns no row for the trade date.
    ("2026-11-26T12:00:00-05:00", lambda day: []),
    # An early close, after the close: the weekly window says after hours, the row says closed.
    (
        "2026-11-27T18:00:00-05:00",
        lambda day: [
            {
                "date": day,
                "open": "09:30",
                "close": "13:00",
                "session_open": "0400",
                "session_close": "1700",
            }
        ],
    ),
]


@pytest.mark.parametrize("when,rows", CLOSED_DAYS)
def test_a_venue_closed_day_is_an_unattended_skip(node_module, monkeypatch, when, rows):
    from meridian.alpaca_unattended import venue_closed_skip

    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, when)
    get = rig.venue.get
    rig.venue.get = lambda path, data=None, *a, **kw: (
        rows((data or {})["start"]) if path == "/calendar" else get(path, data, *a, **kw)
    )
    handle = node.handle()

    async def drive():
        task = asyncio.create_task(run(node))
        await wait_until(lambda: record.data["startup_reconciliation"]["trader_started"])
        handle.stop()
        await task

    asyncio.run(drive())
    record.data["checks_unchanged_after_run"] = True
    assert record.data["venue_closed"] is True and record.data["session"] == "closed"
    assert record.data["order"] is None
    assert all(method == "get" for method, _ in rig.venue.calls)
    assert venue_closed_skip(record)


def test_a_calendar_read_that_fails_is_never_a_skip(node_module, monkeypatch):
    from meridian.alpaca_unattended import venue_closed_skip

    node, record, rig, quotes, clients = session_build(node_module, monkeypatch, SESSIONS[2][0])
    get = rig.venue.get

    attempted = []

    def failing(path, *args, **kwargs):
        if path == "/calendar":
            attempted.append(path)
            raise OSError("calendar unavailable")
        return get(path, *args, **kwargs)

    rig.venue.get = failing
    with suppress(Exception):
        asyncio.run(run(node))
    record.data["checks_unchanged_after_run"] = True
    assert attempted  # the read was attempted, and failed
    assert not record.data["startup_reconciliation"]["trader_started"]
    assert "venue_closed" not in record.data
    assert not venue_closed_skip(record)
