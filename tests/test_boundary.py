"""The lane refuses to start unless the Gateway reports one allowlisted paper account."""

import json
from pathlib import Path

import pytest
from fake_gateway import FakeGateway

from meridian import boundary, ibkr_paper

PAPER = "DUTEST0001"
OTHER = "UTEST00002"
CLEAN = {
    "instrument_open_orders": 0,
    "instrument_open_positions": 0,
    "account_open_orders": 0,
    "account_open_positions": 0,
}


def contract_dict(**overrides: object) -> dict:
    contract: dict = {
        "schema": "meridian.boundary/1",
        "mode": "paper",
        "ibkr": {
            "gateway_host": "127.0.0.1",
            "gateway_port": 4002,
            "paper_accounts_sha256": [boundary.account_hash(PAPER)],
        },
    }
    for key, value in overrides.items():
        if key in contract["ibkr"]:
            contract["ibkr"][key] = value
        else:
            contract[key] = value
    return contract


def write_contract(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "boundary.contract.json"
    path.write_text(json.dumps(contract_dict(**overrides)), encoding="utf-8")
    return path


def bounds(tmp_path: Path) -> boundary.IbkrBoundary:
    return boundary.load_contract(write_contract(tmp_path))


# --- the allowlist ---------------------------------------------------------------------


def test_allowlisted_account_is_returned(tmp_path):
    assert boundary.allowed_account([PAPER], bounds(tmp_path)) == PAPER


def test_surrounding_whitespace_is_ignored_for_the_check_and_the_result(tmp_path):
    assert boundary.allowed_account([f" {PAPER}\n"], bounds(tmp_path)) == PAPER
    assert boundary.account_hash(f" {PAPER}\n") == boundary.account_hash(PAPER)


def test_account_not_on_the_allowlist_is_refused(tmp_path):
    with pytest.raises(boundary.BoundaryError):
        boundary.allowed_account([OTHER], bounds(tmp_path))


def test_no_account_is_refused(tmp_path):
    with pytest.raises(boundary.BoundaryError):
        boundary.allowed_account([], bounds(tmp_path))


def test_more_than_one_account_is_refused_even_if_all_are_listed(tmp_path):
    with pytest.raises(boundary.BoundaryError):
        boundary.allowed_account([PAPER, PAPER], bounds(tmp_path))


def test_an_account_with_a_hyphen_is_refused_even_if_its_hash_is_listed(tmp_path):
    odd = f"IB-{PAPER}"  # the engine's adapter would read this as a different account
    listed = boundary.load_contract(
        write_contract(tmp_path, paper_accounts_sha256=[boundary.account_hash(odd)])
    )
    with pytest.raises(boundary.BoundaryError):
        boundary.allowed_account([odd], listed)


def test_refusal_message_does_not_contain_the_account(tmp_path):
    with pytest.raises(boundary.BoundaryError) as refused:
        boundary.allowed_account([OTHER], bounds(tmp_path))
    assert OTHER not in str(refused.value)


# --- the contract ----------------------------------------------------------------------


def test_missing_contract_is_refused(tmp_path):
    with pytest.raises(boundary.BoundaryError):
        boundary.load_contract(tmp_path / "absent.json")


def test_malformed_contract_is_refused(tmp_path):
    path = tmp_path / "boundary.contract.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(boundary.BoundaryError):
        boundary.load_contract(path)


def test_a_contract_that_states_a_key_twice_is_refused(tmp_path):
    text = json.dumps(contract_dict())
    # A second "mode" after the first: a last-one-wins parser would read "paper".
    doubled = text.replace('"mode": "paper"', '"mode": "live", "mode": "paper"')
    assert doubled != text
    path = tmp_path / "boundary.contract.json"
    path.write_text(doubled, encoding="utf-8")
    with pytest.raises(boundary.BoundaryError):
        boundary.load_contract(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema": "something-else"},
        {"mode": "live"},
        {"mode": "PAPER"},
        {"ibkr": None},
        {"gateway_host": "192.168.1.10"},
        {"gateway_host": "0.0.0.0"},
        {"gateway_host": "localhost"},
        {"gateway_host": ["127.0.0.1"]},
        {"gateway_host": {"127.0.0.1": 1}},
        {"gateway_port": 4003},
        {"gateway_port": "4002"},
        {"gateway_port": 4002.0},
        {"gateway_port": True},
        {"paper_accounts_sha256": []},
        {"paper_accounts_sha256": [PAPER]},
        {"paper_accounts_sha256": "*"},
        {"paper_accounts_sha256": {boundary.account_hash(PAPER): True}},
        {"paper_accounts_sha256": [boundary.account_hash(PAPER).upper()]},
    ],
)
def test_contract_outside_the_paper_boundary_is_refused(tmp_path, overrides):
    with pytest.raises(boundary.BoundaryError):
        boundary.load_contract(write_contract(tmp_path, **overrides))


def test_only_the_gateway_paper_port_on_loopback_is_accepted():
    assert frozenset({4002}) == boundary.PAPER_PORTS
    assert boundary.GATEWAY_HOST == "127.0.0.1"


