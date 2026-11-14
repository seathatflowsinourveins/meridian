"""The strategy template: one state machine per symbol, a dynamic trail, a fast sell, re-entry.

Upstream template (NautilusTrader v2.0.0rc9, commit da6b57aefdd62b44f675e434ffcfefca7f4025dd):
`python/tests/strategies/acceptance.py:515-700`, `_EMACrossTrailingWorkflow` and
`EMACrossTrailingStop`: after an entry fills, submit an emulated trailing stop whose offset is
ATR x `trailing_atr_multiple`. Kept from it: that offset rule and engine-side trailing. Changed
here: many symbols, one book each; `TRAILING_STOP_LIMIT` instead of `TRAILING_STOP_MARKET`,
because the paper lanes take plain DAY LIMIT orders only (`meridian/alpaca/wire.py`,
`submit_payload`); long only; quotes instead of bars; re-entry rules; no close on stop.

What the engine does, not this file (`docs/concepts/orders/emulated.md` at the tag):
- the ratchet: the `OrderEmulator` trails the trigger behind the best bid and moves it in the
  position's favour only (`crates/execution/src/trailing.rs`); modifications of held
  emulated orders bypass the `RiskEngine` and reach no venue (emulated.md:73);
- the fast sell: on the first quote whose bid reaches the trigger, the emulator transforms the
  order into a LIMIT and releases it with the same client order id (emulated.md:67-69, :127);
- the measure: `AverageTrueRange` (`crates/indicators/src/volatility/atr.rs:143-170`).

Per-symbol movement, measured: each quote's mid goes into that symbol's own ATR as high = low =
close with `use_previous`, so its true range is |mid - previous mid| and the ATR is the simple
mean of the last `atr_period` quote-to-quote mid changes. At each entry the trail distance is
max(`trail_atr_multiple` x ATR, `trail_floor_bps` of the mid), rounded up to the tick.

Exit price: the emulated order's limit offset is the trail distance plus `exit_limit_buffer_bps`
of the mid, so the released LIMIT sells up to that buffer under its trigger: marketable unless
the bid gapped below it. Then the template cancels it and, once that cancel is final, re-prices
the remainder at the bid less the buffer on the next quote: one unresolved order per symbol.

Re-entry (`docs/HANDBOOK.md`, "Re-entry and rotation"): R1 in `_check_flat` (the flat receipt)
and `_reentry_refusal` (the cooldown from it); R2's retry band and R5's missing ranking in
`_reentry_refusal` through `rank()` (rotation into another name is a portfolio decision, made
above the template); R3a in `_on_release` (stop-outs before the gain lock) and
`_reentry_refusal` (`reclaim_qualified()`); confidence and size in `_reentry_refusal`. R3, R3b
and R4 are the concrete strategy's (`entry_signal`, `reclaim_qualified`, rotation). R6: paper
re-entry has no count cap here; a lane that keeps re-entry off passes `reentry_enabled=False`.

Rate: no handler blocks or sleeps; every order action is counted in `self.actions`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum
from typing import Any

from nautilus_trader.indicators import AverageTrueRange, MovingAverageType
from nautilus_trader.model import (
    ClientId,
    ClientOrderId,
    InstrumentId,
    OrderReleased,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    StrategyId,
    TimeInForce,
    TrailingOffsetType,
    TriggerType,
)
from nautilus_trader.trading import Strategy, StrategyConfig

from meridian.order_budget.pacer import ActionKind

from .actions import LOCAL, NS_PER_SECOND, ActionLog
from .params import BPS, TemplateParams


class Phase(Enum):
    FLAT = "flat"  # nothing held, nothing working; may enter
    ENTERING = "entering"  # the entry is the one unresolved order
    HOLDING = "holding"  # the emulated trailing stop is the one unresolved order
    EXITING = "exiting"  # released or re-priced exit at the venue, or about to re-price


@dataclass(slots=True)
class SymbolBook:
    """One symbol's state machine. Nothing in it is shared with another symbol."""

    instrument_id: InstrumentId
    tick: Decimal
    atr: AverageTrueRange
    phase: Phase = Phase.FLAT
    order_id: ClientOrderId | None = None
    cancel_sent: bool = False
    submitted_ns: int = 0
    bid: Decimal | None = None
    ask: Decimal | None = None
    entry_px: Decimal | None = None
    held: Decimal = Decimal(0)
    sold: Decimal = Decimal(0)
    trail_distance: Decimal | None = None
    trigger: Decimal | None = None
    triggers: list[tuple[int, str]] = field(default_factory=list)
    ratchets: int = 0
    loosened: int = 0
    entries: list[int] = field(default_factory=list)
    releases: list[int] = field(default_factory=list)
    flat_receipt_ns: int | None = None
    exits: int = 0
    stopouts_in_row: int = 0
    refusals: Counter[str] = field(default_factory=Counter)
    events: list[str] = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return str(self.instrument_id)

    def report(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "entries": len(self.entries),
            "exits": self.exits,
            "trail_ratchets": self.ratchets,
            "trail_loosened": self.loosened,
            "stopouts_in_row": self.stopouts_in_row,
            "refusals": dict(sorted(self.refusals.items())),
            "events": self.events,
        }


