"""
The engine side builds against the installed engine without connecting to anything.

This catches a mismatch between the lane and the pinned engine's API before an attended
run. It does not show that an order works: only a run against the paper Gateway does.
The engine supports one node per process, so exactly one test here builds a real node.
"""

import inspect
import json
import os
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from meridian import boundary, ibkr_paper

FAKE = "DUFAKE0001"


@pytest.fixture
def clean_environ():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def lane_settings() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(("IB_V2_", "IB_PYO3_"))}


def test_the_order_node_builds_offline_with_the_lanes_settings(clean_environ):
    os.environ["IB_V2_BYPASS_RISK"] = "1"  # must not survive into the run
    os.environ["IB_V2_ORDER_INSTRUMENT_ID"] = "ESZ26.XCME"  # nor this
    os.environ["IB_V2_CLOSE_ON_STOP"] = "1"  # nor this

    from meridian import ibkr_node

    record = ibkr_paper.RunRecord("order", 4002)
    node = ibkr_node.build("order", "127.0.0.1", 4002, "DUFAKE0001", record)

    assert node is not None
    assert record.data["engine"]["nautilus_trader"] == "2.0.0rc9"
    # Only the lane's own settings reach upstream's helpers.
    assert lane_settings() == {
        "IB_V2_RECONCILIATION": "1",
        "IB_V2_CLOSE_ON_STOP": "0",
        "IB_V2_ENABLE_ORDER_SUBMISSION": "1",
    }
    # The order's time in force comes from upstream's helper default.
    default_tif = inspect.signature(ibkr_node.OneDayLimit.limit_order).parameters["time_in_force"]
    assert default_tif.default.name == "DAY"


