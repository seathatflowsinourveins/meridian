"""Offline known-answer diagnostics and the actual module command under seccomp."""

import json
import subprocess
import sys

import numpy as np
import pytest
from ml4t.diagnostic.evaluation.stats import compute_pbo, deflated_sharpe_ratio
from test_sim import DRIVER, ROOT

from meridian.sim import runner
from meridian.sim.venue import SETS
from research.metrics import CVConfig, aligned_returns, evaluate_returns


def histories(matrix):
    return {f"trial-{i}": dict(enumerate(column.tolist())) for i, column in enumerate(matrix.T)}


@pytest.fixture(scope="module")
def noise():
    # A deterministic experiment, not a claim that every noise draw fails a 95% test.
    return np.random.default_rng(42).normal(0, 0.01, (1024, 64))


def test_many_noise_trials_do_not_pass_deflated_threshold(noise):
    result = evaluate_returns(histories(noise))
    assert result["n_trials"] == 64
    assert all(not s["dsr"]["is_significant"] for s in result["sets"])
    assert max(s["dsr"]["probability"] for s in result["sets"]) < 0.95
    best = next(s for s in result["sets"] if s["rank"] == 1)
    upstream = deflated_sharpe_ratio(noise)
    assert best["dsr"]["probability"] == pytest.approx(upstream.probability)
    assert best["dsr"]["expected_max_sharpe"] == pytest.approx(upstream.expected_max_sharpe)
    assert all(s["dsr"]["n_trials"] == 64 for s in result["sets"])


def test_planted_drift_ranks_first_and_passes(noise):
    planted = noise.copy()
    planted[:, 0] += 0.003  # constructed signal for this test only, never a strategy parameter
    result = evaluate_returns(histories(planted))
    first = result["sets"][0]
    assert first["rank"] == 1 and first["dsr"]["is_significant"]
    assert first["dsr"]["probability"] > 0.95
    assert first["dsr"]["deflated_sharpe"] > 0
    assert result["pbo"]["pbo"] == 0
    assert all(s["selected_set"] == "trial-0" for s in result["splits"])


def test_purge_embargo_and_test_scores_use_the_actual_split(noise):
    result = evaluate_returns(histories(noise[:48, :3]), CVConfig(4, 2, 1, 2))
    assert len(result["splits"]) == 6
    for split in result["splits"]:
        train = split["train"]
        test = sorted(i for fold in split["tests"] for i in fold)
        assert all(abs(a - b) > 1 for a in train for b in test)
        assert all(not 0 < a - b <= 3 for a in train for b in test)
        expected = noise[test, :3].mean(axis=0) / noise[test, :3].std(axis=0, ddof=1)
        np.testing.assert_allclose(split["test_sharpe"], expected)
        for i, candidate in enumerate(result["sets"]):
            assert split["test_sharpe"][i] in candidate["oos_sharpe"]
    ins = np.array([s["train_sharpe"] for s in result["splits"]])
    oos = np.array([s["test_sharpe"] for s in result["splits"]])
    assert result["pbo"]["pbo"] == compute_pbo(ins, oos).pbo


def test_upstream_pbo_known_reversal():
    ins = np.array([[3, 2, 1], [1, 3, 2]], dtype=float)
    assert compute_pbo(ins, ins).pbo == 0
    assert compute_pbo(ins, -ins).pbo == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_alignment_never_imputes_or_discards(bad):
    with pytest.raises(ValueError, match="identical"):
        aligned_returns({"a": {1: 0.1}, "b": {2: 0.2}})
    with pytest.raises(ValueError, match="finite"):
        aligned_returns({"a": {1: bad}, "b": {1: 0.2}})
    with pytest.raises(ValueError, match="at least two"):
        aligned_returns({"a": {1: 0.1}})


def test_degenerate_histories_do_not_get_significance(noise):
    for matrix in (noise[:1, :3], np.zeros((48, 3)), np.tile(noise[:48, 0:1], (1, 3))):
        with pytest.raises(ValueError):
            evaluate_returns(histories(matrix))
    with pytest.raises(ValueError, match="purged_size"):
        evaluate_returns(histories(noise[:12, :3]))


def test_tied_candidates_have_no_arbitrary_pbo(noise):
    matrix = noise[:48, :3].copy()
    matrix[:, 1] = matrix[:, 0]
    result = evaluate_returns(histories(matrix))
    assert result["pbo"]["status"] == "unavailable"
    assert "tied" in result["pbo"]["reason"]


def test_runner_exposes_engine_returns_without_reconstruction(tmp_path, monkeypatch):
    original = runner.BacktestNode
    engine_results = []

    class Capture:
        def __init__(self, configs):
            self.node = original(configs)

        def __getattr__(self, name):
            return getattr(self.node, name)

        def run(self):
            results = self.node.run()
            engine_results.extend(results)
            return results

    monkeypatch.setattr(runner, "BacktestNode", Capture)
    store = runner.write_catalog(tmp_path, copies=4, spacing_days=7)
    for models in SETS:
        data = runner.run_set(models, store, copies=4)
        assert data["problems"] == []
        assert data["returns_series"] == engine_results[-1].returns_series
        assert len(data["returns_series"]) == 22
    assert len(engine_results) == len(SETS)


# Reuse the simulation's syscall guard, including its narrow tokio AF_UNIX bootstrap.
MODULE_DRIVER = DRIVER.replace("from meridian.sim.runner import main", "import runpy").replace(
    "raise SystemExit(main([]))",
    'sys.argv = ["research.evaluate", "--sessions", "8"]\n'
    'runpy.run_module("research.evaluate", run_name="__main__")',
)


def test_module_command_is_offline_and_deterministic(tmp_path):
    records = []
    for index in range(2):
        folder = tmp_path / str(index)
        result = subprocess.run(
            [sys.executable, "-c", MODULE_DRIVER, str(ROOT), str(folder)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        lines = result.stdout.splitlines()
        assert lines[0].startswith("SYNTHETIC DATA")
        assert lines[-2] == "PASS (synthetic harness only)"
        path = folder / lines[-1].split(": ")[1]
        records.append(json.loads(path.read_text()))
        assert all(p.relative_to(folder).parts[0] == "runs" for p in folder.rglob("*"))
        assert "OOS median" in result.stdout and "PBO across 3 sets" in result.stdout
        for model in SETS:
            assert f"Engine statistics ({model.name}):" in result.stdout
    assert records[0] == records[1]
    record = records[0]
    evaluation = record["evaluation"]
    assert evaluation["n_trials"] == len(SETS) == 3
    assert evaluation["n_observations"] == 50
    assert evaluation["pbo"]["status"] == "ok"
    assert len(evaluation["splits"]) == 6
    for simulation, candidate in zip(record["simulation"], evaluation["sets"], strict=True):
        assert simulation["set"] == candidate["set"]
        assert sorted(map(int, simulation["returns_series"])) == evaluation["timestamps_ns"]
        assert len(candidate["oos_sharpe"]) == 6
        assert candidate["dsr"]["n_trials"] == 3
