"""
An offline stand-in for the Interactive Brokers data client, to test the sandbox lane.

It plays the IB data client's part and nothing more:

- it is added under the same name as IB's data client and reports no venue, so the data
  engine makes it the default data client, as upstream's IB data client does;
- it loads AAPL.XNAS through an instrument provider configured with ``load_ids``, the way the
  lane configures IB's provider, and builds the Equity the way IB's provider builds a stock
  (tick 0.01, price precision 2, lot size 100, USD);
- after a quote subscription it streams quotes for that instrument on the node's event loop.

It opens no socket and imports nothing from the IB adapter. A data client never receives
trading commands, so nothing here can place an order anywhere.

Engine contract (nautilus_trader 2.0.0rc9, ``nautilus_trader/live/clients.py``):
``MarketDataClient`` and ``DataClientFactory``; instruments reach the core through
``_handle_instrument``, market data through ``_handle_data``, request replies through
``_handle_response``, and background work runs through ``self.create_task``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.config import DataClientConfig, InstrumentProviderConfig
from nautilus_trader.live import InstrumentResponse
from nautilus_trader.live.clients import DataClientFactory, MarketDataClient
from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import Currency, Equity, InstrumentId, Price, Quantity, QuoteTick, Symbol

INSTRUMENT_ID = InstrumentId.from_str("AAPL.XNAS")
USD = Currency.from_str("USD")
# A small, repeating walk of the mid, in ticks: the market moves a little and never crosses.
WALK_TICKS = (0, 1, 2, 1, 0, -1, -2, -1)
BID, ASK, SIZE, INTERVAL_S = 229.99, 230.01, 300, 0.25


def aapl_equity(ts_ns: int) -> Equity:
    """AAPL.XNAS shaped like the IB provider's output for a SMART/NASDAQ stock."""
    return Equity(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=Symbol("AAPL"),
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        lot_size=Quantity.from_int(100),
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


class FakeEquityProvider(InstrumentProvider):
    """Knows AAPL.XNAS only, and refuses any other id, as a failed IB contract lookup does."""

    def __init__(self, config: Any, clock: Any) -> None:
        super().__init__(config)
        self._clock = clock

    async def load_all_async(self, filters: dict | None = None) -> None:
        self.add(aapl_equity(self._clock.timestamp_ns()))

    async def load_ids_async(
        self, instrument_ids: list[InstrumentId], filters: dict | None = None
    ) -> None:
        unknown = [str(i) for i in instrument_ids if i != INSTRUMENT_ID]
        if unknown:
            raise ValueError(f"the fake provider has no contract for {unknown}")
        await super().load_ids_async(instrument_ids, filters)


class FakeQuoteDataClient(MarketDataClient):
    """Publishes its instrument on connect, then quotes once a strategy subscribes."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._quoting: set[InstrumentId] = set()
        self._tasks: list[asyncio.Task[Any]] = []

    @property
    def provider(self) -> InstrumentProvider:
        provider = self.instrument_provider
        if provider is None:
            raise RuntimeError("the fake data client needs an instrument provider")
        return provider

    async def _connect(self) -> None:
        await self.provider.initialize()
        for instrument in self.provider.list_all():
            self._handle_instrument(instrument)

    async def _disconnect(self) -> None:
        self._quoting.clear()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _subscribe_quotes(self, command: Any) -> None:
        for instrument_id in command.instrument_ids:
            if instrument_id in self._quoting or self.provider.find(instrument_id) is None:
                continue
            self._quoting.add(instrument_id)
            self._tasks.append(
                self.create_task(self._stream(instrument_id), f"quotes:{instrument_id}")
            )

    async def _unsubscribe_quotes(self, command: Any) -> None:
        for instrument_id in command.instrument_ids:
            self._quoting.discard(instrument_id)

    async def _subscribe_trades(self, command: Any) -> None:
        pass  # no trades in this feed; accepted so a strategy that asks does not fail

    async def _unsubscribe_trades(self, command: Any) -> None:
        pass

    async def _subscribe_instrument(self, command: Any) -> None:
        for instrument_id in command.instrument_ids:
            instrument = self.provider.find(instrument_id)
            if instrument is not None:
                self._handle_instrument(instrument)

    async def _unsubscribe_instrument(self, command: Any) -> None:
        pass

    async def _request_instrument(self, request: Any) -> None:
        instrument = self.provider.find(request.instrument_id)
        if instrument is None:
            raise ValueError(f"no instrument {request.instrument_id}")
        self._handle_response(
            InstrumentResponse(
                client_id=self.client_id,
                instrument_id=request.instrument_id,
                data=instrument,
                correlation_id=request.request_id,
                ts_init=self.clock.timestamp_ns(),
                start=request.start_ns,
                end=request.end_ns,
                params=request.params,
            )
        )

    async def _stream(self, instrument_id: InstrumentId) -> None:
        instrument: Any = self.provider.find(instrument_id)  # an Equity; the stub says object
        assert instrument is not None
        tick = instrument.price_increment.as_double()
        precision = instrument.price_precision
        size = Quantity(SIZE, 0)  # an Equity's size precision is 0; the sandbox drops others
        n = 0
        try:
            while instrument_id in self._quoting:
                shift = WALK_TICKS[n % len(WALK_TICKS)] * tick
                ts = self.clock.timestamp_ns()
                self._handle_data(
                    QuoteTick(
                        instrument_id=instrument_id,
                        bid_price=Price(BID + shift, precision),
                        ask_price=Price(ASK + shift, precision),
                        bid_size=size,
                        ask_size=size,
                        ts_event=ts,
                        ts_init=ts,
                    )
                )
                n += 1
                await asyncio.sleep(INTERVAL_S)
        except asyncio.CancelledError:
            pass


class FakeQuoteDataClientFactory(DataClientFactory):
    """Builds the fake client from the node's context. Starts no work and opens nothing."""

    @staticmethod
    def create(*, name: Any, config: Any, cache: Any, clock: Any) -> FakeQuoteDataClient:
        return FakeQuoteDataClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            venue=None,
            instrument_provider=FakeEquityProvider(config.instrument_provider, clock),
        )


def fake_data_client(name: str) -> tuple[str, Any, Any]:
    """The (name, factory, config) the lane would otherwise build for IB's data client."""
    config = DataClientConfig(
        instrument_provider=InstrumentProviderConfig(load_ids=[str(INSTRUMENT_ID)])
    )
    return name, FakeQuoteDataClientFactory, config
