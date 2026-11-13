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
from types import SimpleNamespace

import pytest
from alpaca_fakes import (
    AAPL,
    PREFIX,
    FakeVenue,
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
    InstrumentId,
    OrderSide,
    OrderStatus,
    Price,
    Quantity,
    TimeInForce,
    VenueOrderId,
)

from meridian.alpaca.budget import ActionKind
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


def drive(rig: Rig, script, *, on_start=None, engine: dict | None = None):
    """Run a node whose strategy submits on start; `script` drives the stream meanwhile."""
    box: dict = {}

    def submit(running):
        box["strategy"] = running
        if on_start is not None:
            on_start(running, box)
        else:
            box["order"] = limit_order(running)
            running.submit_order(box["order"])

    node = build_node(rig, strategy(on_start=submit), engine=engine)
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


def test_a_recovery_read_is_read_again_when_an_execution_reached_the_engine_during_it():
    """The stream delivers an execution while the recovery read is under way, and the venue
    then cancels the rest of the order; that update never reaches the client and opens no
    gap. The read's listing shows the quantity the engine has and an ended order. The engine
    skips an order's snapshot when a fill for it arrived during the read (2.0.0rc9), so
    handing this read over would call the account covered while the engine still holds the
    order as working. It is read again, and the engine learns that the order ended."""
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
        rig.stream.push(execution)
        await asyncio.sleep(0.5)  # the read has ended
        box["after_the_read"] = (status(), client.recoveries, client.coverage_complete)
        await until(lambda: client.coverage_complete)
        await asyncio.sleep(0.3)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), client.recoveries)

    box = drive(rig, script, on_start=two_share_order)
    assert box["error"] is None
    assert box["after_the_read"] == (OrderStatus.PARTIALLY_FILLED, 0, False)  # not handed over
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


@pytest.mark.parametrize(
    ("handed_on_before", "first_read_secs"),
    [(0, 0.0), (1, 0.0), (0, 1.5)],
    ids=["nothing-handed-on-before", "one-share-handed-on-before", "slow-first-read"],
)
def test_a_read_begun_just_after_a_recovery_read_showed_a_fill_is_read_again(
    handed_on_before, first_read_secs
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
    to be the moment the read is handed over, not the moment it began."""
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
        await asyncio.sleep(0.3)  # long enough for the engine to reconcile the read
        box["covered"] = (status(), engine_holds(client), client.recoveries)

    box = drive(rig, script, on_start=on_start)
    filled = str(1 + handed_on_before)
    assert box["error"] is None
    assert box["covered"] == (OrderStatus.CANCELED, [filled], 2)
    assert box["after_the_second_read"] == (1, False)  # not handed over
    assert box["holding"] == [("AAPL.ALPACA", filled)]


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
