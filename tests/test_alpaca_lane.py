"""The attended entry point on fake keys, files, clock, terminal and node only."""

import importlib
import json
from pathlib import Path

import pytest
from order_budget_fixtures import control_rows

from meridian import ibkr_paper
from meridian.alpaca.credentials import PaperKeys


@pytest.fixture
def lane(monkeypatch):
    module = importlib.import_module("meridian.alpaca_lane")
    monkeypatch.setattr(module, "load_paper_keys", lambda: PaperKeys("fake-id", "fake-secret"))
    return module


@pytest.fixture
def settings_file(tmp_path):
    budget = tmp_path / "rows.json"
    data = control_rows()
    for row in data:
        row["scope"] = "REVIEWED"
    budget.write_text(json.dumps(data))
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"order_budget_rows_path": str(budget), "quote_max_age_ns": 42}))
    return path


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"quote_max_age_ns": 42},
        {"order_budget_rows_path": "private-path"},
        {"order_budget_rows_path": None, "quote_max_age_ns": 42},
        {"order_budget_rows_path": "private-path", "quote_max_age_ns": None},
        {"order_budget_rows_path": "private-path", "quote_max_age_ns": True},
        {"order_budget_rows_path": "private-path", "quote_max_age_ns": 0},
        {"order_budget_rows_path": "private-path", "quote_max_age_ns": -1},
        {"order_budget_rows_path": "private-path", "quote_max_age_ns": 1.5},
        {"order_budget_rows_path": "private-path", "quote_max_age_ns": "42"},
    ],
)
def test_settings_refusals_are_value_free(lane, monkeypatch, tmp_path, bad, capsys):
    path = tmp_path / "private-name"
    if bad is not None:
        path.write_text(json.dumps(bad))
    assert lane.main(["restart", "--settings", str(path)]) == 2
    error = capsys.readouterr().err
    assert "private" not in error and str(tmp_path) not in error
    assert error.startswith("REFUSED TO START: local settings")


@pytest.mark.parametrize(
    "answer,tty,expected",
    [("PAPER", True, 0), ("paper", True, 2), ("", True, 2), ("PAPER", False, 2)],
)
def test_typed_word_and_double_checks(lane, monkeypatch, settings_file, answer, tty, expected):
    monkeypatch.setattr(ibkr_paper, "_at_terminal", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    gates = []
    real_gate = lane.preflight

    def gate(path):
        gates.append(True)
        return real_gate(path)

    monkeypatch.setattr(lane, "preflight", gate)
    ran = []
    monkeypatch.setattr(lane, "run_attended", lambda *a: ran.append(a) or 0)
    assert lane.main(["order", "--settings", str(settings_file)]) == expected
    assert len(gates) == (2 if expected == 0 else 1)
    assert bool(ran) == (expected == 0)


def test_restart_needs_no_terminal(lane, monkeypatch, settings_file):
    monkeypatch.setattr(ibkr_paper, "owner_confirms", lambda *a: pytest.fail("restart prompt"))
    monkeypatch.setattr(lane, "run_attended", lambda *a: 0)
    assert lane.main(["restart", "--settings", str(settings_file)]) == 0


@pytest.mark.parametrize("change", ["age", "rows", "keys", "missing"])
def test_change_during_confirmation_refuses(lane, monkeypatch, settings_file, change, capsys):

    def confirm(*_):
        data = json.loads(settings_file.read_text())
        if change == "age":
            data["quote_max_age_ns"] += 1
            settings_file.write_text(json.dumps(data))
        elif change == "rows":
            budget = Path(data["order_budget_rows_path"])
            values = json.loads(budget.read_text())
            values[0]["source"] = "changed-private-source"
            budget.write_text(json.dumps(values))
        elif change == "keys":
            monkeypatch.setattr(lane, "load_paper_keys", lambda: PaperKeys("changed", "secret"))
        else:
            settings_file.unlink()
        return True

    monkeypatch.setattr(ibkr_paper, "owner_confirms", confirm)
    monkeypatch.setattr(lane, "run_attended", lambda *a: pytest.fail("changed gate ran"))
    assert lane.main(["order", "--settings", str(settings_file)]) == 2
    assert "secret" not in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["restart", "order"])
