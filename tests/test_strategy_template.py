"""The strategy template on the engine's native BacktestEngine, offline, synthetic values only."""

import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model import InstrumentId, OrderSide, OrderType, Price, Quantity, TimeInForce

from meridian.alpaca.wire import submit_payload
from meridian.strategy_template import ActionLog, Phase, TemplateParams, TrailingTemplate, sim
from meridian.strategy_template.actions import NS_PER_SECOND

ROOT = Path(__file__).resolve().parents[1]
PARAMS = TemplateParams.from_config(sim.SIM_PARAMS)  # synthetic, uncalibrated
assert PARAMS.provenance == sim.SYNTHETIC


def run(scenarios=None, params=PARAMS, strategy_type=sim.SyntheticBreakout):
    seen = {}

    def inspect(engine, strategy):
        seen["books"] = dict(strategy.books)
        seen["orders"] = list(engine.cache.orders())
        seen["payloads"] = [
            submit_payload(o, "O-")
            for o in engine.cache.orders()
            if not o.is_emulated and o.status.name != "DENIED"
        ]

    data = sim.run(params=params, scenarios=scenarios, strategy_type=strategy_type, inspect=inspect)
    return data, seen


@pytest.fixture(scope="module")
def full():
    return run()


def books_by_name(seen):
    return {str(iid).split(".")[0]: book for iid, book in seen["books"].items()}


def ts(i):
    return sim.START_NS + i * sim.STEP_NS


def test_every_scenario_happens(full):
    data, _ = full
    assert sim.problems(data) == []
    assert data["orders_denied"] == 0


def test_the_trail_never_loosens(full):
    _, seen = full
    for book in seen["books"].values():
        assert book.loosened == 0
        # Split the trigger history by entry: within one holding it only rises.
        bounds = [*book.entries, 1 << 63]
        for start, end in zip(bounds, bounds[1:], strict=False):
            held = [Decimal(t) for when, t in book.triggers if start <= when < end]
            assert held == sorted(held)
    ratchet = books_by_name(seen)["RATCHET"]
    assert ratchet.ratchets > 10 and ratchet.phase is Phase.HOLDING


@pytest.mark.parametrize("name", ["BREACH", "REENTRY", "GAP"])
def test_the_exit_goes_out_on_the_first_quote_that_breaches(full, name):
    _, seen = full
    book = books_by_name(seen)[name]
    bids = sim.SCENARIOS[name][0]
    entry = (book.entries[0] - sim.START_NS) // sim.STEP_NS
    first = None
    for i in range(entry + 1, len(bids)):
        before = [Decimal(t) for when, t in book.triggers if when < ts(i)]
        if before and bids[i] <= before[-1]:
            first = i
            break
    assert first is not None and book.releases[0] == ts(first)


def test_exits_are_marketable_plain_day_limits_the_paper_lane_accepts(full):
    _, seen = full
    venue = [o for o in seen["orders"] if not o.is_emulated]
    assert venue and all(o.order_type == OrderType.LIMIT for o in venue)
    assert all(o.time_in_force == TimeInForce.DAY for o in venue)
    assert len(seen["payloads"]) == len(venue)  # submit_payload refused none
    sells = [o for o in venue if o.side == OrderSide.SELL and o.status.name == "FILLED"]
    assert len(sells) == 3  # BREACH, REENTRY, and GAP's re-priced remainder


def test_a_gap_cancels_the_resting_exit_then_reprices_it(full):
    _, seen = full
    gap = books_by_name(seen)["GAP"]
    assert gap.events == ["entry", "fast-exit", "reprice", "flat"]
    orders = [o for o in seen["orders"] if str(o.instrument_id).startswith("GAP")]
    assert [o.status.name for o in orders if o.side == OrderSide.SELL] == ["CANCELED", "FILLED"]


