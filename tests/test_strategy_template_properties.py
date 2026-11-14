"""Property tests of the strategy template's trailing and re-entry invariants.

Offline and synthetic, through the engine's own `BacktestEngine` exactly as
`tests/test_strategy_template.py` and `sim.py` do it: Hypothesis draws quote paths and the
template's parameters, and each test drives `sim.run` over them. The parameters are arbitrary
values chosen for the test, not calibrated ones; the paths are generated in this process and
are not market data.

Bounded on purpose: at most 50 examples, at most 96 quotes per path, `derandomize=True`, and no
deadline, so the file is deterministic and fits the suite.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from nautilus_trader.model import OrderSide

from meridian.strategy_template import TemplateParams, sim
from meridian.strategy_template.actions import NS_PER_SECOND

BASE_PARAMS = TemplateParams.from_config(sim.SIM_PARAMS)
assert BASE_PARAMS.provenance == sim.SYNTHETIC  # synthetic, uncalibrated test values

PROPERTIES = settings(max_examples=50, deadline=None, derandomize=True)


@dataclass(frozen=True)
class Inputs:
    """One generated case: a quote path and the template's parameters."""

    bids: tuple[Decimal, ...]
    params: TemplateParams


def _cents(value: int) -> Decimal:
    """A venue-legal price: the two decimals the tick requires."""
    return Decimal(value).scaleb(-2)


@st.composite
def template_inputs(draw):
    """A quote path with one or two stop-out-and-re-entry cycles, and valid test parameters.

    The rise after each gap starts at once and is longer than the longest cooldown, so entry
    signals arrive while the cooldown runs: the rule is exercised, not merely passed.
    """
    bids = [_cents(draw(st.integers(min_value=2000, max_value=20000)))] * 9
    for _ in range(draw(st.integers(min_value=5, max_value=10))):
        bids.append(bids[-1] + _cents(draw(st.integers(min_value=1, max_value=8))))
    for _ in range(draw(st.integers(min_value=1, max_value=2))):
        bids.append(bids[-1] - _cents(draw(st.integers(min_value=80, max_value=140))))
        for _ in range(draw(st.integers(min_value=25, max_value=35))):
            bids.append(bids[-1] + _cents(draw(st.integers(min_value=1, max_value=8))))
    bids += [bids[-1]] * draw(st.integers(min_value=0, max_value=5))
    params = replace(
        BASE_PARAMS,
        atr_period=draw(st.integers(min_value=2, max_value=8)),
        trail_atr_multiple=Decimal(draw(st.integers(min_value=10, max_value=40))) / Decimal(10),
        trail_floor_bps=Decimal(draw(st.integers(min_value=1, max_value=10))),
        entry_limit_buffer_bps=Decimal(draw(st.integers(min_value=1, max_value=20))),
        exit_limit_buffer_bps=Decimal(draw(st.integers(min_value=1, max_value=50))),
        entry_timeout_seconds=Decimal(draw(st.integers(min_value=1, max_value=3))),
        base_quantity=draw(st.integers(min_value=2, max_value=50)),
        cooldown_seconds=Decimal(draw(st.integers(min_value=200, max_value=300))) / Decimal(100),
        whipsaw_stopouts_max=draw(st.integers(min_value=3, max_value=5)),
    )
    return Inputs(tuple(bids), params)


def run_template(inputs, strategy_type=sim.SyntheticBreakout):
    """Drive one generated case through `sim.run`; return its books, orders and receipts."""
    seen = {}

    def inspect(engine, strategy):
        seen["books"] = dict(strategy.books)
        seen["orders"] = list(engine.cache.orders())
        seen["receipts"] = list(getattr(strategy, "receipts", ()))

    sim.run(
        scenarios={"PROP": (list(inputs.bids), 1, Decimal("0.9"))},
        params=inputs.params,
        strategy_type=strategy_type,
        inspect=inspect,
    )
    return seen


def only_book(seen):
    books = list(seen["books"].values())
    assert len(books) == 1  # one generated symbol per case
    return books[0]


class RecordsReceipts(sim.SyntheticBreakout):
    """Keeps every flat receipt; `SymbolBook` keeps only the latest one."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.receipts = []

    def _check_flat(self, book):
        before = book.flat_receipt_ns
        super()._check_flat(book)
        if book.flat_receipt_ns is not None and book.flat_receipt_ns != before:
            self.receipts.append(book.flat_receipt_ns)


class Late:
    """An event whose venue time is ten seconds before the engine handles it.

    The same test double as `tests/test_strategy_template.py:310-321`.
    """

    def __init__(self, event):
        self._event = event

    def __getattr__(self, name):
        return getattr(self._event, name)

    @property
    def ts_event(self):
        return self._event.ts_event - 10 * NS_PER_SECOND


class LateReceipts(RecordsReceipts):
    """Late fills, cancels and position events, as in the template's own late-notice test."""

    def on_order_event(self, event):
        late = type(event).__name__ in {"OrderFilled", "OrderCanceled"}
        super().on_order_event(Late(event) if late else event)

    def on_position_event(self, event):
        super().on_position_event(Late(event))


