"""
The Alpaca execution client inside NautilusTrader's real engine, offline.

Each test builds a LiveNode (NautilusTrader 2.0.0rc9) whose execution client talks to an
in-memory paper account (`alpaca_fakes.FakeVenue`), a scripted trade stream and a stand-in
order budget. Startup reconciliation, order commands and stream events go through the engine
exactly as in a run; only the venue is synthetic.

The startup cases replay, on synthetic rows, the shapes of the three attended starts that
failed in the earlier line (docs/m3-alpaca.md, section 2): another writer's orders on the
account, ended history in a symbol the node had not loaded, and fills older than the venue's
order history. A failed start must also say why.
"""

import asyncio
import gc
import json
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests
from alpaca_fakes import (
    AAPL,
    PREFIX,
    FakeVenue,
    Frame,
    Rig,
    api_error,
    build_node,
    fill_activity,
    order_row,
    position_row,
    run,
    stamp,
    strategy,
    update,
)
from nautilus_trader.model import (
    ClientOrderId,
    ExecutionMassStatus,
    InstrumentId,
    OrderSide,
    OrderStatus,
    Price,
    Quantity,
    TimeInForce,
    VenueOrderId,
)

from meridian.alpaca.budget import ActionKind
from meridian.alpaca.execution import (
    NOT_A_TRADE_UPDATE,
    AlpacaPaperExecutionClient,
)
from meridian.alpaca.parsing import parse_equity
from meridian.alpaca.reconcile import OTHER_INSTRUMENT
from meridian.alpaca.reports import timestamp_ns


@pytest.fixture(autouse=True)
def collect_node_cycles():
    """A LiveNode is one per thread; a test's node, strategy and hooks form reference cycles,
    so collect them after each test (as NautilusTrader's own `collect_node_cycles` fixture
    does at v2.0.0rc9, `python/tests/conftest.py`)."""
    yield
    gc.collect()


def started(seen: dict):
    """An on_start hook: record what the client knows once startup passed, then stop."""

    def hook(running):
        client = seen["rig"].clients[0]
        seen["coverage_complete"] = client.coverage_complete
        seen["stream_live"] = client.stream_live
        seen["bulk"] = {
            symbol: client._provides_bulk_position_coverage(InstrumentId.from_str(symbol))
            for symbol in ("AAPL.ALPACA", "TSLA.ALPACA")
        }
        running.shutdown_system("test done")

    return hook


def start(rig: Rig, **config) -> tuple[BaseException | None, dict]:
    """Start a node, stop it once startup passed, and return what the test checks.

    Hooks never hold the node: the node holds its strategy natively, where Python's cycle
    collector cannot see the edge, so a hook that held the node would keep it alive.
    """
    seen: dict = {"rig": rig}
    node = build_node(rig, strategy(on_start=started(seen)), **config)
    error = asyncio.run(run(node))
    seen["instrument_loaded"] = node.cache.instrument(AAPL) is not None
    seen["holding"] = holding(node)
    del node
    return error, seen


def holding(node) -> list[tuple[str, str]]:
    return [(str(p.instrument_id), str(p.quantity)) for p in node.cache.positions_open()]


# ---------------------------------------------------------------- startup reconciliation


def test_a_flat_account_starts_and_reconciles_nothing():
    rig = Rig()
    error, seen = start(rig)
    assert error is None
    assert seen["coverage_complete"] and seen["stream_live"]
    assert seen["instrument_loaded"]
    assert seen["holding"] == []
    assert set(rig.clients[0].report_trace) == {"orders", "fills", "positions"}


def test_every_startup_read_passes_through_the_budget_as_a_query():
    rig = Rig()
    assert start(rig)[0] is None
    assert rig.pacer is not None and rig.pacer.kinds
    assert set(rig.pacer.kinds) == {ActionKind.QUERY}
    assert rig.pacer.wire_requests == len(rig.venue.calls)


def test_an_earlier_filled_order_explains_the_holding_when_the_strategy_claims_it():
    rig = Rig()
    earlier = order_row(client_order_id=f"{PREFIX}earlier-1", submitted_at=stamp(1))
    rig.venue.orders.append(earlier)
    rig.venue.fills.append(fill_activity(earlier))
    rig.venue.positions.append(position_row(qty="1"))
    error, seen = start(rig)
    assert error is None and seen["coverage_complete"]
    assert seen["holding"] == [("AAPL.ALPACA", "1")]


def test_without_the_claim_the_engine_drops_earlier_orders_and_refuses_the_holding():
    """NautilusTrader 2.0.0rc9 filters unclaimed external orders, and every order of an
    earlier run is external to a fresh node (a Python client has no persistent cache). The
    lane's strategy must claim its universe (`external_order_instrument_ids`)."""
    rig = Rig()
    earlier = order_row(client_order_id=f"{PREFIX}earlier-1", submitted_at=stamp(1))
    rig.venue.orders.append(earlier)
    rig.venue.fills.append(fill_activity(earlier))
    rig.venue.positions.append(position_row(qty="1"))
    node = build_node(rig, strategy(claim=False))
    error = asyncio.run(run(node))
    assert isinstance(error, RuntimeError) and "Unresolved positions" in str(error)


def test_failure_case_1_an_old_writers_ended_orders_are_history_not_an_open_writer():
    rig = Rig()
    bought = order_row(client_order_id="OLDWRITER-1", submitted_at=stamp(1), qty="2")
    sold = order_row(client_order_id="OLDWRITER-2", submitted_at=stamp(2), side="sell")
    cancelled = order_row(client_order_id="OLDWRITER-3", submitted_at=stamp(3), status="canceled")
    rig.venue.orders += [bought, sold, cancelled]
    rig.venue.fills += [fill_activity(bought), fill_activity(sold)]
    rig.venue.positions.append(position_row(qty="1"))
    error, seen = start(rig)
    assert error is None and seen["coverage_complete"]
    assert seen["holding"] == [("AAPL.ALPACA", "1")]


def test_failure_case_1_an_old_writers_working_order_refuses_the_start_by_name():
    rig = Rig()
    rig.venue.orders.append(
        order_row(client_order_id="OLDWRITER-4", status="new", submitted_at=stamp(4))
    )
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    trace = rig.clients[0].report_trace["orders"]
    assert trace.reason == "working order of another writer"  # the fixed part only
    assert trace.first == "ValueError" and trace.failures == 1
    assert any("another writer: AAPL" in str(error) for _, error in rig.clients[0].failures)


def test_failure_case_2_ended_history_in_an_unloaded_symbol_is_withheld_and_counted():
    rig = Rig()
    gone = order_row(symbol="TSLA", client_order_id=f"{PREFIX}t-1", submitted_at=stamp(1))
    rig.venue.orders.append(gone)
    rig.venue.fills.append(fill_activity(gone))
    rig.venue.positions.append(position_row(symbol="TSLA", qty="1"))
    error, seen = start(rig)
    assert error is None and seen["coverage_complete"]
    trace = rig.clients[0].report_trace
    assert trace["orders"].withheld_unloaded == 1
    assert trace["positions"].withheld_unloaded == 1
    # A withheld row never lets the engine infer "flat" for its symbol.
    assert seen["bulk"] == {"AAPL.ALPACA": True, "TSLA.ALPACA": False}
    assert seen["holding"] == []


@pytest.mark.parametrize("nested", [False, True])
def test_failure_case_2_a_working_order_in_an_unloaded_symbol_refuses_by_symbol(nested):
    rig = Rig()
    working = order_row(symbol="TSLA", client_order_id=f"{PREFIX}t-2", status="held")
    if nested:  # a working leg behind an ended parent
        working = order_row(
            symbol="TSLA",
            client_order_id=f"{PREFIX}t-3",
            status="filled",
            order_class="oto",
            legs=[working],
        )
    rig.venue.orders.append(working)
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    client = rig.clients[0]
    assert client.report_trace["orders"].reason == "working order outside the lane's universe"
    assert any("universe: TSLA" in str(error) for _, error in client.failures)  # named


def test_a_start_refuses_rows_whose_symbol_it_cannot_read():
    """The venue holds one AAPL share from the lane's earlier filled order, and both the order's
    row and the position's come without a symbol. Neither is known to be outside the universe,
    so neither is withheld as history there: the start refuses. (Withheld, both rows left the
    engine flat against the venue's share, and the start passed.)"""
    rig = Rig()
    earlier = order_row(client_order_id=f"{PREFIX}earlier-1", submitted_at=stamp(1))
    position = position_row(qty="1")
    del earlier["symbol"], position["symbol"]
    rig.venue.orders.append(earlier)
    rig.venue.positions.append(position)
    error, seen = start(rig)
    assert isinstance(error, RuntimeError) and "coverage_complete" not in seen
    client = rig.clients[0]
    reasons = {stage.reason for stage in client.report_trace.values()}
    assert "Alpaca row requires its symbol" in reasons
    assert client.withheld_symbols == set()


def test_failure_case_3_fills_older_than_the_venues_order_history_are_counted():
    rig = Rig()
    listed = order_row(client_order_id=f"{PREFIX}late", submitted_at=stamp(30), qty="1")
    forgotten = order_row(client_order_id=f"{PREFIX}early", submitted_at=stamp(1), side="sell")
    rig.venue.orders.append(listed)  # the venue no longer lists `forgotten`
    rig.venue.fills += [fill_activity(listed), fill_activity(forgotten, when=stamp(1))]
    rig.venue.positions.append(position_row(qty="1"))
    error, seen = start(rig)
    assert error is None and seen["coverage_complete"]
    assert rig.clients[0].report_trace["fills"].before_order_history == 1


def test_the_third_starts_shape_reconciles_with_its_counts():
    """Start 3's recorded shape, rebuilt synthetically from its counts only (sextant#697):
    437 listed orders, 435 of them ended in symbols the node had not loaded, and 8,822 fill
    activities, of which 8,422 are older than the oldest listed order; flat. The start passes.
    FILL paging stops at the order history's horizon, so 5 pages are read instead of the 89
    the earlier line paced through (about 28 s at 180 requests a minute with burst 18)."""
    rig = Rig()
    buy = order_row(client_order_id=f"{PREFIX}buy", submitted_at="2026-11-10T15:00:00.100000Z")
    sell = order_row(
        client_order_id=f"{PREFIX}sell", submitted_at="2026-11-10T15:30:00.100000Z", side="sell"
    )
    others = [
        order_row(
            symbol=f"Z{index:03d}",
            client_order_id=f"OLDWRITER-{index}",
            submitted_at=f"2026-11-0{3 + index // 100}T15:{index % 60:02d}:00.200000Z",
        )
        for index in range(435)
    ]
    rig.venue.orders = [buy, sell, *others]
    explained = [fill_activity(buy), fill_activity(sell)] + [
        fill_activity(others[index % 435]) for index in range(398)
    ]
    forgotten = order_row(submitted_at="2026-10-01T15:00:00.000000Z")  # no longer listed
    old = [
        fill_activity(forgotten, when=f"2026-10-{1 + index // 1000:02d}T14:{index % 60:02d}:00Z")
        for index in range(8422)
    ]
    rig.venue.fills = explained + old
    error, seen = start(rig)
    assert error is None and seen["coverage_complete"]
    trace = rig.clients[0].report_trace
    assert trace["orders"].rows == 437 and trace["orders"].withheld_unloaded == 435
    fills = trace["fills"]
    assert fills.requests["GET /account/activities/FILL"] == 5 and fills.stopped_at_order_history
    assert fills.rows == 500 and fills.before_order_history == 100  # the rest is not read
    assert seen["holding"] == []
    assert rig.pacer is not None and rig.pacer.wire_requests == len(rig.venue.calls) <= 12


def test_an_unexplained_fill_newer_than_the_horizon_still_refuses_after_many_old_pages():
    """Stopping at the horizon never skips a fill that could refuse: those are all newer."""
    rig = Rig()
    listed = order_row(client_order_id=f"{PREFIX}a", submitted_at="2026-11-10T15:00:00.100000Z")
    missing = order_row(client_order_id=f"{PREFIX}b", submitted_at="2026-11-10T16:00:00.100000Z")
    rig.venue.orders = [listed]
    forgotten = order_row(submitted_at="2026-10-01T15:00:00.000000Z")
    rig.venue.fills = [fill_activity(listed), fill_activity(missing)] + [
        fill_activity(forgotten, when=f"2026-10-01T14:{index % 60:02d}:00Z") for index in range(300)
    ]
    rig.venue.positions.append(position_row(qty="1"))
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    assert rig.clients[0].report_trace["fills"].reason == (
        "historical fill that no order report explains"
    )


