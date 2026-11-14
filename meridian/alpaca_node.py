"""Engine side of the attended Alpaca lane; own design, built on rc9's example.

Reuses the vendored IbV2OrderStrategy's once-only quote trigger and DAY LIMIT
constructor through OneDayLimit. Its IB callbacks and environment-driven init
are replaced here, so no IB route or environment setting enters this node.
The upstream quote trigger reads only instrument_id, never bid_size/ask_size.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

import nautilus_trader
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode, LiveNodeConfig
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import (
    ClientId,
    ClientOrderId,
    InstrumentId,
    OrderSide,
    Price,
    Quantity,
    StrategyId,
    TraderId,
)
from nautilus_trader.trading import Strategy, StrategyConfig

from meridian import boundary
from meridian.alpaca.config import AlpacaPaperExecClientConfig
from meridian.alpaca.data import AlpacaQuoteConfig, AlpacaQuoteFactory
from meridian.alpaca.execution import AlpacaPaperExecutionClient
from meridian.alpaca.factories import build_client, production_wiring
from meridian.alpaca.reconcile import engine_config
from meridian.alpaca_lane import INSTRUMENT, Preflight, RunRecord
from meridian.ibkr_node import (
    AUTO_STOP_SECONDS,
    LIMIT_UNDER_BID,
    ORDER_QTY,
    OneDayLimit,
    _output_to,
)

INSTRUMENT_ID = InstrumentId.from_str(INSTRUMENT)
CLIENT_ID = ClientId("ALPACA")
HOUSE_PREFIX = "MERIDIAN-M3-"
# An engine-local label, never the broker's account identifier.
ENGINE_ACCOUNT = "ALPACA-PAPER"


class LaneExecutionClient(AlpacaPaperExecutionClient):
    """The mode and freshness guards also run when the pacer releases a submit."""

    record: RunRecord
    quote_usable: Callable[[], bool]

    def _submit_admitted(self) -> bool:
        return (
            self.record.data["mode"] == "order"
            and self.quote_usable()
            and super()._submit_admitted()
        )

    async def _submit_order(self, command: Any) -> None:
        if self.record.data["mode"] != "order":
            self.record.order_refused("restart cannot submit")
        await super()._submit_order(command)

    async def _cancel_order(self, command: Any) -> None:
        if self.record.data["mode"] != "order":
            self.record.order_refused("restart cannot cancel")
            return
        await super()._cancel_order(command)


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


def build(state: Preflight, record: RunRecord) -> LiveNode:
    """Build only; production constructors do not connect until run_async."""
    clients: dict[str, Any] = {}

    def usable() -> bool:
        quote = clients.get("quote")
        age = None if quote is None else quote.quote_age_ns(INSTRUMENT_ID)
        return type(age) is int and 0 <= age < state.settings.quote_max_age_ns

    class QuoteFactory(DataClientFactory):
        @staticmethod
        def create(**kwargs):
            client = AlpacaQuoteFactory.create(**kwargs)
            clients["quote"] = client
            return client

    class ExecFactory(ExecutionClientFactory):
        @staticmethod
        def create(**kwargs):
            client = build_client(
                **kwargs,
                wiring=production_wiring(kwargs["config"]),
                client_type=LaneExecutionClient,
            )
            assert isinstance(client, LaneExecutionClient)
            client.record = record
            client.quote_usable = usable
            clients["execution"] = client
            return client

    config = AlpacaPaperExecClientConfig.for_paper_equities(
        account_id=ENGINE_ACCOUNT,
        house_prefix=HOUSE_PREFIX,
        universe=[INSTRUMENT],
        order_budget_rows_path=state.settings.rows_path,
    )
    node = LiveNode.build(
        "MERIDIAN-ALPACA-PAPER",
        LiveNodeConfig(
            environment=Environment.LIVE,
            trader_id=TraderId("MERIDIAN-M3"),
            exec_engine=engine_config([INSTRUMENT_ID]),
            exec_clients={"ALPACA": config},
            data_clients={"ALPACA": AlpacaQuoteConfig(universe=[INSTRUMENT])},
        ),
        exec_factories={"ALPACA": ExecFactory},
        data_factories={"ALPACA": QuoteFactory},
    )
    strategy = OnePaperOrder()
    strategy._record = record
    strategy.quote_usable = usable
    strategy.execution_healthy = lambda: bool(
        clients.get("execution") is not None
        and clients["execution"].coverage_complete
        and not clients["execution"].foreign_writer_seen
    )
    node.add_strategy(strategy)
    record.data["engine"] = {"nautilus_trader": nautilus_trader.__version__}
    return node


async def run_until_stop(node: Any, seconds: int) -> None:
    handle = node.handle()

    async def stop_later():
        await asyncio.sleep(seconds)
        handle.stop()

    timer = asyncio.create_task(stop_later())
    try:
        await node.run_async()
    finally:
        timer.cancel()
        await asyncio.gather(timer, return_exceptions=True)


def run(state: Preflight, record: RunRecord) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = boundary.REPO_ROOT / "runs" / f"M3-alpaca-paper-{stamp}-{record.data['mode']}-engine.log"
    # Catch and report only fixed text, including build errors and interruption.
    try:
        with _output_to(path):
            try:
                node = build(state, record)
                asyncio.run(run_until_stop(node, AUTO_STOP_SECONDS[record.data["mode"]]))
            except Exception, KeyboardInterrupt:
                record.engine_error("node failed or interrupted; inspect the local engine log")
    except OSError:
        record.engine_error("engine log unavailable")
