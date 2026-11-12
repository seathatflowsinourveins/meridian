"""
The engine side of the IBKR paper lane. Imported only by ``meridian.ibkr_paper``, after
the boundary gate has passed.

Starting point: NautilusTrader's own Interactive Brokers example at v2.0.0rc9. Its two
helper modules are vendored unmodified under ``upstream/`` (see UPSTREAM.md) and imported
the way upstream's example scripts import them. ``run`` follows upstream's
``notebooks/market_order_example.py``: subclass ``IbV2OrderStrategy``, implement
``submit_example_orders``, build the node with ``build_ib_live_node``.

Own design, and the only additions to that example:
  - the order: one DAY LIMIT BUY priced under the bid, so it rests. Upstream's base
    strategy then cancels it on acceptance (its default), which gives a terminal state
    without taking a position;
  - a refusal to submit when the account already has an open order or position in this
    instrument;
  - the calls that feed the run record.

This lane places exactly one order. Upstream's close-on-stop is switched off, so if the
order ever fills (the bid comes from delayed data), the share stays in the paper account,
the run is reported as a failure, and the owner closes the position by hand.
"""

from __future__ import annotations

import contextlib
import os
import sys
import traceback
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meridian import boundary

if TYPE_CHECKING:
    from meridian.ibkr_paper import RunRecord

UPSTREAM_IB_EXAMPLES = (
    boundary.REPO_ROOT / "upstream/nautilus_trader/v2.0.0rc9/examples/live/interactive_brokers"
)
# Appended, not put first: the vendored folder must not shadow any other module.
sys.path.append(str(UPSTREAM_IB_EXAMPLES))

import nautilus_trader  # noqa: E402
from _common import (  # noqa: E402
    build_ib_live_node,
    default_aapl_instrument_id,
    instrument_provider_config,
    schedule_node_stop,
)
from ib_v2_order_strategies import IbV2OrderStrategy  # noqa: E402
from nautilus_trader.model import OrderSide, Price, Quantity  # noqa: E402

INSTRUMENT_ID = default_aapl_instrument_id()  # AAPL.XNAS, upstream's stock example
ORDER_QTY = "1"
LIMIT_UNDER_BID = 0.02
# Fixed ids, distinct from each other and from the probe's, so runs are comparable.
DATA_CLIENT_ID = 1511
EXEC_CLIENT_ID = 1512
AUTO_STOP_SECONDS = {"order": 60, "restart": 25}


class OneDayLimit(IbV2OrderStrategy):
    """One DAY LIMIT BUY. In restart mode upstream's base strategy submits nothing."""

    strategy_id_value = "MERIDIAN-M1"
    instrument_id_value = INSTRUMENT_ID
    _record: RunRecord

    def __init__(self) -> None:
        # No arguments, as in upstream's strategies: the engine's Strategy base class
        # does not accept extra constructor arguments from a subclass.
        super().__init__()
        self._bid: Price | None = None
        self._order_id: Any = None

    @classmethod
    def create(cls, record: RunRecord) -> OneDayLimit:
        strategy = cls()
        strategy._record = record
        return strategy

    def _open_counts(self) -> dict[str, int]:
        cache = self.cache
        return {
            "instrument_open_orders": len(cache.orders_open(instrument_id=self.instrument_id)),
            "instrument_open_positions": len(
                cache.positions_open(instrument_id=self.instrument_id)
            ),
            "account_open_orders": len(cache.orders_open()),
            "account_open_positions": len(cache.positions_open()),
        }

    def on_start(self) -> None:
        # The node starts strategies only after startup reconciliation returned without error.
        counts = self._open_counts()
        self._record.trader_started(**counts)
        if counts["instrument_open_orders"] or counts["instrument_open_positions"]:
            print(
                f"{self.strategy_id}: the account already has an open order or position in "
                f"{self.instrument_id}; nothing will be submitted.",
                flush=True,
            )
            return
        super().on_start()

    def on_quote(self, quote: Any) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        if not quote.bid_price.is_positive():
            return  # wait for a usable bid
        self._bid = quote.bid_price
        super().on_quote(quote)

    def submit_example_orders(self) -> None:
        if self._bid is None or self.instrument is None:
            raise RuntimeError("no bid to price the order from")
        price = self.instrument.make_price(self._bid.as_double() * (1.0 - LIMIT_UNDER_BID))

        self._order_id = self.client_order_id("LIMIT")
        # limit_order() is upstream's helper; its time in force defaults to DAY.
        order = self.limit_order(self._order_id, OrderSide.BUY, Quantity.from_str(ORDER_QTY), price)
        self._record.order_built(
            client_order_id=str(order.client_order_id),
            instrument_id=str(order.instrument_id),
            side=order.side.name,
            type=order.order_type.name,
            time_in_force=order.time_in_force.name,
            quantity=str(order.quantity),
            price=str(order.price),
        )
        self.submit_ib_order(order)

    def on_order_event(self, event: Any) -> None:
        kind = type(event).__name__
        fields: dict[str, Any] = {"client_order_id": str(event.client_order_id)}
        if kind == "OrderFilled":
            fields.update(
                last_qty=str(event.last_qty),
                last_px=str(event.last_px),
                order_side=event.order_side.name,
            )
        self._record.event(kind, event.ts_event, **fields)
        reason = getattr(event, "reason", None)
        if reason:
            self._record.reason(kind, str(reason))

    def on_position_event(self, event: Any) -> None:
        self._record.event(type(event).__name__, event.ts_event)

    def on_stop(self) -> None:
        # Captured before upstream's stop-time cancel, so it shows what the run left.
        fields: dict[str, Any] = dict(self._open_counts())
        if self._order_id is not None:
            order = self.cache.order(self._order_id)
            if order is not None:
                fields["order_status"] = order.status.name
                fields["filled_qty"] = str(order.filled_qty)
        self._record.at_stop(**fields)
        super().on_stop()