def test_record_pass_and_scrubbing(lane, monkeypatch, settings_file, tmp_path, mode):
    state = lane.preflight(settings_file)
    record = lane.RunRecord(mode, state)
    record.trader_started(
        instrument_open_orders=0,
        instrument_open_positions=0,
        account_open_orders=0,
        account_open_positions=0,
    )
    record.data["checks_unchanged_after_run"] = True
    record.at_stop(
        instrument_open_orders=0,
        instrument_open_positions=0,
        instrument_inflight_orders=0,
        execution_healthy=True,
        order_status="CANCELED" if mode == "order" else None,
        filled=False,
    )
    if mode == "order":
        record.order_built(type="LIMIT", time_in_force="DAY", side="BUY", quantity="1")
        record.event("OrderAccepted", 1)
        record.event("OrderCanceled", 2)
    record.reason("fake", "private-account-marker")
    passed, path = record.write(["private-account-marker"], tmp_path)
    assert passed and path.parent.name == "evidence"
    public = path.read_text()
    assert "private-account-marker" not in public
    assert "quote_max_age_ns" not in public and '"42"' not in public
    data = json.loads(public)
    assert data["budget_rows"] == {"paper_defaults": 0, "reviewed": 16}
    assert data["quote_age_limit_present"] is True
    assert data["commission_source"]
    assert data["lane"] == "alpaca-paper" and data["milestone"] == "M3"
    assert path.name.startswith("M3-alpaca-paper-")
    assert public == json.dumps(data, indent=2, sort_keys=True) + "\n"


@pytest.mark.parametrize(
    "problem",
    [
        "fill",
        "partial",
        "not_canceled",
        "not_accepted",
        "engine_error",
        "not_started",
        "open",
        "inflight",
        "position",
        "refused",
        "coverage",
        "gate",
    ],
)
def test_failed_record_never_becomes_evidence(lane, monkeypatch, settings_file, tmp_path, problem):
    record = lane.RunRecord("order", lane.preflight(settings_file))
    record.trader_started(
        instrument_open_orders=0,
        instrument_open_positions=0,
        account_open_orders=0,
        account_open_positions=0,
    )
    record.data["checks_unchanged_after_run"] = problem != "gate"
    record.order_built(type="LIMIT", time_in_force="DAY", side="BUY", quantity="1")
    if problem != "not_accepted":
        record.event("OrderAccepted", 1)
    if problem == "fill":
        record.event("OrderFilled", 2)
    record.at_stop(
        instrument_open_orders=int(problem == "open"),
        instrument_open_positions=int(problem == "position"),
        instrument_inflight_orders=int(problem == "inflight"),
        execution_healthy=problem != "coverage",
        order_status="ACCEPTED" if problem == "not_canceled" else "CANCELED",
        filled=problem == "partial",
    )
    if problem == "engine_error":
        record.engine_error("private-account-marker")
    if problem == "not_started":
        record.data["startup_reconciliation"]["trader_started"] = False
    if problem == "refused":
        record.order_refused("private-account-marker")
    assert record.write(["private-account-marker"], tmp_path)[0] is False
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("bad", ["missing", "malformed", "fixture", "private-value"])
def test_budget_refusals_disclose_no_values(lane, monkeypatch, settings_file, bad, capsys):
    path = Path(json.loads(settings_file.read_text())["order_budget_rows_path"])
    if bad == "missing":
        path.unlink()
    elif bad == "malformed":
        path.write_text("private-account-marker")
    else:
        data = json.loads(path.read_text())
        data[0]["scope" if bad == "fixture" else "value"] = (
            "FIXTURE_ONLY" if bad == "fixture" else "private-account-marker"
        )
        path.write_text(json.dumps(data))
    assert lane.main(["restart", "--settings", str(settings_file)]) == 2
    assert capsys.readouterr().err == "REFUSED TO START: order budget rows unavailable or invalid\n"