def test_failure_case_3_an_unexplained_newer_fill_still_refuses():
    rig = Rig()
    listed = order_row(client_order_id=f"{PREFIX}a", submitted_at=stamp(1))
    missing = order_row(client_order_id=f"{PREFIX}b", submitted_at=stamp(40))
    rig.venue.orders.append(listed)
    rig.venue.fills += [fill_activity(listed), fill_activity(missing, when=stamp(40))]
    rig.venue.positions.append(position_row(qty="1"))
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    trace = rig.clients[0].report_trace["fills"]
    assert trace.reason == "historical fill that no order report explains"


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("an unexplained fill", "historical fill that no order report explains"),
        ("a page that is not a list", "Alpaca fill page is not a list"),
    ],
)
def test_a_start_refused_by_its_last_stage_reads_nothing_more_and_keeps_its_record(answer, reason):
    """The engine runs the three startup stages concurrently. Here the fill stage ends last (its
    FILL page is slow), after the order and position stages have both been read, and refuses the
    start: failure case 3's newer unexplained fill, or a page that is not a list. Its read began
    during startup, so the start decides: no gap and no recovery read while the start is being
    refused, and the order and position stages keep the record of what they read."""
    rig = Rig()
    listed = order_row(client_order_id=f"{PREFIX}a", submitted_at=stamp(1))
    missing = order_row(client_order_id=f"{PREFIX}b", submitted_at=stamp(40))
    rig.venue.orders.append(listed)
    rig.venue.fills += [fill_activity(listed), fill_activity(missing, when=stamp(40))]
    rig.venue.positions.append(position_row(qty="1"))

    def slow(page):
        time.sleep(1.0)  # in the request's worker thread: the other stages finish meanwhile
        return page if answer == "an unexplained fill" else {"activities": page}

    reshaped(rig.venue, "/account/activities/FILL", slow)
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    client = rig.clients[0]
    assert client._started  # the order and position stages were read before the fill stage failed
    assert client.report_trace["fills"].reason == reason
    assert (client._gap, client.recoveries) == (0, 0)
    assert len(rig.venue.listings) == 2  # the order stage's and the fill stage's own
    orders, positions = client.report_trace["orders"], client.report_trace["positions"]
    assert (orders.rows, orders.cancelled, orders.failures) == (1, False, 0)
    assert (positions.rows, positions.cancelled, positions.failures) == (1, False, 0)


def test_a_failed_start_records_its_stage_counts_and_first_failure_and_no_value():
    rig = Rig()
    rig.venue.fail("get", "/positions", api_error(503))
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    trace = rig.clients[0].report_trace
    assert trace["orders"].failures == 0 and trace["fills"].failures == 0
    positions = trace["positions"]
    assert (positions.first, positions.status, positions.failures) == ("APIError", 503, 1)
    assert positions.requests == {"GET /positions": 1}
    assert positions.reason is None  # a venue body is never copied


def test_a_holding_no_order_explains_refuses_in_the_engine_itself():
    rig = Rig()
    rig.venue.positions.append(position_row(qty="5"))
    error, _ = start(rig)
    assert isinstance(error, RuntimeError) and "Unresolved positions" in str(error)


def test_an_unclassified_order_status_refuses_rather_than_guessing():
    rig = Rig()
    odd = order_row(
        client_order_id=f"{PREFIX}odd", submitted_at=stamp(1), qty="7", limit_price="123.45"
    )
    odd["status"] = "pending_review_v2"
    rig.venue.orders.append(odd)
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    trace = rig.clients[0].report_trace
    assert trace["orders"].first == "UnmappedOrderStatus"
    assert trace["orders"].reason == "Alpaca order status requires classification"
    # The failed start's record names the cause and holds none of the row's values.
    record = repr(trace)
    for value in (odd["id"], odd["client_order_id"], "123.45", "pending_review_v2"):
        assert value not in record


def test_without_fee_evidence_or_a_budget_the_client_refuses_to_connect():
    rig = Rig()
    error, _ = start(rig, commission_per_fill=None)
    assert error is not None
    assert rig.venue.calls == []  # refused before any request

    class NoPacer(Rig):
        def wiring(self):
            from dataclasses import replace

            return replace(super().wiring(), pacer=None)

    rig = NoPacer()
    error, _ = start(rig)
    assert error is not None and rig.venue.calls == []


# ---------------------------------------------------------------- commands and the stream


async def until(condition, timeout: float = 15.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


def limit_order(running, number: int = 1, side=OrderSide.BUY, price: str = "100.00", qty="1"):
    return running.order_factory.limit(
        AAPL,
        side,
        Quantity.from_str(qty),
        Price.from_str(price),
        time_in_force=TimeInForce.DAY,
        client_order_id=ClientOrderId(f"{PREFIX}{number}"),
    )


def drive(rig: Rig, script, *, on_start=None, engine: dict | None = None, **config):
    """Run a node whose strategy submits on start; `script` drives the stream meanwhile.
    `config` overrides the client's settings."""
    box: dict = {}

    def submit(running):
        box["strategy"] = running
        if on_start is not None:
            on_start(running, box)
        else:
            box["order"] = limit_order(running)
            running.submit_order(box["order"])

    node = build_node(rig, strategy(on_start=submit), engine=engine, **config)
    # A running node's state is read through the cache taken before the run.
    held = {"node": node, "cache": node.cache}
    del node

    async def main():
        runner = asyncio.ensure_future(run(held["node"], 60))
        try:
            await until(lambda: "strategy" in box)
            await script(box, lambda number=1: order_status(held["cache"], number))
        finally:
            # Always let the node stop, even when the script failed: its task would otherwise
            # keep the node alive through the failure's traceback.
            if not runner.done() and "strategy" in box:
                box["strategy"].shutdown_system("test done")
            error = await runner
        return error

    try:
        box["error"] = asyncio.run(main())
        box["holding"] = holding(held["node"])
    finally:
        # Even when the script fails: a traceback holding the node would block the next test.
        held.clear()
        box.pop("strategy", None)
    return box


def order_status(cache, number: int | str = 1):
    """By the lane's number (M3-<n>), or by any client order id given as text."""
    wanted = number if isinstance(number, str) else f"{PREFIX}{number}"
    order = cache.order(ClientOrderId(wanted))
    return None if order is None else order.status


def test_a_day_limit_order_is_paced_posted_accepted_and_filled_by_the_stream():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        rig.venue.orders[-1] = {**row, "status": "filled", "filled_qty": "1"}
        rig.stream.push(update("fill", rig.venue.orders[-1]))
        await until(lambda: status() == OrderStatus.FILLED)

    box = drive(rig, script)
    assert box["error"] is None
    assert rig.venue.last_post == {
        "client_order_id": f"{PREFIX}1",
        "symbol": "AAPL",
        "qty": "1",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "100.00",
        "order_class": "simple",
        "extended_hours": False,
    }
    assert rig.pacer is not None and ActionKind.SUBMIT in rig.pacer.kinds
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_a_budget_refusal_rejects_the_order_and_nothing_reaches_the_venue():
    rig = Rig()

    def on_start(running, box):
        assert rig.pacer is not None
        rig.pacer.refuse_kinds.add(ActionKind.SUBMIT)
        box["order"] = limit_order(running)
        running.submit_order(box["order"])

    async def script(box, status):
        await until(lambda: status() == OrderStatus.REJECTED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert ("post", "/orders") not in rig.venue.calls


def test_a_documented_venue_refusal_rejects_the_order():
    rig = Rig()
    rig.venue.fail("post", "/orders", api_error(422))

    async def script(box, status):
        await until(lambda: status() == OrderStatus.REJECTED)

    assert drive(rig, script)["error"] is None


@pytest.mark.parametrize("failure", [api_error(500), api_error(429), TimeoutError("synthetic")])
def test_an_ambiguous_answer_after_send_never_rejects_locally(failure):
    rig = Rig()
    rig.venue.fail("post", "/orders", failure)

    async def script(box, status):
        await until(lambda: ("post", "/orders") in rig.venue.calls)
        await asyncio.sleep(0.2)
        box["status_during_run"] = status()

    box = drive(rig, script)
    assert box["status_during_run"] == OrderStatus.SUBMITTED  # the venue's later answer decides
    # The engine keeps the outcome open and says so at shutdown rather than closing it quietly.
    assert "Submission recovery incomplete" in str(box["error"])


def test_a_cancel_is_paced_sent_once_and_settled_by_the_stream():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        box["strategy"].cancel_order(box["order"].client_order_id)
        # A second cancel while the first is unresolved sends nothing.
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", f"/orders/{row['id']}") in rig.venue.calls)
        await asyncio.sleep(0.2)
        box["unresolved"] = list(client._pending) == [row["id"]]  # a 204 is only an attempt
        row["status"] = "canceled"
        rig.stream.push(update("canceled", row))
        await until(lambda: status() == OrderStatus.CANCELED)
        box["pending"] = list(client._pending)

    box = drive(rig, script)
    assert box["error"] is None
    deletes = [call for call in rig.venue.calls if call[0] == "delete"]
    assert len(deletes) == 1
    assert rig.pacer is not None and ActionKind.CANCEL in rig.pacer.kinds
    assert box["unresolved"] and box["pending"] == []  # the terminal update answered the cancel


# The engine's routine open-order checks, every 0.2 s from the start (rc9 otherwise waits
# `reconciliation_startup_delay_secs` after startup before its first periodic check).
FAST_OPEN_CHECKS = {"open_check_interval_secs": 0.2, "reconciliation_startup_delay_secs": 0.0}


def test_a_gap_stops_new_orders_until_a_full_read_issued_after_it_succeeds():
    """An unclassified update is a gap. The engine's routine open-order checks (every 0.2 s
    here) do not close it; only a full read of orders and positions does. While that read
    fails, new orders are denied; once it succeeds, they pass again."""
    rig = Rig()

    def on_start(running, box):
        box["first"], box["second"] = limit_order(running, 1), limit_order(running, 2)

    async def script(box, status):
        rig.venue.fail("get", "/positions", api_error(503))  # the recovery's read fails
        rig.stream.push({"stream": "trade_updates", "data": {"event": "restated", "order": {}}})
        await until(lambda: not rig.clients[0].coverage_complete)
        await asyncio.sleep(1.0)  # several open-order checks and one failed recovery later
        assert not rig.clients[0].coverage_complete
        box["strategy"].submit_order(box["first"])
        await until(lambda: status(1) == OrderStatus.DENIED)
        rig.venue.failures.clear()  # the next recovery attempt succeeds
        await until(lambda: rig.clients[0].coverage_complete)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start, engine=FAST_OPEN_CHECKS)
    assert box["error"] is None
    client = rig.clients[0]
    assert client.recoveries == 1
    assert rig.venue.last_post["client_order_id"] == f"{PREFIX}2"  # the first was never sent


def test_routine_open_order_checks_never_deny_a_healthy_order():
    rig = Rig()
    rig.venue.listing_delay = 0.05  # each open-order check spends time reading

    def on_start(running, box):
        box["startup_listings"] = rig.venue.calls.count(("get", "/orders"))
        box["orders"] = [limit_order(running, n) for n in range(1, 21)]

    async def script(box, status):
        for order in box["orders"]:
            box["strategy"].submit_order(order)
            await asyncio.sleep(0.05)
        await until(lambda: all(status(n) is not None for n in range(1, 21)))
        await until(lambda: all(status(n) != OrderStatus.SUBMITTED for n in range(1, 21)))
        box["statuses"] = [status(n) for n in range(1, 21)]

    box = drive(rig, script, on_start=on_start, engine=FAST_OPEN_CHECKS)
    assert box["error"] is None
    assert box["statuses"] == [OrderStatus.ACCEPTED] * 20
    # Startup lists the orders twice: the orders stage, and the fills stage's order history.
    assert box["startup_listings"] >= 2
    assert rig.venue.calls.count(("get", "/orders")) > box["startup_listings"]  # checks did run


@pytest.mark.parametrize("symbol", ["AAPL", "TSLA"])
def test_another_writers_activity_on_the_account_stops_new_orders(symbol):
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)

    async def script(box, status):
        foreign = order_row(
            symbol=symbol, client_order_id="web-order-1", status="new", filled_qty="0"
        )
        rig.stream.push(update("new", foreign))
        await until(lambda: rig.clients[0].foreign_writer_seen)
        box["strategy"].submit_order(box["order"])
        await until(lambda: status() == OrderStatus.DENIED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert ("post", "/orders") not in rig.venue.calls


def test_after_the_stream_reconnects_the_client_reads_the_gap_back():
    rig = Rig()

    def on_start(running, box):
        box["calls_before"] = len(rig.venue.calls)

    async def script(box, status):
        rig.stream.push("reconnect")
        await until(lambda: rig.clients[0].stream_restarts == 1)
        await until(lambda: rig.clients[0].coverage_complete)
        await asyncio.sleep(0.1)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    recovered = rig.venue.calls[box["calls_before"] :]
    assert ("get", "/orders") in recovered and ("get", "/positions") in recovered


def test_market_orders_and_modifies_are_refused_without_a_request():
    rig = Rig()

    def on_start(running, box):
        box["market"] = running.order_factory.market(
            AAPL, OrderSide.BUY, Quantity.from_str("1"), client_order_id=ClientOrderId(f"{PREFIX}9")
        )
        running.submit_order(box["market"])

    async def script(box, status):
        await until(lambda: status(9) == OrderStatus.DENIED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert ("post", "/orders") not in rig.venue.calls


def test_a_cancel_refused_before_send_returns_the_order_to_working():
    """The cancel's pre-read fails (503): nothing was sent. The denial carries the command's
    id, so the engine puts the order back to ACCEPTED and a later cancel goes out."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        rig.venue.fail("get", f"/orders/{row['id']}", api_error(503))
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("get", f"/orders/{row['id']}") in rig.venue.calls)
        await until(lambda: status() == OrderStatus.ACCEPTED)
        rig.venue.failures.clear()
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", f"/orders/{row['id']}") in rig.venue.calls)

    box = drive(rig, script)
    assert box["error"] is None


def test_ended_history_the_lane_cannot_map_is_counted_when_it_holds_no_fill():
    rig = Rig()
    replaced = order_row(client_order_id="OLDWRITER-r", status="replaced", filled_qty="0")
    legs = [
        order_row(status="canceled", filled_qty="0"),
        order_row(status="expired", filled_qty="0"),
    ]
    bracket = order_row(
        client_order_id="OLDWRITER-b",
        status="canceled",
        filled_qty="0",
        order_class="bracket",
        legs=legs,
    )
    rig.venue.orders += [replaced, bracket]
    error, seen = start(rig)
    assert error is None and seen["coverage_complete"]
    trace = rig.clients[0].report_trace["orders"]
    # Listed with its legs under it, the bracket is one row and is withheld whole: no leg
    # reaches the engine as an order of its own.
    assert (trace.rows, trace.withheld_unmapped) == (2, 2)


def test_the_stand_in_venue_lists_legs_under_their_parent_only_when_asked_to():
    venue = FakeVenue()
    legs = [
        order_row(status="canceled", filled_qty="0"),
        order_row(status="expired", filled_qty="0"),
    ]
    parent = order_row(status="canceled", filled_qty="0", order_class="bracket", legs=legs)
    venue.orders.append(parent)
    rolled_up = venue.get("/orders", {"status": "all", "nested": True})
    assert [row["id"] for row in rolled_up] == [parent["id"]]
    assert [leg["id"] for leg in rolled_up[0]["legs"]] == [leg["id"] for leg in legs]
    flat = venue.get("/orders", {"status": "all"})
    assert {row["id"] for row in flat} == {parent["id"], *(leg["id"] for leg in legs)}
    assert all(row["legs"] is None for row in flat)


@pytest.mark.parametrize("shape", ["replaced", "bracket"])
def test_ended_history_the_lane_cannot_map_refuses_when_it_holds_fills(shape):
    rig = Rig()
    if shape == "replaced":
        row = order_row(client_order_id="OLDWRITER-r", status="replaced", qty="2", filled_qty="1")
    else:
        legs = [order_row(status="filled", qty="1"), order_row(status="canceled", filled_qty="0")]
        row = order_row(
            client_order_id="OLDWRITER-b", status="filled", order_class="bracket", legs=legs
        )
    rig.venue.orders.append(row)
    error, _ = start(rig)
    assert isinstance(error, RuntimeError)
    reason = rig.clients[0].report_trace["orders"].reason
    assert reason == "ended order the lane cannot map holds fills"


def test_a_report_ahead_of_the_streams_fills_is_not_volunteered():
    """At the venue 1 of 2 shares fills and the rest is cancelled. The cancel's read sees the
    ended row before the stream delivers the fill; handing that row over would make the
    engine invent the fill, and the stream's own execution would then count it twice."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running, qty="2")
        running.submit_order(box["order"])

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        row.update(status="canceled", filled_qty="1", filled_avg_price="100.00")
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: rig.clients[0].withheld_reports == 1)
        rig.stream.push(update("partial_fill", row, qty="1", position_qty="1"))
        rig.stream.push(update("canceled", row))
        await until(lambda: status() == OrderStatus.CANCELED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_a_refusal_owed_to_an_old_cancel_does_not_swallow_the_next_cancels_refusal():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        target = f"/orders/{row['id']}"
        rig.venue.fail("delete", target, api_error(500))  # cancel 1: outcome unknown
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", target) in rig.venue.calls)
        await asyncio.sleep(0.1)
        rig.venue.failures.clear()
        box["strategy"].query_order(box["order"])  # a read finds it still working
        await until(lambda: status() == OrderStatus.ACCEPTED)
        assert rig.clients[0]._owed == {row["id"]: 1}
        box["strategy"].cancel_order(box["order"].client_order_id)  # cancel 2: 204
        await until(lambda: rig.venue.calls.count(("delete", target)) == 2)
        await until(lambda: rig.clients[0]._owed == {})
        rig.stream.push(update("order_cancel_rejected", row))  # the venue refuses cancel 2
        await until(lambda: status() == OrderStatus.ACCEPTED)

    box = drive(rig, script)
    assert box["error"] is None


def queued(rig: Rig) -> bool:
    return rig.pacer is not None and bool(rig.pacer.queue)


def held_budget(rig: Rig) -> None:
    """Hold the stand-in budget so that requests wait in its queue."""
    assert rig.pacer is not None
    rig.pacer.paused_until = 10**30


def release_budget(rig: Rig) -> None:
    assert rig.pacer is not None
    rig.pacer.paused_until = 0
    rig.pacer.drain()


def test_a_cancel_while_its_submit_waits_for_the_budget_withdraws_it_unsent():
    rig = Rig()

    def on_start(running, box):
        held_budget(rig)
        box["order"] = limit_order(running)
        running.submit_order(box["order"])

    async def script(box, status):
        await until(lambda: status() == OrderStatus.SUBMITTED and queued(rig))
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: status() == OrderStatus.CANCELED)
        release_budget(rig)
        await asyncio.sleep(0.2)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert ("post", "/orders") not in rig.venue.calls


def test_a_gap_while_a_submit_waits_for_the_budget_refuses_it_at_admission():
    rig = Rig()

    def on_start(running, box):
        held_budget(rig)
        box["order"] = limit_order(running)
        running.submit_order(box["order"])

    async def script(box, status):
        await until(lambda: status() == OrderStatus.SUBMITTED and queued(rig))
        rig.venue.fail("get", "/positions", api_error(503))  # the gap stays open
        rig.stream.push({"stream": "trade_updates", "data": {"event": "restated", "order": {}}})
        await until(lambda: not rig.clients[0].coverage_complete)
        release_budget(rig)
        await until(lambda: status() == OrderStatus.REJECTED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert ("post", "/orders") not in rig.venue.calls


def test_another_writers_order_reaches_the_engine_and_the_lane_never_cancels_it():
    rig = Rig()

    def on_start(running, box):
        pass

    async def script(box, status):
        foreign = order_row(client_order_id="web-order-1", status="new", filled_qty="0")
        rig.venue.orders.append(foreign)
        rig.stream.push(update("new", foreign))
        await until(lambda: status("web-order-1") == OrderStatus.ACCEPTED)  # claimed, known
        client = rig.clients[0]
        assert client.foreign_writer_seen and client.coverage_complete  # only the flag stops
        box["strategy"].cancel_order(ClientOrderId("web-order-1"))
        await asyncio.sleep(0.3)
        box["after"] = status("web-order-1")

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["after"] == OrderStatus.ACCEPTED
    assert not any(method == "delete" for method, _ in rig.venue.calls)


def hold_the_gaps_read(rig: Rig) -> None:
    """An unknown outcome after send is a gap; failing the order listing (503, no answer, so
    no gap of its own) keeps the gap's full read from settling the cancel first, so a test can
    see what the DELETE's answer, or an explicit read, settles."""
    rig.venue.fail("get", "/orders", api_error(503))


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (api_error(422), OrderStatus.ACCEPTED),  # documented refusal: the cancel is rejected
        (api_error(429), OrderStatus.ACCEPTED),
        (api_error(500), OrderStatus.PENDING_CANCEL),  # ambiguous: the venue's answer decides
        (TimeoutError("synthetic"), OrderStatus.PENDING_CANCEL),
    ],
)
def test_a_deletes_answer_settles_the_cancel_only_when_it_is_a_documented_refusal(
    failure, expected
):
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        target = f"/orders/{rig.venue.orders[-1]['id']}"
        rig.venue.fail("delete", target, failure)
        hold_the_gaps_read(rig)
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", target) in rig.venue.calls)
        await asyncio.sleep(0.3)
        box["after"] = status()

    box = drive(rig, script)
    assert box["after"] == expected


