"""Engine side of the attended Alpaca lane; own design, built on rc9's example.

Reuses the vendored IbV2OrderStrategy's once-only quote trigger and DAY LIMIT
constructor through OneDayLimit. Its IB callbacks and environment-driven init
are replaced here, so no IB route or environment setting enters this node.
The upstream quote trigger reads only instrument_id, never bid_size/ask_size.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import nautilus_trader
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode, LiveNodeConfig
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import ClientOrderId, TraderId

from meridian import boundary
from meridian.alpaca.budget import ActionKind
from meridian.alpaca.config import AlpacaPaperExecClientConfig
from meridian.alpaca.data import AlpacaQuoteConfig, AlpacaQuoteFactory
from meridian.alpaca.execution import AlpacaPaperExecutionClient
from meridian.alpaca.factories import build_client, production_wiring
from meridian.alpaca.reconcile import engine_config
from meridian.alpaca_lane import INSTRUMENT, Preflight, RunRecord
from meridian.alpaca_sessions import Session, session_ns
from meridian.alpaca_strategy import HOUSE_PREFIX, INSTRUMENT_ID
from meridian.alpaca_strategy import OnePaperOrder as OnePaperOrder
from meridian.ibkr_node import AUTO_STOP_SECONDS, _output_to

# An engine-local label, never the broker's account identifier.
ENGINE_ACCOUNT = "ALPACA-PAPER"


class LaneExecutionClient(AlpacaPaperExecutionClient):
    """The mode and freshness guards also run when the pacer releases a submit."""

    record: RunRecord
    quote_usable: Callable[[], bool]

    calendar: dict[date, dict] | None = None
    working_orders: set[str]
    working_callback: Callable[[ClientOrderId], None]

    def current_session(self) -> Session | None:
        return session_ns(self.clock.timestamp_ns(), self.calendar or {})

    async def _connect(self) -> None:
        await super()._connect()
        window = session_ns(self.clock.timestamp_ns())
        self.calendar = {}
        if window is not None:
            day = window.trade_date
            end = day + timedelta(days=1)
            rows = await self._call(
                ActionKind.QUERY,
                "get",
                "/calendar",
                {"start": day.isoformat(), "end": end.isoformat()},
            )
            if not isinstance(rows, list) or len(rows) > 2:
                raise ValueError("invalid lane calendar")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("date"), str):
                    raise ValueError("invalid lane calendar date")
                trade_day = date.fromisoformat(row["date"])
                if not day <= trade_day <= end or trade_day in self.calendar:
                    raise ValueError("invalid lane calendar date")
                self.calendar[trade_day] = row
            current = self.current_session()  # Validate before startup completes.
            self.record.data["session"] = "closed" if current is None else current.name
            self.record.data["feed"] = None if current is None else current.feed

    def _order_report(self, row: Any) -> Any:
        report = super()._order_report(row)
        # Engine ACCEPTED also represents broker acknowledgement/held states.
        # Only venue `new` proves routing; a queued-and-cancelled order cannot pass.
        if row.get("status") == "new" and self._is_house(row.get("client_order_id")):
            self.record.data["venue_working_seen"] = True
            self.working_orders.add(row["client_order_id"])
            self.working_callback(ClientOrderId(row["client_order_id"]))
        return report

    def _submit_admitted(self) -> bool:
        current = self.current_session()
        return (
            self.record.data["mode"] == "order"
            and current is not None
            and current.name == self.record.data["session"]
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
        execution = clients.get("execution")
        session = None if execution is None else execution.current_session()
        age = None if quote is None else quote.quote_age_ns(INSTRUMENT_ID)
        if record.data["order"] is None:
            record.data["session"] = "closed" if session is None else session.name
            record.data["feed"] = None if quote is None else quote.feed
        return (
            session is not None and type(age) is int and 0 <= age < state.settings.quote_max_age_ns
        )

    class QuoteFactory(DataClientFactory):
        @staticmethod
        def create(**kwargs):
            client = AlpacaQuoteFactory.create(**kwargs)
            clients["quote"] = client
            client.session_now = lambda: (
                clients["execution"].current_session() if "execution" in clients else None
            )
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
            client.working_orders = set()
            client.working_callback = lambda cid: clients["strategy"].on_venue_working(cid)
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
    clients["strategy"] = strategy
    strategy.venue_working = lambda cid: (
        "execution" in clients and cid.value in clients["execution"].working_orders
    )
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


def run(state: Preflight, record: RunRecord, log_dir: Path | None = None) -> None:
    """Engine output goes to `log_dir` (the unattended unit's state), else the tree's runs/."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = boundary.REPO_ROOT / "runs" if log_dir is None else log_dir
    path = folder / f"M3-alpaca-paper-{stamp}-{record.data['mode']}-engine.log"
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
