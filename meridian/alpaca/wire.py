"""
The account gateway: every REST request to the paper account, paced, and the exact wire values.

Own design, ported from `sextant-paper@a991b73a:src/sextant/alpaca/wire.py` and trimmed to
M3 (plain DAY LIMIT orders: no replace, no trailing stop, no extended hours). The SDK is
alpaca-py 0.45.0 (`alpaca/common/rest.py`, `alpaca/trading/client.py`); its low-level
`get`/`post`/`delete` are used so that prices and quantities stay decimal strings (its typed
request and response models turn them into floats).

Rules carried from the earlier line (docs/m3-alpaca.md):
- Every REST request, reads included, passes through the one account pacer; the SDK's own
  retries are switched off, so a 429 is seen and paced instead of resent invisibly.
- The pacer's on-wire hook runs once, on the loop, before the request leaves. Afterwards the
  request is "sent": only a documented venue refusal or a later authoritative read settles it.
- A refusal before the wire is "not sent" for every caller.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.stream import TradingStream
from nautilus_trader.model import ContingencyType, OrderSide, OrderType, TimeInForce, TriggerType

from .budget import AccountPacer, ActionKind, PacerRefused
from .constants import PAPER_HOST, PAPER_TRADE_STREAM_URL, PAPER_TRADING_URL

# The REST calls this lane makes. Nothing account-wide (cancel all, close all), no replace.
_READ_PATHS = frozenset(
    {"/account", "/positions", "/orders", "/orders:by_client_order_id", "/account/activities/FILL"}
)
_ASSET_PATH = re.compile(r"/assets/[A-Z][A-Z0-9.]{0,15}")
_ORDER_PATH = re.compile(r"/orders/(?P<id>[^/]+)")

# Documented refusals after send (earlier line, venue reference pages read 2026-11-11):
# POST /v2/orders answers 403 or 422, DELETE /v2/orders/{id} answers 422; a DELETE's 429 is
# a refusal as well. Any other answer after send (5xx, a timeout, a 2xx body that does not
# parse, a POST's 429) leaves the order possibly live, so it is never refused locally.
REFUSALS = {"submit": frozenset({403, 422}), "cancel": frozenset({422, 429})}


class PaperTradingClient(TradingClient):
    """alpaca-py's REST client on the paper host only, with no hidden retries and a timeout."""

    def __init__(self, key_id: str, secret_key: str, *, timeout_secs: float) -> None:
        super().__init__(
            api_key=key_id,
            secret_key=secret_key,
            paper=True,
            raw_data=True,
            url_override=PAPER_TRADING_URL,
        )
        # alpaca-py resends a 429 or 504 up to three times inside one call
        # (common/constants.py DEFAULT_RETRY_ATTEMPTS); each resend is a request the pacer
        # would not see. With 0, the first such answer raises APIError instead.
        self._retry = 0
        # alpaca-py sets no timeout on its requests.Session calls; a stalled call would hold
        # the gateway (and the node's shutdown) forever.
        self._timeout = (timeout_secs, timeout_secs)

    def _one_request(self, method: str, url: str, opts: dict, retry: int) -> Any:
        if not url.startswith(PAPER_TRADING_URL + "/"):
            raise ValueError("refusing a request to a host other than the paper endpoint")
        # alpaca-py 0.45.0 already passes allow_redirects=False (`common/rest.py`, `_request`);
        # it is set here as well, so the keys in the headers never follow a redirect to
        # another host even if a later SDK release changes its default.
        pinned = {**opts, "allow_redirects": False, "timeout": self._timeout}
        return super()._one_request(method, url, pinned, retry)


# alpaca-py's own stream settings (0.45.0, `TradingStream.__init__`), plus the pin: websockets
# 17.4 refuses a cross-origin redirect when the host and port are given (`asyncio/client.py`,
# `process_redirect`), and `proxy=None` keeps an environment proxy out of the path.
STREAM_PARAMS = {
    "ping_interval": 10,
    "ping_timeout": 180,
    "max_queue": 1024,
    "host": PAPER_HOST,
    "port": 443,
    "proxy": None,
}


class PaperTradingStream(TradingStream):
    """alpaca-py's trade-update stream, pinned to the paper host before the keys are sent.

    alpaca-py authenticates in the first frame after the socket opens (`_start_ws`: `_connect`,
    then `_auth`). REST follows no redirect; a websocket handshake would follow one to another
    host, so the socket is checked where it landed before `_auth` runs.
    """

    def __init__(self, key_id: str, secret_key: str) -> None:
        super().__init__(
            key_id,
            secret_key,
            paper=True,
            raw_data=True,
            url_override=PAPER_TRADE_STREAM_URL,
            websocket_params=dict(STREAM_PARAMS),
        )

    async def _connect(self) -> None:
        await super()._connect()
        uri = getattr(getattr(self._ws, "protocol", None), "uri", None)
        if uri is None or not uri.secure or uri.host != PAPER_HOST or uri.port != 443:
            await self.close()
            raise ConnectionError("refusing a trade stream that is not on the paper host")


def house_id(value: str, prefix: str) -> str:
    """The lane writes and touches only orders in its own client-order-id namespace."""
    if not prefix or not value.startswith(prefix) or len(value) > 48 or not value.isascii():
        raise ValueError("client order id outside the lane's namespace")
    return value


def whole(value: Any) -> str:
    number = value.as_decimal()
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        raise ValueError("positive whole quantity required")
    return format(number, ".0f")