def test_the_venues_cancel_refusal_on_the_stream_returns_the_order_to_working():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", f"/orders/{row['id']}") in rig.venue.calls)
        await until(lambda: status() == OrderStatus.PENDING_CANCEL)
        rig.stream.push(update("order_cancel_rejected", {**row, "status": "new"}))
        await until(lambda: status() == OrderStatus.ACCEPTED)

    assert drive(rig, script)["error"] is None


def cancel_refusals(box) -> list[tuple[str, str]]:
    """Each cancel refusal the strategy has been told of, in order: the event and its reason.
    The engine reports a cancel refused before it was sent as denied, one refused after as
    rejected."""
    return [
        (type(event).__name__, str(event.reason))
        for event in box["strategy"].events
        if type(event).__name__ in ("OrderCancelDenied", "OrderCancelRejected")
    ]


def test_the_venues_refusal_after_a_read_already_settled_the_cancel_emits_nothing_more():
    """The DELETE's answer is lost (500). A later read finds the order still working and
    settles the cancel with one refusal. The venue's own refusal then arrives on the stream:
    it is late, is counted, and the engine is not told a second time."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        target = f"/orders/{row['id']}"
        rig.venue.fail("delete", target, api_error(500))
        hold_the_gaps_read(rig)
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", target) in rig.venue.calls)
        await until(lambda: row["id"] in client._pending and client._pending[row["id"]].ended > 0)
        box["strategy"].query_order(box["order"])
        await until(lambda: status() == OrderStatus.ACCEPTED and cancel_refusals(box))
        box["settled_by_the_read"] = cancel_refusals(box)
        rig.stream.push(update("order_cancel_rejected", {**row, "status": "new"}))
        await until(lambda: client.late_answers == 1)
        await asyncio.sleep(0.3)  # long enough for a second refusal to reach the strategy
        box["after_the_late_refusal"] = cancel_refusals(box)
        box["status"] = status()

    box = drive(rig, script)
    assert box["error"] is None
    assert box["settled_by_the_read"] == [
        ("OrderCancelRejected", "venue order still working after an unanswered cancel")
    ]
    assert box["after_the_late_refusal"] == box["settled_by_the_read"]
    assert box["status"] == OrderStatus.ACCEPTED


@pytest.mark.parametrize("answered", [f"{PREFIX}another", "web-order-7"])
def test_a_cancel_whose_read_answers_another_order_sends_no_delete_and_is_refused(answered):
    """GET /orders/{id} answers a row with another client order id (another order of the
    lane, or another writer's). The lane never deletes on such an answer: the cancel is
    refused unsent, and the order goes back to working."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        row["client_order_id"] = answered
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("get", f"/orders/{row['id']}") in rig.venue.calls)
        await until(lambda: cancel_refusals(box) or "delete" in {m for m, _ in rig.venue.calls})
        await asyncio.sleep(0.3)  # long enough for a DELETE to go out, if one were sent
        box["refusals"] = cancel_refusals(box)
        box["status"] = status()

    box = drive(rig, script)
    assert box["error"] is None
    assert not any(method == "delete" for method, _ in rig.venue.calls)
    assert box["refusals"] == [
        ("OrderCancelDenied", "not sent: venue order is outside the requested namespace")
    ]
    assert box["status"] == OrderStatus.ACCEPTED


def test_only_a_read_issued_after_the_deletes_own_call_ended_settles_it():
    rig = Rig()
    rig.venue.delete_delay = 0.4

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: row["id"] in client._pending)  # the DELETE is on the wire
        box["strategy"].query_order(box["order"])  # a read while it is still in flight
        await asyncio.sleep(0.2)
        box["early"] = row["id"] in client._pending
        await until(lambda: client._pending[row["id"]].ended > 0)  # its own call ended
        rig.venue.orders[-1]["status"] = "new"  # the venue did not act on it
        box["strategy"].query_order(box["order"])
        await until(lambda: row["id"] not in client._pending)
        box["owed"] = dict(client._owed)

    box = drive(rig, script)
    assert box["error"] is None
    assert box["early"] is True  # the early read did not settle the cancel
    assert list(box["owed"].values()) == [1]  # the later one did, and owes the venue's refusal


def test_after_a_reconnect_the_engine_learns_what_the_gap_held():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        row = rig.venue.orders[-1]
        row.update(status="filled", filled_qty="1", filled_avg_price="100.00")  # while away
        rig.venue.positions.append(position_row(qty="1"))
        rig.stream.push("reconnect")
        await until(lambda: rig.clients[0].recoveries == 1)
        await until(lambda: status() == OrderStatus.FILLED)

    box = drive(rig, script)
    assert box["error"] is None
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def two_share_order(running, box) -> None:
    box["order"] = limit_order(running, qty="2")
    running.submit_order(box["order"])