def test_reentry_waits_for_the_flat_receipt_and_the_cooldown(full):
    _, seen = full
    book = books_by_name(seen)["REENTRY"]
    assert book.exits == 1 and len(book.entries) == 2 and book.flat_receipt_ns is not None
    cooldown = int(PARAMS.cooldown_seconds * NS_PER_SECOND)
    assert book.entries[1] >= book.flat_receipt_ns + cooldown
    assert book.entries[1] - sim.STEP_NS < book.flat_receipt_ns + cooldown  # not later either
    assert book.refusals["cooldown"] > 0
    second = [o for o in seen["orders"] if str(o.instrument_id).startswith("REENTRY")][-2]
    # Confidence 0.8 with a floor of 0.5: 10 x (0.5 + 0.5 x 0.8) = 9.
    assert second.side == OrderSide.BUY and second.quantity == Quantity.from_int(9)
    breach = books_by_name(seen)["BREACH"]
    assert len(breach.entries) == 1 and breach.refusals["no ranking"] > 0


REENTRY_BIDS = sim.SCENARIOS["REENTRY"][0]


@pytest.mark.parametrize(
    ("rank", "confidence", "change", "reason"),
    [
        (5, Decimal("0.8"), {}, "rank outside the retry band"),
        (1, None, {}, "no confidence"),
        (1, Decimal("0.3"), {}, "confidence under the minimum"),
        (1, Decimal("0.8"), {"reentry_enabled": False}, "re-entry off"),
        (1, Decimal("0.8"), {"base_quantity": 1, "confidence_size_floor": Decimal(0)}, None),
    ],
)
def test_reentry_only_under_its_rule(rank, confidence, change, reason):
    data, seen = run({"REENTRY": (REENTRY_BIDS, rank, confidence)}, replace(PARAMS, **change))
    book = books_by_name(seen)["REENTRY"]
    assert book.exits == 1
    if reason is None:  # 1 x (0 + 1 x 0.8) rounds down to no share
        reason = "size under one share"
    assert len(book.entries) == 1 and book.refusals[reason] > 0


def test_whipsaw_needs_a_reclaim_after_stopouts_before_the_gain_lock():
    # Enter on a small breakout, fall straight back through the trail: a loss stop-out.
    bids = sim.path("70.00", ("0", 8), ("0.05", 1, "0"), ("-0.05", 6, "0"), ("0.04", 40, "0"))
    params = replace(PARAMS, whipsaw_stopouts_max=1)
    _, seen = run({"WHIP": (bids, 1, Decimal("0.9"))}, params)
    book = books_by_name(seen)["WHIP"]
    assert book.exits == 1 and book.stopouts_in_row == 1 and len(book.entries) == 1
    assert book.refusals["whipsaw: needs a reclaim or oversell"] > 0

    class Reclaims(sim.SyntheticBreakout):
        def reclaim_qualified(self, book, quote):
            return True

    _, seen = run({"WHIP": (bids, 1, Decimal("0.9"))}, params, Reclaims)
    assert len(books_by_name(seen)["WHIP"].entries) == 2


def test_symbols_do_not_affect_each_other(full):
    data, _ = full
    for name, scenario in sim.SCENARIOS.items():
        alone, _ = run({name: scenario})
        assert alone["symbols"][f"{name}.SIM"] == data["symbols"][f"{name}.SIM"]


class RestingEntry(sim.SyntheticBreakout):
    """An entry far under the bid rests, so the symbol stays ENTERING across quotes."""

    second_order_sent = None

    def entry_price(self, book, quote):
        return quote.bid_price.as_decimal() - Decimal(5)

    def observe(self, book, quote):
        super().observe(book, quote)
        if book.phase is Phase.ENTERING and self.second_order_sent is None:
            order = self.order_factory.limit(
                book.instrument_id,
                OrderSide.BUY,
                Quantity.from_int(1),
                Price.from_str("1.00"),
                time_in_force=TimeInForce.DAY,
            )
            self.second_order_sent = self._send(book, order, "SUBMIT", "test", 0, Phase.ENTERING)