def test_missing_credentials_refuse_without_exception_text(
    lane, monkeypatch, settings_file, capsys
):

    def missing():
        raise RuntimeError("private-account-marker")

    monkeypatch.setattr(lane, "load_paper_keys", missing)
    assert lane.main(["restart", "--settings", str(settings_file)]) == 2
    assert capsys.readouterr().err == "REFUSED TO START: paper credentials unavailable\n"


def test_template_nulls_and_tracked_settings_refused(lane):
    root = Path(__file__).resolve().parents[1]
    path = root / "deploy/alpaca-lane.template.json"
    assert json.loads(path.read_text()) == {
        "order_budget_rows_path": None,
        "quote_max_age_ns": None,
    }
    with pytest.raises(lane.Refused, match="local settings unavailable or invalid"):
        lane.load_settings(path)


@pytest.mark.parametrize("failure", [False, True])
def test_engine_output_is_local_even_on_failure(
    lane, monkeypatch, settings_file, tmp_path, capfd, failure
):
    node = importlib.import_module("meridian.alpaca_node")
    state = lane.preflight(settings_file)
    record = lane.RunRecord("restart", state)
    monkeypatch.setattr(node.boundary, "REPO_ROOT", tmp_path)

    def build(*_):
        print("private-account-marker")
        if failure:
            raise RuntimeError("private-account-marker")
        return object()

    async def run_fake(*_):
        print("private-account-marker")

    monkeypatch.setattr(node, "build", build)
    monkeypatch.setattr(node, "run_until_stop", run_fake)
    node.run(state, record)
    out = capfd.readouterr()
    assert "private-account-marker" not in out.out + out.err
    assert "private-account-marker" in next((tmp_path / "runs").glob("*.log")).read_text()
    assert record.data["engine_error"] is failure


@pytest.mark.parametrize("changed", [False, True])
def test_post_run_checks_and_record_result(
    lane, monkeypatch, settings_file, tmp_path, changed, capsys
):
    node = importlib.import_module("meridian.alpaca_node")
    state = lane.preflight(settings_file)
    monkeypatch.setattr(lane.boundary, "REPO_ROOT", tmp_path / "output")

    def run_fake(state, record):
        record.trader_started(
            instrument_open_orders=0,
            instrument_open_positions=0,
            account_open_orders=0,
            account_open_positions=0,
        )
        record.at_stop(
            instrument_open_orders=0,
            instrument_open_positions=0,
            instrument_inflight_orders=0,
            execution_healthy=True,
            filled=False,
        )
        if changed:
            settings_file.unlink()

    monkeypatch.setattr(node, "run", run_fake)
    assert lane.run_attended("restart", settings_file, state) == int(changed)
    assert (tmp_path / "output/evidence").exists() is (not changed)
    assert "private" not in capsys.readouterr().out


def test_loader_scope_counts_are_displayed_and_recorded(lane, monkeypatch, settings_file, capsys):
    path = Path(json.loads(settings_file.read_text())["order_budget_rows_path"])
    values = json.loads(path.read_text())
    for row in values[:3]:
        row["scope"] = "PAPER_DEFAULT"
    path.write_text(json.dumps(values))
    seen = []
    monkeypatch.setattr(lane, "run_attended", lambda *args: seen.append(args[-1]) or 0)
    assert lane.main(["restart", "--settings", str(settings_file)]) == 0
    assert (
        capsys.readouterr().out
        == "Budget rows: 3 paper defaults, 13 reviewed; quote-age limit present.\n"
    )
    assert lane.RunRecord("restart", seen[0]).data["budget_rows"] == {
        "paper_defaults": 3,
        "reviewed": 13,
    }