def one_more_share(rig: Rig, row: dict) -> dict:
    """At the venue one more share of the order fills. Returns the stream's message for that
    execution; its order row is the order as it is after it."""
    filled = int(row["filled_qty"]) + 1
    done = filled == int(row["qty"])
    when = stamp(30, filled)
    row.update(
        status="filled" if done else "partially_filled",
        filled_qty=str(filled),
        filled_avg_price="100.00",
        updated_at=when,
    )
    rig.venue.positions[:] = [position_row(qty=str(filled))]
    event = "fill" if done else "partial_fill"
    return update(event, row, qty="1", position_qty=str(filled), timestamp=when)


def engine_holds(client) -> list[str]:
    return [str(position.quantity) for position in client.cache.positions_open()]


def backlogged(client, seconds: float) -> None:
    """From now on the engine receives what the client hands it `seconds` late, in order: an
    engine behind on its queue, whose own record of an order lags what it was handed. The
    client's own stamps (`_last_execution`) must then do what that record cannot."""
    loop, hand, queue = asyncio.get_running_loop(), client._handle_report, []

    def release() -> None:
        while queue:
            hand(*queue.pop(0))

    def late(*report) -> None:
        if not queue:
            loop.call_later(seconds, release)
        queue.append(report)

    client._handle_report = late


# The engine as it runs, and an engine that processes what the client hands it 0.6 s late.
ENGINES = pytest.mark.parametrize("backlog", [0.0, 0.6], ids=["prompt-engine", "backlogged-engine"])


@pytest.mark.parametrize("shown_by_the_read", [1, 2])
def test_a_fill_the_recovery_read_showed_first_is_not_counted_again_from_the_stream(
    shown_by_the_read,
):
    """A 2-share order. The stream is lost and comes back, and the read that follows shows
    the engine one share (or both) as filled; the engine infers those fills. The stream then
    delivers the same executions: each is counted as known and not handed on. The execution
    after them is new and is handed on. The engine holds what the venue holds throughout."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        executions = [one_more_share(rig, row) for _ in range(shown_by_the_read)]
        rig.stream.push("reconnect")
        await until(lambda: client.recoveries == 1 and engine_holds(client) == [row["filled_qty"]])
        for message in executions:  # the stream delivers what the read already showed
            rig.stream.push(message)
        await until(lambda: client.known_executions + len(client._forwarded) == len(executions))
        await asyncio.sleep(0.3)  # long enough for a forwarded fill to reach the engine
        box["engine"], box["venue"] = engine_holds(client), [row["filled_qty"]]
        if shown_by_the_read == 1:
            rig.stream.push(one_more_share(rig, row))  # the next execution is new
        await until(lambda: status() == OrderStatus.FILLED)
        box["known"], box["complete"] = client.known_executions, client.coverage_complete

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    assert box["engine"] == box["venue"] == [str(shown_by_the_read)]
    assert box["known"] == shown_by_the_read and box["complete"]
    assert box["holding"] == [("AAPL.ALPACA", "2")] and rig.venue.positions[0]["qty"] == "2"
    assert rig.clients[0].recoveries == 1


def test_a_fill_the_startup_read_showed_first_is_not_counted_again_from_the_stream():
    """The same at startup, where the stream is subscribed before the account is read: an
    earlier order shows one of its two shares filled, the engine infers that fill, and the
    stream then delivers the execution."""
    rig = Rig()
    earlier = order_row(
        client_order_id=f"{PREFIX}earlier",
        status="partially_filled",
        qty="2",
        filled_qty="1",
        submitted_at=stamp(1),
    )
    rig.venue.orders.append(earlier)
    rig.venue.fills.append(fill_activity(earlier))
    rig.venue.positions.append(position_row(qty="1"))

    def on_start(running, box):
        pass

    async def script(box, status):
        client = rig.clients[0]
        box["at_start"] = engine_holds(client)
        rig.stream.push(update("partial_fill", earlier, qty="1", position_qty="1"))
        await until(lambda: client.known_executions + len(client._forwarded) == 1)
        await asyncio.sleep(0.3)  # long enough for a forwarded fill to reach the engine
        box["engine"], box["known"] = engine_holds(client), client.known_executions
        box["status"] = status(f"{PREFIX}earlier")

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["at_start"] == box["engine"] == [earlier["filled_qty"]]
    assert box["known"] == 1 and box["status"] == OrderStatus.PARTIALLY_FILLED


@pytest.mark.parametrize(
    ("delivered", "repeats", "gaps"),
    [
        pytest.param([1, 2], 0, 0, id="in order"),
        pytest.param([1, 1, 2, 2], 2, 0, id="each twice"),
        pytest.param([2, 1], 0, 1, id="out of order"),
    ],
)
def test_two_partial_fills_are_counted_once_each_however_the_stream_delivers_them(
    delivered, repeats, gaps
):
    """A 2-share order fills in two executions of one share. In order, each is handed on.
    Delivered twice, the repeats are counted and dropped. Out of order, the later one does not
    continue from what the engine has, so it is withheld as a gap, and the full read that the
    gap starts shows the engine the order. The engine ends with what the venue holds."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        executions = {1: one_more_share(rig, row), 2: one_more_share(rig, row)}
        for number in delivered:
            rig.stream.push(executions[number])
        await until(lambda: status() == OrderStatus.FILLED and client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for a repeated fill to reach the engine
        box["engine"] = engine_holds(client)

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    assert box["engine"] == ["2"] and box["holding"] == [("AAPL.ALPACA", "2")]
    client = rig.clients[0]
    assert (client.duplicate_executions, client.known_executions) == (repeats, 0)
    assert client.recoveries == gaps
    assert [str(error) for _, error in client.failures] == [
        "fill does not continue from the filled quantity the engine has"
    ] * gaps


def test_a_fill_whose_order_row_cannot_be_the_order_after_it_is_a_gap():
    """A read has shown the engine one share of a 2-share order. A fill update then reports an
    execution of two shares while its order row shows one share filled, which no order holds
    after a two-share execution. The row sits at the quantity the engine has, yet the update
    is not taken for the fill the read showed: it is a gap, nothing is handed on, and the
    gap's read shows the engine the order."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        one_more_share(rig, row)  # only the read below shows the engine this share
        rig.stream.push("reconnect")
        await until(lambda: client.recoveries == 1 and engine_holds(client) == ["1"])
        rig.stream.push(update("partial_fill", row, qty="2", position_qty="1"))
        await until(lambda: client.failures or client.known_executions)  # a gap, or known
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for a forwarded fill to reach the engine
        box["engine"], box["status"] = engine_holds(client), status()

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    client = rig.clients[0]
    assert [str(error) for _, error in client.failures] == [
        "fill does not continue from the filled quantity the engine has"
    ]
    assert (client.known_executions, len(client._forwarded)) == (0, 0)
    assert client.recoveries == 2  # the read that showed the share, and the gap's
    assert box["engine"] == ["1"] and box["status"] == OrderStatus.PARTIALLY_FILLED
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_a_fill_that_arrives_during_the_recovery_read_does_not_hide_the_one_after_it():
    """The stream delivers the first execution while the recovery read is under way, and the
    read's listing already shows the second. The engine skips an order's snapshot when a fill
    for it arrived during the read (2.0.0rc9), so that read is not handed over and the known
    quantity stays at one share. The second execution then arrives and is handed on, not taken
    for one a read had shown; the next read closes the gap."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.venue.listing_delay = 0.3  # the recovery's order listing takes this long
        rig.stream.push("reconnect")
        await until(lambda: client.stream_restarts == 1)
        await asyncio.sleep(0.1)  # the listing is under way
        first, second = one_more_share(rig, row), one_more_share(rig, row)
        rig.stream.push(first)
        await asyncio.sleep(0.5)  # the read has ended
        box["after_the_read"] = (engine_holds(client), client.recoveries, client.coverage_complete)
        rig.stream.push(second)
        await until(lambda: status() == OrderStatus.FILLED and client.coverage_complete)
        box["known"], box["handed_on"] = client.known_executions, len(client._forwarded)

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    assert box["after_the_read"] == (["1"], 0, False)  # not handed over
    assert (box["known"], box["handed_on"]) == (0, 2)
    assert box["holding"] == [("AAPL.ALPACA", "2")] and rig.clients[0].recoveries == 1


@ENGINES
def test_a_recovery_read_is_read_again_when_an_execution_reached_the_engine_during_it(backlog):
    """The stream delivers an execution while the recovery read is under way, and the venue
    then cancels the rest of the order; that update never reaches the client and opens no
    gap. The read's listing shows the quantity the engine has and an ended order. The engine
    skips an order's snapshot when a fill for it arrived during the read (2.0.0rc9), so
    handing this read over would call the account covered while the engine still holds the
    order as working. It is read again, and the engine learns that the order ended. With the
    engine behind on its queue, its record does not show the fill when the read ends."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.venue.listing_delay = 0.3  # the recovery's order listing takes this long
        rig.stream.push("reconnect")
        await until(lambda: client.stream_restarts == 1)
        await asyncio.sleep(0.1)  # the listing is under way
        execution = one_more_share(rig, row)
        row.update(status="canceled", canceled_at=row["updated_at"])  # no update for this
        if backlog:
            backlogged(client, backlog)
        rig.stream.push(execution)
        await asyncio.sleep(0.5)  # the read has ended
        box["after_the_read"] = (client.recoveries, client.coverage_complete)
        box["status_after_the_read"] = status()
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3 + backlog)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), client.recoveries)

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    assert box["after_the_read"] == (0, False)  # not handed over
    if not backlog:
        assert box["status_after_the_read"] == OrderStatus.PARTIALLY_FILLED
    assert box["covered"] == (OrderStatus.CANCELED, ["1"], 1)
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_an_order_update_showing_a_fill_the_engine_lacks_is_a_gap_that_stops_the_read():
    """A share of a 2-share order fills while the stream is away. The recovery read lists the
    order as partially filled; while it reads the positions, the venue cancels the rest and
    the stream delivers that update. Its row shows a fill the engine has not been handed, so
    it is withheld; handing the read over would then show the engine a working order and call
    the account covered. The withheld update is a gap: that read is not handed over, and the
    next one shows the engine the order ended."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        one_more_share(rig, row)  # its update is lost with the stream
        rig.venue.positions_delay = 0.5  # the recovery's positions read takes this long
        calls = len(rig.venue.calls)
        rig.stream.push("reconnect")
        await until(lambda: ("get", "/positions") in rig.venue.calls[calls:])  # orders listed
        rig.venue.positions_delay = 0.0
        row.update(status="canceled", canceled_at=row["updated_at"])
        rig.stream.push(update("canceled", row))  # this update is delivered
        await until(lambda: client.withheld_reports == 1)
        await asyncio.sleep(0.8)  # the read under way has ended
        box["after_the_read"] = (status(), client.recoveries, client.coverage_complete)
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), client.recoveries)

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    assert box["covered"] == (OrderStatus.CANCELED, ["1"], 1)
    assert box["after_the_read"] == (OrderStatus.ACCEPTED, 0, False)  # not handed over
    assert [str(error) for _, error in rig.clients[0].failures] == [
        "order update shows a fill the engine has not been handed"
    ]
    assert box["holding"] == [("AAPL.ALPACA", "1")]


@ENGINES
@pytest.mark.parametrize(
    ("handed_on_before", "first_read_secs"),
    [(0, 0.0), (1, 0.0), (0, 1.5)],
    ids=["nothing-handed-on-before", "one-share-handed-on-before", "slow-first-read"],
)
def test_a_read_begun_just_after_a_recovery_read_showed_a_fill_is_read_again(
    handed_on_before, first_read_secs, backlog
):
    """A share of the order fills while the stream is away, and the recovery read shows the
    engine that share; the engine infers the fill as it reconciles that read. A second gap
    opens in the same moment, and the venue cancels the rest meanwhile with no update. The
    engine skips an order's snapshot when a fill for it is stamped after the read began
    (2.0.0rc9), so the second read would show it nothing for that order while the account is
    called covered. It is read again, and the engine learns that the order ended.

    The cases: a 2-share order with nothing handed on before the gap; a 3-share order whose
    first share the stream delivered and the adapter handed on, so the read raises the known
    quantity from one share to two; and a first read slower than the margin, so the stamp has
    to be the moment the read is handed over, not the moment it began. Each also with the
    engine behind on its queue: its record does not show the fill when the second read ends."""
    rig = Rig()
    shares = 2 + handed_on_before

    def on_start(running, box):
        box["order"] = limit_order(running, qty=str(shares))
        running.submit_order(box["order"])

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        if handed_on_before:
            rig.stream.push(one_more_share(rig, row))  # delivered and handed on
            await until(lambda: len(client._forwarded) == 1)
            await asyncio.sleep(1.2)  # past the margin, so the first read is not read again
        one_more_share(rig, row)  # lost with the stream; the first read shows it
        rig.venue.positions_delay = first_read_secs  # the first read's positions read
        if backlog:
            backlogged(client, backlog)
        rig.stream.push("reconnect")
        async with asyncio.timeout(15):
            while client.recoveries < 1:  # act in the loop turn the first read is handed over
                await asyncio.sleep(0)
        rig.venue.positions_delay = 0.0
        row.update(status="canceled", canceled_at=row["updated_at"])  # no update for this
        rig.stream.push({"stream": "trade_updates", "data": {"event": "restated", "order": {}}})
        await until(lambda: len(client.failures) == 1)  # the second gap
        await asyncio.sleep(0.5)  # the second read has ended
        box["after_the_second_read"] = (client.recoveries, client.coverage_complete)
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3 + backlog)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), client.recoveries)

    box = drive(rig, script, on_start=on_start)
    filled = str(1 + handed_on_before)
    assert box["error"] is None
    assert box["covered"] == (OrderStatus.CANCELED, [filled], 2)
    assert box["after_the_second_read"] == (1, False)  # not handed over
    assert box["holding"] == [("AAPL.ALPACA", filled)]