def _ceil(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def _floor(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


class TrailingTemplate(Strategy):
    """Subclass and implement `entry_signal`; override the other hooks as the strategy needs."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        # The engine's Strategy is a native class whose __new__ takes only a config.
        return super().__new__(cls)

    def __init__(
        self,
        params: TemplateParams,
        instrument_ids: Iterable[InstrumentId],
        *,
        strategy_id: str,
        client_id: ClientId | None = None,
    ) -> None:
        if not isinstance(params, TemplateParams):
            raise TypeError("TrailingTemplate refuses to start without TemplateParams")
        ids = list(instrument_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("TrailingTemplate needs distinct instrument ids")
        super().__init__(StrategyConfig(strategy_id=StrategyId(strategy_id)))
        self.params = params
        self.instrument_ids = ids
        self.client_id = client_id
        self.books: dict[InstrumentId, SymbolBook] = {}
        self.actions = ActionLog()
        self._by_order: dict[ClientOrderId, SymbolBook] = {}

    # Hooks for the concrete strategy. They must not block.
    def observe(self, book: SymbolBook, quote: QuoteTick) -> None:
        """Every usable quote, before the template decides anything for that symbol."""

    def entry_signal(self, book: SymbolBook, quote: QuoteTick) -> bool:
        raise NotImplementedError("a concrete strategy says when its setup fires")

    def rank(self, book: SymbolBook) -> int | None:
        """The symbol's current rank (1 is best); None means missing, stale or ambiguous."""
        return None

    def confidence(self, book: SymbolBook) -> Decimal | None:
        return None

    def reclaim_qualified(self, book: SymbolBook, quote: QuoteTick) -> bool:
        """R3a: after the whipsaw limit, a capped reclaim or a qualifying OVERSELL."""
        return False

    def entry_price(self, book: SymbolBook, quote: QuoteTick) -> Decimal:
        """A marketable buy: up to entry_limit_buffer_bps above the ask, up to the tick."""
        ask = quote.ask_price.as_decimal()
        return _ceil(ask * (1 + self.params.entry_limit_buffer_bps / BPS), book.tick)

    # Engine callbacks.
    def on_start(self) -> None:
        for iid in self.instrument_ids:
            instrument = self.cache.instrument(iid)
            if instrument is None:
                self.log.error(f"no instrument {iid}: symbol not started")
                continue
            atr = AverageTrueRange(
                self.params.atr_period, ma_type=MovingAverageType.Simple, use_previous=True
            )
            self.books[iid] = SymbolBook(iid, instrument.price_increment.as_decimal(), atr)
            self.subscribe_quotes(iid, client_id=self.client_id)

    def on_stop(self) -> None:
        # No stop-time cancel or close, as in the lanes: the owner inspects what is left.
        for iid in self.books:
            self.unsubscribe_quotes(iid, client_id=self.client_id)

    def on_quote(self, quote: QuoteTick) -> None:
        book = self.books.get(quote.instrument_id)
        if book is None:
            return
        bid, ask = quote.bid_price.as_decimal(), quote.ask_price.as_decimal()
        if bid <= 0 or ask < bid:
            return
        book.bid, book.ask = bid, ask
        mid = float((bid + ask) / 2)
        book.atr.update_raw(mid, mid, mid)
        self.observe(book, quote)
        if book.phase is Phase.FLAT:
            self._maybe_enter(book, quote)
        elif book.phase is Phase.ENTERING:
            self._entry_timeout(book, quote.ts_event)
        elif book.phase is Phase.HOLDING:
            self._watch_trail(book, quote.ts_event)
        else:
            self._work_exit(book, quote)

    def on_order_event(self, event: Any) -> None:
        book = self._by_order.get(event.client_order_id)
        if book is None or event.client_order_id != book.order_id:
            return
        if isinstance(event, OrderReleased):
            self._on_release(book, event.ts_event)
        order = self.cache.order(event.client_order_id)
        if order is not None and order.is_closed:
            self._resolve(book, order, event.ts_event)

    def on_position_event(self, event: Any) -> None:
        book = self.books.get(event.instrument_id)
        if book is not None:
            self._check_flat(book, event.ts_event)

    # The state machine.
    def _maybe_enter(self, book: SymbolBook, quote: QuoteTick) -> None:
        if not book.atr.initialized or not self.entry_signal(book, quote):
            return
        if not self._is_flat(book.instrument_id):
            book.refusals["not flat"] += 1
            return
        qty: int | None = self.params.base_quantity
        if book.exits:
            refusal, qty = self._reentry_refusal(book, quote)
            if refusal:
                book.refusals[refusal] += 1
                return
        price = Price.from_str(format(self.entry_price(book, quote), "f"))
        order = self.order_factory.limit(
            book.instrument_id,
            OrderSide.BUY,
            Quantity.from_int(qty),
            price,
            time_in_force=TimeInForce.DAY,
        )
        book.entries.append(quote.ts_event)
        book.events.append("reentry" if book.exits else "entry")
        if not self._send(book, order, ActionKind.SUBMIT, "entry", quote.ts_event, Phase.ENTERING):
            book.entries.pop()
            book.events.pop()

    def _reentry_refusal(self, book: SymbolBook, quote: QuoteTick) -> tuple[str | None, int]:
        p = self.params
        if not p.reentry_enabled:
            return "re-entry off", 0
        if book.flat_receipt_ns is None:  # R1
            return "no flat receipt", 0
        if quote.ts_event < book.flat_receipt_ns + int(p.cooldown_seconds * NS_PER_SECOND):
            return "cooldown", 0
        rank = self.rank(book)
        if rank is None:  # R5
            return "no ranking", 0
        if rank > p.retry_rank_band:  # R2
            return "rank outside the retry band", 0
        if book.stopouts_in_row >= p.whipsaw_stopouts_max and not self.reclaim_qualified(
            book, quote
        ):  # R3a
            return "whipsaw: needs a reclaim or oversell", 0
        confidence = self.confidence(book)
        if confidence is None:
            return "no confidence", 0
        if not 0 <= confidence <= 1 or confidence < p.reentry_min_confidence:
            return "confidence under the minimum", 0
        scale = p.confidence_size_floor + (1 - p.confidence_size_floor) * confidence
        qty = int(_floor(p.base_quantity * scale, Decimal(1)))
        if qty < 1:
            return "size under one share", 0
        return None, qty

    def _entry_timeout(self, book: SymbolBook, ts_ns: int) -> None:
        timeout_ns = int(self.params.entry_timeout_seconds * NS_PER_SECOND)
        order = self._order(book)
        if book.cancel_sent or order is None or not order.is_open:
            return
        if ts_ns - book.submitted_ns >= timeout_ns:
            self._cancel(book, "cancel-entry", ts_ns)

    def _protect(self, book: SymbolBook, ts_ns: int) -> None:
        p, tick = self.params, book.tick
        assert book.bid is not None and book.ask is not None
        mid = (book.bid + book.ask) / 2
        atr = Decimal(str(book.atr.value))
        distance = max(
            _ceil(max(atr * p.trail_atr_multiple, mid * p.trail_floor_bps / BPS), tick), tick
        )
        buffer = max(_ceil(mid * p.exit_limit_buffer_bps / BPS, tick), tick)
        book.trail_distance, book.trigger = distance, None
        order = self.order_factory.trailing_stop_limit(
            book.instrument_id,
            OrderSide.SELL,
            Quantity.from_str(format(book.held, "f")),
            None,
            limit_offset=distance + buffer,
            trailing_offset=distance,
            trailing_offset_type=TrailingOffsetType.PRICE,
            trigger_type=TriggerType.BID_ASK,
            time_in_force=TimeInForce.DAY,
            emulation_trigger=TriggerType.BID_ASK,
        )
        self._send(book, order, LOCAL, "protect", ts_ns, Phase.HOLDING)

    def _watch_trail(self, book: SymbolBook, ts_ns: int) -> None:
        order = self._order(book)
        if order is None or not order.is_emulated or order.trigger_price is None:
            return
        trigger = order.trigger_price.as_decimal()
        if book.trigger is not None and trigger < book.trigger:
            book.loosened += 1
        elif book.trigger is not None and trigger > book.trigger:
            book.ratchets += 1
        if trigger != book.trigger:
            book.trigger = trigger
            book.triggers.append((ts_ns, format(trigger, "f")))

    def _on_release(self, book: SymbolBook, ts_ns: int) -> None:
        self.actions.record(ts_ns, ActionKind.REDUCE, book.symbol, "release")
        book.phase, book.cancel_sent, book.submitted_ns = Phase.EXITING, False, ts_ns
        book.releases.append(ts_ns)
        book.events.append("fast-exit")
        trigger, entry = book.trigger, book.entry_px
        if trigger is not None and entry is not None and trigger >= entry:  # gain lock armed
            book.stopouts_in_row = 0
        else:
            book.stopouts_in_row += 1

    def _work_exit(self, book: SymbolBook, quote: QuoteTick) -> None:
        order = self._order(book)
        bid = quote.bid_price.as_decimal()
        if order is not None and not order.is_closed:
            if order.is_open and not book.cancel_sent and order.price.as_decimal() > bid:
                self._cancel(book, "cancel-exit", quote.ts_event)  # gapped through: re-price
            return
        remaining = book.held - book.sold
        price = _floor(bid * (1 - self.params.exit_limit_buffer_bps / BPS), book.tick)
        if remaining <= 0 or price <= 0:
            return
        exit_order = self.order_factory.limit(
            book.instrument_id,
            OrderSide.SELL,
            Quantity.from_str(format(remaining, "f")),
            Price.from_str(format(price, "f")),
            time_in_force=TimeInForce.DAY,
        )
        if self._send(
            book, exit_order, ActionKind.REDUCE, "reprice", quote.ts_event, Phase.EXITING
        ):
            book.events.append("reprice")

    def _resolve(self, book: SymbolBook, order: Any, ts_ns: int) -> None:
        filled = order.filled_qty.as_decimal()
        self._by_order.pop(order.client_order_id, None)
        if book.phase is Phase.ENTERING:
            book.order_id = None
            if filled > 0:
                book.entry_px = Decimal(str(order.avg_px))
                book.held, book.sold = filled, Decimal(0)
                self._protect(book, ts_ns)
            else:
                book.phase = Phase.FLAT
                book.entries.pop()
                book.events.append("entry-unfilled")
            return
        # HOLDING (the emulated stop ended unreleased) or EXITING: sell what is left.
        book.sold += filled
        book.order_id = None
        book.phase = Phase.EXITING
        self._check_flat(book, ts_ns)

    def _check_flat(self, book: SymbolBook, ts_ns: int) -> None:
        """R1's flat receipt: net zero and every order final; unknown or partial is not flat."""
        if book.phase is not Phase.EXITING or self._order(book) is not None:
            return
        if book.held - book.sold > 0 or not self._is_flat(book.instrument_id):
            return
        book.phase, book.flat_receipt_ns = Phase.FLAT, ts_ns
        book.exits += 1
        book.events.append("flat")

    # Orders: one unresolved per symbol, every action counted.
    def _order(self, book: SymbolBook) -> Any:
        return None if book.order_id is None else self.cache.order(book.order_id)

    def _is_flat(self, iid: InstrumentId) -> bool:
        cache = self.cache
        return not (
            cache.positions_open(instrument_id=iid)
            or cache.orders_open(instrument_id=iid)
            or cache.orders_inflight(instrument_id=iid)
            or cache.orders_emulated(instrument_id=iid)
        )

    def _send(
        self, book: SymbolBook, order: Any, kind: Any, what: str, ts_ns: int, phase: Phase
    ) -> bool:
        current = self._order(book)
        if book.order_id is not None and (current is None or not current.is_closed):
            book.refusals["one unresolved order"] += 1
            return False
        # State first: a simulated venue can answer inside submit_order.
        book.order_id, book.cancel_sent, book.submitted_ns = order.client_order_id, False, ts_ns
        book.phase = phase
        self._by_order[order.client_order_id] = book
        self.actions.record(ts_ns, kind, book.symbol, what)
        self.submit_order(order, client_id=self.client_id)
        return True

    def _cancel(self, book: SymbolBook, what: str, ts_ns: int) -> None:
        assert book.order_id is not None
        book.cancel_sent = True
        self.actions.record(ts_ns, ActionKind.CANCEL, book.symbol, what)
        self.cancel_order(book.order_id, client_id=self.client_id)
