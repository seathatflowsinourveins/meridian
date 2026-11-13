"""
The Alpaca paper execution client on NautilusTrader 2.0.0rc9's Python adapter interface.

Own design, ported from `sextant-paper@a991b73a:src/sextant/alpaca/execution.py` and trimmed
to M3: plain DAY LIMIT entries and their closes, cancel, query, the trade-update stream and
startup reconciliation. No modify (so no replacement lineage), no trailing stops or brackets,
no account-wide action. The engine owns order state; this client only reads the venue, sends
what the engine commands, and hands the engine reports.

Upstream interface: `nautilus_trader.live.clients.ExecutionClient` and
`docs/developer_guide/python_adapters.md` at tag v2.0.0rc9; layout after the upstream
`examples/live/_template/`. Commands run as supervised tasks (`create_task`) so that a paced
wire call never blocks the client's command queue.

Rules carried from the earlier line, each with a test (docs/m3-alpaca.md, section 3):
- The send boundary: `_mark_sent` (the pacer's on-wire hook) is the one place a command
  becomes "sent". Before it, any refusal is "not sent"; after it, only a documented venue
  refusal or a later read settles the command, and the order is never rejected locally.
- One unresolved cancel per order; a terminal event, a refusal, or a read issued after the
  DELETE's own call ended answers it.
- Every trade update is classified before it acts. An unclassified one, a lost stream or a
  venue answer the lane cannot read or map (a listing's shape or pages, a row, a single
  order's answer) is a gap: new orders are denied until a full read of orders and positions,
  issued after the latest gap, has been handed to the engine. A request that gets no answer
  is not a gap. Another writer's activity stops new orders until a restart.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from alpaca.common.exceptions import APIError
from nautilus_trader.common import Logger
from nautilus_trader.core import UUID4, unix_nanos_to_iso8601
from nautilus_trader.live.clients import ExecutionClient
from nautilus_trader.model import (
    AccountBalance,
    ClientOrderId,
    ExecutionMassStatus,
    InstrumentId,
    Money,
    OrderFilled,
    OrderFillVoided,
    OrderStatus,
    VenueOrderId,
)

from .budget import AccountPacer, ActionKind
from .constants import NOT_SUPPORTED, VENUE
from .credentials import PaperKeys
from .parsing import instrument_id, parse_equity
from .reconcile import (
    ANOTHER_WRITER,
    IncompleteCoverage,
    StageTrace,
    check_one_writer,
    explain_fills,
    list_fill_activities,
    list_orders,
    merge_listings,
    oldest_submission,
    row_symbol,
    traced,
    unmappable_history,
    withheld_unloaded,
)
from .reports import TERMINAL, decimal_text, order_status_report, position_status_report
from .reports import fill_report as make_fill_report
from .trade_updates import (
    REPLACE_EVENTS,
    TradeUpdate,
    UnclassifiedTradeUpdate,
    is_listening_ack,
    parse_trade_update,
)
from .wire import REFUSALS, AccountGateway, house_id, submit_payload

# How long disconnect waits for the SDK's stream to stop by itself before cancelling it.
STREAM_STOP_GRACE_SECS = 6.0
# Recovery reads again after a failure, waiting this long, doubling up to the cap.
RECOVERY_RETRY_SECS = (1.0, 30.0)
# NautilusTrader 2.0.0rc9 skips an order's snapshot in a mass status when a fill of that order
# reached the engine at or after the status's `ts_init` (`crates/execution/src/engine/mod.rs`,
# `is_order_snapshot_stale`). The engine stamps a fill when it processes it, shortly after this
# client hands it on, so an execution handed on this long before a recovery read began is
# treated as one the engine may stamp later than the read.
SNAPSHOT_MARGIN_NS = 1_000_000_000


@dataclass(frozen=True)
class Wiring:
    """What the client builds at connect. Production wiring is in `factories.py`."""

    keys: Callable[[], PaperKeys]
    sdk: Callable[[PaperKeys], Any]
    stream: Callable[[PaperKeys], Any]
    pacer: Callable[[Callable[[], int]], AccountPacer] | None


@dataclass(eq=False)
class _Command:
    """One submit or cancel, from its hook until an authoritative answer settles it."""

    kind: str  # "submit" or "cancel"
    native: Any
    venue_order_id: VenueOrderId | None = None
    command_id: UUID4 | None = None  # the engine command it answers (causation of a refusal)
    sent: bool = False  # set only by _mark_sent, before the request leaves
    withdrawn: bool = False  # admission refuses it from here on
    settled: bool = False  # one refusal or answer was applied
    submitted: bool = False  # OrderSubmitted was emitted
    row_id: str | None = None  # the venue order a DELETE targets
    ended: int = 0  # the tick when its own HTTP call ended; 0 while it runs


def _unresolved(exc: BaseException, token: _Command) -> bool:
    """After send, only a documented refusal resolves a command locally."""
    if not token.sent:
        return False
    status = exc.status_code if isinstance(exc, APIError) else None
    return status not in REFUSALS[token.kind]


def _why(exc: BaseException) -> str:
    """A refusal reason for an engine event: our own text, or the error's class and HTTP status.
    A venue's error body is never copied into an event."""
    if isinstance(exc, APIError):
        return f"{type(exc).__name__} {exc.status_code}"
    if type(exc) in (ValueError, RuntimeError):
        return str(exc)[:200]
    return type(exc).__name__


