"""
The engine side builds against the installed engine without connecting to anything.

This catches a mismatch between the lane and the pinned engine's API before an attended
run. It does not show that an order works: only a run against the paper Gateway does.
The engine supports one node per process, so exactly one test here builds a real node.
"""

import inspect
import os
import sys
from types import SimpleNamespace

import pytest

from meridian import ibkr_paper


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
    node = ibkr_node.build("order", "127.0.0.1", 4002, "DUTEST0001", record)

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


@pytest.mark.parametrize("mode", ["order", "restart"])
def test_upstreams_helper_is_driven_as_the_lane_intends(clean_environ, monkeypatch, mode):
    os.environ["IB_V2_BYPASS_RISK"] = "1"
    os.environ["IB_V2_ORDER_INSTRUMENT_ID"] = "ESZ26.XCME"
    os.environ["IB_V2_RECONCILIATION"] = "0"

    from meridian import ibkr_node

    upstream_common = sys.modules["_common"]  # upstream's helper module, loaded by ibkr_node
    builder = RecordingBuilder()
    monkeypatch.setattr(upstream_common, "LiveNode", SimpleNamespace(builder=lambda *a: builder))

    record = ibkr_paper.RunRecord(mode, 4002)
    ibkr_node.build(mode, "127.0.0.1", 4002, "DUTEST0001", record)

    # Reconciliation is on and the risk engine is not bypassed, whatever the shell held.
    assert builder.named("with_reconciliation") == [(True,)]
    assert builder.named("with_risk_engine_config") == []
    # One data client and one execution client, on the gated endpoint and account.
    ((_, _, data_config),) = builder.named("add_data_client")
    ((_, _, exec_config),) = builder.named("add_exec_client")
    assert (data_config.host, data_config.port, data_config.client_id) == ("127.0.0.1", 4002, 1511)
    assert (exec_config.host, exec_config.port, exec_config.client_id) == ("127.0.0.1", 4002, 1512)
    assert exec_config.account_id == "DUTEST0001"
    # One strategy, on the lane's instrument and not the one the shell asked for.
    (strategy,) = builder.strategies
    assert str(strategy.instrument_id) == "AAPL.XNAS"
    assert ("IB_V2_ENABLE_ORDER_SUBMISSION" in os.environ) == (mode == "order")
    assert os.environ["IB_V2_CLOSE_ON_STOP"] == "0"
