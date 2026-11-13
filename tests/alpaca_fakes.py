"""
Offline stand-ins for the Alpaca lane's tests: a paper account in memory, its trade-update
stream, an order budget with the earlier pacer's interface, and a node builder.

Everything here is synthetic. Ids are made-up UUIDs, prices and times are invented, and no
row was copied from a real account. Nothing opens a socket.
"""

from __future__ import annotations

import asyncio
import heapq
import inspect
import itertools
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from alpaca.common.exceptions import APIError
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode, LiveNodeConfig
from nautilus_trader.live.clients import ExecutionClientFactory
from nautilus_trader.model import InstrumentId, TraderId
from nautilus_trader.trading import Strategy, StrategyConfig

from meridian.alpaca import reconcile
from meridian.alpaca.budget import ActionKind, PacerRefused
from meridian.alpaca.config import AlpacaPaperExecClientConfig
from meridian.alpaca.credentials import PaperKeys
from meridian.alpaca.execution import Wiring
from meridian.alpaca.factories import build_client
from meridian.alpaca.reports import TERMINAL, timestamp_ns

PREFIX = "M3-"
AAPL = InstrumentId.from_str("AAPL.ALPACA")
TEST_COMMISSION = {
    "commission_per_fill": "0.00",
    "commission_source": "https://example.invalid/synthetic-test-fee-row",
}
_ids = itertools.count(1)


def uuid() -> str:
    """A made-up UUID, unique within the test run."""
    return f"00000000-0000-4000-8000-{next(_ids):012d}"


def stamp(minute: int, second: int = 0) -> str:
    return f"2026-11-02T14:{minute:02d}:{second:02d}.123456Z"


def api_error(status: int, text: str = '{"code": 1, "message": "synthetic"}') -> APIError:
    return APIError(text, SimpleNamespace(response=SimpleNamespace(status_code=status)))


def order_row(
    *,
    symbol: str = "AAPL",
    client_order_id: str | None = None,
    status: str = "filled",
    side: str = "buy",
    qty: str = "1",
    filled_qty: str | None = None,
    limit_price: str = "100.00",
    submitted_at: str | None = None,
    order_class: str = "simple",
    legs: list | None = None,
    type: str = "limit",
) -> dict[str, Any]:
    submitted = submitted_at or stamp(0)
    if filled_qty is None:
        filled_qty = qty if status == "filled" else "0"
    return {
        "id": uuid(),
        "client_order_id": client_order_id or f"{PREFIX}{next(_ids)}",
        "created_at": submitted,
        "updated_at": submitted,
        "submitted_at": submitted,
        "filled_at": submitted if status == "filled" else None,
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": None,
        "asset_id": "00000000-0000-4000-8000-00000000aaaa",
        "symbol": symbol,
        "asset_class": "us_equity",
        "notional": None,
        "qty": qty,
        "filled_qty": filled_qty,
        "filled_avg_price": limit_price if filled_qty != "0" else None,
        "order_class": order_class,
        "order_type": type,
        "type": type,
        "side": side,
        "time_in_force": "day",
        "limit_price": limit_price,
        "stop_price": None,
        "status": status,
        "extended_hours": False,
        "legs": legs,
        "trail_percent": None,
        "trail_price": None,
        "hwm": None,
    }


def position_row(symbol: str = "AAPL", qty: str = "1", avg: str = "100.00") -> dict[str, Any]:
    return {
        "asset_id": "00000000-0000-4000-8000-00000000aaaa",
        "symbol": symbol,
        "exchange": "NASDAQ",
        "asset_class": "us_equity",
        "avg_entry_price": avg,
        "qty": qty,
        "side": "long",
        "market_value": avg,
        "cost_basis": avg,
        "qty_available": qty,
    }


def fill_activity(order: dict[str, Any], *, cum_qty: str | None = None, when: str | None = None):
    return {
        "id": f"20261102000000000::{uuid()}",
        "activity_type": "FILL",
        "transaction_time": when or order["submitted_at"],
        "type": "fill",
        "price": order["limit_price"],
        "qty": order["filled_qty"],
        "side": order["side"],
        "symbol": order["symbol"],
        "leaves_qty": "0",
        "order_id": order["id"],
        "cum_qty": cum_qty or order["filled_qty"],
        "order_status": "filled",
    }