def test_no_second_order_while_one_is_unresolved_and_a_stale_entry_is_cancelled():
    data, seen = run({"REST": sim.SCENARIOS["RATCHET"]}, strategy_type=RestingEntry)
    book = books_by_name(seen)["REST"]
    assert book.refusals["one unresolved order"] == 1
    buys = [o for o in seen["orders"] if o.side == OrderSide.BUY]
    cancelled = [o for o in buys if o.status.name == "CANCELED"]
    assert buys[: len(cancelled)] == cancelled and len(buys) - len(cancelled) <= 1
    # Each entry rests until entry_timeout_seconds, is cancelled, and only then may the next go.
    starts = [o.ts_init for o in buys]
    gap = int(PARAMS.entry_timeout_seconds * NS_PER_SECOND)
    assert len(starts) > 1 and all(b - a >= gap for a, b in zip(starts, starts[1:], strict=False))
    assert data["actions"]["counts"]["CANCEL"] == len(cancelled) and not book.exits


def test_the_action_counts(full):
    data, _ = full
    actions = data["actions"]
    # Entries 5 (one a re-entry), 4 sells (3 releases, 1 re-price), 1 cancel; 5 emulated stops.
    assert actions["counts"] == {"CANCEL": 1, "LOCAL": 5, "REDUCE": 4, "SUBMIT": 5}
    assert actions["venue_actions"] == 10
    assert actions["max_venue_actions_per_minute"] == 10
    log = ActionLog()
    for t in (0, 1, NS_PER_SECOND - 1, NS_PER_SECOND, 3 * NS_PER_SECOND):
        log.record(t, "SUBMIT", "X", "entry")
    log.record(0, "LOCAL", "X", "protect")
    assert log.max_in_window(NS_PER_SECOND) == 3 and log.max_in_window(60 * NS_PER_SECOND) == 5


def test_many_symbols_run_concurrently():
    data = sim.run(copies=20)
    assert len(data["symbols"]) == 100 and sim.problems(data, 20) == []
    assert data["actions"]["max_venue_actions_per_second"] >= 20


def test_the_template_refuses_to_start_without_parameters():
    ids = [InstrumentId.from_str("AAA.SIM")]
    with pytest.raises(TypeError, match="refuses to start"):
        TrailingTemplate(None, ids, strategy_id="T-1")  # type: ignore[arg-type]
    config = dict(sim.SIM_PARAMS)
    del config["cooldown_seconds"]
    with pytest.raises(ValueError, match="missing \\['cooldown_seconds'\\]"):
        TemplateParams.from_config(config)
    with pytest.raises(ValueError, match="unknown \\['stop_pct'\\]"):
        TemplateParams.from_config({**sim.SIM_PARAMS, "stop_pct": 1})
    for name, bad in [
        ("provenance", " "),
        ("atr_period", 0),
        ("exit_limit_buffer_bps", "0"),
        ("trail_floor_bps", "-1"),
        ("reentry_min_confidence", "1.5"),
        ("reentry_enabled", "yes"),
    ]:
        with pytest.raises(ValueError, match="refused"):
            TemplateParams.from_config({**sim.SIM_PARAMS, name: bad})
    with pytest.raises(TypeError):
        TemplateParams()  # type: ignore[call-arg]


def test_the_command_writes_under_runs_only_and_opens_no_socket(tmp_path):
    code = f"""
import sys
sys.path.insert(0, {str(ROOT / "tests")!r})
from test_alpaca_sim import block_sockets
block_sockets()
from pathlib import Path
from meridian import boundary
from meridian.strategy_template import sim
boundary.REPO_ROOT = Path({str(tmp_path)!r})
raise SystemExit(sim.main([]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout and "SIMULATION" in result.stdout
    written = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert len(written) == 1 and written[0].startswith("runs/M4-template-")
