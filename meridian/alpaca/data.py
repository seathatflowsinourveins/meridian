"""Session-selected prices only, after rc9's examples/live/_template/data.py; no REST calls.

Alpaca's market-data-faq (read 2026-11-13) assigns regular users, including paper
credentials, stream.data.alpaca.markets; its sandbox is for broker partners.
Free overnight quotes are real-time indicative; pre/after-market uses delayed
SIP. See alpaca_sessions.py and UPSTREAM.md (24/5 pages, read 2026-11-13).

alpaca-py 0.45.0's StockDataStream supplies configuration and quote dispatch. Its
MsgPack decoder and typed Quote use floats, so the wire hooks below use Alpaca's
documented JSON protocol with decimal text. Its blocking subscription helpers
are used only to register handlers; sends are awaited on the engine loop.
Quote sizes are validated then dropped: Alpaca documents round lots but its
Asset model has no per-symbol shares per lot (official models.html#asset and
real-time-stock-pricing-data, read 2026-11-13; URLs in UPSTREAM.md). Ticks carry
zero sizes as UNKNOWN, never measured zero liquidity; no consumer may use sizes.
This follows NautilusTrader v2.0.0rc9, crates/adapters/coinapi/src/websocket/
messages.rs:239 and parse.rs:156-165, and interactive_brokers/src/data/parse.rs:
98-105. crates/model/src/data/quote.rs:75-105 allows zero quantities with matching
precision. These tagged sources were read 2026-11-13.
There is no SDK reconnect loop: any loss or unreadable/unmapped frame latches a
failure. A lane must check quote_age_ns before using the engine's cached quote.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import websockets
from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream
from nautilus_trader.config import DataClientConfig
from nautilus_trader.live.clients import DataClientFactory, MarketDataClient
from nautilus_trader.model import Equity, InstrumentId, Price, Quantity, QuoteTick

from meridian.alpaca_sessions import SIP_DELAY_NS, Session, session_ns

from .constants import VENUE
from .credentials import PaperKeys, load_paper_keys
from .reports import decimal_text, timestamp_ns

DATA_HOST = "stream.data.alpaca.markets"
DATA_URL = "wss://stream.data.alpaca.markets/v2/iex"
FEED_PATHS = {"iex": "/v2/iex", "overnight": "/v1beta1/overnight", "delayed_sip": "/v2/delayed_sip"}
# Basic equities websocket limit: about-market-data-api (read 2026-11-13).
MAX_SYMBOLS = 30
# Authentication must finish within 10 seconds: streaming-market-data, same date.
AUTH_TIMEOUT = 10


class AlpacaQuoteConfig(DataClientConfig):
    """Prices only; sizes are not carried and no consumer may use tick sizes.

    Instruments must already be loaded by the execution client's budgeted reads.
    """

    def __init__(self, *, universe: list[str], **kwargs: Any) -> None:
        if set(kwargs) - {"instrument_provider", "routing"}:
            raise TypeError("unexpected quote configuration field")
        ids = [InstrumentId.from_str(value) for value in universe]
        if not 0 < len(ids) <= MAX_SYMBOLS or len(set(ids)) != len(ids):
            raise ValueError("quote universe must contain 1 to 30 distinct instruments")
        if any(
            i.venue != VENUE or not re.fullmatch(r"[A-Z][A-Z0-9.-]*", i.symbol.value) for i in ids
        ):
            raise ValueError("quote universe requires ALPACA equity symbols")
        self.universe = tuple(ids)


def decode_frame(raw: Any) -> list[dict]:
    """Keep JSON numbers as text; refuse malformed envelopes and nonstandard numbers."""

    def invalid(_: str) -> None:
        raise ValueError("nonstandard JSON number")

    rows = json.loads(raw, parse_float=str, parse_int=str, parse_constant=invalid)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid quote frame envelope")
    return rows


class AlpacaQuoteStream(StockDataStream):
    """The pinned SDK stream, JSON wire hooks, and no threaded or automatic runner."""

    def __init__(self, keys: PaperKeys) -> None:
        super().__init__(
            keys.key_id,
            keys.secret_key,
            raw_data=True,
            feed=DataFeed.IEX,
            url_override=DATA_URL,
        )
        self.feed = "iex"
        # Keep the pinned SDK's ping defaults. Explicit host/port prevent cross-origin
        # redirects in locked websockets; disable environment proxy discovery.
        self._pinned_params: dict[str, Any] = {
            **self._websocket_params,
            "host": DATA_HOST,
            "port": 443,
            "proxy": None,
        }

    def select_feed(self, feed: str) -> None:
        if feed not in FEED_PATHS:
            raise ValueError("unsupported quote feed")
        self.feed = feed
        self._endpoint = "wss://" + DATA_HOST + FEED_PATHS[feed]

    async def _connect(self) -> None:
        endpoint = "wss://" + DATA_HOST + FEED_PATHS[self.feed]
        if self._endpoint != endpoint:
            raise ConnectionError("quote endpoint changed")
        self._ws = await websockets.connect(
            endpoint,
            additional_headers={"Content-Type": "application/json"},
            **self._pinned_params,
        )
        uri = getattr(getattr(self._ws, "protocol", None), "uri", None)
        if (
            uri is None
            or not uri.secure
            or uri.host != DATA_HOST
            or uri.port != 443
            or uri.path != FEED_PATHS[self.feed]
        ):
            await self.close()
            raise ConnectionError("quote stream host or feed mismatch")
        if decode_frame(await self._ws.recv()) != [{"T": "success", "msg": "connected"}]:
            raise ConnectionError("quote stream welcome refused")

    async def _auth(self) -> None:
        await self._ws.send(
            json.dumps(
                {
                    "action": "auth",
                    "key": self._api_key,
                    "secret": self._secret_key,
                }
            )
        )
        if decode_frame(await self._ws.recv()) != [{"T": "success", "msg": "authenticated"}]:
            raise ConnectionError("quote stream authentication refused")

    async def subscribe(self, handler: Any, symbols: list[str]) -> None:
        # _running remains False: the SDK only registers here, never blocks this loop.
        self.subscribe_quotes(handler, *symbols)
        await self._ws.send(json.dumps({"action": "subscribe", "quotes": symbols}))

    async def unsubscribe(self, symbols: list[str]) -> None:
        self.unsubscribe_quotes(*symbols)
        await self._ws.send(json.dumps({"action": "unsubscribe", "quotes": symbols}))

    async def receive(self) -> list[dict]:
        return decode_frame(await self._ws.recv())


class AlpacaQuoteClient(MarketDataClient):
    """One stream; failed data stays unusable until a new client is constructed."""

    def __init__(
        self, *, quote_config: AlpacaQuoteConfig, stream: AlpacaQuoteStream, **kwargs: Any
    ):
        super().__init__(config=quote_config, venue=VENUE, **kwargs)
        self._config = quote_config
        self._stream = stream
        self._universe = {i.symbol.value: i for i in quote_config.universe}
        self._subscribed: set[str] = set()
        self._acknowledged: set[str] = set()
        self._pending: list[set[str]] = []
        self._last: dict[InstrumentId, int] = {}
        self._received: dict[InstrumentId, int] = {}
        self.session: Session | None = None
        self.session_now: Callable[[], Session | None] = lambda: session_ns(
            self.clock.timestamp_ns()
        )
        self._switch_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.failure_reason: str | None = None
        self.stream_live = False

    def quote_age_ns(self, instrument_id: InstrumentId) -> int | None:
        """Event age, or None if absent, unsubscribed, unacknowledged or failed.

        No freshness threshold is invented here. The attended lane must compare
        this age with its own sourced limit; engine cache presence is insufficient.
        """
        stamp = self._last.get(instrument_id)
        if (
            not self.stream_live
            or self.session != self.session_now()
            or self.failure_reason
            or stamp is None
            or instrument_id.symbol.value not in self._acknowledged
            or instrument_id.symbol.value not in self._subscribed
        ):
            return None
        age = self.clock.timestamp_ns() - stamp
        if age < 0:
            return None
        delay = SIP_DELAY_NS if self.session and self.session.feed == "delayed_sip" else 0
        return max(age, delay + self.clock.timestamp_ns() - self._received[instrument_id])

    def _fail(self, reason: str) -> None:
        self.failure_reason = self.failure_reason or reason
        self.stream_live = False
        self._acknowledged.clear()

    async def _connect(self) -> None:
        if self.failure_reason:
            raise RuntimeError("quote client failed; construct a new client")
        try:
            await self._switch_session()
            self._task = self.create_task(self._read(), "alpaca-quotes")
        except asyncio.CancelledError:
            self._fail("quote stream connection cancelled")
            await self._stream.close()
            raise
        except Exception:
            self._fail("quote stream connection failed")
            await self._stream.close()
            raise RuntimeError(self.failure_reason) from None

    @property
    def feed(self) -> str | None:
        return None if self.session is None else self.session.feed

    async def _switch_session(self) -> None:
        async with self._switch_lock:
            current = self.session_now()
            if self.session == current and (self.stream_live or current is None):
                return
            self.stream_live = False
            self.session = current  # Invalidate a receive before closing its old socket.
            self._last.clear()
            self._received.clear()
            self._acknowledged.clear()
            self._pending.clear()
            await self._stream.close()
            if current is None:
                return
            self._stream.select_feed(current.feed)
            async with asyncio.timeout(AUTH_TIMEOUT):
                await self._stream._start_ws()
            self.stream_live = True
            if self._subscribed:
                self._pending.append(set(self._subscribed))
                await self._stream.subscribe(self._on_quote, sorted(self._subscribed))

    async def _disconnect(self) -> None:
        self.stream_live = False
        self._acknowledged.clear()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._stream.close()
        self._last.clear()
        self._subscribed.clear()
        self._pending.clear()

    async def _subscribe_quotes(self, command: Any) -> None:
        try:
            if self.failure_reason:
                raise ValueError("quote stream unavailable")
            if self.session != self.session_now():
                await self._switch_session()
            ids = command.instrument_ids
            if any(i not in self._config.universe for i in ids):
                raise ValueError("instrument outside quote universe")
            for iid in ids:
                instrument = self.cache.instrument(iid)
                if (
                    not isinstance(instrument, Equity)
                    or instrument.raw_symbol.value != iid.symbol.value
                ):
                    raise ValueError("quote instrument not loaded")
            symbols = sorted({i.symbol.value for i in ids} - self._subscribed)
            if symbols:
                self._subscribed.update(symbols)
                if self.stream_live:
                    self._pending.append(set(self._subscribed))
                    await self._stream.subscribe(self._on_quote, symbols)
        except Exception:
            self._fail("quote subscription failed")
            raise RuntimeError(self.failure_reason) from None

    async def _unsubscribe_quotes(self, command: Any) -> None:
        symbols = sorted({i.symbol.value for i in command.instrument_ids} & self._subscribed)
        for symbol in symbols:
            self._last.pop(self._universe[symbol], None)
        self._subscribed.difference_update(symbols)
        self._acknowledged.difference_update(symbols)
        if symbols and self.stream_live:
            try:
                self._pending.append(set(self._subscribed))
                await self._stream.unsubscribe(symbols)
            except Exception:
                self._fail("quote unsubscribe failed")
                raise RuntimeError(self.failure_reason) from None

    async def _read(self) -> None:
        try:
            while not self.failure_reason:
                if self.session != self.session_now():
                    await self._switch_session()
                if not self.stream_live:
                    await asyncio.sleep(1)
                    continue
                receiving_session = self.session
                timeout = asyncio.timeout(1)
                try:
                    async with timeout:
                        rows = await self._stream.receive()
                except TimeoutError:
                    if timeout.expired():
                        continue
                    raise  # A transport timeout is a failure, not the session poll timer.
                except Exception:
                    if self.session != receiving_session:
                        continue  # A subscription changed sessions and closed that socket.
                    raise
                if self.session != receiving_session or self.session != self.session_now():
                    continue  # Never publish a frame from the previous session.
                for row in rows:
                    if row.get("T") == "subscription":
                        symbols = row.get("quotes")
                        if (
                            not isinstance(symbols, list)
                            or not all(isinstance(s, str) for s in symbols)
                            or not self._pending
                            or set(symbols) != self._pending.pop(0)
                        ):
                            raise ValueError("quote subscription acknowledgement mismatch")
                        self._acknowledged = set(symbols) & self._subscribed
                    elif row.get("T") == "q" and row.get("S") in self._universe:
                        # A queued quote after unsubscribe is ignored, never freshened.
                        if row["S"] in self._subscribed:
                            if row["S"] not in self._acknowledged:
                                raise ValueError("quote before subscription acknowledgement")
                            await self._stream._dispatch(row)
                    else:
                        raise ValueError("unmapped quote stream message")
        except asyncio.CancelledError:
            if self.stream_live:
                self._fail("quote stream reader cancelled")
            raise
        except Exception:
            self._fail("quote stream lost or unreadable/unmapped frame")
        finally:
            self.stream_live = False
            await self._stream.close()

    async def _on_quote(self, row: Any) -> None:
        if self.failure_reason or not self.stream_live or self.session != self.session_now():
            return
        iid = self._universe[row["S"]]
        instrument = self.cache.instrument(iid)
        if not isinstance(instrument, Equity):
            raise ValueError("quote instrument unavailable")
        now = self.clock.timestamp_ns()
        event = timestamp_ns(row.get("t"), "quote timestamp")
        if event <= 0 or event > now:
            raise ValueError("invalid quote time")
        if self.session is None or event < int(self.session.start.timestamp()) * 1_000_000_000:
            return  # Old session quotes cannot authorize an order, even with a large age limit.
        prices = [decimal_text(row.get(key), key) for key in ("bp", "ap")]
        if any(value <= 0 for value in prices) or prices[0] > prices[1]:
            raise ValueError("invalid quote prices")
        bid, ask = [Price.from_decimal_dp(p, instrument.price_precision) for p in prices]
        if [bid.as_decimal(), ask.as_decimal()] != prices:
            raise ValueError("quote price loses precision")
        sizes = [decimal_text(row.get(key), key) for key in ("bs", "as")]
        if any(s < 0 or s != s.to_integral_value() for s in sizes):
            raise ValueError("invalid quote round-lot sizes")
        # Upstream's unknown-size convention, not a conversion or liquidity estimate.
        unknown = Quantity.from_decimal_dp(Decimal(0), instrument.size_precision)
        if event <= self._last.get(iid, 0):
            return  # replayed/out-of-order quotes do not refresh the last event
        self._last[iid] = event
        self._received[iid] = now
        self._handle_data(QuoteTick(iid, bid, ask, unknown, unknown, event, now))


class AlpacaQuoteFactory(DataClientFactory):
    """Loads the same systemd credentials as execution; construction opens no socket."""

    @staticmethod
    def create(*, name, config, cache, clock) -> AlpacaQuoteClient:
        return build_quote_client(name=name, config=config, cache=cache, clock=clock)


def build_quote_client(
    *,
    name: str,
    config: Any,
    cache: Any,
    clock: Any,
    keys: Callable[[], PaperKeys] = load_paper_keys,
    stream: Callable[[PaperKeys], AlpacaQuoteStream] = AlpacaQuoteStream,
) -> AlpacaQuoteClient:
    if not isinstance(config, AlpacaQuoteConfig):
        raise TypeError("expected AlpacaQuoteConfig")
    return AlpacaQuoteClient(
        name=name,
        quote_config=config,
        cache=cache,
        clock=clock,
        stream=stream(keys()),
    )
