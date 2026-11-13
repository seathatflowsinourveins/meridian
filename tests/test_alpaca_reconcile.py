"""
Startup reconciliation's rules, one by one, on synthetic venue rows: the paged order listing,
what is withheld, what refuses, how historical fills are explained, and the engine settings
the lane insists on. The same rules run inside the real engine in `test_alpaca_node.py`.
"""

import asyncio

import pytest
from alpaca_fakes import FakeVenue, fill_activity, order_row, stamp
from nautilus_trader.live import SubmissionRecoveryPolicy
from nautilus_trader.model import InstrumentId

from meridian.alpaca.budget import ActionKind
from meridian.alpaca.reconcile import (
    IncompleteCoverage,
    StageTrace,
    check_one_writer,
    engine_config,
    explain_fills,
    list_fill_activities,
    list_orders,
    reason_of,
    traced,
    unmappable_history,
    until_covering,
    withheld_unloaded,
)
from meridian.alpaca.reports import timestamp_ns

AAPL = InstrumentId.from_str("AAPL.ALPACA")


def caller(venue: FakeVenue):
    async def call(kind, method, path, data=None, **_):
        assert kind == ActionKind.QUERY
        return getattr(venue, method)(path, data)

    return call


def orders_at(count: int, *, same_instant_from: int | None = None) -> list[dict]:
    """`count` orders a second apart; from `same_instant_from` on, all at one instant that is
    older than every other row, so newest first they are the last rows of the listing."""
    rows = []
    for index in range(count):
        minute, second = divmod(index, 60)
        when = f"2026-11-0{1 + minute // 60}{stamp(minute % 60, second)[10:]}"
        if same_instant_from is not None and index >= same_instant_from:
            when = "2026-10-31T14:00:00.000000Z"
        rows.append(order_row(submitted_at=when))
    return rows


@pytest.mark.parametrize("inclusive", [True, False])
def test_the_order_listing_is_read_whole_past_the_500_row_cap(inclusive):
    venue = FakeVenue()
    venue.until_inclusive = inclusive
    venue.orders = orders_at(1203)
    rows = asyncio.run(list_orders(caller(venue), {"status": "all"}, max_pages=10))
    assert sorted(row["id"] for row in rows) == sorted(row["id"] for row in venue.orders)
    assert all(data == "/orders" for _, data in venue.calls)
    assert len(venue.calls) == 3  # 500, 500 and 203 rows


@pytest.mark.parametrize("inclusive", [True, False])
def test_rows_sharing_the_page_edge_instant_are_never_skipped(inclusive):
    venue = FakeVenue()
    venue.until_inclusive = inclusive
    venue.orders = orders_at(520, same_instant_from=480)  # 40 at one instant: rows 480-519
    rows = asyncio.run(list_orders(caller(venue), {"status": "all"}, max_pages=10))
    assert sorted(row["id"] for row in rows) == sorted(row["id"] for row in venue.orders)


def test_a_venue_that_drops_the_edge_rows_is_incomplete_coverage():
    """A venue that reads `until` at whole seconds loses the rows at the page edge; the
    contiguity check notices instead of returning a short history."""

    class CoarseUntil(FakeVenue):
        def _list(self, data):
            if "until" in data:
                data = dict(data, until=data["until"][:19] + "Z")  # truncated to the second
            return super()._list(data)

    venue = CoarseUntil()
    venue.until_inclusive = False
    venue.orders = orders_at(520, same_instant_from=480)
    with pytest.raises(IncompleteCoverage, match="coverage incomplete") as info:
        asyncio.run(list_orders(caller(venue), {"status": "all"}, max_pages=10))
    assert reason_of(info.value.failures[0][1]) == "order pages are not contiguous"


def test_the_next_page_asks_one_microsecond_past_the_edge():
    edge = timestamp_ns("2026-11-02T14:00:00.942282657Z", "edge")
    assert until_covering(edge) == "2026-11-02T14:00:00.942283Z"
    assert 0 < timestamp_ns(until_covering(edge), "until") - edge <= 1_000


def test_a_page_with_no_new_rows_is_incomplete_coverage():
    venue = FakeVenue()
    venue.orders = orders_at(600, same_instant_from=0)  # 600 rows at one instant
    with pytest.raises(IncompleteCoverage) as info:
        asyncio.run(list_orders(caller(venue), {"status": "all"}, max_pages=10))
    assert reason_of(info.value.failures[0][1]) == "order page made no progress"