# Open-order checks as FAST_OPEN_CHECKS, acting on an order 0.5 s after its latest event (rc9
# otherwise defers an order for 5 s after it, `open_check_threshold_ms`).
PROMPT_OPEN_CHECKS = {**FAST_OPEN_CHECKS, "open_check_threshold_ms": 500}


@pytest.mark.parametrize("then", ["next-share", "cancel"])
def test_a_fill_the_engines_open_order_check_inferred_is_not_counted_again(then):
    """One share of a 2-share order fills, and the engine's routine open-order check reads it
    before the stream delivers it: the engine infers that fill from the order report. The
    stream's execution then sits at the quantity the engine holds, so it is counted as known
    and not handed on. Then the next share fills and is handed on, or the venue cancels the
    rest and that update is handed on with no gap. The engine holds what the venue holds."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        first = one_more_share(rig, row)  # the stream has not delivered it yet
        await until(lambda: status() == OrderStatus.PARTIALLY_FILLED)  # inferred by a check
        box["inferred"] = (engine_holds(client), client.known_executions, len(client._forwarded))
        rig.stream.push(first)
        await until(lambda: client.known_executions + len(client._forwarded) == 1)
        await asyncio.sleep(0.3)  # long enough for a forwarded fill to reach the engine
        box["after_the_stream"] = engine_holds(client)
        if then == "next-share":
            rig.stream.push(one_more_share(rig, row))
            ended = OrderStatus.FILLED
        else:
            row.update(status="canceled", canceled_at=row["updated_at"])
            rig.stream.push(update("canceled", row))
            ended = OrderStatus.CANCELED
        await until(lambda: status() in (ended, OrderStatus.FILLED))  # FILLED: counted twice
        await asyncio.sleep(0.3)  # long enough for a forwarded fill to reach the engine
        box["end"] = (status(), engine_holds(client), [row["filled_qty"]])
        box["complete"] = client.coverage_complete

    box = drive(rig, script, on_start=two_share_order, engine=PROMPT_OPEN_CHECKS)
    client = rig.clients[0]
    ended, filled = {
        "next-share": (OrderStatus.FILLED, "2"),
        "cancel": (OrderStatus.CANCELED, "1"),
    }[then]
    assert box["error"] is None
    assert box["inferred"] == (["1"], 0, 0)  # the check showed the fill, not the stream
    assert box["after_the_stream"] == ["1"]
    assert box["end"] == (ended, [filled], [filled]) and box["complete"]
    assert (client.known_executions, len(client._forwarded)) == (1, int(filled) - 1)
    assert (client.failures, client.withheld_reports, client.recoveries) == ([], 0, 0)
    assert box["holding"] == [("AAPL.ALPACA", filled)]


def test_a_recovery_read_during_which_an_open_order_check_showed_a_fill_is_read_again():
    """A share of a 2-share order fills while the stream is away, and the engine's routine
    open-order check reads it. Before the check's answer is back, the venue cancels the rest
    (no update reaches the client), the stream returns and recovery begins its read. The engine
    infers the fill from the check's answer during that read, so it would skip the order's
    snapshot in it (2.0.0rc9) while the account is called covered. The read is read again,
    and the engine learns that the order ended."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        await asyncio.sleep(0.6)  # the checks act on the order from now on
        rig.venue.open_answer_delay = 0.8
        rig.venue.positions_delay = 1.2  # the recovery's positions read
        one_more_share(rig, row)  # its update is lost with the stream
        listed = len(rig.venue.listings)
        await until(  # a check's listing of every open order has read the partial fill
            lambda: any(
                query["status"] == "open" and "after" not in query
                for query in rig.venue.listings[listed:]
            )
        )
        row.update(status="canceled", canceled_at=row["updated_at"])  # no update for this
        rig.stream.push("reconnect")
        await until(lambda: client.stream_restarts == 1)
        rig.venue.open_answer_delay = 0.0
        await until(lambda: status() == OrderStatus.PARTIALLY_FILLED)  # the check's answer
        read_began = any(query["status"] == "all" for query in rig.venue.listings[listed:])
        box["inferred_during_the_read"] = read_began and client.recoveries == 0
        rig.venue.positions_delay = 0.0
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), client.recoveries)

    box = drive(rig, script, on_start=two_share_order, engine=PROMPT_OPEN_CHECKS)
    assert box["error"] is None
    assert box["inferred_during_the_read"]
    assert box["covered"] == (OrderStatus.CANCELED, ["1"], 1)
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_a_recovery_read_showing_fewer_fills_than_the_engine_has_is_not_handed_over():
    """Both shares of a 2-share order fill and are handed on. The venue then lists the order
    with one share filled (a correction Alpaca does not document, or a listing behind the
    stream), with an update the lane cannot classify. Handed over, that read would make the
    engine void a fill, and the share filling again would then be dropped as known. It is not
    handed over, and new orders are denied. When the venue fills the share again, its
    execution sits at the quantity the engine holds and is not handed on; the next read shows
    what the engine holds and is handed over."""
    rig = Rig()

    def on_start(running, box):
        two_share_order(running, box)
        box["second"] = limit_order(running, 2)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.stream.push(one_more_share(rig, row))
        rig.stream.push(one_more_share(rig, row))
        await until(lambda: status() == OrderStatus.FILLED)
        row.update(status="partially_filled", filled_qty="1")
        rig.venue.positions[:] = [position_row(qty="1")]
        rig.stream.push(update("trade_bust", row))  # not an event the lane classifies
        await until(lambda: client.failures)
        await asyncio.sleep(1.5)  # recovery has read the venue twice
        box["while_lower"] = (engine_holds(client), client.coverage_complete, client.recoveries)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        rig.stream.push(one_more_share(rig, row))  # the venue fills the share again
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), [row["filled_qty"]], client.recoveries)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["while_lower"] == (["2"], False, 0)
    assert box["second_status"] == OrderStatus.DENIED
    assert box["covered"] == (OrderStatus.FILLED, ["2"], ["2"], 1)
    assert rig.clients[0].known_executions == 1
    assert box["holding"] == [("AAPL.ALPACA", "2")]


def test_startup_reads_wait_for_the_venues_subscription_acknowledgement():
    rig = Rig()
    rig.stream.ack = False  # the venue never confirms trade_updates
    node = build_node(rig, strategy(), timeouts={"timeout_reconciliation_secs": 2})
    error = asyncio.run(run(node, 30))
    del node
    assert error is not None
    read = {path for _, path in rig.venue.calls}
    assert not read & {"/orders", "/positions", "/account/activities/FILL"}


def test_two_cancel_commands_for_one_order_send_one_delete():
    """Called at the adapter directly: the engine itself sends only one while pending."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client = rig.clients[0]
        command = SimpleNamespace(
            client_order_id=box["order"].client_order_id, venue_order_id=None, command_id=None
        )
        await client._cancel_order(command)
        await client._cancel_order(command)
        await asyncio.sleep(0.3)

    box = drive(rig, script)
    assert box["error"] is None
    assert [method for method, _ in rig.venue.calls].count("delete") == 1


def test_a_second_cancel_while_the_first_waits_for_the_budget_sends_nothing():
    """Both commands read the order while the budget still has room for two requests. The
    first DELETE then waits in the budget's queue, not yet on the wire, so only the slot taken
    before the budget tells the second command that a cancel is under way. When the budget
    opens again, one DELETE goes out."""
    rig = Rig()

    def waiting_deletes() -> int:
        assert rig.pacer is not None
        return sum(item.kind == ActionKind.CANCEL for item in rig.pacer.queue)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, pacer, row = rig.clients[0], rig.pacer, rig.venue.orders[-1]
        assert pacer is not None
        command = SimpleNamespace(
            client_order_id=box["order"].client_order_id, venue_order_id=None, command_id=None
        )
        pacer.limit = len(pacer.admitted) + 2  # the two reads pass; a DELETE has to wait
        await client._cancel_order(command)
        await client._cancel_order(command)
        await until(lambda: rig.venue.calls.count(("get", f"/orders/{row['id']}")) == 2)
        await until(lambda: waiting_deletes() >= 1)
        await asyncio.sleep(0.3)  # long enough for the second command to queue one as well
        box["waiting"], box["on_the_wire"] = waiting_deletes(), list(client._pending)
        pacer.limit = 180  # the budget opens again
        pacer.drain()
        await until(lambda: "delete" in {method for method, _ in rig.venue.calls})
        await asyncio.sleep(0.3)

    box = drive(rig, script)
    assert box["error"] is None
    assert box["waiting"] == 1 and box["on_the_wire"] == []
    assert [method for method, _ in rig.venue.calls].count("delete") == 1


def test_a_modify_is_denied_and_the_order_stays_working():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        box["strategy"].modify_order(box["order"].client_order_id, quantity=Quantity.from_str("2"))
        await asyncio.sleep(0.3)
        box["after"] = status()

    box = drive(rig, script)
    assert box["after"] == OrderStatus.ACCEPTED
    assert not any(method == "patch" for method, _ in rig.venue.calls)


def test_a_closing_sell_is_paced_as_reduce():
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running, side=OrderSide.SELL)
        running.submit_order(box["order"])

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert rig.pacer is not None and ActionKind.REDUCE in rig.pacer.kinds
    assert ActionKind.SUBMIT not in rig.pacer.kinds


def test_a_single_order_report_reads_the_lanes_order_and_refuses_anything_else():
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, mine = rig.clients[0], rig.venue.orders[-1]
        coid = box["order"].client_order_id

        def query(venue_id=None, client_id=None):
            return client._generate_order_status_report(
                SimpleNamespace(venue_order_id=venue_id, client_order_id=client_id)
            )

        report = await query(VenueOrderId(mine["id"]), coid)
        box["status"] = report.order_status
        foreign = order_row(client_order_id="web-order-2", status="new", filled_qty="0")
        other = order_row(client_order_id=f"{PREFIX}other", status="new", filled_qty="0")
        rig.venue.orders += [foreign, other]
        with pytest.raises(ValueError, match="another writer"):
            await query(None, ClientOrderId("web-order-2"))
        with pytest.raises(ValueError, match="another order"):
            await query(VenueOrderId(other["id"]), coid)
        box["missing"] = await query(None, ClientOrderId(f"{PREFIX}missing"))

    box = drive(rig, script)
    assert box["error"] is None
    assert box["status"] == OrderStatus.ACCEPTED and box["missing"] is None


def test_an_order_query_the_lane_cannot_map_denies_new_orders_until_a_read_settles():
    """The engine queries an order whose venue status the lane has not classified. The read
    fails, and it is a gap as a listing's row would be: new orders are denied until a full read
    succeeds, which it does once the venue shows a status the lane knows."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"], box["third"] = limit_order(running, 2), limit_order(running, 3)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        row["status"] = "pending_review_v2"
        calls = len(rig.venue.calls)
        box["strategy"].query_order(box["order"])
        await until(lambda: ("get", f"/orders/{row['id']}") in rig.venue.calls[calls:])
        await asyncio.sleep(0.2)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        row["status"] = "new"  # a status the lane knows again
        await until(lambda: client.coverage_complete)
        box["strategy"].submit_order(box["third"])
        await until(lambda: status(3) == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["second_status"] == OrderStatus.DENIED
    assert type(rig.clients[0].failures[0][1]).__name__ == "UnmappedOrderStatus"
    assert rig.venue.last_post["client_order_id"] == f"{PREFIX}3"  # the second was never sent


def test_a_windowed_open_order_check_still_reads_older_working_orders():
    rig = Rig()
    old = order_row(client_order_id=f"{PREFIX}old", status="new", filled_qty="0")
    old["submitted_at"] = old["created_at"] = old["updated_at"] = "2026-11-01T14:00:00.000000Z"
    rig.venue.orders.append(old)

    def on_start(running, box):
        pass

    async def script(box, status):
        client = rig.clients[0]
        start = timestamp_ns("2026-11-02T00:00:00.000000Z", "start")  # after the old order
        reports = await client._generate_order_status_reports(
            SimpleNamespace(open_only=True, start=start, end=None, instrument_id=None)
        )
        box["ids"] = [str(report.client_order_id) for report in reports]

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["ids"] == [f"{PREFIX}old"]
    # Startup's two listings, the windowed one and its open-order merge: every listing asks
    # the venue for legs under their parent, which the leg rules in reconcile.py rely on.
    assert len(rig.venue.listings) >= 4
    assert all(query.get("nested") is True for query in rig.venue.listings)


@pytest.mark.parametrize(
    ("event", "row_status"),
    [
        ("pending_replace", "pending_replace"),
        ("replaced", "replaced"),
        ("order_replace_rejected", "new"),
    ],
)
def test_a_replace_event_for_the_lanes_order_is_a_gap(event, row_status):
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        rig.venue.fail("get", "/positions", api_error(503))  # the gap stays open
        row = rig.venue.orders[-1]
        rig.stream.push(update(event, {**row, "status": row_status}))
        await until(lambda: not rig.clients[0].coverage_complete)
        box["second"] = limit_order(box["strategy"], 2)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) == OrderStatus.DENIED)

    box = drive(rig, script)
    assert box["error"] is None


