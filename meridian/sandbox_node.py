"""
The engine side of the sandbox lane. Imported by ``meridian.sandbox_lane`` only after the
paper checks have passed, and by the offline tests.

Starting point: upstream's sandbox example at v2.0.0rc9, ``examples/live/sandbox/exec_tester.py``
(read, not copied; see UPSTREAM.md): a live node with one data client, the engine's sandbox
execution client added with ``add_simulated_exec_client``, and upstream's built-in
``ExecTester`` strategy. Upstream feeds it Binance data. This lane feeds it Interactive Brokers
data, configured the way upstream's IB helper configures its data client (``_common.py``,
vendored under ``upstream/``).

Own design, and the changes to that example:
  - the data client is IB's, for AAPL.XNAS, on the gated Gateway, and it does not reconnect on
    its own after a drop; the node has no execution client but the sandbox, so no order can
    reach IBKR;
  - the simulated account is a cash account of 100,000 USD on venue XNAS, the instrument's
    venue, with a flat fee of 1.00 USD per order (a round stand-in, not a broker's schedule);
  - ExecTester trades 1 share with DAY orders: it buys at market on the first quote, keeps a
    LIMIT buy resting 500 ticks under the bid, and on stop cancels it and sells the share. Its
    LIMIT sells are off: in a cash account a sell without the share is rejected, and ExecTester
    sends it again on every quote. It has no client id, so its orders route by venue, to the
    sandbox. Its book and trade subscriptions are off (quotes only), it does not post-only, it
    closes reduce-only on stop, and it claims no external orders;
  - the risk engine is not bypassed (upstream's example bypasses it), and the node has
    explicit connection, reconciliation, portfolio and stop timeouts (reconciliation stays
    off, as in the example);
  - the lane stops the node from its own timer, so a stop before the minute is up (a Ctrl-C)
    fails the run;
  - an actor counts the quotes it sees; the run record is read from the cache at the end, and
    the execution clients the engine registered are read from its log.

``tests/test_sandbox_lane.py`` fails if an execution client other than the sandbox is ever
added here.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
import traceback
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meridian import boundary

if TYPE_CHECKING:
    from meridian.sandbox_lane import SandboxRecord

UPSTREAM_IB_EXAMPLES = (
    boundary.REPO_ROOT / "upstream/nautilus_trader/v2.0.0rc9/examples/live/interactive_brokers"
)
# Appended, not put first: the vendored folder must not shadow any other module.
sys.path.append(str(UPSTREAM_IB_EXAMPLES))

import nautilus_trader  # noqa: E402
from _common import (  # noqa: E402
    default_aapl_instrument_id,
    instrument_provider_config,
    market_data_type,
)
from nautilus_trader.adapters import interactive_brokers as ib  # noqa: E402
from nautilus_trader.adapters.sandbox import (  # noqa: E402
    SandboxExecutionClientConfig,
    SandboxExecutionClientFactory,
)
from nautilus_trader.common import DataActor, Environment  # noqa: E402
from nautilus_trader.execution import FixedFeeModel  # noqa: E402
from nautilus_trader.live import LiveNode  # noqa: E402
from nautilus_trader.model import (  # noqa: E402
    AccountId,
    AccountType,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    Quantity,
    StrategyId,
    TimeInForce,
    TraderId,
    Venue,
)
from nautilus_trader.testkit import ExecTesterConfig  # noqa: E402

INSTRUMENT_ID = default_aapl_instrument_id()  # AAPL.XNAS, upstream's stock example
SANDBOX_VENUE = InstrumentId.from_str(INSTRUMENT_ID).venue.value  # XNAS: orders route by venue
DATA_CLIENT_NAME = "IB"
SANDBOX_CLIENT_NAME = "SANDBOX"
# Distinct from the client ids of the IBKR lane (1511, 1512), its probes (1598, 1599).
DATA_CLIENT_ID = 1521
RUN_SECONDS = 60
STARTING_USD = 100_000
SANDBOX_ACCOUNT = f"{SANDBOX_VENUE}-SANDBOX-001"  # the engine's own form for a sandbox account
REGISTERED = re.compile(r"Registered (ExecutionClient|DataClient)-([A-Za-z0-9_]+)")
TESTER_ID = "EXEC_TESTER-001"

DataClient = tuple[str, Any, Any]  # (name, factory, config), as add_data_client takes them


def ib_data_client(host: str, port: int) -> DataClient:
    """IB's data client, configured as upstream's IB helper (``_common.py``) configures it."""
    # Upstream's helpers read IB_V2_* variables. Start from none, so nothing in the shell (a
    # market data type, a timeout) changes what this run does.
    for name in [n for n in os.environ if n.startswith(("IB_V2_", "IB_PYO3_"))]:
        del os.environ[name]
    config = ib.InteractiveBrokersDataClientConfig(
        host=host,
        port=port,
        client_id=DATA_CLIENT_ID,
        connection_timeout=10,
        request_timeout=30,
        market_data_type=market_data_type(),  # delayed-frozen, upstream's default
        instrument_provider=instrument_provider_config(load_ids=[INSTRUMENT_ID]),
        # After a drop, no reconnect to a Gateway the paper checks have not seen: the feed ends
        # and the run fails on the checks after it.
        max_reconnect_attempts=0,
    )
    return DATA_CLIENT_NAME, ib.InteractiveBrokersDataClientFactory(), config


def sandbox_exec_config() -> SandboxExecutionClientConfig:
    usd = Currency.from_str("USD")
    return SandboxExecutionClientConfig(
        venue=Venue(SANDBOX_VENUE),
        starting_balances=[Money(STARTING_USD, usd)],
        account_id=AccountId.from_str(SANDBOX_ACCOUNT),
        base_currency=usd,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        # The sandbox does not build without a fee model.
        fee_model=FixedFeeModel(Money(1.00, usd), charge_commission_once=True),
    )


def exec_tester_config() -> ExecTesterConfig:
    """Upstream's example settings, for 1 share of a US stock in a simulated cash account."""
    return ExecTesterConfig(
        strategy_id=StrategyId.from_str(TESTER_ID),
        instrument_id=InstrumentId.from_str(INSTRUMENT_ID),
        client_id=None,  # route by venue; a client id would send its orders to that client
        order_qty=Quantity.from_int(1),
        subscribe_book=False,
        subscribe_quotes=True,
        subscribe_trades=False,
        open_position_on_start_qty=Decimal(1),
        open_position_on_first_quote=True,
        open_position_time_in_force=TimeInForce.DAY,
        enable_limit_buys=True,
        enable_limit_sells=False,  # a cash account cannot sell what it does not hold
        tob_offset_ticks=500,  # 500 x 0.01 = 5.00 USD from the touch: they rest
        limit_time_in_force=TimeInForce.DAY,
        use_post_only=False,
        cancel_orders_on_stop=True,
        close_positions_on_stop=True,
        close_positions_time_in_force=TimeInForce.DAY,
        reduce_only_on_stop=True,
        dry_run=False,
        log_data=False,
    )