def test_a_listing_longer_than_its_page_budget_is_incomplete_coverage():
    venue = FakeVenue()
    venue.orders = orders_at(1203)
    with pytest.raises(IncompleteCoverage) as info:
        asyncio.run(list_orders(caller(venue), {"status": "all"}, max_pages=2))
    assert reason_of(info.value.failures[0][1]) == "order listing needs more pages than its budget"


def test_a_failed_page_is_incomplete_coverage_never_an_empty_account():
    venue = FakeVenue()
    venue.fail("get", "/orders", TimeoutError("synthetic timeout"))
    with pytest.raises(IncompleteCoverage):
        asyncio.run(list_orders(caller(venue), {"status": "all"}, max_pages=10))


def test_fill_activities_are_paged_by_the_last_rows_id():
    venue = FakeVenue()
    order = order_row()
    venue.fills = [fill_activity(order, when=f"2026-11-02T13:{m:02d}:00Z") for m in range(0, 60)]
    venue.fills += [fill_activity(order, when=f"2026-11-02T12:{m:02d}:00Z") for m in range(0, 60)]
    rows = asyncio.run(list_fill_activities(caller(venue), {}, max_pages=5))
    assert len(rows) == 120 and len({row["id"] for row in rows}) == 120
    with pytest.raises(IncompleteCoverage):
        asyncio.run(list_fill_activities(caller(venue), {}, max_pages=1))


def loaded(symbol: str) -> bool:
    return symbol == "AAPL"


def test_ended_history_outside_the_universe_is_withheld_and_working_orders_refuse():
    assert withheld_unloaded(order_row(symbol="TSLA", status="filled"), loaded) is True
    assert withheld_unloaded(order_row(symbol="TSLA", status="canceled"), loaded) is True
    assert withheld_unloaded(order_row(symbol="AAPL", status="new"), loaded) is False
    with pytest.raises(ValueError, match="working order outside the lane's universe: TSLA"):
        withheld_unloaded(order_row(symbol="TSLA", status="new"), loaded)


def test_a_working_leg_behind_an_ended_parent_refuses_at_any_depth():
    deep = order_row(symbol="TSLA", status="held")
    middle = order_row(symbol="TSLA", status="canceled", legs=[deep])
    parent = order_row(symbol="TSLA", status="filled", order_class="oto", legs=[middle])
    with pytest.raises(ValueError, match="working order outside"):
        withheld_unloaded(parent, loaded)
    missing = order_row(symbol="TSLA", status="filled")
    del missing["status"]
    with pytest.raises(ValueError, match="working order outside"):
        withheld_unloaded(missing, loaded)


NO_SYMBOL = object()  # the row has no symbol field at all


@pytest.mark.parametrize(
    "symbol",
    [NO_SYMBOL, None, "", 123, ["TSLA"]],
    ids=["absent", "null", "empty", "number", "list"],
)
def test_a_row_whose_symbol_cannot_be_read_is_never_withheld(symbol):
    """An ended row without a symbol in text is not known to be outside the universe: it may be
    the lane's own order. It refuses, as its own failure, and so does a fill it would explain."""
    row = order_row(status="filled", submitted_at=stamp(1))
    fill = fill_activity(row)
    if symbol is NO_SYMBOL:
        del row["symbol"]
    else:
        row["symbol"] = symbol
    with pytest.raises(ValueError, match="^Alpaca row requires its symbol$"):
        withheld_unloaded(row, loaded)
    with pytest.raises(IncompleteCoverage) as info:
        explain([fill], [row])
    assert reason_of(info.value.failures[0][1]) == "Alpaca row requires its symbol"


def test_another_writers_working_order_refuses_and_its_ended_orders_do_not():
    check_one_writer(order_row(client_order_id="M3-7", status="new"), "M3-")
    check_one_writer(order_row(client_order_id="OLDWRITER-1", status="filled"), "M3-")
    check_one_writer(order_row(client_order_id="OLDWRITER-2", status="canceled"), "M3-")
    with pytest.raises(ValueError, match="working order of another writer: AAPL"):
        check_one_writer(order_row(client_order_id="OLDWRITER-3", status="new"), "M3-")
    with pytest.raises(ValueError, match="another writer"):
        check_one_writer(order_row(client_order_id="web-order", status="pending_new"), "M3-")