# ---------------------------------------------------------------- venue answers after startup


def answering(venue, path: str, answer):
    """From now on GET `path` answers `answer(query)`, whatever the venue holds. Returns what
    restores the venue's own answer."""
    get = venue.get

    def patched(asked: str, data: dict | None = None, **kwargs):
        if asked != path:
            return get(asked, data, **kwargs)
        venue.calls.append(("get", asked))
        return answer(data or {})

    venue.get = patched
    return lambda: setattr(venue, "get", get)


def reshaped(venue, path: str, change):
    """From now on GET `path` answers `change(answer)`, `answer` being the venue's own; `change`
    runs where the venue does, in the request's worker thread. Returns what restores the venue's
    own answer."""
    get = venue.get

    def patched(asked: str, data: dict | None = None, **kwargs):
        answer = get(asked, data, **kwargs)
        return change(answer) if asked == path else answer

    venue.get = patched
    return lambda: setattr(venue, "get", get)


def not_json(*_):
    """What a 2xx answer whose body is not JSON raises inside alpaca-py's request (it decodes
    there): requests' JSONDecodeError."""
    raise requests.exceptions.JSONDecodeError("Expecting value", "<html>synthetic</html>", 0)


# One full page of the order listing: 500 working rows, all submitted at one instant.
FULL_PAGE = [order_row(status="new", filled_qty="0") for _ in range(500)]
UNREADABLE_LISTINGS = {
    "not-a-list": (lambda query: {"orders": FULL_PAGE}, "Alpaca order page is not a list"),
    "not-json": (not_json, "Alpaca answer is not JSON"),
    "no-progress": (lambda query: list(FULL_PAGE), "order page made no progress"),
    "not-contiguous": (
        lambda query: [] if "until" in query else list(FULL_PAGE),
        "order pages are not contiguous",
    ),
    "over-budget": (
        lambda query: list(FULL_PAGE),
        "order listing needs more pages than its budget",
    ),
}


@pytest.mark.parametrize("shape", list(UNREADABLE_LISTINGS))
def test_an_order_listing_the_lane_cannot_read_after_startup_denies_new_orders(shape):
    """The engine's routine open-order check (every 0.2 s here) meets an order listing whose
    shape or pages the lane cannot read: not a list; a 2xx answer whose body is not JSON; a
    full page, then the same page again; a full page, then one without its edge rows; more pages
    than the read's budget (one page here). After startup that is a gap, as a row the lane
    cannot map is: new orders are denied until a full read succeeds."""
    rig = Rig()
    answer, reason = UNREADABLE_LISTINGS[shape]

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"], box["third"] = limit_order(running, 2), limit_order(running, 3)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, pacer = rig.clients[0], rig.pacer
        assert pacer is not None
        budget = pacer.controls["request_budget"]
        restore = answering(rig.venue, "/orders", answer)
        if shape == "over-budget":
            pacer.controls["request_budget"] = 1
        await until(lambda: not client.coverage_complete, timeout=5.0)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) == OrderStatus.DENIED)
        box["reason"] = str(client.failures[0][1])
        restore()
        pacer.controls["request_budget"] = budget
        await until(lambda: client.coverage_complete)
        box["strategy"].submit_order(box["third"])
        await until(lambda: status(3) == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start, engine=FAST_OPEN_CHECKS)
    assert box["error"] is None
    assert box["reason"] == reason
    assert rig.venue.last_post["client_order_id"] == f"{PREFIX}3"  # the second was never sent


@pytest.mark.parametrize("failure", ["http-503", "budget-refusal"])
def test_an_order_listing_that_gets_no_answer_after_startup_is_not_a_gap(failure):
    """The open-order check's request itself fails: the venue answers 503, or the budget
    refuses the read before the wire. No answer was read, so it is not a gap: the stream still
    carries the account's changes and the next check reads again. New orders pass."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"] = limit_order(running, 2)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, pacer = rig.clients[0], rig.pacer
        assert pacer is not None
        if failure == "http-503":
            rig.venue.fail("get", "/orders", api_error(503))
        else:
            pacer.refuse_kinds.add(ActionKind.QUERY)
        before = client.report_trace["orders"]
        await until(lambda: client.report_trace["orders"] is not before)
        await until(lambda: client.report_trace["orders"].failures == 1)
        # Read at once: each check replaces the trace when it starts.
        box["first"] = client.report_trace["orders"].first
        await asyncio.sleep(0.5)  # a few more failed checks
        box["seen"] = (client.coverage_complete, client.failures, client.recoveries)
        pacer.refuse_kinds.clear()
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start, engine=FAST_OPEN_CHECKS)
    assert box["error"] is None
    assert box["seen"] == (True, [], 0)
    assert box["first"] == ("APIError" if failure == "http-503" else "ValueError")


def report_read(client, row: dict, read: str):
    """A report the engine can ask for after startup, for the lane's order `row`: its open-order
    check's listing, a targeted or strategy query, its position checks (when set), and fills,
    which those checks ask for and so does a targeted query of an ended order with fills the
    engine lacks (in an open-order check over all orders)."""
    scope = SimpleNamespace(
        open_only=read == "open-orders", start=None, end=None, instrument_id=None
    )
    if read == "open-orders":
        return client._generate_order_status_reports(scope)
    if read == "one-order":
        query = SimpleNamespace(venue_order_id=VenueOrderId(row["id"]), client_order_id=None)
        return client._generate_order_status_report(query)
    if read == "positions":
        return client._generate_position_status_reports(scope)
    return client._generate_fill_reports(scope)


def symbol_dropped(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "symbol"}


def ended_without_symbol(row: dict) -> dict:
    """The lane's order, filled, in a row without its symbol: it can only be withheld as history
    outside the universe if the lane takes it for such."""
    return symbol_dropped({**row, "status": "filled", "filled_qty": row["qty"]})


UNREADABLE_ANSWERS = {
    "a row that is not a row": lambda row: lambda query: ["not a row"],
    "a list": lambda row: lambda query: [dict(row)],
    "not a list": lambda row: lambda query: {"rows": []},
    "its ended row without a symbol": lambda row: lambda query: ended_without_symbol(row),
    "a listing of that row": lambda row: lambda query: [ended_without_symbol(row)],
    "a position without a symbol": lambda row: lambda query: [symbol_dropped(position_row())],
    "a body that is not JSON": lambda row: not_json,
    "an unexplained fill": lambda row: (
        lambda query: [fill_activity(order_row(), when="2026-11-02T15:00:00.000000Z")]
    ),
    "an order history without a time": lambda row: lambda query: [{**row, "submitted_at": "?"}],
}


@pytest.mark.parametrize(
    ("read", "path", "answer", "failure"),
    [
        (
            "open-orders",
            "/orders",
            "a row that is not a row",
            "'str' object has no attribute 'get'",
        ),
        ("open-orders", "/orders", "a listing of that row", "Alpaca row requires its symbol"),
        ("one-order", "/orders/{id}", "a list", "'list' object has no attribute 'get'"),
        (
            "one-order",
            "/orders/{id}",
            "its ended row without a symbol",
            "Alpaca row requires its symbol",
        ),
        ("one-order", "/orders/{id}", "a body that is not JSON", "Alpaca answer is not JSON"),
        ("positions", "/positions", "not a list", "Alpaca positions are not a list"),
        ("positions", "/positions", "a body that is not JSON", "Alpaca answer is not JSON"),
        (
            "positions",
            "/positions",
            "a position without a symbol",
            "Alpaca row requires its symbol",
        ),
        (
            "positions",
            "/positions",
            "a row that is not a row",
            "'str' object has no attribute 'get'",
        ),
        ("fills", "/account/activities/FILL", "not a list", "Alpaca fill page is not a list"),
        (
            "fills",
            "/account/activities/FILL",
            "a body that is not JSON",
            "Alpaca answer is not JSON",
        ),
        (
            "fills",
            "/account/activities/FILL",
            "an unexplained fill",
            "historical fill that no order report explains",
        ),
        (
            "fills",
            "/orders",
            "an order history without a time",
            "submitted_at is not a valid timestamp",
        ),
    ],
)
def test_an_answer_the_lane_cannot_read_after_startup_is_a_gap(read, path, answer, failure):
    """Each report the engine can ask for after startup, called directly on an answer the lane
    cannot read or map. Whatever the failure's type (a row that is not a row fails with
    AttributeError; an order history without a time fails outside any listing), it is a gap at
    once: new orders stop before the gap's read, which restores coverage once the venue
    answers again. A row without its symbol is one: it is not known to be outside the universe,
    so it is never withheld as history there. So is a 2xx answer whose body is not JSON: the
    venue answered (a request that gets none is no gap, below)."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        restore = answering(
            rig.venue, path.format(id=row["id"]), UNREADABLE_ANSWERS[answer](dict(row))
        )
        try:
            await report_read(client, row, read)
        except Exception as exc:  # what the engine logs as a failed report
            box["raised"] = type(exc).__name__
        box["gap"] = (not client.coverage_complete, [str(error) for _, error in client.failures])
        restore()
        await until(lambda: client.coverage_complete)
        box["recoveries"] = client.recoveries

    box = drive(rig, script)
    assert box["error"] is None
    assert "raised" in box
    assert box["gap"][0] is True and box["gap"][1][-1:] == [failure]
    assert box["recoveries"] == 1


@pytest.mark.parametrize("read", ["order row", "position row"])
def test_a_gaps_read_meeting_a_row_without_its_symbol_withholds_nothing(read):
    """The lane's order fills at the venue behind an update the lane cannot classify (a gap).
    The gap's read gets the order's row, or the position's, without a symbol. That row is not
    history outside the universe: the read fails, new orders stay denied and nothing is
    withheld. Once the venue answers with the symbol, the read shows the engine the fill and the
    share. (Withheld, the row left the engine without the fill, or let it take the venue for
    flat, while the account was called covered.)"""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"], box["third"] = limit_order(running, 2), limit_order(running, 3)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        if read == "order row":
            mine = row["id"]
            restore = reshaped(
                rig.venue,
                "/orders",
                lambda rows: [symbol_dropped(r) if r["id"] == mine else r for r in rows],
            )
        else:
            restore = reshaped(
                rig.venue, "/positions", lambda rows: list(map(symbol_dropped, rows))
            )
        row.update(status="filled", filled_qty="1", filled_avg_price=row["limit_price"])
        rig.venue.positions.append(position_row())
        rig.stream.push(update("trade_bust", row))  # unclassified: a gap
        await until(
            lambda: (
                client.recoveries > 0
                or any(
                    str(error) == "Alpaca row requires its symbol" for _, error in client.failures
                )
            )
        )
        box["read"] = (client.coverage_complete, sorted(client.withheld_symbols))
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        restore()
        await until(lambda: client.coverage_complete)
        box["strategy"].submit_order(box["third"])
        await until(lambda: status(3) == OrderStatus.ACCEPTED)
        box["first_status"] = status()

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["read"] == (False, [])
    assert box["second_status"] == OrderStatus.DENIED
    assert box["first_status"] == OrderStatus.FILLED
    assert box["holding"] == [("AAPL.ALPACA", "1")]


