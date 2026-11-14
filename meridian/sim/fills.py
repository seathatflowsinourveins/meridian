"""Alpaca paper's random partial fills, as a Python subclass of the engine's `FillModel`.

Alpaca's paper page (https://docs.alpaca.markets/us/docs/paper-trading, "Fill assumptions",
read 2026-11-14): "When orders are eligible to be filled, they will receive partial fills for
a random size 10% of the time. If the order price is still marketable, the remaining quantity
would be re-evaluated for a subsequent fill."

The extension point (NautilusTrader v2.0.0rc9, da6b57aefdd62b44f675e434ffcfefca7f4025dd):
`docs/concepts/backtesting/fill-models.md` "Custom fill models": a Python object passed as
`fill_model` implements `is_limit_filled` and `is_slipped`, and may return a synthetic
`OrderBook` from `get_orderbook_for_fill_simulation`; a book restricts the fill to its
liquidity and is not topped up, and `None` keeps the standard fill logic. The matching engine
asks that hook each time it fills a LIMIT order (`crates/execution/src/matching_engine/mod.rs`,
`determine_limit_fill_model_price_and_volume`), so a remainder that is still marketable is
re-evaluated on a later quote, with a fresh draw, as the page says.

Only LIMIT orders are drawn: the lanes send nothing else to the venue (`runner`'s
`orders_not_day_limit`), and rc9 does not re-evaluate a MARKET remainder. Each draw comes from
this model's own `random.Random(seed)`: the same seed gives the same fills run to run. The
engine reuses one instance across runs (fill-models.md), so `venue.venue_config` builds a new
one per run.
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Any

from nautilus_trader.execution import FillModel
from nautilus_trader.model import (
    BookOrder,
    BookType,
    OrderBook,
    OrderSide,
    OrderType,
    Price,
    Quantity,
)

# Alpaca's paper page, above: "partial fills for a random size 10% of the time".
ALPACA_PAPER_PARTIAL_RATE = 0.1


class PaperFillModel(FillModel):
    """The engine's L1 fill with seeded touch and slip draws, and Alpaca's partial fills."""

    def __init__(
        self,
        *,
        prob_fill_on_limit: float = 1.0,
        prob_slippage: float = 0.0,
        partial_rate: float = ALPACA_PAPER_PARTIAL_RATE,
        random_seed: int = 0,
    ) -> None:
        super().__init__()
        for p in (prob_fill_on_limit, prob_slippage, partial_rate):
            if not 0.0 <= p <= 1.0:
                raise ValueError("fill probabilities must lie in [0, 1]")
        self.prob_fill_on_limit, self.prob_slippage = prob_fill_on_limit, prob_slippage
        self.partial_rate = partial_rate
        # Separate streams, so turning slippage on does not move the partial-fill draws.
        self._touch, self._slip, self._partial = (
            random.Random(f"{random_seed}:{name}") for name in ("touch", "slip", "partial")
        )
        self.partial_fills = 0  # partial books returned
        self.fill_attempts = 0  # LIMIT fill attempts drawn

    def is_limit_filled(self) -> bool:
        return self._touch.random() < self.prob_fill_on_limit

    def is_slipped(self) -> bool:
        return self._slip.random() < self.prob_slippage

    def partial_quantity(self, leaves: int) -> int | None:
        """One draw: None (fill as usual) or a random part of `leaves`, 1 to leaves - 1."""
        self.fill_attempts += 1
        if self._partial.random() >= self.partial_rate or leaves < 2:
            return None
        self.partial_fills += 1
        return self._partial.randint(1, leaves - 1)

    def get_orderbook_for_fill_simulation(
        self,
        instrument: Any,
        order: Any,
        best_bid: Price | None = None,
        best_ask: Price | None = None,
    ) -> OrderBook | None:
        if order.order_type != OrderType.LIMIT or best_bid is None or best_ask is None:
            return None
        qty = self.partial_quantity(int(Decimal(str(order.leaves_qty))))
        if qty is None:
            return None
        # The opposite side's top of book, with only `qty` on it: the fill stops there.
        book = OrderBook(instrument.id, BookType.L2_MBP)
        side, price = (
            (OrderSide.SELL, best_ask) if order.side == OrderSide.BUY else (OrderSide.BUY, best_bid)
        )
        size = Quantity(qty, instrument.size_precision)
        book.add(BookOrder(side, price, size, 1), 0, 0, 0)
        return book