def price_text(value: Any) -> str:
    """Alpaca accepts two decimals at or above $1.00 and four below (earlier line's reading)."""
    number = value.as_decimal()
    tick = Decimal("0.01") if number >= 1 else Decimal("0.0001")
    if not number.is_finite() or number <= 0 or number % tick:
        raise ValueError("limit price must already be on the venue's tick")
    # Canonical text at the tick: an instrument at precision 4 gives "100.0000", sent as "100.00".
    return format(number.quantize(tick), "f")


def submit_payload(order: Any, prefix: str) -> dict[str, Any]:
    """The POST /v2/orders body for one plain DAY LIMIT order, or ValueError."""
    if order.order_type != OrderType.LIMIT:
        raise ValueError("only LIMIT orders")
    if order.time_in_force != TimeInForce.DAY or order.expire_time is not None:
        raise ValueError("only DAY time in force")
    if order.is_post_only or order.is_reduce_only or order.is_quote_quantity:
        raise ValueError("post-only, reduce-only and quote-quantity orders are not supported")
    if (
        order.display_qty is not None
        or order.contingency_type not in (None, ContingencyType.NO_CONTINGENCY)
        or order.order_list_id is not None
        or order.parent_order_id is not None
        or order.linked_order_ids
        or order.exec_algorithm_id is not None
        or order.emulation_trigger not in (None, TriggerType.NO_TRIGGER)
    ):
        raise ValueError("iceberg, contingent, emulated and algorithm orders are not supported")
    return {
        "client_order_id": house_id(str(order.client_order_id), prefix),
        "symbol": order.instrument_id.symbol.value,
        "qty": whole(order.quantity),
        "side": "buy" if order.side == OrderSide.BUY else "sell",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": price_text(order.price),
        "order_class": "simple",
        "extended_hours": False,
    }


def permitted(method: str, path: str) -> bool:
    if method == "get" and (path in _READ_PATHS or _ASSET_PATH.fullmatch(path)):
        return True
    if method == "post" and path == "/orders":
        return True
    match = _ORDER_PATH.fullmatch(path)
    if match and method in ("get", "delete"):
        try:
            UUID(match["id"])
        except ValueError:
            return False
        return True
    return False


class AccountGateway:
    """Every REST call, including reads, passes through the same account pacer."""

    def __init__(
        self,
        sdk: Any,
        pacer: AccountPacer,
        position_counts: Callable[[], tuple[int, int]],
    ) -> None:
        self.sdk, self.pacer, self.position_counts = sdk, pacer, position_counts
        self.tasks: set[asyncio.Task] = set()

    async def call(
        self,
        kind: ActionKind,
        method: str,
        path: str,
        data: dict | None = None,
        *,
        admission: Callable[[], bool] = lambda: True,
        on_wire: Callable[[], None] = lambda: None,
        on_end: Callable[[], None] = lambda: None,
    ) -> Any:
        if not permitted(method, path):
            raise ValueError(f"unsupported account endpoint: {method.upper()} {path}")
        future: asyncio.Future = asyncio.get_running_loop().create_future()

        async def perform() -> None:
            try:
                result = await asyncio.to_thread(getattr(self.sdk, method), path, data or {})
            except Exception as exc:
                if isinstance(exc, APIError) and exc.status_code == 429:
                    self.pacer.on_rate_limited()
                if not future.done():
                    future.set_exception(exc)
            else:
                self.pacer.on_success()
                if not future.done():
                    future.set_result(result)
            finally:
                on_end()  # the wire call itself ended, whoever still awaits it

        def allowed() -> bool:
            try:
                return admit()
            except Exception as exc:  # a failed check refuses only its own request
                if not future.done():
                    future.set_exception(exc)
                return False

        def admit() -> bool:
            if future.done():  # cancelled or refused while queued: never sent
                return False
            if kind == ActionKind.SUBMIT:
                # The pacer drops a SUBMIT whose reserve it cannot compute without calling
                # refuse(); check the inputs here so that the caller hears a refusal.
                opened, exiting = self.position_counts()
                controls = self.pacer.controls
                if (
                    any(type(n) is not int or n < 0 for n in (opened, exiting))
                    or controls["reserve_per_open_position"] is None
                    or (exiting and controls["reserve_per_exiting_position"] is None)
                ):
                    future.set_exception(ValueError("entry reserve authority unavailable"))
                    return False
            if not admission():
                future.set_exception(ValueError("wire admission refused"))
                return False
            return True

        def send(mark: Callable[[], None]) -> None:
            mark()
            on_wire()
            task = asyncio.get_running_loop().create_task(perform())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        def refuse(reason: str) -> None:
            if not future.done():
                future.set_exception(ValueError(reason))

        try:
            self.pacer.request(
                kind, send, admission=allowed, position_counts=self.position_counts, refuse=refuse
            )
        except PacerRefused as exc:
            refuse(exc.reason)  # the pacer calls refuse() before it raises; nothing was sent
        try:
            while not future.done():
                # The pacer counts integer nanoseconds; the float is only asyncio's wait.
                await asyncio.wait({future}, timeout=self.pacer.bucket.interval_ns / 1e9)
                self.pacer.drain()
            return await future
        except asyncio.CancelledError:
            future.cancel()  # a queued request is then dropped at admission
            raise

    async def close(self) -> None:
        # A cancelled await cannot stop a synchronous call already in its thread; the
        # request timeout bounds how long this waits.
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