def test_ended_history_no_simple_report_can_carry_is_counted_only_without_fills():
    assert unmappable_history(order_row(status="filled")) is False  # a plain row is mapped
    assert unmappable_history(order_row(status="replaced", filled_qty="0")) is True
    ended_legs = [order_row(status="canceled", filled_qty="0")]
    bracket = order_row(status="canceled", filled_qty="0", order_class="bracket", legs=ended_legs)
    assert unmappable_history(bracket) is True
    with pytest.raises(ValueError, match="cannot map holds fills"):
        unmappable_history(order_row(status="replaced", qty="2", filled_qty="1"))
    filled_leg = [order_row(status="filled", qty="1")]
    with pytest.raises(ValueError, match="cannot map holds fills"):
        unmappable_history(order_row(status="filled", order_class="oto", legs=filled_leg))
    no_quantity = order_row(status="replaced")
    del no_quantity["filled_qty"]  # an unknown fill count is not "no fills"
    with pytest.raises(ValueError, match="cannot map holds fills"):
        unmappable_history(no_quantity)
    working_leg = [order_row(status="new", filled_qty="0")]
    with pytest.raises(ValueError, match="working order the lane cannot map"):
        unmappable_history(order_row(status="filled", order_class="oto", legs=working_leg))


def explain(fills, orders):
    trace = StageTrace()
    explain_fills(fills, orders, trace, loaded)
    return trace


def test_a_fill_is_explained_by_a_listed_order_with_at_least_its_quantity():
    order = order_row(qty="3", filled_qty="3", submitted_at=stamp(5))
    assert explain([fill_activity(order, cum_qty="2"), fill_activity(order)], [order]).failures == 0
    with pytest.raises(IncompleteCoverage, match="coverage incomplete"):
        explain([fill_activity(order, cum_qty="4")], [order])


def test_a_fill_older_than_the_venues_order_history_is_counted_not_refused():
    listed = order_row(submitted_at=stamp(30))
    gone = order_row(submitted_at=stamp(1))  # the venue no longer lists it
    trace = explain([fill_activity(gone, when=stamp(1))], [listed])
    assert trace.before_order_history == 1


def test_an_unlisted_fill_newer_than_the_oldest_listed_order_refuses():
    listed = order_row(submitted_at=stamp(1))
    missing = order_row(submitted_at=stamp(30))
    with pytest.raises(IncompleteCoverage) as info:
        explain([fill_activity(missing, when=stamp(30))], [listed])
    assert reason_of(info.value.failures[0][1]) == "historical fill that no order report explains"


def test_fills_with_no_listed_order_at_all_refuse():
    with pytest.raises(IncompleteCoverage):
        explain([fill_activity(order_row())], [])


def test_a_fill_for_working_history_outside_the_universe_refuses():
    working = order_row(symbol="TSLA", status="partially_filled", qty="2", filled_qty="1")
    with pytest.raises(IncompleteCoverage, match="working order outside"):
        explain([fill_activity(working, cum_qty="1")], [working])


def test_a_failed_stage_records_its_first_failure_and_never_a_value():
    trace: dict[str, StageTrace] = {}
    failure = ValueError("historical fill that no order report explains")
    with pytest.raises(IncompleteCoverage), traced(trace, "fills"):
        raise IncompleteCoverage([], [(None, failure), (None, ValueError("other"))])
    entry = trace["fills"]
    assert (entry.first, entry.failures, entry.reason) == ("ValueError", 2, failure.args[0])
    # Text that merely starts like ours is not kept (the earlier line's prefix rule let a venue
    # status word through, sextant#688); a variable part after a colon is dropped.
    with pytest.raises(ValueError), traced(trace, "orders"):
        raise ValueError("Alpaca says account 12345 had a fill at 187.25")
    assert trace["orders"].reason is None
    with pytest.raises(ValueError), traced(trace, "orders"):
        raise ValueError("working order outside the lane's universe: TSLA")
    assert trace["orders"].reason == "working order outside the lane's universe"
    with pytest.raises(ValueError), traced(trace, "orders"):
        raise ValueError("submitted_at is not a valid timestamp")
    assert trace["orders"].reason == "submitted_at is not a valid timestamp"
    with pytest.raises(KeyError), traced(trace, "positions"):
        raise KeyError("qty")
    assert trace["positions"].reason is None and trace["positions"].first == "KeyError"
    with pytest.raises(RuntimeError), traced(trace, "positions"):
        raise RuntimeError("historical fill that no order report explains")  # not our type
    assert trace["positions"].reason is None


