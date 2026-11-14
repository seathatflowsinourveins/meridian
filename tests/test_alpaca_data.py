"""Synthetic frames only. No credentials or broker/data network are used."""

import asyncio
import gc
import importlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from alpaca_fakes import AAPL, run
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode, LiveNodeConfig
from nautilus_trader.live.clients import DataClientFactory
from nautilus_trader.model import InstrumentId, TraderId
from nautilus_trader.trading import Strategy

from meridian.alpaca.credentials import PaperKeys, PaperKeysUnavailable
from meridian.alpaca.parsing import parse_equity
from meridian.alpaca.reports import timestamp_ns

STAMP = "2026-11-02T14:30:00.123456789Z"
EVENT = timestamp_ns(STAMP, "synthetic")
# Invented test values; never a calibrated or venue row.
QUOTE = '[{"T":"q","S":"AAPL","bp":100.1234,"ap":100.1235,"bs":3,"as":4,"t":"' + STAMP + '"}]'
EQUITY = parse_equity({"symbol": "AAPL", "class": "us_equity"}, ts_init=EVENT)
KEYS = PaperKeys("synthetic-key-id", "synthetic-secret")


class Socket:
    def __init__(self):
        self.protocol = SimpleNamespace(
            uri=SimpleNamespace(
                secure=True,
                host="stream.data.alpaca.markets",
                port=443,
                path="/v2/iex",
            )
        )
        self.frames = asyncio.Queue()
        self.frames.put_nowait('[{"T":"success","msg":"connected"}]')
        self.sent = []
        self.symbols = set()
        self.closed = False
        self.auto_ack = True

    async def recv(self):
        frame = await self.frames.get()
        if isinstance(frame, Exception):
            raise frame
        return frame

    async def send(self, raw):
        row = json.loads(raw)
        self.sent.append(row["action"])
        if row["action"] == "auth":
            self.frames.put_nowait('[{"T":"success","msg":"authenticated"}]')
        else:
            if row["action"] == "subscribe":
                self.symbols.update(row["quotes"])
            else:
                self.symbols.difference_update(row["quotes"])
            if self.auto_ack:
                self.frames.put_nowait(
                    json.dumps(
                        [
                            {"T": "subscription", "quotes": sorted(self.symbols)},
                        ]
                    )
                )

    async def close(self):
        self.closed = True


@pytest.fixture
def data(monkeypatch):
    # Import here so each test, not just collection, fails when implementation is absent.
    module = importlib.import_module("meridian.alpaca.data")

    async def forbidden(*args, **kwargs):
        raise AssertionError("network is forbidden in tests")

    monkeypatch.setattr(module.websockets, "connect", forbidden)
    from datetime import datetime

    from meridian.alpaca_sessions import session_at

    monkeypatch.setattr(module, "session_ns", lambda _: session_at(datetime.fromisoformat(STAMP)))
    yield module
    gc.collect()


def config(data, **overrides):
    return data.AlpacaQuoteConfig(
        **{
            "universe": [str(AAPL)],
            **overrides,
        }
    )


def rig(data, monkeypatch, socket=None):
    socket = socket or Socket()
    calls = []

    async def connect(url, **kwargs):
        calls.append((url, kwargs))
        return socket

    monkeypatch.setattr(data.websockets, "connect", connect)
    stream = data.AlpacaQuoteStream(KEYS)
    clock = SimpleNamespace(ns=EVENT + 10, timestamp_ns=lambda: clock.ns)
    cache = SimpleNamespace(instrument=lambda iid: EQUITY if iid == AAPL else None)

    class Client(data.AlpacaQuoteClient):
        def create_task(self, coroutine, name="background"):
            return asyncio.create_task(coroutine, name=name)

        def _handle_data(self, tick):
            ticks.append(tick)

    ticks = []
    client = Client(
        name="ALPACA", quote_config=config(data), cache=cache, clock=clock, stream=stream
    )
    return SimpleNamespace(client=client, socket=socket, ticks=ticks, clock=clock, calls=calls)


