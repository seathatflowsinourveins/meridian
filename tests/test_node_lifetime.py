"""A failing node test must not poison the next test on the same engine thread."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["lane", "execution", "ibkr"])
def test_failure_releases_node_before_next_test(tmp_path, kind):
    root = Path(__file__).resolve().parents[1]
    cases = {
        "lane": [
            "test_alpaca_lane_node.py::test_modes_reconcile_and_only_order_accepts_then_cancels[order]",
            "test_alpaca_lane_node.py::test_modes_reconcile_and_only_order_accepts_then_cancels[restart]",
        ],
        "execution": [
            "test_alpaca_node.py::test_a_flat_account_starts_and_reconciles_nothing",
            "test_alpaca_node.py::test_every_startup_read_passes_through_the_budget_as_a_query",
        ],
        "ibkr": [
            "test_ibkr_node_offline.py::test_the_order_node_builds_offline_with_the_lanes_settings",
            "test_alpaca_node.py::test_a_flat_account_starts_and_reconciles_nothing",
        ],
    }
    # A local pytest plugin plants an assertion while the node is in the test's
    # traceback: during a run, after a run, or after the IB builder (never run).
    (tmp_path / "plant_failure.py").write_text(
        """
import pytest

@pytest.fixture(autouse=True)
def plant(request, monkeypatch):
    name = request.node.name
    module = request.module
    def fail(*args, **kwargs):
        pytest.fail("planted node failure")
    if name.endswith("[order]"):
        original = module.wait_until
        async def fail_running(condition):
            await original(condition)
            fail()
        monkeypatch.setattr(module, "wait_until", fail_running)
    elif name == "test_a_flat_account_starts_and_reconciles_nothing" and KIND == "execution":
        monkeypatch.setattr(module, "holding", fail)
    elif name == "test_the_order_node_builds_offline_with_the_lanes_settings":
        monkeypatch.setattr(module, "lane_settings", fail)
""".replace("KIND", repr(kind))
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "plant_failure"]
        + [f"tests/{case}" for case in cases[kind]],
        cwd=root,
        env={"PYTHONPATH": os.pathsep.join([str(tmp_path), str(root / "tests")])},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr
    assert "planted node failure" in result.stdout
    assert "A LiveNode already exists" not in result.stdout