def test_the_engine_settings_cannot_hide_a_gap():
    config = engine_config([AAPL])
    assert config.reconciliation and not config.generate_missing_orders
    assert not config.filter_position_reports and config.filter_unclaimed_external_orders
    assert config.reconciliation_instrument_ids == ["AAPL.ALPACA"]
    assert config.reconciliation_lookback_mins is None
    assert config.submission_recovery_policy == SubmissionRecoveryPolicy.RETAIN_UNRESOLVED
    assert config.inflight_check_interval_ms == 0
    assert config.open_check_interval_secs and config.open_check_interval_secs > 0
    for bad in (
        {"reconciliation_lookback_mins": 60},
        {"generate_missing_orders": True},
        {"filter_position_reports": True},
        {"filter_unclaimed_external_orders": False},
        {"submission_recovery_policy": SubmissionRecoveryPolicy.RESOLVE_LOCALLY},
    ):
        with pytest.raises(ValueError):
            engine_config([AAPL], **bad)
    with pytest.raises(ValueError):
        engine_config([])


@pytest.mark.parametrize(
    ("settings", "cadence"),
    [
        ({}, 2.0),  # rc9's in-flight default, 2000 ms, as the open-order cadence
        ({"inflight_check_interval_ms": 500}, 0.5),
        ({"inflight_check_interval_ms": 0, "open_check_interval_secs": 1.0}, 1.0),
        ({"inflight_check_interval_ms": 2000, "open_check_interval_secs": 0.2}, 0.2),
        ({"position_check_interval_secs": 30.0}, 2.0),
    ],
)
def test_the_engine_settings_returned_check_open_orders_and_never_in_flight(settings, cadence):
    config = engine_config([AAPL], **settings)
    assert config.inflight_check_interval_ms == 0
    assert config.open_check_interval_secs == cadence


@pytest.mark.parametrize(
    "settings",
    [
        {"inflight_check_interval_ms": 0},
        {"inflight_check_interval_ms": 0, "open_check_interval_secs": None},
        {"open_check_interval_secs": None},
    ],
)
def test_engine_settings_that_leave_no_order_check_are_refused(settings):
    """In-flight checks are always off here, so settings without an open-order cadence would
    leave no periodic check of the venue at all: refused, whatever in-flight interval was
    passed."""
    with pytest.raises(ValueError, match="open-order checks must replace in-flight checks"):
        engine_config([AAPL], **settings)


@pytest.mark.parametrize(
    ("settings", "refusal"),
    [
        # rc9's own upper limit: the node's first periodic check a day after the start.
        ({"reconciliation_startup_delay_secs": 86_400.0}, "reconciliation_startup_delay_secs"),
        ({"reconciliation_startup_delay_secs": 60.5}, "reconciliation_startup_delay_secs"),
        ({"open_check_interval_secs": 1e9}, "open_check_interval_secs"),
        ({"open_check_interval_secs": 60.5}, "open_check_interval_secs"),
        ({"inflight_check_interval_ms": 61_000}, "open_check_interval_secs"),  # sets the cadence
        # Checks that run but defer every order with local activity inside the threshold.
        ({"open_check_threshold_ms": 4_294_967_295}, "open_check_threshold_ms"),
        ({"open_check_threshold_ms": 60_001}, "open_check_threshold_ms"),
        ({"single_order_query_delay_ms": 60_001}, "single_order_query_delay_ms"),
        ({"open_check_missing_retries": 31}, "open_check_missing_retries"),  # 31 x 2 s
        (
            {"open_check_interval_secs": 0.2, "open_check_missing_retries": 301},
            "open_check_missing_retries",
        ),
        ({"max_single_order_queries_per_cycle": 0}, "max_single_order_queries_per_cycle"),
        ({"filtered_client_order_ids": ["M3-1"]}, "filtered_client_order_ids"),
    ],
)
def test_engine_settings_under_which_a_check_waits_too_long_or_never_acts_are_refused(
    settings, refusal
):
    """A check that comes too late, or runs without acting, leaves an order whose answer or
    update was lost as unresolved as no check does. No setting may let one wait more than a
    minute, a check must be able to query a single order, and no order may be filtered out."""
    with pytest.raises(ValueError, match=f"^{refusal} would "):
        engine_config([AAPL], **settings)


def test_engine_settings_at_the_longest_check_wait_are_accepted():
    settings = {
        "reconciliation_startup_delay_secs": 60.0,
        "open_check_interval_secs": 60.0,
        "open_check_threshold_ms": 60_000,
        "single_order_query_delay_ms": 60_000,
        "open_check_missing_retries": 1,
        "max_single_order_queries_per_cycle": 1,
    }
    config = engine_config([AAPL], **settings)
    assert [getattr(config, name) for name in settings] == list(settings.values())
    assert engine_config([AAPL], open_check_missing_retries=30).open_check_missing_retries == 30