@pytest.mark.parametrize(
    ("read", "path", "raised"),
    [
        ("one-order", "/orders/{id}", "APIError"),
        ("positions", "/positions", "APIError"),
        ("fills", "/account/activities/FILL", "APIError"),
        ("fills", None, "IncompleteCoverage"),  # the budget refuses its first request
    ],
)
def test_a_report_whose_request_gets_no_answer_after_startup_is_not_a_gap(read, path, raised):
    """The same reads when a request itself fails (a 503, or the budget refusing it before the
    wire): no answer was read, so it is not a gap, as for an order listing."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row, pacer = rig.clients[0], rig.venue.orders[-1], rig.pacer
        assert pacer is not None
        if path is None:
            pacer.refuse_kinds.add(ActionKind.QUERY)
        else:
            rig.venue.fail("get", path.format(id=row["id"]), api_error(503))
        try:
            await report_read(client, row, read)
        except Exception as exc:
            box["raised"] = type(exc).__name__
        box["seen"] = (client.coverage_complete, client.failures, client.recoveries)
        pacer.refuse_kinds.clear()

    box = drive(rig, script)
    assert box["error"] is None
    assert (box["raised"], box["seen"]) == (raised, (True, [], 0))


def answered_with(venue, change) -> None:
    """From now on POST /orders stores the order as before but answers `change(row)`."""
    post = venue.post
    venue.post = lambda path, data=None: change(post(path, data))


SUBMIT_ANSWERS = {
    "a list": lambda row: [row],
    "another order's row": lambda row: row | {"client_order_id": f"{PREFIX}other"},
    "a body that is not JSON": not_json,
}


@pytest.mark.parametrize("answer", list(SUBMIT_ANSWERS))
def test_a_submits_answer_the_lane_cannot_read_is_a_gap(answer):
    """POST /orders stores the order but answers a list, the row of another order, or a 2xx
    body that is not JSON (the venue took the order). Each answer is a gap: the next order is
    denied until a full read, which shows the engine the order as the venue holds it."""
    rig = Rig()
    answered_with(rig.venue, SUBMIT_ANSWERS[answer])

    def on_start(running, box):
        box["order"], box["second"] = limit_order(running), limit_order(running, 2)

    async def script(box, status):
        client = rig.clients[0]
        rig.venue.fail("get", "/positions", api_error(503))  # the gap's read waits
        box["strategy"].submit_order(box["order"])
        await until(lambda: not client.coverage_complete, timeout=5.0)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) == OrderStatus.DENIED)
        rig.venue.failures.clear()
        await until(lambda: status() == OrderStatus.ACCEPTED)  # shown by the gap's read

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert rig.venue.last_post["client_order_id"] == f"{PREFIX}1"  # the second was never sent


@pytest.mark.parametrize(
    ("answer", "deletes"),
    [
        ("another order's row", 0),
        ("a row without a venue id", 0),
        ("a body that is not JSON", 0),
        ("an ended row it cannot map", 0),
        ("a working row in an unclassified status", 1),
    ],
)
def test_a_cancels_read_the_lane_cannot_read_is_a_gap(answer, deletes):
    """The cancel's read of the lane's order answers what the lane cannot read or map: another
    order's row, a row without a venue id, or a 2xx body that is not JSON (the cancel is refused
    unsent); an ended row it cannot map (nothing to delete); a working row in a status it has
    not classified (the DELETE still goes to the lane's own order). Each is a gap."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.venue.fail("get", "/positions", api_error(503))  # the gap's read waits
        if answer == "another order's row":
            row["client_order_id"] = f"{PREFIX}another"
        elif answer == "a row without a venue id":
            answering(rig.venue, f"/orders/{row['id']}", lambda query: {**row, "id": None})
        elif answer == "a body that is not JSON":
            answering(rig.venue, f"/orders/{row['id']}", not_json)
        elif answer == "an ended row it cannot map":
            row.update(status="canceled", qty="many")
        else:
            row["status"] = "pending_review_v2"
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: not client.coverage_complete, timeout=5.0)
        await asyncio.sleep(0.3)  # long enough for a DELETE to go out, if one were sent
        box["deletes"] = [method for method, _ in rig.venue.calls].count("delete")

    box = drive(rig, script)
    assert box["error"] is None
    assert box["deletes"] == deletes


@pytest.mark.parametrize("read", ["query", "second cancel"])
def test_a_row_the_lane_cannot_map_settles_no_earlier_cancel(read):
    """A cancel's DELETE got no answer (500), so it waits for a read issued after its call
    ended. That read, an order query or a second cancel's, finds the order in a status the
    lane has not classified. Such a row settles nothing: the engine is told of no refusal, the
    cancel stays unresolved and no second DELETE goes out; the read is a gap. Once the venue
    shows a status the lane knows, the gap's read settles the cancel."""
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        target = f"/orders/{row['id']}"
        rig.venue.fail("delete", target, api_error(500))
        hold_the_gaps_read(rig)
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: row["id"] in client._pending and client._pending[row["id"]].ended > 0)
        row["status"] = "pending_review_v2"
        reads = rig.venue.calls.count(("get", target))
        if read == "query":
            box["strategy"].query_order(box["order"])
        else:
            await client._cancel_order(
                SimpleNamespace(
                    client_order_id=box["order"].client_order_id,
                    venue_order_id=None,
                    command_id=None,
                )
            )
        await until(lambda: rig.venue.calls.count(("get", target)) > reads)
        await asyncio.sleep(0.3)  # long enough for a refusal or a DELETE, if either came
        pending = row["id"] in client._pending
        box["unsettled"] = (cancel_refusals(box), pending, client.coverage_complete)
        row["status"] = "new"  # a status the lane knows: the gap's read settles the cancel
        del rig.venue.failures[("get", "/orders")]
        await until(lambda: bool(cancel_refusals(box)))
        box["settled"] = cancel_refusals(box)

    box = drive(rig, script)
    assert box["error"] is None
    assert box["unsettled"] == ([], True, False)
    assert [method for method, _ in rig.venue.calls].count("delete") == 1
    assert box["settled"] == [
        ("OrderCancelRejected", "venue order still working after an unanswered cancel")
    ]


# ---------------------------------------------------------------- the eighth round's sequences


def answer_lost(venue, method: str, act) -> None:
    """From now on the venue carries out each `method` request, then `act(row)` changes the
    order's row as the venue would, and the answer is lost (a timeout): the outcome is unknown
    to the lane. No trade update follows."""
    perform = getattr(venue, method)

    def lost(path: str, data: dict | None = None, **kwargs):
        perform(path, data, **kwargs)
        target = path.removeprefix("/orders/") if method == "delete" else None
        for row in venue.orders:
            if target is None and row is venue.orders[-1] or row["id"] == target:
                act(row)
        raise TimeoutError("synthetic: the answer was lost")

    setattr(venue, method, lost)


def test_a_cancel_whose_answer_was_lost_is_read_back_under_the_default_settings():
    """The DELETE's answer is lost and the venue cancels the order; no update follows. Under
    `engine_config`'s default settings the engine's open-order checks list open orders only, and
    rc9 only logs an order it holds that is missing there, so no check settles this cancel (the
    engine held it PENDING_CANCEL with coverage declared). An unknown outcome after send is a
    gap: its full read shows the engine the order cancelled, and new orders pass again."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"] = limit_order(running, 2)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client = rig.clients[0]
        answer_lost(rig.venue, "delete", lambda row: row.update(status="canceled"))
        box["strategy"].cancel_order(box["order"].client_order_id)
        await until(lambda: ("delete", f"/orders/{rig.venue.orders[-1]['id']}") in rig.venue.calls)
        await until(lambda: status() == OrderStatus.CANCELED, timeout=8)
        await until(lambda: client.coverage_complete)
        box["pending"] = list(client._pending)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["pending"] == []
    client = rig.clients[0]
    assert client.recoveries == 1  # the unknown outcome was a gap, closed by one full read
    assert [str(error) for _, error in client.failures] == [
        "cancel outcome unknown after send: TimeoutError"
    ]


def test_a_submission_whose_answer_was_lost_is_read_back_under_the_default_settings():
    """The POST's answer is lost and the order fills at once; no update follows in time. Under
    the default settings no check reads an order that has left the open listing. The unknown
    outcome is a gap: its read shows the engine the fill. The stream's late fill update is then
    known, not counted again."""
    rig = Rig()

    def filled(row):
        row.update(status="filled", filled_qty="1", filled_avg_price="100.00")
        rig.venue.positions.append(position_row())

    def on_start(running, box):
        answer_lost(rig.venue, "post", filled)
        box["order"] = limit_order(running)
        running.submit_order(box["order"])

    async def script(box, status):
        client = rig.clients[0]
        await until(lambda: ("post", "/orders") in rig.venue.calls)
        await until(lambda: status() == OrderStatus.FILLED, timeout=8)
        await until(lambda: client.coverage_complete)
        rig.stream.push(update("fill", rig.venue.orders[-1]))
        await until(lambda: client.known_executions == 1)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    client = rig.clients[0]
    assert client.recoveries == 1
    assert [str(error) for _, error in client.failures] == [
        "submit outcome unknown after send: TimeoutError"
    ]
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_an_order_in_an_instrument_outside_the_universe_is_denied_unsent():
    """Another instrument of the venue is loaded in the node (as a data client would load it),
    and the engine routes an order in it to this AAPL-only client. It is denied before
    OrderSubmitted and before any request: posted, it would be an order whose reports and
    executions the client then refuses."""
    rig = Rig()
    msft = InstrumentId.from_str("MSFT.ALPACA")

    def on_start(running, box):
        box["order"] = None

    async def script(box, status):
        client = rig.clients[0]
        client._handle_instrument(
            parse_equity(
                {"id": "x", "class": "us_equity", "symbol": "MSFT", "tradable": True},
                ts_init=0,
            )
        )
        await until(lambda: client.cache.instrument(msft) is not None)
        order = box["strategy"].order_factory.limit(
            msft,
            OrderSide.BUY,
            Quantity.from_str("1"),
            Price.from_str("100.00"),
            time_in_force=TimeInForce.DAY,
            client_order_id=ClientOrderId(f"{PREFIX}1"),
        )
        box["strategy"].submit_order(order)
        await until(
            lambda: status() not in (None, OrderStatus.INITIALIZED, OrderStatus.SUBMITTED), 5
        )
        await asyncio.sleep(0.3)  # long enough for a POST to go out, if one were sent
        box["status"] = status()
        box["covered"] = client.coverage_complete

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["status"] == OrderStatus.DENIED
    assert ("post", "/orders") not in rig.venue.calls
    assert box["covered"] is True  # a refusal before send is no gap


@pytest.mark.parametrize(
    ("read", "symbol"),
    [
        ("order row", "aapl"),
        ("order row", " AAPL"),
        ("order row", "AAPL "),
        ("order row", "MSFT"),  # the engine's order is in AAPL
        ("position row", "aapl"),
        ("position row", "AAPL\n"),
    ],
)
def test_a_gaps_read_meeting_a_row_in_another_symbol_form_withholds_nothing(read, symbol):
    """As for a row without its symbol: the lane's order fills behind a gap, and the gap's read
    gets its row, or the position's, with a symbol that differs from the universe's only in
    case or surrounding space, or (the order's row) another instrument than the engine's order.
    Neither is history outside the universe: the read fails, new orders stay denied and nothing
    is withheld, until the venue answers in its own form."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"], box["third"] = limit_order(running, 2), limit_order(running, 3)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        if read == "order row":
            mine = row["id"]
            restore = reshaped(
                rig.venue,
                "/orders",
                lambda rows: [{**r, "symbol": symbol} if r["id"] == mine else r for r in rows],
            )
        else:
            restore = reshaped(
                rig.venue, "/positions", lambda rows: [{**r, "symbol": symbol} for r in rows]
            )
        row.update(status="filled", filled_qty="1", filled_avg_price=row["limit_price"])
        rig.venue.positions.append(position_row())
        failures = len(client.failures)
        rig.stream.push(update("trade_bust", row))  # unclassified: a gap
        await until(lambda: client.recoveries > 0 or len(client.failures) > failures + 1)
        box["read"] = (client.coverage_complete, sorted(client.withheld_symbols))
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        restore()
        await until(lambda: client.coverage_complete)
        box["strategy"].submit_order(box["third"])
        await until(lambda: status(3) == OrderStatus.ACCEPTED)
        box["first_status"] = status()

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["read"] == (False, [])
    assert box["second_status"] == OrderStatus.DENIED
    assert box["first_status"] == OrderStatus.FILLED
    assert box["holding"] == [("AAPL.ALPACA", "1")]