def build(mode: str, host: str, port: int, account: str, record: RunRecord) -> Any:
    """Build the node the way upstream's example does. Connects to nothing."""
    # Upstream's helpers read IB_V2_* variables. Start from none, so nothing in the shell
    # (a risk-engine bypass, another instrument) can change what this run does.
    for name in [n for n in os.environ if n.startswith(("IB_V2_", "IB_PYO3_"))]:
        del os.environ[name]
    os.environ["IB_V2_RECONCILIATION"] = "1"
    os.environ["IB_V2_CLOSE_ON_STOP"] = "0"  # this lane never places a second order
    if mode == "order":
        os.environ["IB_V2_ENABLE_ORDER_SUBMISSION"] = "1"

    record.data["engine"] = {"nautilus_trader": nautilus_trader.__version__}
    node = build_ib_live_node(
        name="MERIDIAN-IBKR-PAPER",
        trader_id="MERIDIAN-001",
        host=host,
        port=port,
        data_client_id=DATA_CLIENT_ID,
        exec_client_id=EXEC_CLIENT_ID,
        account_id=account,
        provider_config=instrument_provider_config(load_ids=[INSTRUMENT_ID]),
    )
    strategy = OneDayLimit.create(record)
    if str(strategy.instrument_id) != INSTRUMENT_ID:
        raise RuntimeError("the strategy is not on the lane's instrument")
    node.add_strategy(strategy)
    return node


@contextlib.contextmanager
def _output_to(path: Path) -> Iterator[None]:
    """Send everything written to stdout and stderr, by Python or by the engine's Rust core
    (file descriptors 1 and 2), to a local file, and restore both afterwards."""
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


def run(mode: str, host: str, port: int, account: str, record: RunRecord) -> None:
    """Build the node and run it until it stops itself.

    The engine's own output can name the account, so it goes to a log in ``runs/`` (ignored by
    git) and the terminal shows only the lane's lines.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log = boundary.REPO_ROOT / "runs" / f"M1-ibkr-paper-{stamp}-{mode}-engine.log"
    shown = log.relative_to(boundary.REPO_ROOT)
    record.local["engine_log"] = str(shown)
    print(f"Engine output goes to {shown} (it can show the account id; it stays on this machine).")
    failure = None
    with _output_to(log):
        try:
            node = build(mode, host, port, account, record)
            schedule_node_stop(node, AUTO_STOP_SECONDS[mode])
            node.run()
        except KeyboardInterrupt:
            failure = "interrupted"
        except Exception as e:  # a failed connection or reconciliation aborts with an error
            failure = f"{type(e).__name__}: {e}"
            traceback.print_exc()  # into the log
    if failure is not None:
        record.engine_error(failure)  # the text stays in runs/, never in evidence/
        kind = failure.split(":", 1)[0]
        print(f"The node stopped with an error ({kind}); details in {shown}.", file=sys.stderr)