def update(event: str, order: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A raw trade_updates message as alpaca-py hands it over with raw_data=True."""
    data: dict[str, Any] = {"event": event, "order": dict(order), "timestamp": stamp(30)}
    if event in ("fill", "partial_fill"):
        data.update(
            execution_id=uuid(), price=order["limit_price"], qty=order["qty"], position_qty="1"
        )
    data.update(extra)
    return {"stream": "trade_updates", "data": data}


def unnested(row: dict[str, Any]) -> list[dict[str, Any]]:
    """An order and its legs as rows of their own, none holding legs."""
    rows = [{**row, "legs": None}]
    for leg in row.get("legs") or []:
        rows += unnested(leg)
    return rows


class FakeVenue:
    """The paper account's REST surface as alpaca-py's low-level get/post/delete see it."""

    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []
        self.positions: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []
        self.assets = {"AAPL", "MSFT"}
        self.calls: list[tuple[str, str]] = []
        self.listings: list[dict[str, Any]] = []  # the query of each GET /orders
        self.failures: dict[tuple[str, str], BaseException] = {}
        self.until_inclusive = True
        self.listing_delay = 0.0  # seconds each GET /orders takes, in its worker thread
        # Seconds the answer to an open-order listing takes after the venue read its orders.
        self.open_answer_delay = 0.0
        self.positions_delay = 0.0  # seconds each GET /positions takes, in its worker thread
        self.delete_delay = 0.0  # seconds each DELETE takes, in its worker thread
        self.accept_status = "accepted"

    def fail(self, method: str, path: str, error: BaseException) -> None:
        self.failures[(method, path)] = error

    def _check(self, method: str, path: str) -> None:
        self.calls.append((method, path))
        if method == "get" and path == "/orders" and self.listing_delay:
            time.sleep(self.listing_delay)
        if method == "get" and path == "/positions" and self.positions_delay:
            time.sleep(self.positions_delay)
        error = self.failures.get((method, path))
        if error is not None:
            raise error

    def get(self, path: str, data: dict | None = None, **_: Any) -> Any:
        self._check("get", path)
        data = data or {}
        if path == "/account":
            return {
                "equity": "100000.00",
                "buying_power": "200000.00",
                "cash": "100000.00",
                "currency": "USD",
            }
        if path.startswith("/assets/"):
            symbol = path.removeprefix("/assets/")
            if symbol not in self.assets:
                raise api_error(404)
            return {"id": uuid(), "class": "us_equity", "symbol": symbol, "tradable": True}
        if path == "/positions":
            return [dict(row) for row in self.positions]
        if path == "/orders":
            rows = self._list(data)
            if data.get("status") == "open" and self.open_answer_delay:
                time.sleep(self.open_answer_delay)
            return rows
        if path == "/orders:by_client_order_id":
            for row in self.orders:
                if row["client_order_id"] == data.get("client_order_id"):
                    return dict(row)
            raise api_error(404)
        if path.startswith("/orders/"):
            for row in self.orders:
                if row["id"] == path.removeprefix("/orders/"):
                    return dict(row)
            raise api_error(404)
        if path == "/account/activities/FILL":
            return self._fills(data)
        raise AssertionError(f"unexpected GET {path}")

    def _list(self, data: dict) -> list[dict[str, Any]]:
        self.listings.append(dict(data))
        status = data.get("status", "open")
        # alpaca-py 0.45.0, GetOrdersRequest.nested: "If true, the result will roll up multi-leg
        # orders under the legs field of primary order." Read here as: without it, each leg is
        # listed as an order of its own and no row holds legs. Not checked against the venue.
        orders = self.orders
        if data.get("nested") is not True:
            orders = [part for row in self.orders for part in unnested(row)]
        rows = [
            row
            for row in orders
            if status == "all" or (status == "open") == (row["status"] not in TERMINAL)
        ]
        if "symbols" in data:
            rows = [row for row in rows if row["symbol"] in data["symbols"].split(",")]
        if "after" in data:
            floor_ns = timestamp_ns(data["after"], "after")
            rows = [r for r in rows if timestamp_ns(r["submitted_at"], "s") > floor_ns]
        if "until" in data:
            limit_ns = timestamp_ns(data["until"], "until")
            keep = (
                (lambda ns: ns <= limit_ns) if self.until_inclusive else (lambda ns: ns < limit_ns)
            )
            rows = [r for r in rows if keep(timestamp_ns(r["submitted_at"], "s"))]
        rows.sort(key=lambda r: timestamp_ns(r["submitted_at"], "s"), reverse=True)
        return [dict(row) for row in rows[: int(data.get("limit", 50))]]

    def _fills(self, data: dict) -> list[dict[str, Any]]:
        rows = sorted(self.fills, key=lambda r: r["transaction_time"], reverse=True)
        token = data.get("page_token")
        if token is not None:
            index = next(i for i, row in enumerate(rows) if row["id"] == token)
            rows = rows[index + 1 :]
        return [dict(row) for row in rows[: int(data.get("page_size", 100))]]

    def post(self, path: str, data: dict | None = None) -> Any:
        self._check("post", path)
        assert path == "/orders" and data is not None
        row = order_row(
            symbol=data["symbol"],
            client_order_id=data["client_order_id"],
            status=self.accept_status,
            side=data["side"],
            qty=data["qty"],
            limit_price=data["limit_price"],
            submitted_at=stamp(20),
        )
        self.orders.append(row)
        self.last_post = data
        return dict(row)

    def delete(self, path: str, data: dict | None = None) -> Any:
        self._check("delete", path)
        if self.delete_delay:
            time.sleep(self.delete_delay)
        for row in self.orders:
            if row["id"] == path.removeprefix("/orders/"):
                row["status"] = "pending_cancel"
                return None
        raise api_error(404)


@dataclass(frozen=True)
class Frame:
    """A websocket frame's text, pushed undecoded: the stand-in stream decodes it as the SDK
    does."""

    text: str


class FakeStream:
    """alpaca-py's TradingStream surface the client uses, driven by the test."""

    def __init__(self) -> None:
        self._trade_updates_handler: Callable | None = None
        self.queue: asyncio.Queue | None = None
        self.stopped = False
        self.closed = 0
        self.sockets = 0
        self.ack = True

    def subscribe_trade_updates(self, handler: Callable) -> None:
        assert inspect.iscoroutinefunction(handler)
        self._trade_updates_handler = handler

    async def _dispatch(self, message: dict) -> None:
        if message.get("stream") == "trade_updates" and self._trade_updates_handler:
            await self._trade_updates_handler(message)

    async def _start_ws(self) -> None:
        self.sockets += 1

    async def close(self) -> None:
        self.closed += 1

    async def _consume(self) -> None:
        """alpaca-py 0.45.0 `TradingStream._consume`: receive a frame, decode it, read its
        stream name and dispatch it. A `Frame` is decoded here, as the SDK decodes each one."""
        assert self.queue is not None
        while not self.stopped:
            try:
                message = await asyncio.wait_for(self.queue.get(), 0.05)
            except TimeoutError:
                continue
            if message == "reconnect":
                await self.close()
                await self._start_ws()
                await self._dispatch(
                    {"stream": "listening", "data": {"streams": ["trade_updates"]}}
                )
                continue
            if isinstance(message, Frame):
                message = json.loads(message.text)
            message.get("stream")
            await self._dispatch(message)

    async def _run_forever(self) -> None:
        self.queue = asyncio.Queue()
        await self._start_ws()
        if self.ack:
            await self._dispatch({"stream": "listening", "data": {"streams": ["trade_updates"]}})
        while not self.stopped:
            try:
                await self._consume()
            except Exception:
                # alpaca-py's `_drive_run` logs what the receive loop raised once the session is
                # up, and carries on with the socket open.
                continue

    def stop(self) -> None:
        self.stopped = True

    def push(self, message: Any) -> None:
        assert self.queue is not None, "stream not running"
        self.queue.put_nowait(message)


@dataclass(order=True)
class _Queued:
    kind: int
    sequence: int
    send: Callable = field(compare=False)
    admission: Callable[[], bool] = field(compare=False)
    refuse: Callable[[str], None] | None = field(compare=False)


@dataclass
class _Bucket:
    interval_ns: int


class FakePacer:
    """A deterministic budget with the earlier pacer's interface: `limit` admissions per
    window in priority order (CANCEL first, SUBMIT last), on an integer-nanosecond clock the
    test controls. It is a stand-in for M2's pacer, not a copy of it."""

    def __init__(self, now_ns: Callable[[], int], *, limit: int = 180, window_ns: int = 60 * 10**9):
        self.now_ns, self.limit, self.window_ns = now_ns, limit, window_ns
        self.bucket = _Bucket(interval_ns=1_000_000)  # the gateway polls every millisecond
        self.controls: dict[str, int | None] = {
            "request_budget": limit,
            "reserve_per_open_position": 0,
            "reserve_per_exiting_position": 0,
        }
        self.queue: list[_Queued] = []
        self.sequence = itertools.count()
        self.admitted: list[int] = []  # admission times, for the window
        self.kinds: list[ActionKind] = []  # wire order
        self.wire_requests = 0
        self.rate_limited = 0
        self.successes = 0
        self.refuse_kinds: set[ActionKind] = set()
        self.paused_until = 0

    def request(
        self, kind, send, *, admission=lambda: True, position_counts=None, refuse=None, **_
    ):
        if kind in self.refuse_kinds:
            if refuse is not None:
                refuse("synthetic pacer refusal")
            raise PacerRefused("synthetic pacer refusal")
        heapq.heappush(self.queue, _Queued(int(kind), next(self.sequence), send, admission, refuse))
        self.drain()

    def drain(self) -> None:
        while self.queue:
            now = self.now_ns()
            if now < self.paused_until:
                return
            self.admitted = [t for t in self.admitted if now - t < self.window_ns]
            item = self.queue[0]
            if not item.admission():
                heapq.heappop(self.queue)
                continue
            if len(self.admitted) >= self.limit:
                return
            heapq.heappop(self.queue)
            self.admitted.append(now)
            used = False

            def before_wire(kind=item.kind) -> None:
                nonlocal used
                assert not used, "one admitted action permits one wire request"
                used = True
                self.wire_requests += 1
                self.kinds.append(ActionKind(kind))

            item.send(before_wire)

    def on_rate_limited(self, reset_after_ns: int | None = None) -> None:
        self.rate_limited += 1
        self.paused_until = self.now_ns() + (reset_after_ns or 10**9)

    def on_success(self) -> None:
        self.successes += 1


class Clock:
    """An integer-nanosecond clock for the fake pacer."""

    def __init__(self) -> None:
        self.ns = 1_794_000_000_000_000_000

    def __call__(self) -> int:
        return self.ns


@dataclass
class Rig:
    venue: FakeVenue = field(default_factory=FakeVenue)
    stream: FakeStream = field(default_factory=FakeStream)
    clock: Clock = field(default_factory=Clock)
    pacer: FakePacer | None = None
    clients: list = field(default_factory=list)

    def wiring(self) -> Wiring:
        def pacer(now_ns: Callable[[], int]) -> FakePacer:
            self.pacer = FakePacer(self.clock)
            return self.pacer

        return Wiring(
            keys=lambda: PaperKeys("synthetic-key-id", "synthetic-secret"),
            sdk=lambda keys: self.venue,
            stream=lambda keys: self.stream,
            pacer=pacer,
        )


def exec_config(**overrides: Any) -> AlpacaPaperExecClientConfig:
    values: dict[str, Any] = {
        "account_id": "ALPACA-TEST",
        "house_prefix": PREFIX,
        "universe": ["AAPL.ALPACA"],
        **TEST_COMMISSION,
    }
    values.update(overrides)
    return AlpacaPaperExecClientConfig(**values)


class ClaimingStrategy(Strategy):
    """Claims the lane's universe so earlier orders reconcile as its own (see the docs).

    NautilusTrader's Strategy takes its constructor arguments in `__new__`, so hooks are set
    as attributes by `strategy()` rather than passed to the constructor.
    """

    def __init__(self, config: StrategyConfig | None = None) -> None:
        super().__init__(config)
        self.on_start_hook: Callable | None = None
        self.events: list[Any] = []

    def on_start(self) -> None:
        if self.on_start_hook is not None:
            self.on_start_hook(self)
        else:
            self.shutdown_system("test done")

    def on_order_event(self, event: Any) -> None:
        # Every order event the engine hands the strategy (2.0.0rc9 has no `on_event` hook).
        self.events.append(event)


def strategy(*, claim: bool = True, on_start: Callable | None = None) -> ClaimingStrategy:
    config = StrategyConfig(external_order_instrument_ids=[AAPL]) if claim else None
    built = ClaimingStrategy(config)
    built.on_start_hook = on_start
    return built


def build_node(
    rig: Rig,
    strategy: Strategy,
    *,
    engine: dict | None = None,
    timeouts: dict | None = None,
    **config: Any,
) -> LiveNode:
    class Factory(ExecutionClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock, trader_id):
            client = build_client(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                trader_id=trader_id,
                wiring=rig.wiring(),
            )
            rig.clients.append(client)
            return client

    node = LiveNode.build(
        "M3-TEST",
        LiveNodeConfig(
            environment=Environment.LIVE,
            trader_id=TraderId("M3-TEST"),
            **{
                "timeout_connection_secs": 15,
                "timeout_reconciliation_secs": 30,
                "timeout_portfolio_secs": 10,
                "timeout_disconnection_secs": 10,
                "delay_post_stop_secs": 0,
                **(timeouts or {}),
            },
            exec_engine=reconcile.engine_config([AAPL], **(engine or {})),
            exec_clients={"ALPACA": exec_config(**config)},
        ),
        exec_factories={"ALPACA": Factory},
    )
    node.add_strategy(strategy)
    return node


async def run(node: LiveNode, seconds: float = 10) -> BaseException | None:
    """Run the node until its strategy stops it; return what the run raised, if anything."""
    try:
        async with asyncio.timeout(seconds):
            await node.run_async()
    except Exception as exc:
        # Without its traceback: the frames would hold the node, and a node is one per thread.
        exc.__traceback__ = exc.__context__ = exc.__cause__ = None
        return exc
    return None