@pytest.mark.parametrize(
    "frame", ['{"stream": "trade_updates", "data": ', "[]", '"trade_updates"', "null"]
)
def test_a_stream_frame_the_sdk_cannot_decode_is_a_gap(frame):
    """In alpaca-py 0.45.0 the receive loop decodes each frame before dispatching it
    (`TradingStream._consume`), and its run loop logs what that raises and carries on with the
    socket open (`_drive_run`). A frame that is not JSON, or not an object, never reaches the
    lane's handler, so the update it carried is lost without a socket loss. It is a gap: new
    orders are denied until a full read, and the read shows the engine what the frame held."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"] = limit_order(running, 2)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.venue.fail("get", "/positions", api_error(503))  # hold the gap's read back
        row.update(status="filled", filled_qty="1", filled_avg_price=row["limit_price"])
        rig.venue.positions.append(position_row())
        rig.stream.push(Frame(frame))  # the fill's update, as the SDK cannot decode it
        await until(lambda: rig.stream.queue is not None and rig.stream.queue.empty())
        await asyncio.sleep(0.3)  # long enough for the receive loop to have handled it
        box["after_frame"] = (client.coverage_complete, client.stream_live, rig.stream.closed)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        rig.venue.failures.clear()
        await until(lambda: client.coverage_complete)
        box["first_status"] = status()

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["after_frame"] == (False, True, 0)  # the socket stays open, as in the SDK
    assert box["second_status"] == OrderStatus.DENIED
    assert box["first_status"] == OrderStatus.FILLED
    assert box["holding"] == [("AAPL.ALPACA", "1")]


@pytest.mark.parametrize("change", ["fill", "cancel", "partial"])
def test_recovery_does_not_admit_an_order_before_the_engine_applies_the_read(change):
    """Hold the mass report at the client output boundary, without a timing assumption.
    The read discovers a fill; another order must stay denied until that fill is applied.
    """
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running, qty="3" if change == "partial" else "1")
        running.submit_order(box["order"])
        box["second"], box["third"] = limit_order(running, 2), limit_order(running, 3)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        if change == "partial":
            rig.stream.push(one_more_share(rig, row))
            await until(lambda: status() == OrderStatus.PARTIALLY_FILLED)
        hand, pending, queued = client._handle_report, [], asyncio.Event()

        def hold(report, fills=None):
            if isinstance(report, ExecutionMassStatus):
                pending.append(report)
                queued.set()
            else:
                hand(report, fills)

        client._handle_report = hold
        if change == "cancel":
            row["status"] = "canceled"
        else:
            one_more_share(rig, row)  # the read discovers this execution, not the stream
        rig.stream.push(Frame("[]"))
        try:
            await queued.wait()
            box["held"] = (client.coverage_complete, status(), engine_holds(client))
            box["strategy"].submit_order(box["second"])
            await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
            box["second_status"] = status(2)
        finally:
            client._handle_report = hand
            for report in pending:
                hand(report)
        await until(lambda: client.coverage_complete)
        box["applied"] = (status(), engine_holds(client))
        box["strategy"].submit_order(box["third"])
        await until(lambda: status(3) == OrderStatus.ACCEPTED)

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    previous = OrderStatus.PARTIALLY_FILLED if change == "partial" else OrderStatus.ACCEPTED
    assert box["held"] == (False, previous, ["1"] if change == "partial" else [])
    assert box["second_status"] == OrderStatus.DENIED
    assert (
        box["applied"]
        == {
            "fill": (OrderStatus.FILLED, ["1"]),
            "cancel": (OrderStatus.CANCELED, []),
            "partial": (OrderStatus.PARTIALLY_FILLED, ["2"]),
        }[change]
    )


class PositionView:
    """A cache view whose positions can be held behind its already-current orders."""

    def __init__(self, cache, signed_qty):
        self.cache = cache
        self.signed_qty = Decimal(signed_qty)

    def __getattr__(self, name):
        return getattr(self.cache, name)

    def positions_open(self, **kwargs):
        return [SimpleNamespace(instrument_id=AAPL, signed_qty=self.signed_qty)]


@pytest.mark.parametrize("quantity", ["0", "1", "-1"])
def test_recovery_waits_for_net_positions_including_flat_and_accepts_equal_reads(quantity):
    """Even with every order current, a wrong net position holds admission closed. Once
    equal, an unchanged read (empty when flat) needs no engine mutation and can complete.
    """
    rig = Rig()
    if quantity != "0":
        earlier = order_row(side="sell" if quantity == "-1" else "buy")
        rig.venue.orders.append(earlier)
        rig.venue.fills.append(fill_activity(earlier))
        rig.venue.positions.append(
            {**position_row(qty=quantity), "side": "short" if quantity == "-1" else "long"}
        )

    async def script(box, status):
        client = rig.clients[0]
        cache, hand, queued, pending = client.cache, client._handle_report, asyncio.Event(), []

        def hold(report, fills=None):
            pending.append(report)
            queued.set()

        client.cache = PositionView(cache, "-1" if quantity == "1" else "1")
        client._handle_report = hold
        try:
            rig.stream.push(Frame("[]"))
            await queued.wait()
            box["held"] = (client.coverage_complete, client._submit_admitted())
            client.cache = cache
            # The actual cache already equals this read, which we have not released.
            await until(lambda: client.coverage_complete)
            box["equal"] = (client._submit_admitted(), client.recoveries)
        finally:
            client.cache, client._handle_report = cache, hand
            for report in pending:
                hand(report)

    box = drive(rig, script, on_start=lambda running, box: None)
    assert box["error"] is None
    assert box["held"] == (False, False)
    assert box["equal"] == (True, 1)


def test_startup_coverage_waits_for_the_engine_to_apply_the_read(monkeypatch):
    rig, before = Rig(), []
    earlier = order_row()
    rig.venue.orders.append(earlier)
    rig.venue.fills.append(fill_activity(earlier))
    rig.venue.positions.append(position_row())
    stage_done = AlpacaPaperExecutionClient._startup_stage_done

    def observe(client, *args):
        stage_done(client, *args)
        if client._started:
            before.append((client.coverage_complete, engine_holds(client)))

    monkeypatch.setattr(AlpacaPaperExecutionClient, "_startup_stage_done", observe)
    error, seen = start(rig)
    assert error is None
    assert before == [(False, [])]
    assert seen["coverage_complete"]
    assert seen["holding"] == [("AAPL.ALPACA", "1")]


def test_a_filtered_unclaimed_report_never_opens_coverage_and_times_out(monkeypatch):
    """rc9 filters an external order without an instrument claim. Its absence is not proof
    of application: bounded failure and fresh reads replace a silent, indefinite wait.
    """
    rig = Rig()
    earlier = order_row(status="canceled", filled_qty="0")
    rig.venue.orders.append(earlier)
    original = strategy
    monkeypatch.setitem(globals(), "strategy", lambda **kw: original(claim=False, **kw))

    def on_start(running, box):
        box["order"] = limit_order(running)
        box["at_start"] = rig.clients[0].coverage_complete
        running.submit_order(box["order"])

    async def script(box, status):
        client = rig.clients[0]
        await until(lambda: status() in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["status"] = status()
        assert box["status"] == OrderStatus.DENIED
        await until(
            lambda: any(
                str(exc) == "Alpaca recovery read did not converge in the engine cache"
                for _, exc in client.failures
            )
        )
        await until(lambda: rig.venue.calls.count(("get", "/positions")) > 1)
        box["after_timeout"] = (
            client.coverage_complete,
            client.recoveries,
            client.cache.order(ClientOrderId(earlier["client_order_id"])),
        )

    # Synthetic short deadline: exercises the configured bound, not a timing cure.
    box = drive(rig, script, on_start=on_start, request_timeout_secs=0.1)
    assert box["error"] is None
    assert box["at_start"] is False
    assert box["after_timeout"] == (False, 0, None)
    assert ("post", "/orders") not in rig.venue.calls


def test_a_stream_fill_between_handover_and_convergence_requires_a_fresh_read():
    """Queue the read's first share followed by the stream's second share, in output order.
    The duplicate first share stays known; the newer cache cannot acknowledge the old read.
    """
    rig = Rig()

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        first = one_more_share(rig, row)
        hand, cache, queued, pending = (client._handle_report, client.cache, asyncio.Event(), [])

        def hold(report, fills=None):
            pending.append((report, fills))
            if isinstance(report, ExecutionMassStatus):
                queued.set()

        client._handle_report = hold
        try:
            rig.stream.push(Frame("[]"))
            await queued.wait()
            assert not client.coverage_complete
            rig.stream.push(first)
            rig.stream.push(one_more_share(rig, row))
            await until(lambda: len(pending) == 2 and client.known_executions == 1)
            # Prevent an observation between the two applications from completing the read.
            client.cache = PositionView(cache, "0")
            for report, fills in pending:
                hand(report, fills)
            await until(lambda: status() == OrderStatus.FILLED)
            client.cache = cache
            assert not client.coverage_complete
        finally:
            client.cache, client._handle_report = cache, hand
        await until(lambda: client.coverage_complete)
        box["fills"] = fills_of(client)
        box["failures"] = [str(exc) for _, exc in client.failures]
        box["counts"] = (client.known_executions, len(client._forwarded), client.recoveries)

    box = drive(rig, script, on_start=two_share_order, request_timeout_secs=0.1)
    assert box["error"] is None
    assert box["fills"] == ("2", 2)
    assert box["counts"] == (1, 1, 1)
    assert "Alpaca recovery read did not converge in the engine cache" in box["failures"]
    assert box["holding"] == [("AAPL.ALPACA", "2")]


def fills_of(client, number: int = 1) -> tuple[str, int]:
    """The engine's filled quantity of the lane's order and how many fills it counted."""
    order = client.cache.order(ClientOrderId(f"{PREFIX}{number}"))
    return str(order.filled_qty), len(order.trade_ids)


@pytest.mark.parametrize("stream", [None, "trade_update"], ids=["no-stream", "other-stream"])
def test_a_decoded_frame_that_is_not_a_trade_update_is_a_gap(stream):
    """alpaca-py 0.45.0's dispatcher (`TradingStream._dispatch`) acts only on stream
    "trade_updates", and the authorisation answer never reaches it (`_auth` reads that). A
    fill's update that decodes to an object without that stream (its key missing, or another
    name) would be dropped there with the fill. It is a gap: new orders are denied until a
    full read, and the read shows the engine the fill, counted once."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"] = limit_order(running, 2)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.venue.fail("get", "/positions", api_error(503))  # hold the gap's read back
        row.update(status="filled", filled_qty="1", filled_avg_price=row["limit_price"])
        rig.venue.positions.append(position_row())
        message = update("fill", row)
        if stream is None:
            del message["stream"]
        else:
            message["stream"] = stream
        rig.stream.push(Frame(json.dumps(message)))  # the fill's update, as no handler sees it
        await until(lambda: rig.stream.queue is not None and rig.stream.queue.empty())
        await asyncio.sleep(0.3)  # long enough for the receive loop to have handled it
        box["after_frame"] = (client.coverage_complete, client.stream_live, rig.stream.closed)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        rig.venue.failures.clear()
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for a second count to reach the engine
        box["first_status"], box["fills"] = status(), fills_of(client)
        box["failures"] = {str(error) for _, error in client.failures}

    box = drive(rig, script, on_start=on_start)
    assert box["error"] is None
    assert box["after_frame"] == (False, True, 0)
    assert box["second_status"] == OrderStatus.DENIED
    assert box["first_status"] == OrderStatus.FILLED
    assert box["fills"] == ("1", 1)
    assert NOT_A_TRADE_UPDATE in box["failures"]
    assert box["holding"] == [("AAPL.ALPACA", "1")]


def test_a_stream_update_for_the_lanes_order_in_another_loaded_instrument_is_a_gap():
    """Both AAPL and MSFT are in the universe. The stream reports the lane's AAPL order filled
    with the symbol MSFT: it is the lane's order and its symbol is loaded, but the engine's
    order is in AAPL. Handed on, it would be a fill in the wrong instrument. It is a gap: new
    orders are denied until a full read, which shows the engine the fill in AAPL, once."""
    rig = Rig()

    def on_start(running, box):
        box["order"] = limit_order(running)
        running.submit_order(box["order"])
        box["second"] = limit_order(running, 2)

    async def script(box, status):
        await until(lambda: status() == OrderStatus.ACCEPTED)
        client, row = rig.clients[0], rig.venue.orders[-1]
        rig.venue.fail("get", "/positions", api_error(503))  # hold the gap's read back
        row.update(status="filled", filled_qty="1", filled_avg_price=row["limit_price"])
        rig.venue.positions.append(position_row())
        rig.stream.push(update("fill", {**row, "symbol": "MSFT"}))
        await until(lambda: not client.coverage_complete)
        box["strategy"].submit_order(box["second"])
        await until(lambda: status(2) in (OrderStatus.DENIED, OrderStatus.ACCEPTED))
        box["second_status"] = status(2)
        rig.venue.failures.clear()
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for a second count to reach the engine
        box["first_status"], box["fills"] = status(), fills_of(client)
        box["failures"] = {str(error) for _, error in client.failures}

    box = drive(rig, script, on_start=on_start, universe=["AAPL.ALPACA", "MSFT.ALPACA"])
    assert box["error"] is None
    assert box["second_status"] == OrderStatus.DENIED
    assert box["first_status"] == OrderStatus.FILLED
    assert box["fills"] == ("1", 1)
    assert OTHER_INSTRUMENT in box["failures"]
    assert box["holding"] == [("AAPL.ALPACA", "1")]