class QuoteCounter(DataActor):
    """Counts the quotes the node receives for the instrument, and notes that it started."""

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.quotes = 0

    def on_start(self) -> None:
        self.started = True
        self.subscribe_quotes(InstrumentId.from_str(INSTRUMENT_ID))

    def on_quote(self, quote: Any) -> None:
        self.quotes += 1


def build(data_client: DataClient) -> tuple[Any, QuoteCounter]:
    """Build the node: one data client, the sandbox as its only execution client, upstream's
    ExecTester. Connects to nothing."""
    builder = (
        LiveNode.builder("MERIDIAN-SANDBOX", TraderId.from_str("MERIDIAN-002"), Environment.SANDBOX)
        .with_timeout_connection(15)
        .with_timeout_reconciliation(5)
        .with_timeout_portfolio(5)
        .with_timeout_disconnection_secs(5)
        .with_delay_post_stop_secs(3)
        .with_reconciliation(False)  # nothing to reconcile: the venue starts empty each run
        .add_data_client(*data_client)
        .add_simulated_exec_client(
            SANDBOX_CLIENT_NAME, SandboxExecutionClientFactory(), sandbox_exec_config()
        )
    )
    node = builder.build()
    counter = QuoteCounter()
    node.add_actor(counter)
    node.add_builtin_strategy("ExecTester", exec_tester_config())
    return node, counter


