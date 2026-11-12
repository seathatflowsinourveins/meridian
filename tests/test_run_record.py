"""The committed run record is scrubbed, and a run passes only when M1's conditions hold."""

import json

import pytest

from meridian import ibkr_paper

ACCOUNT = "DUTEST0001"
ACCOUNT_HASH = "ab" * 32
FORBIDDEN = [ACCOUNT, ACCOUNT_HASH]
T0 = 1_794_000_000_000_000_000
ORDER_ID = "IBV2-00000000-LIMIT"


def counts(instrument_orders=0, instrument_positions=0, account_orders=0, account_positions=0):
    return {
        "instrument_open_orders": instrument_orders,
        "instrument_open_positions": instrument_positions,
        "account_open_orders": account_orders,
        "account_open_positions": account_positions,
    }


def order_run() -> ibkr_paper.RunRecord:
    record = ibkr_paper.RunRecord("order", 4002)
    record.trader_started(**counts())
    record.order_built(
        client_order_id=ORDER_ID,
        instrument_id="AAPL.XNAS",
        side="BUY",
        type="LIMIT",
        time_in_force="DAY",
        quantity="1",
        price="200.00",
    )
    for kind in ("OrderSubmitted", "OrderAccepted", "OrderCanceled"):
        record.event(kind, T0, client_order_id=ORDER_ID)
    record.at_stop(**counts(), order_status="CANCELED", filled_qty="0")
    record.paper_checks_after_run(True)
    return record


def restart_run(at_start: dict | None = None, at_stop: dict | None = None):
    record = ibkr_paper.RunRecord("restart", 4002)
    record.trader_started(**(at_start or counts()))
    record.at_stop(**(at_stop or counts()))
    record.paper_checks_after_run(True)
    return record


# --- what gets written ---------------------------------------------------------------------


def test_a_clean_order_run_passes_and_is_written_to_evidence(tmp_path):
    passed, path = order_run().write(FORBIDDEN, root=tmp_path)
    assert passed
    assert path.parent == tmp_path / "evidence"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["result"] == "pass"
    assert written["problems"] == []
    assert written["order"]["time_in_force"] == "DAY"
    assert [e["type"] for e in written["events"]] == [
        "OrderSubmitted",
        "OrderAccepted",
        "OrderCanceled",
    ]
    assert "local" not in written


def test_broker_free_text_stays_out_of_evidence(tmp_path):
    record = order_run()
    record.reason("OrderCanceled", f"cancelled for account {ACCOUNT}")
    passed, path = record.write(FORBIDDEN, root=tmp_path)
    assert passed
    assert ACCOUNT not in path.read_text(encoding="utf-8")
    local = next((tmp_path / "runs").iterdir()).read_text(encoding="utf-8")
    assert ACCOUNT in local  # kept locally, in the ignored runs/ folder


@pytest.mark.parametrize("leak", [ACCOUNT, ACCOUNT.lower(), ACCOUNT_HASH])
def test_a_record_holding_an_account_identifier_is_not_written(tmp_path, leak):
    record = order_run()
    record.data["order"]["client_order_id"] = f"X-{leak}"
    with pytest.raises(RuntimeError):
        record.write(FORBIDDEN, root=tmp_path)
    assert not (tmp_path / "evidence").exists()


# --- what makes an order run fail --------------------------------------------------------------


def filled(record):
    record.event("OrderFilled", T0, client_order_id=ORDER_ID, last_qty="1", last_px="200.00")
    record.at_stop(**counts(instrument_positions=1), order_status="FILLED", filled_qty="1")


ORDER_FAILURES = {
    "trader never started": lambda r: r.data["startup_reconciliation"].update(trader_started=False),
    "no order": lambda r: r.data.update(order=None),
    "not a DAY order": lambda r: r.data["order"].update(time_in_force="GTC"),
    "not a LIMIT order": lambda r: r.data["order"].update(type="MARKET"),
    "never accepted": lambda r: r.data.update(
        events=[e for e in r.data["events"] if e["type"] != "OrderAccepted"]
    ),
    "not terminal": lambda r: r.data["at_stop"].update(order_status="ACCEPTED"),
    "order open at stop": lambda r: r.data["at_stop"].update(instrument_open_orders=1),
    "position open at stop": lambda r: r.data["at_stop"].update(instrument_open_positions=1),
    "no state at stop": lambda r: r.data.update(at_stop=None),
    "filled": filled,
    "filled, by status only": lambda r: r.data["at_stop"].update(order_status="FILLED"),
    "engine error": lambda r: r.engine_error("RuntimeError: disconnect timeout"),
    "paper checks failed after the run": lambda r: r.paper_checks_after_run(False),
    "no check after the run": lambda r: r.data["boundary"].update(
        paper_checks_passed_after_run=None
    ),
    "instrument not clean at start": lambda r: r.data["startup_reconciliation"].update(
        instrument_open_positions_at_start=1
    ),
}


@pytest.mark.parametrize("name", sorted(ORDER_FAILURES))
def test_an_order_run_that_misses_a_condition_fails_and_writes_no_evidence(tmp_path, name):
    record = order_run()
    ORDER_FAILURES[name](record)
    passed, path = record.write(FORBIDDEN, root=tmp_path)
    assert not passed
    assert path.parent == tmp_path / "runs"
    assert not (tmp_path / "evidence").exists()


def test_a_fill_is_named_as_the_problem(tmp_path):
    record = order_run()
    filled(record)
    record.write(FORBIDDEN, root=tmp_path)
    assert any("filled" in problem for problem in record.data["problems"])


def test_an_engine_error_keeps_its_text_out_of_evidence_data():
    record = order_run()
    record.engine_error(f"RuntimeError: account {ACCOUNT}")
    assert record.data["engine_error"] is True
    assert ACCOUNT not in json.dumps(record.data)


def test_other_open_items_in_the_account_are_recorded_but_do_not_fail_the_run(tmp_path):
    record = order_run()
    record.trader_started(**counts(account_orders=2, account_positions=3))
    record.at_stop(
        **counts(account_orders=2, account_positions=3), order_status="CANCELED", filled_qty="0"
    )
    passed, path = record.write(FORBIDDEN, root=tmp_path)
    assert passed
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["at_stop"]["account_open_positions"] == 3


# --- restart -----------------------------------------------------------------------------------


def test_a_clean_restart_passes(tmp_path):
    passed, _ = restart_run().write(FORBIDDEN, root=tmp_path)
    assert passed


@pytest.mark.parametrize("at_start", [counts(instrument_orders=1), counts(instrument_positions=1)])
def test_a_restart_that_finds_the_instrument_open_at_start_fails(tmp_path, at_start):
    # Clean again by the stop: only the at-start rule can catch this.
    passed, _ = restart_run(at_start=at_start, at_stop=counts()).write(FORBIDDEN, root=tmp_path)
    assert not passed


@pytest.mark.parametrize("at_stop", [counts(instrument_orders=1), counts(instrument_positions=1)])
def test_a_restart_that_ends_with_the_instrument_open_fails(tmp_path, at_stop):
    passed, _ = restart_run(at_stop=at_stop).write(FORBIDDEN, root=tmp_path)
    assert not passed


def test_a_restart_where_the_trader_never_started_fails(tmp_path):
    record = ibkr_paper.RunRecord("restart", 4002)
    record.paper_checks_after_run(True)
    passed, _ = record.write(FORBIDDEN, root=tmp_path)
    assert not passed
