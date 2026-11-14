"""Alpaca lane wiring and lifecycle against synthetic venue and quote streams."""

import asyncio
import gc
import importlib
from types import SimpleNamespace
from typing import Any, cast

import pytest
from alpaca_fakes import Rig, fill_activity, order_row, position_row, run, update
from nautilus_trader.core import unix_nanos_to_iso8601
from nautilus_trader.model import ClientOrderId, OrderSide, Price, Quantity


@pytest.fixture
def node_module(monkeypatch):
    module = importlib.import_module("meridian.alpaca_node")
    real_config = module.LiveNodeConfig
    monkeypatch.setattr(
        module, "LiveNodeConfig", lambda **kw: real_config(**kw, delay_post_stop_secs=0)
    )
    # Never construct a real credential reader or network transport in these tests.
    monkeypatch.setattr(module, "production_wiring", lambda *_: pytest.fail("production wiring"))
    yield module
    gc.collect()


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


def build(module, monkeypatch, mode="order", rig=None):
    from meridian.alpaca.data import AlpacaQuoteClient
    from meridian.alpaca_lane import RunRecord

    rig = rig or Rig()
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
        client = original(**kwargs)
        captured["exec"] = client
        return client

    monkeypatch.setattr(module, "build_client", execution)
    monkeypatch.setattr(module, "production_wiring", lambda *_: None)

    def quote_factory(*, name, config, cache, clock):
        client = AlpacaQuoteClient(
            name=name, quote_config=config, cache=cache, clock=clock, stream=cast(Any, quotes)
        )
        captured["quote"] = client
        return client

    monkeypatch.setattr(module.AlpacaQuoteFactory, "create", quote_factory)
    record = RunRecord(mode, state())
    node = module.build(state(), record)
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