class RecordingBuilder:
    """Stands in for the engine's node builder and records how upstream's helper drives it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.strategies: list = []

    def __getattr__(self, name: str):
        def method(*args, **kwargs):
            self.calls.append((name, args))
            if name == "build":
                return SimpleNamespace(add_strategy=self.strategies.append)
            return self

        return method

    def named(self, name: str) -> list[tuple]:
        return [args for called, args in self.calls if called == name]


LANE_SETTINGS = {
    "order": {
        "IB_V2_RECONCILIATION": "1",
        "IB_V2_CLOSE_ON_STOP": "0",
        "IB_V2_ENABLE_ORDER_SUBMISSION": "1",
    },
    "fill": {
        "IB_V2_RECONCILIATION": "1",
        "IB_V2_CLOSE_ON_STOP": "0",
        "IB_V2_ENABLE_ORDER_SUBMISSION": "1",
        "IB_V2_CANCEL_ON_ACCEPT": "0",
    },
    "restart": {"IB_V2_RECONCILIATION": "1", "IB_V2_CLOSE_ON_STOP": "0"},
}


@pytest.mark.parametrize("mode", ["order", "fill", "restart"])
def test_upstreams_helper_is_driven_as_the_lane_intends(clean_environ, monkeypatch, mode):
    os.environ["IB_V2_BYPASS_RISK"] = "1"
    os.environ["IB_V2_ORDER_INSTRUMENT_ID"] = "ESZ26.XCME"
    os.environ["IB_V2_RECONCILIATION"] = "0"
    # Each would change what a run does: the stop-time cancel, the wait for a quote.
    os.environ["IB_V2_CANCEL_ON_STOP"] = "0"
    os.environ["IB_V2_WAIT_FOR_QUOTE"] = "0"

    from meridian import ibkr_node

    upstream_common = sys.modules["_common"]  # upstream's helper module, loaded by ibkr_node
    builder = RecordingBuilder()
    monkeypatch.setattr(upstream_common, "LiveNode", SimpleNamespace(builder=lambda *a: builder))

    record = ibkr_paper.RunRecord(mode, 4002)
    ibkr_node.build(mode, "127.0.0.1", 4002, "DUFAKE0001", record)

    # Reconciliation is on and the risk engine is not bypassed, whatever the shell held.
    assert builder.named("with_reconciliation") == [(True,)]
    assert builder.named("with_risk_engine_config") == []
    # One data client and one execution client, on the gated endpoint and account.
    ((_, _, data_config),) = builder.named("add_data_client")
    ((_, _, exec_config),) = builder.named("add_exec_client")
    assert (data_config.host, data_config.port, data_config.client_id) == ("127.0.0.1", 4002, 1511)
    assert (exec_config.host, exec_config.port, exec_config.client_id) == ("127.0.0.1", 4002, 1512)
    assert exec_config.account_id == "DUFAKE0001"
    # One strategy, on the lane's instrument and not the one the shell asked for.
    (strategy,) = builder.strategies
    assert str(strategy.instrument_id) == "AAPL.XNAS"
    # Exactly the lane's settings for this mode reach upstream's helpers, nothing from the shell.
    # (Fill mode turns cancel-on-accept off; the stop-time cancel stays on in every mode.)
    assert lane_settings() == LANE_SETTINGS[mode]
    expected = ibkr_node.OneRoundTrip if mode == "fill" else ibkr_node.OneDayLimit
    assert type(strategy) is expected
    # (The engine sets the strategy id at registration; the class names the one it will get.)
    assert expected.strategy_id_value == ("MERIDIAN-M1-FILL" if mode == "fill" else "MERIDIAN-M1")


@pytest.mark.parametrize(
    ("side", "bid", "ask", "expected"),
    [
        ("BUY", 199.0, 200.0, 204.0),
        ("SELL", 199.0, 200.0, 195.02),
        ("SELL", 201.0, 200.0, 196.98),  # a SELL needs only the bid, even on a crossed quote
        ("SELL", 199.0, 0.0, 195.02),
    ],
)
def test_fill_mode_prices_its_orders_past_the_quote(side, bid, ask, expected):
    from meridian import ibkr_node

    assert ibkr_node.marketable_limit(side, bid, ask) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("side", "bid", "ask"),
    [
        ("BUY", 0.0, 200.0),
        ("BUY", 199.0, 0.0),
        ("BUY", 201.0, 200.0),  # crossed: no BUY from it
        ("SELL", 0.0, 200.0),
        ("HOLD", 199.0, 200.0),
    ],
)
def test_fill_mode_refuses_to_price_from_a_bad_quote(side, bid, ask):
    from meridian import ibkr_node

    with pytest.raises(ValueError):
        ibkr_node.marketable_limit(side, bid, ask)


def test_client_order_ids_compare_by_value():
    # on_order_filled matches the fill to the BUY by this comparison.
    from nautilus_trader.model import ClientOrderId

    assert ClientOrderId.from_str("IBV2-1-BUY") == ClientOrderId.from_str("IBV2-1-BUY")
    assert ClientOrderId.from_str("IBV2-1-BUY") != ClientOrderId.from_str("IBV2-1-SELL")


class FakePrice:
    def __init__(self, value: float) -> None:
        self.value = value

    def is_positive(self) -> bool:
        return self.value > 0

    def as_double(self) -> float:
        return self.value


def offline_strategy(monkeypatch, mode: str) -> SimpleNamespace:
    """The lane's strategy for ``mode`` outside any node. Orders are caught at the engine's own
    ``submit_order``, below the lane's ``submit_ib_order``, so its refusal is what is tested."""
    from meridian import ibkr_node

    record = ibkr_paper.RunRecord(mode, 4002)
    cls = ibkr_node.OneRoundTrip if mode == "fill" else ibkr_node.OneDayLimit
    strategy = cls.create(record)
    strategy.instrument = SimpleNamespace(make_price=lambda value: round(value, 2))
    sent: list = []

    def limit_order(self, client_order_id, side, quantity, price, *rest, **kwargs):
        return SimpleNamespace(
            client_order_id=client_order_id,
            instrument_id=self.instrument_id,
            side=side,
            order_type=SimpleNamespace(name="LIMIT"),
            time_in_force=SimpleNamespace(name="DAY"),
            quantity=quantity,
            price=price,
        )

    monkeypatch.setattr(cls, "limit_order", limit_order)
    monkeypatch.setattr(cls, "submit_order", lambda self, order, client_id=None: sent.append(order))

    def quote(bid: float, ask: float):
        strategy.on_quote(
            SimpleNamespace(
                instrument_id=strategy.instrument_id,
                bid_price=FakePrice(bid),
                ask_price=FakePrice(ask),
            )
        )

    return SimpleNamespace(strategy=strategy, record=record, sent=sent, quote=quote)