def _utc(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def capture(
    node: Any, counter: QuoteCounter, data_client: DataClient, record: SandboxRecord
) -> None:
    """What the run left, read from the node's cache once it has stopped."""
    cache = node.cache
    instrument_id = InstrumentId.from_str(INSTRUMENT_ID)
    record.data["node"] = {
        "environment": node.environment.name,
        "configured_data_clients": [data_client[0]],
        "configured_execution_clients": [SANDBOX_CLIENT_NAME],
        "sandbox_venue": SANDBOX_VENUE,
        "account_type": "CASH",
        "account_id": SANDBOX_ACCOUNT,
        "starting_balance": f"{STARTING_USD} USD",
        "registered_execution_clients": [],
        "registered_data_clients": [],
    }
    record.data["strategy"] = {
        "name": "ExecTester",
        "source": "nautilus_trader built-in; upstream example examples/live/sandbox/exec_tester.py",
        "instrument_id": INSTRUMENT_ID,
        "order_qty": "1",
    }
    record.data["trader_started"] = counter.started
    record.data["market_data"] = {
        "instrument_loaded": cache.instrument(instrument_id) is not None,
        "quotes_received": counter.quotes,
    }
    orders, events = [], []
    for order in cache.orders():
        orders.append(
            {
                "client_order_id": str(order.client_order_id),
                "side": order.side.name,
                "type": order.order_type.name,
                "time_in_force": order.time_in_force.name,
                "quantity": str(order.quantity),
                "status": order.status.name,
                "filled_qty": str(order.filled_qty),
                "execution_client": str(cache.client_id(order.client_order_id)),
                "account_id": None if order.account_id is None else str(order.account_id),
            }
        )
        for event in order.events():
            events.append(
                {
                    "type": type(event).__name__,
                    "client_order_id": str(event.client_order_id),
                    "ts_event_utc": _utc(event.ts_event),
                }
            )
            reason = getattr(event, "reason", None)
            if reason:
                record.local["reasons"].append(
                    {"type": type(event).__name__, "reason": str(reason)}
                )
    record.data["orders"] = sorted(orders, key=lambda o: o["client_order_id"])
    record.data["events"] = sorted(events, key=lambda e: (e["ts_event_utc"], e["client_order_id"]))
    record.data["at_stop"] = {
        "open_orders": len(cache.orders_open()),
        "open_positions": len(cache.positions_open()),
    }


def registered_clients(log_text: str) -> tuple[list[str], list[str]]:
    """The execution and data clients the engine says it registered, from its log."""
    found = REGISTERED.findall(log_text)
    return [n for k, n in found if k[0] == "E"], [n for k, n in found if k[0] == "D"]


@contextlib.contextmanager
def _output_to(path: Path) -> Iterator[None]:
    """Send everything written to stdout and stderr, by Python or by the engine's Rust core
    (file descriptors 1 and 2), to a local file, and restore both afterwards. The same code as
    the IBKR lane's engine module has; this module does not import that one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    saved = (os.dup(1), os.dup(2))
    log = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    stream = open(log, "w", buffering=1, encoding="utf-8", errors="replace", closefd=False)  # noqa: SIM115
    old = (sys.stdout, sys.stderr)
    try:
        os.dup2(log, 1)
        os.dup2(log, 2)
        sys.stdout = sys.stderr = stream
        yield
    finally:
        stream.flush()
        sys.stdout, sys.stderr = old
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        stream.close()
        for fd in (*saved, log):
            os.close(fd)


def run(data_client: DataClient, record: SandboxRecord, seconds: int = RUN_SECONDS) -> None:
    """Build the node, run it for ``seconds``, and capture the result into ``record``.

    The engine's own output can name the account the Gateway serves, so it goes to a log in
    ``runs/`` (ignored by git) and the terminal shows only the lane's lines.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log = boundary.REPO_ROOT / "runs" / f"M2-sandbox-{stamp}-engine.log"
    shown = log.relative_to(boundary.REPO_ROOT)
    record.local["engine_log"] = str(shown)
    record.data["engine"] = {"nautilus_trader": nautilus_trader.__version__}
    print(f"Engine output goes to {shown} (it can show the account id; it stays on this machine).")
    failure = None
    with _output_to(log):
        node = counter = timer = None
        on_time = threading.Event()
        try:
            node, counter = build(data_client)
            handle = node.handle()

            def stop() -> None:
                on_time.set()
                handle.stop()

            # The lane's own timer, cancelled below: nothing outlives the run to signal later.
            timer = threading.Timer(seconds, stop)
            timer.daemon = True
            timer.start()
            node.run()  # returns once the node has stopped, by this timer or by anything else
            if not on_time.is_set():
                failure = "interrupted: the node stopped before its time"
        except KeyboardInterrupt:
            failure = "interrupted"
        except Exception as e:  # a failed connection or a refused build stops the run
            failure = f"{type(e).__name__}: {e}"
            traceback.print_exc()  # into the log
        finally:
            if timer is not None:
                timer.cancel()
        if node is not None and counter is not None:
            try:
                capture(node, counter, data_client, record)
            except Exception as e:
                failure = failure or f"{type(e).__name__}: {e}"
                traceback.print_exc()
    if record.data["node"] is not None:  # what the engine itself says it registered
        execution, data = registered_clients(log.read_text(encoding="utf-8", errors="replace"))
        record.data["node"]["registered_execution_clients"] = execution
        record.data["node"]["registered_data_clients"] = data
    if failure is not None:
        record.engine_error(failure)  # the text stays in runs/, never in evidence/
        kind = failure.split(":", 1)[0]
        print(f"The node stopped with an error ({kind}); details in {shown}.", file=sys.stderr)