@pytest.fixture(scope="module", autouse=True)
def _warm_the_engine():
    """Pay NautilusTrader's one-time startup outside the first Hypothesis example."""
    sim.run(scenarios={"WARM": (sim.SCENARIOS["QUIET"][0][:12], None, None)})


# Invariant: while a long position is held, the trailing level never moves down.
# Promise: strategy.py:11-13 (the ratchet "moves it in the position's favour only");
# docs/HANDBOOK.md:186 ("it only ratchets up").
@given(template_inputs())
@PROPERTIES
def test_the_trailing_level_never_moves_down_while_a_position_is_held(inputs):
    book = only_book(run_template(inputs))
    assert book.triggers and book.ratchets > 0
    assert book.loosened == 0
    bounds = [*book.entries, 1 << 63]
    for start, end in zip(bounds, bounds[1:], strict=False):
        held = [Decimal(trigger) for when, trigger in book.triggers if start <= when < end]
        assert held == sorted(held)


# Invariant: every trailing level the template records is at or below the bid it was set from.
# Promise: strategy.py:11-12 ("the OrderEmulator trails the trigger behind the best bid").
@given(template_inputs())
@PROPERTIES
def test_the_trailing_level_is_never_above_the_bid_it_was_set_from(inputs):
    book = only_book(run_template(inputs))
    assert book.triggers
    for when, trigger in book.triggers:
        offset = when - sim.START_NS
        assert offset % sim.STEP_NS == 0
        index = offset // sim.STEP_NS
        assert 0 <= index < len(inputs.bids)
        assert Decimal(trigger) <= inputs.bids[index]


# Invariant: a fast exit on a symbol happens before any re-entry on that symbol.
# Promise: docs/HANDBOOK.md:86-88 (R1: re-enter only after a broker-flat receipt); the receipt
# is `strategy.py:400-408`, and `_reentry_refusal` (:274-280) refuses without it.
@given(template_inputs())
@PROPERTIES
def test_a_fast_exit_comes_before_any_reentry(inputs):
    book = only_book(run_template(inputs))
    assert len(book.entries) > 1 and book.releases
    for index in range(1, len(book.entries)):
        assert len(book.releases) >= index
        assert book.releases[index - 1] < book.entries[index]


# Invariant: a re-entry waits out its cooldown, measured from the flat receipt on the engine's
# clock, not from the sell's (possibly backdated) venue time and not from the wall clock.
# Promise: docs/HANDBOOK.md:86-88 ("only cooldown_seconds after that receipt, not after the
# sell"); strategy.py:276-279 ("Both sides on the engine clock") and :406 (`self.clock`).
@given(template_inputs())
@PROPERTIES
def test_reentry_waits_out_its_cooldown_on_the_engine_clock(inputs):
    seen = run_template(inputs, strategy_type=LateReceipts)
    book = only_book(seen)
    assert len(book.entries) > 1 and book.refusals["cooldown"] > 0
    cooldown_ns = int(inputs.params.cooldown_seconds * NS_PER_SECOND)
    last_quote_ns = sim.START_NS + (len(inputs.bids) - 1) * sim.STEP_NS
    for index in range(1, len(book.entries)):
        entry = book.entries[index]
        receipts = [ts for ts in seen["receipts"] if ts < entry]
        assert receipts
        receipt = max(receipts)
        assert entry >= receipt + cooldown_ns
        assert receipt >= book.releases[index - 1]  # not backdated from a late fill event
        assert sim.START_NS <= receipt <= last_quote_ns  # the engine's clock, not wall time


# Invariant: a symbol never holds more than its configured size.
# Promise: strategy.py:247-250 (enter only when flat, then `base_quantity`), :295-296 (a
# re-entry scales `base_quantity` by a factor in [0, 1]; params.py:66-68 holds confidence and
# its floor in [0, 1]), and docs/HANDBOOK.md:105-107 ("Confidence and size").
@given(template_inputs())
@PROPERTIES
def test_a_symbol_never_holds_more_than_its_configured_size(inputs):
    seen = run_template(inputs)
    book = only_book(seen)
    assert book.held > 0
    assert book.held <= inputs.params.base_quantity
    buys = [order for order in seen["orders"] if order.side == OrderSide.BUY]
    assert buys
    assert all(order.quantity.as_decimal() <= inputs.params.base_quantity for order in buys)