def test_restart_mode_sends_nothing_even_when_a_quote_arrives(clean_environ, monkeypatch):
    lane = offline_strategy(monkeypatch, "restart")
    lane.quote(199.0, 200.0)  # restart mode never subscribes; this stands in for one that did
    assert lane.sent == []
    assert lane.record.data["orders_refused"] == 0  # the quote was ignored, not refused
    lane.strategy._bid = FakePrice(199.0)
    lane.strategy.submit_example_orders()  # even a direct call reaches no venue
    assert lane.sent == []
    assert lane.record.data["orders_refused"] == 1  # and the run fails, saying why
    assert any("refused to send 1 order" in problem for problem in lane.record.problems())


@pytest.mark.parametrize(("mode", "allowed"), [("order", 1), ("fill", 2), ("restart", 0)])
def test_each_mode_sends_at_most_its_own_number_of_orders(
    clean_environ, monkeypatch, mode, allowed
):
    lane = offline_strategy(monkeypatch, mode)
    lane.strategy._bid = FakePrice(199.0)
    if mode == "fill":
        lane.strategy._ask = FakePrice(200.0)
    for _ in range(allowed + 2):
        lane.strategy.submit_example_orders()
    assert len(lane.sent) == allowed
    assert lane.record.data["orders_refused"] == 2  # the extra ones were refused


@pytest.mark.parametrize("mode", ["order", "fill"])
@pytest.mark.parametrize("held", ["instrument_open_orders", "instrument_open_positions"])
def test_an_open_order_or_position_at_start_holds_every_order(
    clean_environ, monkeypatch, mode, held
):
    from meridian import ibkr_node

    lane = offline_strategy(monkeypatch, mode)
    counts = dict.fromkeys(
        (
            "instrument_open_orders",
            "instrument_open_positions",
            "account_open_orders",
            "account_open_positions",
        ),
        0,
    )
    counts[held] = 1
    monkeypatch.setattr(type(lane.strategy), "_open_counts", lambda self: counts)
    started: list = []
    monkeypatch.setattr(ibkr_node.IbV2OrderStrategy, "on_start", lambda self: started.append(1))
    lane.strategy.on_start()
    assert started == []  # upstream's start never ran: no instrument, no subscription
    # So in a run no quote arrives and no order could even be built. This quote stands in for
    # one that arrives anyway, with the test's instrument set: the guard is the layer tested.
    lane.quote(199.0, 200.0)
    assert lane.sent == []
    assert lane.record.data["orders_refused"] == 1


def test_a_mode_without_an_order_budget_sends_nothing(clean_environ, monkeypatch):
    lane = offline_strategy(monkeypatch, "order")
    lane.record.data["mode"] = "some later mode"
    lane.strategy._bid = FakePrice(199.0)
    lane.strategy.submit_example_orders()
    assert lane.sent == []
    assert lane.record.data["orders_refused"] == 1


def test_every_mode_has_its_own_order_budget():
    from meridian import ibkr_node

    assert set(ibkr_node.MAX_ORDERS) == set(ibkr_paper.MODES)


def test_order_mode_sends_its_one_order_on_the_first_quote(clean_environ, monkeypatch):
    lane = offline_strategy(monkeypatch, "order")
    lane.quote(199.0, 200.0)
    lane.quote(198.0, 199.0)
    (order,) = lane.sent
    assert order.price == 195.02  # 2% under the bid, so it rests
    assert lane.record.data["orders_refused"] == 0


@pytest.fixture
def round_trip(clean_environ, monkeypatch):
    """A fill-mode strategy outside any node: its orders are caught, not sent."""
    lane = offline_strategy(monkeypatch, "fill")
    strategy, record, sent = lane.strategy, lane.record, lane.sent

    def quote(bid: float, ask: float):
        strategy.on_quote(
            SimpleNamespace(
                instrument_id=strategy.instrument_id,
                bid_price=FakePrice(bid),
                ask_price=FakePrice(ask),
            )
        )

    def fill(client_order_id, last_px: float, qty: str = "1"):
        from nautilus_trader.model import Quantity

        # A stand-in for the engine's OrderFilled event, with only the fields the lane reads.
        event: Any = SimpleNamespace(
            client_order_id=client_order_id,
            last_px=FakePrice(last_px),
            last_qty=Quantity.from_str(qty),
        )
        strategy.on_order_filled(event)

    return SimpleNamespace(strategy=strategy, record=record, sent=sent, quote=quote, fill=fill)