def _bounds(command: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for name, venue_name in (("start", "after"), ("end", "until")):
        value = getattr(command, name, None)
        if value is not None:
            params[venue_name] = unix_nanos_to_iso8601(value)
    if getattr(command, "instrument_id", None) is not None:
        params["symbols"] = command.instrument_id.symbol.value
    return params


def _is_full_listing(command: Any) -> bool:
    """A read of every order, not the engine's open-only or windowed checks."""
    return not command.open_only and not _bounds(command)


def _engine_filled(order: Any) -> Decimal:
    return Decimal(0) if order is None else order.filled_qty.as_decimal()


def _fill_since(order: Any, ts_ns: int) -> bool:
    """rc9's `is_order_snapshot_stale` on the engine's own record of the order: a fill or a
    voided fill stamped at or after `ts_ns` (`crates/execution/src/engine/mod.rs`)."""
    return order is not None and any(
        isinstance(event, (OrderFilled, OrderFillVoided)) and event.ts_init >= ts_ns
        for event in order.events()
    )


class AlpacaPaperExecutionClient(ExecutionClient):
    def __init__(
        self,
        *,
        wiring: Wiring,
        house_prefix: str,
        universe: Sequence[InstrumentId],
        commission: Money | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        house_id(house_prefix, house_prefix)
        self.wiring = wiring
        self.house_prefix = house_prefix
        self.universe = tuple(universe)
        self.commission = commission
        self.gateway: AccountGateway | None = None
        self.report_trace: dict[str, StageTrace] = {}
        self.failures: list[tuple[object, BaseException]] = []
        # Gap generations: `_gap` counts evidence that the engine's view may be stale;
        # `_covered` is the generation the latest full read (orders and positions) covers.
        self._gap = 0
        self._covered = -1
        self._started = False  # both startup stages have been read once
        self._startup_gens: dict[str, int] = {}
        self._recovery: asyncio.Task | None = None
        self.recoveries = 0
        self.withheld_symbols: set[str] = set()
        self.foreign_writer_seen = False
        self._stream: Any = None
        self._stream_task: asyncio.Task | None = None
        self._listening: asyncio.Future | None = None
        self.stream_live = False
        self.stream_restarts = 0
        self._closing = False
        self._actions: set[asyncio.Task] = set()
        self._commands: set[_Command] = set()
        self._submissions: dict[str, _Command] = {}
        self._pending: dict[str, _Command] = {}  # venue id -> its one unresolved DELETE
        self._cancelling: dict[str, _Command] = {}  # venue id -> a DELETE on its way to the wire
        self._owed: dict[str, int] = {}  # stream refusals owed to read-settled cancels
        self._cancel_seen: set[str] = set()
        self._forwarded: set[tuple[str, str]] = set()  # (venue id, execution id)
        # Per venue order: the filled quantity this client has handed the engine, in forwarded
        # executions or in a mass status. The engine may hold more (`_known`). A status report
        # claiming more than both is not volunteered: the engine would invent a fill that the
        # stream then delivers (from the stream itself it is a gap). An execution at or below
        # them is not forwarded: a read already showed the engine that fill.
        self._known_filled: dict[str, Decimal] = {}
        # Venue id -> when its latest execution was handed on, or inferred from a recovery read.
        self._last_execution: dict[str, int] = {}
        self.late_answers = 0
        self.duplicate_executions = 0
        self.known_executions = 0
        self.withheld_reports = 0
        self._tick = 0

    # ---------------------------------------------------------------- helpers

    @property
    def coverage_complete(self) -> bool:
        """True while the stream is live and a full read covers the latest gap."""
        return self.stream_live and self._covered == self._gap

    def _log(self) -> Logger:
        # Built per call: the engine's Logger is bound to the thread that creates it.
        return Logger("AlpacaPaper")

    def _now(self) -> int:
        self._tick += 1
        return self._tick

    def _is_house(self, client_order_id: object) -> bool:
        return isinstance(client_order_id, str) and client_order_id.startswith(self.house_prefix)

    def _is_loaded(self, symbol: str) -> bool:
        iid = instrument_id(symbol)
        return iid in self.universe and self.cache.instrument(iid) is not None

    def _instrument(self, symbol: object) -> Any:
        if not isinstance(symbol, str) or not self._is_loaded(symbol):
            raise ValueError("Alpaca row instrument is not loaded")
        return self.cache.instrument(instrument_id(symbol))

    def _incomplete(self, error: BaseException) -> None:
        """A gap: new orders stop until a full read issued after it has been handed over."""
        self._gap += 1
        self.failures.append((None, error))
        self._log().error(f"Alpaca account view incomplete: {type(error).__name__}: {error}")
        self._schedule_recovery()

    def _note_failures(
        self, failures: list[tuple[object, BaseException]], *, after_startup: bool
    ) -> None:
        """A venue answer the lane cannot read or map is a gap when its read began after
        startup; during the startup reads the start decides, and a failed stage refuses it. The
        caller (`_reading`) passes only such failures: a request that got no answer is not one
        (the stream still carries the account's changes)."""
        if any(ANOTHER_WRITER in str(error) for _, error in failures):
            self.foreign_writer_seen = True
        if failures and after_startup:
            self._incomplete(failures[0][1])

    @contextlib.contextmanager
    def _reading(self, requests: Sequence[BaseException] = ()) -> Iterator[None]:
        """Around the code that reads a venue answer: whatever fails in there, of any type (a
        listing that is not a list or whose pages do not join, a row that is not a row, a row
        our rules or mappers refuse), goes through `_note_failures`. A request's own failure is
        not the answer's: each one raised by a request, as `_traced_call` records it in
        `requests` (an HTTP error, a timeout, the budget refusing it before the wire), stays out
        of it, wrapped in `IncompleteCoverage` or not. Everything propagates unchanged.

        Whether the read is a startup read is decided as it begins. The engine runs the three
        startup stages concurrently, so the fill stage can fail after the order and position
        stages have marked startup done: that failure refuses the start, and is no gap."""
        after_startup = self._started
        try:
            yield
        except Exception as exc:
            wrapped = exc.failures if isinstance(exc, IncompleteCoverage) else None
            failures = wrapped or [(None, exc)]
            self._note_failures(
                [(o, e) for o, e in failures if not any(e is request for request in requests)],
                after_startup=after_startup,
            )
            raise

    def _position_counts(self) -> tuple[int, int]:
        opened = len(self.cache.positions_open(venue=self.venue, account_id=self.account_id))
        exiting = len(
            {
                order.instrument_id
                for order in self.cache.orders_open(venue=self.venue, account_id=self.account_id)
                if order.is_sell
            }
        )
        return opened, exiting

    async def _call(self, kind: ActionKind, method: str, path: str, data=None, **kwargs) -> Any:
        if self.gateway is None:
            raise RuntimeError("account gateway is disconnected")
        return await self.gateway.call(kind, method, path, data, **kwargs)

    def _traced_call(self, trace: StageTrace, requests: list[BaseException]) -> Callable:
        """A paced request counted in `trace`; what it raises is recorded in `requests`."""

        async def call(kind: ActionKind, method: str, path: str, data=None, **kwargs) -> Any:
            trace.count_request(method, path)
            try:
                return await self._call(kind, method, path, data, **kwargs)
            except Exception as exc:
                requests.append(exc)
                raise

        return call

    def _max_pages(self) -> int:
        if self.gateway is None:
            raise RuntimeError("account gateway is disconnected")
        budget = self.gateway.pacer.controls["request_budget"]
        if type(budget) is not int or budget <= 0:
            raise ValueError("request budget unavailable")
        return budget

    def _queue(self, operation, name: str, token: _Command | None = None) -> None:
        if self._closing:
            operation.close()
            if token is not None:
                self._refuse(token, f"{token.kind} not sent: the client is closing")
            return
        try:
            task = self.create_task(operation, name)
        except BaseException:
            operation.close()
            if token is not None:
                self._refuse(token, f"{token.kind} not sent: scheduling failed")
            raise
        self._actions.add(task)
        task.add_done_callback(self._actions.discard)
        if token is not None:
            self._commands.add(token)
            task.add_done_callback(lambda done: self._task_done(token, done))

    def _task_done(self, token: _Command, task: asyncio.Task) -> None:
        self._commands.discard(token)
        if task.cancelled() and not token.sent:
            self._refuse(token, f"{token.kind} not sent before cancellation")

    def _mark_sent(self, token: _Command) -> None:
        """The send boundary: the one place on-wire evidence is recorded."""
        token.sent = True
        if token.kind == "cancel" and token.row_id is not None:
            self._pending[token.row_id] = token
            self._cancel_seen.add(token.row_id)
            # A refusal owed to an earlier, read-settled attempt no longer answers anything:
            # the next refusal is this attempt's (a later read can still correct it).
            self._owed.pop(token.row_id, None)

    def _resolve(self, row_id: str, *, issued: int | None = None) -> _Command | None:
        token = self._pending.get(row_id)
        if token is None or (issued is not None and not 0 < token.ended < issued):
            return None
        token.settled = True
        del self._pending[row_id]
        return token

    def _refuse(self, token: _Command, reason: str) -> None:
        if not token.sent:
            token.withdrawn = True
        if token.settled:
            if token.sent:
                self.late_answers += 1
            return
        token.settled = True
        if token.row_id is not None and self._pending.get(token.row_id) is token:
            del self._pending[token.row_id]
        native, now = token.native, self.clock.timestamp_ns()
        if native is None:
            return
        if token.kind == "submit":
            if token.submitted:
                self.generate_order_rejected(native, reason, now, False)
            else:
                self.generate_order_denied(native, reason)
        elif token.sent:
            self.generate_order_cancel_rejected(
                native, token.venue_order_id, reason, now, token.command_id
            )
        else:
            # With the command's id the engine returns the order from PENDING_CANCEL to its
            # previous state; without it the denial would leave the order stuck there.
            self.generate_order_cancel_denied(native, reason, now, token.command_id)

    def _order_report(self, row: Mapping[str, Any]) -> Any:
        return order_status_report(
            row,
            account_id=self.account_id,
            instrument=self._instrument(row.get("symbol")),
            ts_init=self.clock.timestamp_ns(),
        )

    def _engine_order(self, venue_id: str, client_order_id: object) -> Any:
        """The engine's own record of a venue order, found as the engine finds a report's
        order: by client order id, else by venue id. None for one it does not hold."""
        order = None
        if isinstance(client_order_id, ClientOrderId):
            order = self.cache.order(client_order_id)
        elif isinstance(client_order_id, str) and client_order_id:
            order = self.cache.order(ClientOrderId(client_order_id))
        if order is None:
            found = self.cache.client_order_id(VenueOrderId(venue_id))
            order = None if found is None else self.cache.order(found)
        return order

    def _known(self, venue_id: str, client_order_id: object) -> Decimal:
        """The order's filled quantity the engine has, or will have once it has processed
        what this client handed it. The engine can hold more than this client handed it: its
        routine open-order check (or a query that check sends) infers a fill from an order
        report this client answered (NautilusTrader 2.0.0rc9, `crates/live/src/execution/
        manager.rs`, `reconcile_open_order_reports`). The node first processes what this client
        handed it, then compares and applies those fills in one step (`crates/live/src/node/
        mod.rs`, `drain_exec_events_before_reconciliation`). After startup only a mass status
        lowers an order's fills (or a report marked voided, which no Alpaca status maps to), and
        `_recover_once` never hands over one that would. So the larger of the two is what the
        engine has."""
        known = self._known_filled.get(venue_id, Decimal(0))
        return max(known, _engine_filled(self._engine_order(venue_id, client_order_id)))

    def _volunteer(self, report: Any) -> bool:
        """Hand the engine a status report it did not ask for, unless it claims fills the
        engine has not received: those come from the stream, or from a later full read.
        False when it is withheld."""
        venue_id = report.venue_order_id.value
        if report.filled_qty.as_decimal() > self._known(venue_id, report.client_order_id):
            self.withheld_reports += 1
            return False
        self._handle_report(report)
        return True

    def _know_fills(self, reports: Sequence[Any], *, inferred_at: int | None = None) -> None:
        """The engine reconciles these reports, fills included (startup or recovery). With
        `inferred_at` (recovery), an order whose known quantity a report raises is stamped as
        if an execution of it was handed on then: the engine infers that fill as it processes
        the read, and a read that begins soon after would have that order's snapshot skipped."""
        for report in reports:
            venue_id = report.venue_order_id.value
            filled = report.filled_qty.as_decimal()
            known = self._known_filled.get(venue_id)
            if inferred_at is not None and filled > (known or Decimal(0)):
                self._last_execution[venue_id] = inferred_at
            self._known_filled[venue_id] = filled if known is None else max(known, filled)

    def _settle(self, row: Mapping[str, Any], issued: int) -> None:
        """An authoritative read answers this order's unresolved cancel, if it ended before."""
        if row.get("status") == "pending_cancel":
            return
        token = self._resolve(str(row.get("id")), issued=issued)
        if token is None or row.get("status") in TERMINAL:
            return
        native = self.cache.order(ClientOrderId(str(row.get("client_order_id"))))
        if getattr(native, "status", None) == OrderStatus.PENDING_CANCEL:
            # The venue's own refusal may still arrive; it is owed and answers nothing.
            self._owed[str(row["id"])] = self._owed.get(str(row["id"]), 0) + 1
            self.generate_order_cancel_rejected(
                native,
                VenueOrderId(str(row["id"])),
                "venue order still working after an unanswered cancel",
                self.clock.timestamp_ns(),
                token.command_id,
            )

    # ---------------------------------------------------------------- lifecycle

    async def _connect(self) -> None:
        if self.wiring.pacer is None:
            raise ValueError("order budget unavailable: the lane needs the M2 account pacer")
        if self.commission is None:
            raise ValueError("fill reports unavailable: sourced commission evidence required")
        if not self.universe:
            raise ValueError("the lane's universe is empty")
        keys = self.wiring.keys()
        pacer = self.wiring.pacer(self.clock.timestamp_ns)
        self.gateway = AccountGateway(self.wiring.sdk(keys), pacer, self._position_counts)
        self._closing = False
        ts_init = self.clock.timestamp_ns()
        for iid in self.universe:
            row = await self._call(ActionKind.QUERY, "get", f"/assets/{iid.symbol.value}")
            equity = parse_equity(row, ts_init=ts_init)
            if equity.id != iid:
                raise ValueError("Alpaca asset row does not match the universe")
            self._handle_instrument(equity)
        await self._do_query_account(None)
        loop = asyncio.get_running_loop()
        self._listening = loop.create_future()
        self.stream_live = False
        self._stream = self.wiring.stream(keys)
        self._observe(self._stream)
        self._stream.subscribe_trade_updates(self._on_trade_update)
        self._stream_task = self.create_task(self._stream._run_forever(), "alpaca-trade-updates")

    def _observe(self, stream: Any) -> None:
        """See each socket the SDK opens and each subscription the venue confirms.

        alpaca-py 0.45.0 (`trading/stream.py`) sends the listen request without waiting for
        the venue's acknowledgement, drops that acknowledgement in its dispatcher, and
        reconnects without telling its caller. Wrapping these three methods is how the earlier
        line learned of them; this client runs the stream on the node's own loop.
        """
        dispatch, start, close = stream._dispatch, stream._start_ws, stream.close

        async def observed_dispatch(message: dict) -> None:
            if is_listening_ack(message):
                self._on_stream("listening")
            await dispatch(message)

        async def observed_start() -> None:
            self._on_stream("socket")
            await start()

        async def observed_close() -> None:
            self._on_stream("closed")
            await close()

        stream._dispatch, stream._start_ws, stream.close = (
            observed_dispatch,
            observed_start,
            observed_close,
        )

    def _on_stream(self, kind: str) -> None:
        if kind == "listening":
            first = self._listening is not None and not self._listening.done()
            self.stream_live = True
            if first:
                assert self._listening is not None
                self._listening.set_result(None)
            else:  # resubscribed after a loss: read the gap back
                self._schedule_recovery()
        elif self.stream_live:
            self.stream_restarts += 1
            self.stream_live = False
            self._gap += 1
            self._log().error("Alpaca trade stream lost; the SDK is reconnecting")

    async def _subscribed(self) -> None:
        """Startup reads wait for the venue's subscription acknowledgement, so nothing that
        happens between a read and the subscription is lost. The engine's reconciliation
        timeout bounds the wait."""
        if self._listening is not None:
            await asyncio.shield(self._listening)

    async def _disconnect(self) -> None:
        # Disconnect never cancels orders or closes positions.
        self._closing = True
        self.stream_live = False
        for token in tuple(self._commands):
            if not token.sent:
                self._refuse(token, f"{token.kind} not sent before disconnect")
        actions = tuple(self._actions)
        if self._recovery is not None:
            actions += (self._recovery,)
        for action in actions:
            action.cancel()
        if actions:
            await asyncio.gather(*actions, return_exceptions=True)
        if self._stream is not None:
            self._stream.stop()
            task = self._stream_task
            if task is not None and not task.done():
                # The SDK checks its stop flag between reads (at most 5 s apart); a connect or
                # sign-in that hangs never reaches that check, so it is cancelled after a grace.
                done, _ = await asyncio.wait({task}, timeout=STREAM_STOP_GRACE_SECS)
                if not done:
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self._stream.close()
            self._stream = self._stream_task = None
        if self.gateway is not None:
            await self.gateway.close()

    def _schedule_recovery(self) -> None:
        if self._closing or not self._started:  # during the startup reads, the start decides
            return
        if self._recovery is not None and not self._recovery.done():
            return
        self._recovery = self.create_task(self._recover(), "alpaca-recovery")

    async def _recover(self) -> None:
        """Read every order and the positions again and hand the engine one mass status, as at
        startup, until a read issued after the latest gap succeeds. A lost stream waits for
        its next acknowledgement, which schedules this again."""
        delay, cap = RECOVERY_RETRY_SECS
        while not self._closing and self._covered != self._gap:
            if not self.stream_live:
                return
            if await self._recover_once():
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, cap)

    async def _recover_once(self) -> bool:
        gen, socket = self._gap, self.stream_restarts
        scope: Any = SimpleNamespace(open_only=False, instrument_id=None, start=None, end=None)
        # Stamped before the first read: a fill the stream delivers meanwhile stays newer.
        ts_init = self.clock.timestamp_ns()
        try:
            orders = await self._generate_order_status_reports(scope)
            positions = await self._generate_position_status_reports(scope)
        except Exception as exc:
            self._log().error(f"Alpaca recovery read failed: {type(exc).__name__}")
            return False
        if self._gap != gen or self.stream_restarts != socket or not self.stream_live:
            return False
        # The engine skips the snapshot of an order whose execution reached it since the read
        # began (SNAPSHOT_MARGIN_NS). For that order this read would show the engine nothing:
        # not a fill it lacks, and not a status the stream did not deliver. Read again. A fill
        # the engine infers from a recovery read counts as such an execution (_know_fills), and
        # so does any fill in the engine's own record, such as one its open-order check inferred.
        # A read showing an order with less filled than the engine has or was handed is not
        # handed over either: the engine would void fills on a lagging listing or on a
        # correction Alpaca does not document. Read again; new orders stay denied meanwhile.
        for report in orders:
            venue_id = report.venue_order_id.value
            order = self._engine_order(venue_id, report.client_order_id)
            last = self._last_execution.get(venue_id, 0)
            if last >= ts_init - SNAPSHOT_MARGIN_NS or _fill_since(order, ts_init):
                self._log().warning(
                    "Alpaca recovery reads again: a fill reached the engine during the read "
                    "or just before it"
                )
                return False
            known = max(self._known_filled.get(venue_id, Decimal(0)), _engine_filled(order))
            if report.filled_qty.as_decimal() < known:
                self._log().warning(
                    "Alpaca recovery reads again: the venue shows less filled than the engine has"
                )
                return False
        mass = ExecutionMassStatus(self.client_id, self.account_id, VENUE, ts_init)
        mass.add_order_reports(orders)
        mass.add_position_reports(positions)
        self._know_fills(orders, inferred_at=self.clock.timestamp_ns())
        self._handle_report(mass)
        self._covered = gen
        self.recoveries += 1
        return True

    # ---------------------------------------------------------------- commands

    def _command(self, kind: str, command: Any) -> _Command:
        native = command.order if kind == "submit" else self.cache.order(command.client_order_id)
        return _Command(
            kind,
            native,
            getattr(command, "venue_order_id", None),
            getattr(command, "command_id", None),
        )

    async def _submit_order(self, command: Any) -> None:
        token = self._command("submit", command)
        self._queue(self._do_submit_order(command, token), "alpaca-submit", token)

    async def _cancel_order(self, command: Any) -> None:
        token = self._command("cancel", command)
        self._queue(self._do_cancel_order(command, token), "alpaca-cancel", token)

    async def _query_order(self, command: Any) -> None:
        self._queue(self._do_query_order(command), "alpaca-query-order")

    async def _query_account(self, command: Any) -> None:
        self._queue(self._do_query_account(command), "alpaca-query-account")

    async def _submit_order_list(self, command: Any) -> None:
        for order in command.order_list.orders:
            self.generate_order_denied(order, NOT_SUPPORTED)

    async def _modify_order(self, command: Any) -> None:
        native = self.cache.order(command.client_order_id)
        if native is not None:
            self.generate_order_modify_denied(
                native, NOT_SUPPORTED, self.clock.timestamp_ns(), command.command_id
            )

    async def _cancel_all_orders(self, command: Any) -> None:
        raise NotImplementedError("account-wide cancellation is not part of this lane")

    def _submit_admitted(self) -> bool:
        return self.coverage_complete and not self.foreign_writer_seen

    async def _do_submit_order(self, command: Any, token: _Command) -> None:
        native = command.order
        try:
            payload = submit_payload(native, self.house_prefix)
        except ValueError as exc:
            token.settled = True
            self.generate_order_denied(native, str(exc))
            return
        if not self._submit_admitted():
            token.settled = True
            self.generate_order_denied(native, "account view incomplete: no new order")
            return
        self.generate_order_submitted(native)
        token.submitted = True
        root = str(native.client_order_id)
        self._submissions[root] = token
        kind = ActionKind.REDUCE if native.is_sell else ActionKind.SUBMIT
        try:
            row = await self._call(
                kind,
                "post",
                "/orders",
                payload,
                admission=lambda: not token.withdrawn and self._submit_admitted(),
                on_wire=lambda: self._mark_sent(token),
            )
        except Exception as exc:
            if _unresolved(exc, token):
                # Sent: the venue's later status decides, never a local reject.
                self._log().warning(f"Alpaca submit outcome unknown ({type(exc).__name__})")
                return
            reason = "venue refused the order" if token.sent else f"not sent: {_why(exc)}"
            self._refuse(token, reason)
            return
        finally:
            if self._submissions.get(root) is token:
                self._submissions.pop(root)
        token.settled = True
        # An answer the lane cannot read or map, or another order's row, is a gap (`_reading`);
        # the stream or the gap's read then shows the engine this order.
        with contextlib.suppress(Exception), self._reading():
            report = self._order_report(row)
            if report.client_order_id != native.client_order_id:
                raise ValueError("venue answered with another order")
            self._volunteer(report)

    async def _current(self, command: Any) -> tuple[dict, Any]:
        """The venue's row of the order a cancel targets, and its report. A row of another
        order, or one without a venue id, is a gap that refuses the cancel; a row the lane
        cannot map is a gap with no report (None), and settles no earlier cancel."""
        issued = self._now()
        root = house_id(str(command.client_order_id), self.house_prefix)
        venue = command.venue_order_id or self.cache.venue_order_id(command.client_order_id)
        if venue is not None:
            row = await self._call(ActionKind.QUERY, "get", f"/orders/{venue}")
        else:
            row = await self._call(
                ActionKind.QUERY, "get", "/orders:by_client_order_id", {"client_order_id": root}
            )
        with self._reading():
            if not isinstance(row, dict) or row.get("client_order_id") != root:
                raise ValueError("venue order is outside the requested namespace")
            if not isinstance(row.get("id"), str) or not row["id"]:
                raise ValueError("Alpaca order report requires its venue and client order ids")
        try:
            with self._reading():
                report = self._order_report(row)
        except Exception:
            return row, None
        self._settle(row, issued)
        return row, report

    async def _do_cancel_order(self, command: Any, token: _Command) -> None:
        native = token.native
        try:
            root = house_id(str(command.client_order_id), self.house_prefix)
            pending = self._submissions.get(root)
            if pending is not None and not pending.sent:
                # Withdrawn while queued: the pacer's admission drops it; nothing was sent.
                pending.withdrawn = pending.settled = token.settled = True
                if native is not None:
                    self.generate_order_canceled(native, None, self.clock.timestamp_ns())
                return
            row, report = await self._current(command)
            token.row_id, token.venue_order_id = row["id"], VenueOrderId(row["id"])
            if row.get("status") in TERMINAL:
                token.settled = True
                if report is not None:
                    self._volunteer(report)
                return
            # A working row the lane cannot map is a gap (`_current`); the DELETE still goes
            # to the lane's own order, by the venue id its read returned.
            if row["id"] in self._pending or row["id"] in self._cancelling:
                token.settled = True  # one unresolved cancel per order; never re-cancel
                return
            # The slot is taken before the request enters the budget, so a second cancel
            # command that reads the order meanwhile sends nothing either.
            self._cancelling[row["id"]] = token
            try:
                await self._call(
                    ActionKind.CANCEL,
                    "delete",
                    f"/orders/{row['id']}",
                    admission=lambda: not token.withdrawn,
                    on_wire=lambda: self._mark_sent(token),
                    on_end=lambda: setattr(token, "ended", self._now()),
                )
            finally:
                if self._cancelling.get(row["id"]) is token:
                    del self._cancelling[row["id"]]
            # DELETE answers 204 for an attempt; the terminal event or a read settles it.
            token.settled = True
        except Exception as exc:
            if _unresolved(exc, token):
                self._log().warning(f"Alpaca cancel outcome unknown ({type(exc).__name__})")
                return
            reason = "venue refused the cancel" if token.sent else f"not sent: {_why(exc)}"
            self._refuse(token, reason)

    async def _do_query_order(self, command: Any) -> None:
        report = await self._generate_order_status_report(command)
        if report is not None:
            self._volunteer(report)

    async def _do_query_account(self, command: Any) -> None:
        row = await self._call(ActionKind.QUERY, "get", "/account")
        # Net value as total, available funds clamped to it, locked derived after rounding:
        # the earlier line's reading of NautilusTrader's IBKR account mapping.
        total = decimal_text(row.get("equity"), "account equity")
        available = decimal_text(row.get("buying_power"), "account buying power")
        decimal_text(row.get("cash"), "account cash")
        currency = row.get("currency")
        if currency != "USD":
            raise ValueError("Alpaca account currency must be USD")
        if total >= 0:
            available = min(total, max(Decimal(0), available))
        total_money = Money.from_str(f"{total} USD")
        free_money = Money.from_str(f"{available} USD")
        locked = total_money.as_decimal() - free_money.as_decimal()
        self.generate_account_state(
            [AccountBalance(total_money, Money.from_str(f"{locked} USD"), free_money)],
            [],
            True,
            self.clock.timestamp_ns(),
        )

    # ---------------------------------------------------------------- reconciliation

    async def _generate_order_status_report(self, command: Any) -> Any:
        issued = self._now()
        venue = command.venue_order_id
        try:
            if venue is not None:
                row = await self._call(ActionKind.QUERY, "get", f"/orders/{venue}")
            elif command.client_order_id is not None:
                row = await self._call(
                    ActionKind.QUERY,
                    "get",
                    "/orders:by_client_order_id",
                    {"client_order_id": str(command.client_order_id)},
                )
            else:
                return None
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise
        # As for a listing's row: an answer the lane cannot read or map is a gap. A row settles
        # an earlier cancel only once it maps, as this order's.
        with self._reading():
            check_one_writer(row, self.house_prefix)
            if withheld_unloaded(row, self._is_loaded) or unmappable_history(row):
                return None
            report = self._order_report(row)
            if (
                command.client_order_id is not None
                and report.client_order_id != command.client_order_id
            ):
                raise ValueError("venue answered with another order")
            self._settle(row, issued)
        return report

    async def _generate_order_status_reports(self, command: Any) -> list:
        await self._subscribed()
        issued, gen, full = self._now(), self._gap, _is_full_listing(command)
        startup, bounds = not self._started, _bounds(command)
        requests: list[BaseException] = []
        with traced(self.report_trace, "orders") as trace:
            call, pages = self._traced_call(trace, requests), self._max_pages()
            with self._reading(requests):
                params = {"status": "open" if command.open_only else "all", "nested": True}
                rows = await list_orders(call, {**params, **bounds}, max_pages=pages)
                if getattr(command, "start", None) is not None:
                    # A submission-time window cannot cover older orders still working.
                    opened = await list_orders(
                        call, {"status": "open", "nested": True}, max_pages=pages
                    )
                    rows = merge_listings(rows, opened)
                trace.rows = len(rows)
                reports, failures, withheld = [], [], set()
                for row in rows:
                    try:
                        check_one_writer(row, self.house_prefix)
                        if withheld_unloaded(row, self._is_loaded):
                            trace.withheld_unloaded += 1
                            withheld.add(row["symbol"])  # text: `withheld_unloaded` read it
                            continue
                        if unmappable_history(row):
                            trace.withheld_unmapped += 1
                            continue
                        report = self._order_report(row)
                        self._settle(row, issued)  # only a row that maps settles a cancel
                        reports.append(report)
                    except Exception as exc:
                        failures.append((None, exc))
                if failures:
                    self.failures.extend(failures)
                    raise IncompleteCoverage(reports, failures)
        self.withheld_symbols |= withheld
        if startup:
            self._know_fills(reports)
            if full:
                self._startup_stage_done("orders", gen)
        return reports

    async def _generate_fill_reports(self, command: Any) -> list:
        await self._subscribed()
        requests: list[BaseException] = []
        with traced(self.report_trace, "fills") as trace:
            call, pages = self._traced_call(trace, requests), self._max_pages()
            params = _bounds(command)
            params.pop("symbols", None)
            if getattr(command, "instrument_id", None) is not None:
                params["symbol"] = command.instrument_id.symbol.value
            # After startup the engine asks for fills only in its position checks, if set.
            with self._reading(requests):
                # The whole order history first: a fill in the window may be an older order's,
                # and its oldest submission bounds how far back the FILL pages need reading.
                orders = await list_orders(call, {"status": "all", "nested": True}, max_pages=pages)
                fills = await list_fill_activities(
                    call,
                    params,
                    max_pages=pages,
                    horizon_ns=oldest_submission(orders),
                    trace=trace,
                )
                trace.rows = len(fills)
                explain_fills(fills, orders, trace, self._is_loaded)
        return []

    async def _generate_position_status_reports(self, command: Any) -> list:
        await self._subscribed()
        gen = self._gap
        with traced(self.report_trace, "positions") as trace:
            trace.count_request("get", "/positions")
            rows = await self._call(ActionKind.QUERY, "get", "/positions")
            with self._reading():
                if not isinstance(rows, list):
                    raise IncompleteCoverage(
                        [], [(None, ValueError("Alpaca positions are not a list"))]
                    )
                trace.rows = len(rows)
                reports, failures = [], []
                for row in rows:
                    try:
                        symbol = row_symbol(row)  # unreadable: refused, never withheld
                        if not self._is_loaded(symbol):
                            trace.withheld_unloaded += 1
                            self.withheld_symbols.add(symbol)
                            continue
                        reports.append(
                            position_status_report(
                                row,
                                account_id=self.account_id,
                                instrument=self._instrument(symbol),
                                ts_init=self.clock.timestamp_ns(),
                            )
                        )
                    except Exception as exc:
                        failures.append((None, exc))
                if failures:
                    self.failures.extend(failures)
                    raise IncompleteCoverage(reports, failures)
        self._startup_stage_done("positions", gen)
        return reports

    def _startup_stage_done(self, stage: str, gen: int) -> None:
        """The engine runs the startup stages concurrently, in no fixed order. Once both the
        full order listing and the positions have been read, each since the latest gap, the
        view is covered; a gap during the reads is read back once startup has passed. After
        startup, `_recover_once` alone decides coverage."""
        if self._started:
            return
        self._startup_gens[stage] = gen
        if not {"orders", "positions"} <= self._startup_gens.keys():
            return
        self._started = True
        if self._startup_gens["orders"] == self._startup_gens["positions"] == self._gap:
            self._covered = self._gap
        else:
            self._schedule_recovery()

    def _provides_bulk_position_coverage(self, instrument_id: Any) -> bool:
        # A withheld row never lets the engine infer "flat" for its instrument.
        return self.coverage_complete and instrument_id.symbol.value not in self.withheld_symbols

    def _calculate_commission(self, instrument, last_qty, last_px, liquidity_side) -> Any:
        return self.commission

    # ---------------------------------------------------------------- trade updates

    async def _on_trade_update(self, message: dict) -> None:
        """Every update is classified and its safety facts recorded before anything else."""
        try:
            update = parse_trade_update(message)
        except UnclassifiedTradeUpdate as exc:
            self._incomplete(exc)
            return
        late, answered = self._record(update)
        try:
            self._process(update, late, answered)
        except Exception as exc:
            self._incomplete(exc)

    def _record(self, update: TradeUpdate) -> tuple[bool, _Command | None]:
        """Synchronous, on arrival: the cancel this update answers, if any, and whether it is
        a refusal that a read already emitted (late)."""
        venue_id, late, answered = update.venue_order_id, False, None
        if update.is_terminal:
            answered = self._resolve(venue_id)
            self._owed.pop(venue_id, None)
        if update.event == "order_cancel_rejected":
            if self._owed.get(venue_id):
                self._owed[venue_id] -= 1
                late = True
            else:
                answered = self._resolve(venue_id)
                late = answered is None and venue_id in self._cancel_seen
        self.late_answers += late
        return late, answered

    def _process(self, update: TradeUpdate, late: bool, answered: _Command | None) -> None:
        loaded = self._is_loaded(update.symbol)
        if not self._is_house(update.client_order_id):
            # One writer per account: another writer is acting on it. New orders stop until
            # a restart reconciles; the engine still hears about the lane's own symbols.
            self.foreign_writer_seen = True
            self._log().error(f"another writer's order changed in {update.symbol}")
            if loaded:
                self._forward(update)
            return
        if not loaded:
            raise ValueError("house order outside the loaded universe")
        if update.event in REPLACE_EVENTS:
            raise ValueError("house order replaced at the venue; this lane never modifies")
        native = self.cache.order(ClientOrderId(update.client_order_id))
        if update.event == "order_cancel_rejected":
            if native is not None and not late:
                self.generate_order_cancel_rejected(
                    native,
                    VenueOrderId(update.venue_order_id),
                    "venue refused the cancel",
                    update.ts_event,
                    answered.command_id if answered is not None else None,
                )
            return
        self._forward(update)

    def _forward(self, update: TradeUpdate) -> None:
        """Hand the engine a status report, or an execution it does not have yet.

        A fill update's order row carries the order's filled quantity after that execution.
        The engine has the order's fills up to `_known`, so an execution is one of:
        - already forwarded (the same execution id again): counted, not handed on;
        - at or below the known quantity: a startup or recovery read, or the engine's routine
          open-order check, showed the engine this fill first and it inferred it from the order
          report, so handing the execution on would count it twice. Counted, not handed on;
        - the next one (it starts exactly at the known quantity): handed on;
        - anything else (an execution before it has not arrived, or the row contradicts
          itself): a gap. It is withheld, because once it were forwarded the missing one would
          look known when it arrives; the gap's full read shows the engine the order instead.

        Not verified on the wire: that the row is the order after the execution. If it were the
        order before it, an order's first execution would be a gap, but a later one would sit
        at or below the known quantity and be dropped as known, leaving the engine behind the
        venue with no gap. Quantity alone cannot tell the two apart.

        An update that is not a fill and shows more filled than the engine has is withheld
        and is a gap: the engine has not been handed a fill the venue made before this state,
        and a read already under way may have listed the order before it. That read is not
        handed over; the next one shows the engine the order.
        """
        if not update.is_fill:
            if not self._volunteer(self._order_report(update.order)):
                raise ValueError("order update shows a fill the engine has not been handed")
            return
        if self.commission is None:
            raise ValueError("fill commission evidence unavailable")
        venue_id = update.venue_order_id
        key = (venue_id, str(update.execution_id))
        if key in self._forwarded:
            self.duplicate_executions += 1
            return
        qty = update.qty or Decimal(0)
        after = decimal_text(update.order.get("filled_qty"), "filled quantity")
        known = self._known(venue_id, update.client_order_id)
        if qty <= after <= known:
            self.known_executions += 1
            return
        if after - qty != known:
            raise ValueError("fill does not continue from the filled quantity the engine has")
        now = self.clock.timestamp_ns()
        report = make_fill_report(
            update.data,
            account_id=self.account_id,
            instrument=self._instrument(update.symbol),
            ts_init=now,
            commission=self.commission,
        )
        self._forwarded.add(key)
        self._known_filled[venue_id] = after
        self._last_execution[venue_id] = now
        self._handle_report(report)