async def settle():
    # Advance the fake loop only; there is no network or wall-clock wait.
    for _ in range(5):
        await asyncio.sleep(0)


async def subscribed(rig):
    await rig.client._connect()
    await rig.client._subscribe_quotes(SimpleNamespace(instrument_ids=[AAPL]))
    await settle()


def test_subscription_exact_quote_age_and_unsubscribe(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        await subscribed(r)
        assert r.client.quote_age_ns(AAPL) is None
        r.socket.frames.put_nowait(QUOTE)
        await settle()
        (tick,) = r.ticks
        assert tick.instrument_id == AAPL
        assert tick.bid_price.as_decimal() == Decimal("100.1234")
        assert tick.ask_price.as_decimal() == Decimal("100.1235")
        assert tick.bid_size.as_decimal() == tick.ask_size.as_decimal() == 0
        assert tick.ts_event == EVENT and tick.ts_init == EVENT + 10
        assert r.client.quote_age_ns(AAPL) == 10
        r.clock.ns += 100
        assert r.client.quote_age_ns(AAPL) == 110
        await r.client._unsubscribe_quotes(SimpleNamespace(instrument_ids=[AAPL]))
        r.socket.frames.put_nowait(QUOTE)
        await settle()
        assert len(r.ticks) == 1 and r.client.quote_age_ns(AAPL) is None
        assert r.socket.sent == ["auth", "subscribe", "unsubscribe"]
        await r.client._disconnect()
        assert r.socket.closed

    asyncio.run(check())


@pytest.mark.parametrize(
    "bad",
    [
        "not JSON",
        "{}",
        "[]",
        "[null]",
        QUOTE.replace("100.1234", "100.123456"),
        QUOTE.replace("100.1234", "NaN"),
        QUOTE.replace("100.1234", "-1"),
        QUOTE.replace("100.1234", "101.1234"),
        QUOTE.replace('"bs":3', '"bs":-1'),
        QUOTE.replace('"bs":3', '"bs":0.5'),
        QUOTE.replace('"AAPL"', '"MSFT"'),
        QUOTE.replace('"S":"AAPL",', ""),
        QUOTE.replace("2026-11", "2027-11"),
        '[{"T":"error","msg":"synthetic sensitive body"}]',
        '[{"T":"subscription","quotes":["MSFT"]}]',
        ConnectionError("synthetic sensitive body"),
    ],
)
def test_bad_frame_or_loss_latches_failure_and_invalidates_old_quote(data, monkeypatch, bad):
    async def check():
        r = rig(data, monkeypatch)
        await subscribed(r)
        r.socket.frames.put_nowait(QUOTE)
        await settle()
        assert r.client.quote_age_ns(AAPL) is not None
        # Ensure malformed quotes are newer, so this exercises validation not replay filtering.
        frame = bad.replace(".123456789Z", ".123456790Z") if isinstance(bad, str) else bad
        r.socket.frames.put_nowait(frame)
        await settle()
        assert r.client.failure_reason and "sensitive" not in r.client.failure_reason
        assert not r.client.stream_live and r.client.quote_age_ns(AAPL) is None
        assert len(r.ticks) == 1 and r.socket.closed
        with pytest.raises(RuntimeError, match="new client"):
            await r.client._connect()
        await r.client._disconnect()

    asyncio.run(check())


def test_unloaded_or_outside_universe_subscription_is_unsent(data, monkeypatch):
    async def check():
        for iid in [InstrumentId.from_str("MSFT.ALPACA"), AAPL]:
            r = rig(data, monkeypatch)
            if iid == AAPL:
                r.client.cache.instrument = lambda _: None
            await r.client._connect()
            with pytest.raises(RuntimeError, match="subscription failed"):
                await r.client._subscribe_quotes(SimpleNamespace(instrument_ids=[iid]))
            assert r.socket.sent == ["auth"]
            assert not r.client.stream_live
            await r.client._disconnect()

    asyncio.run(check())


def test_replayed_quotes_cannot_refresh_age(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        await subscribed(r)
        r.socket.frames.put_nowait(QUOTE)
        await settle()
        r.clock.ns += 500
        r.socket.frames.put_nowait(QUOTE)
        r.socket.frames.put_nowait(QUOTE.replace(".123456789Z", ".123456788Z"))
        await settle()
        assert len(r.ticks) == 1 and r.client.quote_age_ns(AAPL) == 510
        await r.client._disconnect()

    asyncio.run(check())


def test_quote_before_acknowledgement_is_not_published(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        r.socket.auto_ack = False
        await subscribed(r)
        r.socket.frames.put_nowait(QUOTE)
        await settle()
        assert not r.ticks and r.client.failure_reason
        await r.client._disconnect()

    asyncio.run(check())


@pytest.mark.parametrize(
    "change",
    [
        {"host": "wrong.invalid"},
        {"secure": False},
        {"port": 80},
        {"path": "/v2/sip"},
    ],
)
def test_host_is_pinned_before_authentication(data, monkeypatch, change):
    async def check():
        r = rig(data, monkeypatch)
        for name, value in change.items():
            setattr(r.socket.protocol.uri, name, value)
        with pytest.raises(RuntimeError, match="connection failed"):
            await r.client._connect()
        assert r.socket.closed and r.socket.sent == []
        url, kwargs = r.calls[0]
        assert url == data.DATA_URL
        assert kwargs["host"] == data.DATA_HOST and kwargs["port"] == 443
        assert kwargs["proxy"] is None
        assert kwargs["additional_headers"] == {"Content-Type": "application/json"}

    asyncio.run(check())


def test_factory_refuses_without_credentials_and_opens_nothing(data, monkeypatch):
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    with pytest.raises(PaperKeysUnavailable):
        data.AlpacaQuoteFactory.create(name="ALPACA", config=config(data), cache=None, clock=None)
    made = data.build_quote_client(
        name="ALPACA", config=config(data), cache=None, clock=None, keys=lambda: KEYS
    )
    assert isinstance(made._stream, data.AlpacaQuoteStream)
    assert not made.stream_live


@pytest.mark.parametrize(
    "overrides",
    [
        {"universe": []},
        {"universe": [str(AAPL), str(AAPL)]},
        {"universe": ["AAPL.XNAS"]},
        {"round_lot_sizes": {}},
        {"round_lot_sizes": {str(AAPL): 0}},
        {"round_lot_sizes": {str(AAPL): True}},
        {"feed": "sip"},
    ],
)
def test_config_refuses_invalid_or_paid_feed_choices(data, overrides):
    with pytest.raises((ValueError, TypeError)):
        config(data, **overrides)


@pytest.mark.parametrize(
    "when,feed",
    [
        ("2026-11-02T07:00:00Z", "overnight"),
        ("2026-11-02T13:00:00Z", "delayed_sip"),
        ("2026-11-02T17:00:00Z", "iex"),
        ("2026-11-02T23:00:00Z", "delayed_sip"),
    ],
)
def test_quote_reaches_real_engine_cache_and_strategy(data, monkeypatch, when, feed):
    from datetime import datetime

    from meridian.alpaca_sessions import session_at

    monkeypatch.setattr(data, "session_ns", lambda _: session_at(datetime.fromisoformat(when)))
    frame = QUOTE.replace(STAMP, when)
    seen = []
    socket = Socket()
    socket.protocol.uri.path = data.FEED_PATHS[feed]
    original_send = socket.send

    async def send(raw):
        await original_send(raw)
        if json.loads(raw)["action"] == "subscribe":
            socket.frames.put_nowait(frame)

    socket.send = send

    async def connect(*args, **kwargs):
        return socket

    monkeypatch.setattr(data.websockets, "connect", connect)

    class Client(data.AlpacaQuoteClient):
        async def _connect(self):
            self._handle_instrument(EQUITY)
            await super()._connect()

    class Factory(DataClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock):
            return Client(
                name=name,
                quote_config=config,
                cache=cache,
                clock=clock,
                stream=data.AlpacaQuoteStream(KEYS),
            )

    class Observer(Strategy):
        def on_start(self):
            self.subscribe_quotes(AAPL)

        def on_quote(self, quote):
            seen.append(quote)
            self.shutdown_system("synthetic quote received")

    node = LiveNode.build(
        "M3-DATA-TEST",
        LiveNodeConfig(
            environment=Environment.LIVE,
            trader_id=TraderId("M3-DATA-TEST"),
            data_clients={"ALPACA": config(data)},
            delay_post_stop_secs=0,
        ),
        data_factories={"ALPACA": Factory},
    )
    node.add_strategy(Observer())
    assert asyncio.run(run(node)) is None
    assert len(seen) == 1
    tick = node.cache.quote(AAPL)
    assert tick is not None and tick.bid_price.as_decimal() == Decimal("100.1234")
    assert seen[0].ts_event == timestamp_ns(when, "synthetic")


def test_json_decimal_text_survives_values_beyond_float_precision(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        await subscribed(r)
        frame = QUOTE.replace("100.1234", "1234567890123.1234").replace(
            "100.1235", "1234567890123.1235"
        )
        r.socket.frames.put_nowait(frame)
        await settle()
        (tick,) = r.ticks
        assert tick.bid_price.as_decimal() == Decimal("1234567890123.1234")
        assert tick.ask_price.as_decimal() == Decimal("1234567890123.1235")
        await r.client._disconnect()

    asyncio.run(check())


@pytest.mark.parametrize("action", ["subscribe", "unsubscribe"])
def test_failed_subscription_send_invalidates_data(data, monkeypatch, action):
    async def check():
        r = rig(data, monkeypatch)
        if action == "unsubscribe":
            await subscribed(r)
            r.socket.frames.put_nowait(QUOTE)
            await settle()
            assert r.client.quote_age_ns(AAPL) is not None
        else:
            await r.client._connect()

        async def fail(raw):
            raise ConnectionError("synthetic body")

        r.socket.send = fail
        method = getattr(r.client, "_" + action + "_quotes")
        with pytest.raises(RuntimeError):
            await method(SimpleNamespace(instrument_ids=[AAPL]))
        assert r.client.quote_age_ns(AAPL) is None and r.client.failure_reason
        await r.client._disconnect()

    asyncio.run(check())


def test_basic_plan_symbol_cap(data):
    universe = [f"S{i}.ALPACA" for i in range(31)]
    with pytest.raises(ValueError, match="30"):
        config(data, universe=universe)


@pytest.mark.parametrize("sizes", [(0, 0), (3, 4), (999999, 1)])
def test_quote_sizes_are_not_carried_whatever_the_frame_says(data, monkeypatch, sizes):
    async def check():
        r = rig(data, monkeypatch)
        await subscribed(r)
        frame = QUOTE.replace('"bs":3', f'"bs":{sizes[0]}').replace('"as":4', f'"as":{sizes[1]}')
        r.socket.frames.put_nowait(frame)
        await settle()
        (tick,) = r.ticks
        assert tick.bid_size.as_decimal() == tick.ask_size.as_decimal() == 0
        assert tick.bid_size.precision == tick.ask_size.precision == EQUITY.size_precision
        assert tick.bid_price.as_decimal() == Decimal("100.1234")
        await r.client._disconnect()

    asyncio.run(check())


def test_price_only_config_needs_no_size_conversion(data):
    assert data.AlpacaQuoteConfig(universe=[str(AAPL)]).universe == (AAPL,)