def test_the_first_usable_quote_sends_one_buy_priced_to_fill(round_trip):
    from nautilus_trader.model import OrderSide

    round_trip.quote(0.0, 200.0)  # no bid yet
    round_trip.quote(201.0, 200.0)  # crossed
    assert round_trip.sent == []
    round_trip.quote(199.0, 200.0)
    round_trip.quote(150.0, 151.0)  # a later quote sends nothing more
    (buy,) = round_trip.sent
    assert buy.side == OrderSide.BUY and str(buy.quantity) == "1"
    assert buy.price == 204.0  # 2% above the ask
    assert round_trip.record.data["order"]["side"] == "BUY"


def test_the_buys_fill_sends_one_sell_of_the_filled_quantity(round_trip):
    from nautilus_trader.model import OrderSide

    round_trip.quote(199.0, 200.0)
    (buy,) = round_trip.sent
    round_trip.fill("not-the-buy", 200.0)  # another order's fill sends nothing
    assert len(round_trip.sent) == 1
    round_trip.fill(buy.client_order_id, 200.5)
    round_trip.fill(buy.client_order_id, 200.5)  # a repeated fill sends no second SELL
    assert len(round_trip.sent) == 2
    sell = round_trip.sent[1]
    assert sell.side == OrderSide.SELL and str(sell.quantity) == "1"
    assert sell.price == 195.02  # 2% under the lower of the bid (199) and the fill (200.5)
    assert round_trip.record.data["close_order"]["side"] == "SELL"
    assert round_trip.record.data["orders_refused"] == 0  # the repeat was ignored, not refused


def test_the_sell_prices_from_the_fill_when_the_delayed_bid_is_stale(round_trip):
    round_trip.quote(199.0, 200.0)
    (buy,) = round_trip.sent
    round_trip.fill(buy.client_order_id, 190.0)  # the live price fell below the delayed bid
    assert round_trip.sent[1].price == 186.2  # 2% under 190, not under 199


def test_the_closing_sell_goes_through_the_same_guard(round_trip, monkeypatch):
    from meridian import ibkr_node

    monkeypatch.setitem(ibkr_node.MAX_ORDERS, "fill", 1)  # room for the BUY only
    round_trip.quote(199.0, 200.0)
    (buy,) = round_trip.sent
    round_trip.fill(buy.client_order_id, 200.5)
    assert round_trip.sent == [buy]  # the SELL was refused, not sent around the guard
    assert round_trip.record.data["orders_refused"] == 1


class TalkativeNode:
    """Writes the account the way the engine can: to fds 1 and 2 directly, and through Python."""

    def __init__(self, fail: bool) -> None:
        self.fail = fail

    def run(self) -> None:
        os.write(1, f"AccountState(account_id=IB-{FAKE})\n".encode())
        os.write(2, f"native stderr {FAKE}\n".encode())
        print(f"python stdout {FAKE}")
        print(f"python stderr {FAKE}", file=sys.stderr)
        if self.fail:
            raise RuntimeError(f"reconciliation failed for account {FAKE}")


@pytest.mark.parametrize("fail", [False, True], ids=["clean-stop", "engine-error"])
def test_engine_output_goes_to_the_local_log_not_the_terminal(tmp_path, monkeypatch, capfd, fail):
    from meridian import ibkr_node

    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ibkr_node, "build", lambda *a, **k: TalkativeNode(fail))
    monkeypatch.setattr(ibkr_node, "schedule_node_stop", lambda node, seconds: None)
    record = ibkr_paper.RunRecord("restart", 4002)

    ibkr_node.run("restart", "127.0.0.1", 4002, FAKE, record)

    out, err = capfd.readouterr()
    assert FAKE not in out + err  # nothing the engine wrote reaches the terminal
    assert "-engine.log" in out
    (log,) = (tmp_path / "runs").glob("*-engine.log")
    text = log.read_text(encoding="utf-8")
    for piece in ("AccountState", "native stderr", "python stdout", "python stderr"):
        assert piece in text
    assert oct(log.stat().st_mode & 0o777) == "0o600"
    assert record.data["engine_error"] is fail
    assert FAKE not in json.dumps(record.data)  # the error text stays in the local part
    if fail:
        assert "RuntimeError" in err and "Traceback" in text
    # The terminal works normally again afterwards.
    print("after the run")
    assert "after the run" in capfd.readouterr().out