# --- the lane, end to end against a stand-in Gateway -------------------------------------


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """Point the lane at a temp contract and record whether the engine side was reached."""
    reached: list[str] = []

    def fake_run_node(mode, bounds, account):
        reached.append(account)
        return 0

    monkeypatch.setattr(ibkr_paper, "_run_node", fake_run_node)

    def start(gateway: FakeGateway, mode: str = "order", confirm: bool = True) -> int:
        # The stand-in listens on a free port; allow that one port for this test only.
        monkeypatch.setattr(boundary, "PAPER_PORTS", frozenset({gateway.port}))
        contract = write_contract(tmp_path, gateway_port=gateway.port)
        monkeypatch.setattr(boundary, "CONTRACT_PATH", contract)
        if confirm:  # stand in for the owner typing the word; the tests below leave it real
            monkeypatch.setattr(ibkr_paper, "owner_confirms", lambda: True)
        return ibkr_paper.main([mode])

    return start, reached


def test_lane_refuses_to_start_against_a_non_allowlisted_account(lane, capsys):
    start, reached = lane
    with FakeGateway(OTHER) as gateway:
        assert start(gateway) == 2
    assert reached == []  # the engine side was never entered
    err = capsys.readouterr().err
    assert "REFUSED TO START" in err
    assert OTHER not in err


def test_lane_refuses_when_the_gateway_reports_two_accounts(lane, capsys):
    start, reached = lane
    with FakeGateway(f"{PAPER},{OTHER}") as gateway:
        assert start(gateway) == 2
    assert reached == []
    err = capsys.readouterr().err
    assert PAPER not in err and OTHER not in err


def test_lane_refuses_when_the_gateway_reports_no_account(lane):
    start, reached = lane
    with FakeGateway("") as gateway:
        assert start(gateway) == 2
    assert reached == []


def test_lane_refuses_when_no_gateway_is_listening(lane):
    start, reached = lane
    with FakeGateway(PAPER) as gateway:
        pass  # closed again: nothing listens on that port now
    assert start(gateway) == 2
    assert reached == []


def test_lane_refuses_without_a_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(boundary, "CONTRACT_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(ibkr_paper, "_run_node", lambda *a: pytest.fail("engine side reached"))
    assert ibkr_paper.main(["order"]) == 2


def test_lane_starts_with_the_account_the_gateway_reports_when_it_is_allowlisted(lane):
    start, reached = lane
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 0
    assert reached == [PAPER]


# --- order mode needs the owner at a terminal ------------------------------------------------


def test_order_mode_refuses_without_a_terminal(lane, capsys):
    start, reached = lane
    with FakeGateway(PAPER) as gateway:
        # The real check runs: under pytest neither stdin nor stdout is a terminal.
        assert start(gateway, "order", confirm=False) == 2
    assert reached == []
    assert "needs the owner at a terminal" in capsys.readouterr().err


@pytest.mark.parametrize(("typed", "exit_code"), [("yes", 2), ("paper", 2), ("", 2), ("PAPER", 0)])
def test_order_mode_goes_on_only_when_the_owner_types_the_word(lane, monkeypatch, typed, exit_code):
    start, reached = lane
    monkeypatch.setattr(ibkr_paper, "_at_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)
    with FakeGateway(PAPER) as gateway:
        assert start(gateway, "order", confirm=False) == exit_code
    assert reached == ([PAPER] if exit_code == 0 else [])


def test_restart_mode_needs_no_confirmation(lane, monkeypatch):
    start, reached = lane
    monkeypatch.setattr(ibkr_paper, "owner_confirms", lambda: pytest.fail("asked in restart"))
    with FakeGateway(PAPER) as gateway:
        assert start(gateway, "restart", confirm=False) == 0
    assert reached == [PAPER]


# --- the hand-off to the engine, and the check after the run ---------------------------------


@pytest.fixture
def engine_stub(tmp_path, monkeypatch):
    """Run the real _run_node with the engine replaced by a clean restart."""
    from meridian import ibkr_node  # imported first: it fixes its paths at import time

    seen: dict = {}

    def fake_run(mode, host, port, account, record):
        seen.update(mode=mode, host=host, port=port, account=account)
        record.trader_started(**CLEAN)
        record.at_stop(**CLEAN)

    monkeypatch.setattr(ibkr_node, "run", fake_run)
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)

    def start(gateway: FakeGateway) -> int:
        monkeypatch.setattr(boundary, "PAPER_PORTS", frozenset({gateway.port}))
        contract = write_contract(tmp_path, gateway_port=gateway.port)
        monkeypatch.setattr(boundary, "CONTRACT_PATH", contract)
        return ibkr_paper.main(["restart"])

    return start, seen


def test_the_engine_gets_the_gated_host_port_and_account(engine_stub, tmp_path):
    start, seen = engine_stub
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 0
        assert seen == {
            "mode": "restart",
            "host": "127.0.0.1",
            "port": gateway.port,
            "account": PAPER,
        }
        assert gateway.sessions == 2  # asked before the run and again after it
    (evidence,) = (tmp_path / "evidence").iterdir()
    text = evidence.read_text(encoding="utf-8")
    assert PAPER not in text and boundary.account_hash(PAPER) not in text
    assert json.loads(text)["boundary"] == {
        "account_on_paper_allowlist_before_run": True,
        "account_on_paper_allowlist_after_run": True,
    }


def test_no_evidence_when_the_gateway_reports_another_account_after_the_run(engine_stub, tmp_path):
    start, seen = engine_stub
    with FakeGateway(PAPER, later_accounts=OTHER) as gateway:
        assert start(gateway) == 1
    assert seen["account"] == PAPER
    assert not (tmp_path / "evidence").exists()


def test_no_evidence_when_the_gateway_reports_no_account_after_the_run(engine_stub, tmp_path):
    start, seen = engine_stub
    with FakeGateway(PAPER, later_accounts="") as gateway:
        assert start(gateway) == 1
    assert not (tmp_path / "evidence").exists()
