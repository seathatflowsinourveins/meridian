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
from typing import Any

import nautilus_trader
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode, LiveNodeConfig
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import TraderId

from meridian import boundary
from meridian.alpaca.config import AlpacaPaperExecClientConfig
from meridian.alpaca.data import AlpacaQuoteConfig, AlpacaQuoteFactory
from meridian.alpaca.execution import AlpacaPaperExecutionClient
from meridian.alpaca.factories import build_client, production_wiring
from meridian.alpaca.reconcile import engine_config
from meridian.alpaca_lane import INSTRUMENT, Preflight, RunRecord
from meridian.alpaca_strategy import HOUSE_PREFIX, INSTRUMENT_ID
from meridian.alpaca_strategy import OnePaperOrder as OnePaperOrder
from meridian.ibkr_node import AUTO_STOP_SECONDS, _output_to

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
