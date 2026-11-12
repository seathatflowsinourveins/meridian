"""The lane refuses to start unless every paper check in meridian/boundary.py holds."""

import json
import os
from pathlib import Path

import pytest
from fake_gateway import FakeGateway

from meridian import boundary, ibkr_paper

# Fake ids. They have letters between prefix and digits, so they never look like a real id
# to tests/test_public_tree.py.
PAPER = "DUTEST0001"
OTHER = "UTEST00002"  # the form of a real-money account
NOT_LISTED = "DUTEST0003"  # the paper form, but not on the allowlist
NOT_PAPER_FORM = [OTHER, "FTEST0003", "ITEST0004", "XTEST0005", "DTEST", "dutest0001", "D", "0001"]
CLEAN = {
    "instrument_open_orders": 0,
    "instrument_open_positions": 0,
    "account_open_orders": 0,
    "account_open_positions": 0,
}
JTS_PAPER = "[IBGateway]\nApiOnly=true\n\n[Logon]\nLocale=en\ntradingMode=p\n"
LISTEN, ESTABLISHED = "0A", "01"


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


def no_contract(tmp_path: Path) -> boundary.IbkrBoundary:
    return boundary.load_contract(tmp_path / "absent.json")


# --- check 3: the account, and check 4: the optional allowlist ----------------------------------


def test_without_a_contract_a_paper_form_account_is_returned(tmp_path):
    assert boundary.allowed_account([PAPER], no_contract(tmp_path)) == PAPER


@pytest.mark.parametrize("account", NOT_PAPER_FORM)
def test_an_account_not_of_the_paper_form_is_refused_without_a_contract(tmp_path, account):
    with pytest.raises(boundary.BoundaryError, match="not of the paper form"):
        boundary.allowed_account([account], no_contract(tmp_path))


@pytest.mark.parametrize("account", NOT_PAPER_FORM)
def test_an_account_not_of_the_paper_form_is_refused_even_if_its_hash_is_listed(tmp_path, account):
    listed = boundary.load_contract(
        write_contract(tmp_path, paper_accounts_sha256=[boundary.account_hash(account)])
    )
    with pytest.raises(boundary.BoundaryError, match="not of the paper form"):
        boundary.allowed_account([account], listed)


def test_allowlisted_account_is_returned(tmp_path):
    assert boundary.allowed_account([PAPER], bounds(tmp_path)) == PAPER


def test_surrounding_whitespace_is_ignored_for_the_check_and_the_result(tmp_path):
    assert boundary.allowed_account([f" {PAPER}\n"], bounds(tmp_path)) == PAPER
    assert boundary.account_hash(f" {PAPER}\n") == boundary.account_hash(PAPER)


def test_with_a_contract_an_account_not_on_its_allowlist_is_refused(tmp_path):
    with pytest.raises(boundary.BoundaryError, match="not on the paper allowlist"):
        boundary.allowed_account([NOT_LISTED], bounds(tmp_path))


@pytest.mark.parametrize("reported", [[], [""], [" "], [PAPER, PAPER], [PAPER, NOT_LISTED]])
def test_anything_but_exactly_one_account_is_refused(tmp_path, reported):
    for b in (no_contract(tmp_path), bounds(tmp_path)):
        with pytest.raises(boundary.BoundaryError):
            boundary.allowed_account(reported, b)


def test_an_account_with_a_hyphen_is_refused_even_if_its_hash_is_listed(tmp_path):
    odd = f"IB-{PAPER}"  # the engine's adapter would read this as a different account
    listed = boundary.load_contract(
        write_contract(tmp_path, paper_accounts_sha256=[boundary.account_hash(odd)])
    )
    with pytest.raises(boundary.BoundaryError):
        boundary.allowed_account([odd], listed)


@pytest.mark.parametrize("account", [OTHER, NOT_LISTED])
def test_refusal_message_does_not_contain_the_account(tmp_path, account):
    with pytest.raises(boundary.BoundaryError) as refused:
        boundary.allowed_account([account], bounds(tmp_path))
    assert account not in str(refused.value)


# --- the optional contract -------------------------------------------------------------------


def test_no_contract_means_no_allowlist_and_the_fixed_target(tmp_path):
    b = no_contract(tmp_path)
    assert b.paper_accounts_sha256 is None
    assert (b.host, b.port) == ("127.0.0.1", 4002)


def test_a_dangling_contract_link_is_refused_not_ignored(tmp_path):
    path = tmp_path / "boundary.contract.json"
    os.symlink(tmp_path / "nowhere.json", path)
    with pytest.raises(boundary.BoundaryError):
        boundary.load_contract(path)


def test_a_contract_that_is_a_directory_is_refused(tmp_path):
    path = tmp_path / "boundary.contract.json"
    path.mkdir()
    with pytest.raises(boundary.BoundaryError):
        boundary.load_contract(path)


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


def test_the_fixed_target_and_the_gateway_paths():
    assert frozenset({4002}) == boundary.PAPER_PORTS
    assert boundary.PAPER_PORT == 4002
    assert boundary.GATEWAY_HOST == "127.0.0.1"
    assert Path.home() / "Jts" / "jts.ini" == boundary.JTS_INI
    assert Path.home() / "Jts" / "ibgateway" == boundary.GATEWAY_DIR
    assert boundary.PAPER_TRADING_MODE == "p"


# --- check 1: the Gateway's jts.ini says Paper Trading ---------------------------------------


def write_jts(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "jts.ini"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_a_paper_login_passes(tmp_path):
    boundary.require_paper_login(write_jts(tmp_path, JTS_PAPER))


def test_spaces_around_the_value_are_ignored(tmp_path):
    boundary.require_paper_login(write_jts(tmp_path, "[Logon]\ntradingMode =  p  \n"))


@pytest.mark.parametrize(
    "text",
    [
        "[Logon]\ntradingMode=l\n",
        "[Logon]\ntradingMode=P\n",
        "[Logon]\ntradingMode=\n",
        "[Logon]\ntradingMode=paper\n",
        "[Logon]\ntradingMode=p ; live\n",
        "[Logon]\nLocale=en\n",  # no key
        "[IBGateway]\ntradingMode=p\n",  # the key, but in another section
        "[logon]\ntradingMode=p\n",  # another section name
        "[Logon]\ntradingMode=p\nTradingMode=l\n",  # the key twice
        "[Logon]\ntradingMode=p\n[Logon]\nLocale=en\n",  # the section twice
        "tradingMode=p\n",  # no section
        "",
        "not a settings file\n",
    ],
)
def test_anything_but_a_clear_paper_login_is_refused(tmp_path, text):
    with pytest.raises(boundary.BoundaryError):
        boundary.require_paper_login(write_jts(tmp_path, text))


def test_a_settings_file_that_is_not_utf8_is_refused(tmp_path):
    with pytest.raises(boundary.BoundaryError):
        boundary.require_paper_login(write_jts(tmp_path, b"[Logon]\ntradingMode=p\n\xff\xfe\n"))


def test_no_settings_file_is_refused(tmp_path):
    with pytest.raises(boundary.BoundaryError):
        boundary.require_paper_login(tmp_path / "absent.ini")


# --- check 2: the Gateway listens on the paper port only (a stand-in /proc) -------------------

TCP_HEAD = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  "
    "timeout inode\n"
)


def tcp_row(n: int, port: int, state: str, inode: int, v6: bool = False) -> str:
    zero = "0" * (32 if v6 else 8)
    return (
        f"{n:4d}: {zero}:{port:04X} {zero}:0000 {state} 00000000:00000000 00:00000000 "
        f"00000000  1000        0 {inode} 1 0000000000000000 100 0 0 10 0\n"
    )


def fake_proc(root: Path, processes, tcp=(), tcp6=None) -> Path:
    """processes: [(exe, [socket inodes])]; tcp, tcp6: [(port, state, inode)], None = absent."""
    proc = root / "proc"
    (proc / "net").mkdir(parents=True)
    for name, rows, v6 in (("tcp", tcp, False), ("tcp6", tcp6, True)):
        if rows is not None:
            body = "".join(tcp_row(i, *row, v6=v6) for i, row in enumerate(rows))
            (proc / "net" / name).write_text(TCP_HEAD + body, encoding="ascii")
    (proc / "self").mkdir()  # not a process number: skipped
    for pid, (exe, inodes) in enumerate(processes, start=100):
        fd = proc / str(pid) / "fd"
        fd.mkdir(parents=True)
        os.symlink(exe, proc / str(pid) / "exe")
        for n, inode in enumerate(inodes):
            os.symlink(f"socket:[{inode}]", fd / str(n))
        os.symlink("/dev/null", fd / str(len(inodes)))  # an open file that is not a socket
    return proc


@pytest.fixture
def gw(tmp_path):
    gateway_dir = (tmp_path / "Jts" / "ibgateway").resolve()
    return gateway_dir, str(gateway_dir / "1050" / "jre" / "bin" / "java")


def test_the_gateway_on_the_paper_port_is_seen(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(tmp_path, [(java, [11])], tcp=[(4002, LISTEN, 11)])
    assert boundary.gateway_listen_ports(proc, gateway_dir) == {4002}


def test_an_ipv6_listener_counts_too(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(
        tmp_path, [(java, [11, 12])], tcp=[], tcp6=[(4002, LISTEN, 11), (5000, LISTEN, 12)]
    )
    assert boundary.gateway_listen_ports(proc, gateway_dir) == {4002, 5000}


def test_a_connection_that_is_not_listening_is_not_a_port(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(tmp_path, [(java, [11])], tcp=[(4002, ESTABLISHED, 11)])
    assert boundary.gateway_listen_ports(proc, gateway_dir) == frozenset()


def test_another_program_on_the_paper_port_is_not_the_gateway(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(tmp_path, [(java, []), ("/usr/bin/python3", [11])], tcp=[(4002, LISTEN, 11)])
    assert boundary.gateway_listen_ports(proc, gateway_dir) == frozenset()


def test_ports_of_every_gateway_process_are_counted(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(
        tmp_path, [(java, [11]), (java, [12])], tcp=[(4002, LISTEN, 11), (5000, LISTEN, 12)]
    )
    assert boundary.gateway_listen_ports(proc, gateway_dir) == {4002, 5000}


@pytest.mark.parametrize("exe", ["/usr/bin/python3", "{dir}-old/1050/jre/bin/java", "{dir}"])
def test_no_gateway_process_is_refused(tmp_path, gw, exe):
    gateway_dir, _ = gw
    proc = fake_proc(tmp_path, [(exe.format(dir=gateway_dir), [11])], tcp=[(4002, LISTEN, 11)])
    with pytest.raises(boundary.BoundaryError, match="not running"):
        boundary.gateway_listen_ports(proc, gateway_dir)


def test_an_unreadable_socket_table_is_refused(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(tmp_path, [(java, [11])], tcp=None)
    with pytest.raises(boundary.BoundaryError):
        boundary.gateway_listen_ports(proc, gateway_dir)


def test_a_malformed_socket_table_is_refused(tmp_path, gw):
    gateway_dir, java = gw
    proc = fake_proc(tmp_path, [(java, [11])], tcp=[(4002, LISTEN, 11)])
    (proc / "net" / "tcp").write_text(TCP_HEAD + "   0: garbage\n", encoding="ascii")
    with pytest.raises(boundary.BoundaryError):
        boundary.gateway_listen_ports(proc, gateway_dir)


@pytest.mark.parametrize(
    ("listening", "passes"),
    [({4002}, True), ({4002, 5000}, False), ({5000}, False), (set(), False)],
)
def test_the_lane_needs_the_gateway_on_the_paper_port_only(
    tmp_path, gw, monkeypatch, listening, passes
):
    gateway_dir, java = gw
    ports = sorted(listening)
    inodes = list(range(20, 20 + len(ports)))
    rows = [(port, LISTEN, inode) for port, inode in zip(ports, inodes, strict=True)]
    monkeypatch.setattr(boundary, "PROC", fake_proc(tmp_path, [(java, inodes)], tcp=rows))
    monkeypatch.setattr(boundary, "GATEWAY_DIR", gateway_dir)
    if passes:
        boundary.require_gateway_on_paper_port_only()
    else:
        with pytest.raises(boundary.BoundaryError):
            boundary.require_gateway_on_paper_port_only()


# --- the lane, end to end against a stand-in Gateway -------------------------------------


@pytest.fixture
def paper_state(tmp_path, monkeypatch):
    """The Gateway's local state on a paper login, with no contract. Tests change parts."""
    jts = write_jts(tmp_path, JTS_PAPER)
    monkeypatch.setattr(boundary, "JTS_INI", jts)
    monkeypatch.setattr(boundary, "CONTRACT_PATH", tmp_path / "no-contract.json")
    extra_ports: set[int] = set()

    def use(gateway: FakeGateway) -> None:
        # The stand-in listens on a free port; make that the paper port for this test only.
        monkeypatch.setattr(boundary, "PAPER_PORT", gateway.port)
        monkeypatch.setattr(boundary, "PAPER_PORTS", frozenset({gateway.port}))
        monkeypatch.setattr(
            boundary,
            "gateway_listen_ports",
            lambda proc=None, gateway_dir=None: frozenset({gateway.port, *extra_ports}),
        )

    return jts, extra_ports, use


def allowlist(tmp_path: Path, monkeypatch, gateway: FakeGateway, accounts) -> None:
    contract = write_contract(
        tmp_path,
        gateway_port=gateway.port,
        paper_accounts_sha256=[boundary.account_hash(a) for a in accounts],
    )
    monkeypatch.setattr(boundary, "CONTRACT_PATH", contract)


@pytest.fixture
def lane(tmp_path, monkeypatch, paper_state):
    """Start the lane against a stand-in Gateway; record whether the engine side was reached."""
    _, _, use = paper_state
    reached: list[str] = []

    def fake_run_node(mode, bounds, account):
        reached.append(account)
        return 0

    monkeypatch.setattr(ibkr_paper, "_run_node", fake_run_node)

    def start(gateway: FakeGateway, mode: str = "order", confirm: bool = True, listed=None) -> int:
        use(gateway)
        if listed is not None:
            allowlist(tmp_path, monkeypatch, gateway, listed)
        if confirm:  # stand in for the owner typing the word; the tests below leave it real
            monkeypatch.setattr(ibkr_paper, "owner_confirms", lambda: True)
        return ibkr_paper.main([mode])

    return start, reached


def test_lane_starts_without_a_contract_when_every_paper_check_holds(lane):
    start, reached = lane
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 0
    assert reached == [PAPER]


def test_lane_refuses_a_real_money_form_account(lane, capsys):
    start, reached = lane
    with FakeGateway(OTHER) as gateway:
        assert start(gateway) == 2
    assert reached == []  # the engine side was never entered
    err = capsys.readouterr().err
    assert "REFUSED TO START" in err and "not of the paper form" in err
    assert OTHER not in err


def test_lane_refuses_a_real_money_form_account_even_if_the_contract_lists_it(lane, capsys):
    start, reached = lane
    with FakeGateway(OTHER) as gateway:
        assert start(gateway, listed=(PAPER, OTHER)) == 2
    assert reached == []
    assert "not of the paper form" in capsys.readouterr().err


def test_lane_refuses_to_start_against_a_non_allowlisted_account(lane, capsys):
    start, reached = lane
    with FakeGateway(NOT_LISTED) as gateway:
        assert start(gateway, listed=(PAPER,)) == 2
    assert reached == []
    err = capsys.readouterr().err
    assert "REFUSED TO START" in err and "not on the paper allowlist" in err
    assert NOT_LISTED not in err


def test_lane_starts_with_an_allowlisted_account(lane):
    start, reached = lane
    with FakeGateway(PAPER) as gateway:
        assert start(gateway, listed=(PAPER,)) == 0
    assert reached == [PAPER]


@pytest.mark.parametrize("jts_text", ["[Logon]\ntradingMode=l\n", None])
def test_lane_refuses_unless_jts_says_paper_and_never_contacts_the_gateway(
    lane, paper_state, capsys, jts_text
):
    start, reached = lane
    jts, _, _ = paper_state
    if jts_text is None:
        jts.unlink()
    else:
        jts.write_text(jts_text, encoding="utf-8")
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 2
        assert gateway.sessions == 0
    assert reached == []
    assert "REFUSED TO START" in capsys.readouterr().err


def test_lane_refuses_when_the_gateway_also_listens_on_another_port(lane, paper_state):
    start, reached = lane
    _, extra_ports, _ = paper_state
    extra_ports.add(5000)
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 2
        assert gateway.sessions == 0
    assert reached == []


def test_lane_refuses_with_a_malformed_contract(lane, tmp_path, monkeypatch):
    start, reached = lane
    bad = tmp_path / "bad.contract.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(boundary, "CONTRACT_PATH", bad)  # present but malformed: refuse
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 2
        assert gateway.sessions == 0
    assert reached == []


@pytest.mark.parametrize("accounts", [f"{PAPER},{NOT_LISTED}", ""])
def test_lane_refuses_unless_the_gateway_reports_exactly_one_account(lane, capsys, accounts):
    start, reached = lane
    with FakeGateway(accounts) as gateway:
        assert start(gateway) == 2
    assert reached == []
    err = capsys.readouterr().err
    assert PAPER not in err and NOT_LISTED not in err


def test_lane_refuses_when_no_gateway_is_listening(lane):
    start, reached = lane
    with FakeGateway(PAPER) as gateway:
        pass  # closed again: nothing listens on that port now
    assert start(gateway) == 2
    assert reached == []


# --- the owner's optional contract command ------------------------------------------------------


@pytest.fixture
def contract_cmd(monkeypatch, paper_state):
    """Run ``python -m meridian.boundary contract`` against a stand-in Gateway."""
    _, _, use = paper_state
    asked: list[bool] = []

    def run(gateway: FakeGateway, typed: str = "PAPER", at_terminal: bool = True) -> int:
        use(gateway)
        monkeypatch.setattr(boundary, "_owner_at_terminal", lambda: at_terminal)

        def answer() -> str:
            asked.append(True)
            return typed + "\n"

        monkeypatch.setattr(boundary, "_read_answer", answer)
        return boundary._main(["contract"])

    return run, asked


def test_contract_command_prints_a_contract_that_lets_only_that_account_through(
    contract_cmd, capsys, tmp_path
):
    run, asked = contract_cmd
    with FakeGateway(PAPER) as gateway:
        assert run(gateway) == 0
    out = capsys.readouterr().out
    assert PAPER not in out  # only its hash goes into the file
    path = tmp_path / "printed.contract.json"
    path.write_text(out, encoding="utf-8")
    loaded = boundary.load_contract(path)
    assert loaded.paper_accounts_sha256 == frozenset({boundary.account_hash(PAPER)})
    assert loaded.port == gateway.port and loaded.host == "127.0.0.1"
    assert boundary.allowed_account([PAPER], loaded) == PAPER
    with pytest.raises(boundary.BoundaryError):
        boundary.allowed_account([NOT_LISTED], loaded)


def test_the_contract_text_names_the_real_paper_port_and_loopback(tmp_path):
    path = tmp_path / "boundary.contract.json"
    path.write_text(boundary.contract_text(PAPER), encoding="utf-8")
    loaded = boundary.load_contract(path)
    assert (loaded.host, loaded.port) == ("127.0.0.1", 4002)
    assert PAPER not in path.read_text(encoding="utf-8")


def test_contract_command_refuses_without_a_terminal_and_does_not_ask_the_gateway(contract_cmd):
    run, asked = contract_cmd
    with FakeGateway(PAPER) as gateway:
        assert run(gateway, at_terminal=False) == 2
        assert gateway.sessions == 0
    assert asked == []


def test_contract_command_refuses_when_jts_does_not_say_paper(contract_cmd, paper_state, capsys):
    run, asked = contract_cmd
    jts, _, _ = paper_state
    jts.write_text("[Logon]\ntradingMode=l\n", encoding="utf-8")
    with FakeGateway(PAPER) as gateway:
        assert run(gateway) == 2
        assert gateway.sessions == 0
    assert asked == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize("typed", ["yes", "paper", ""])
def test_contract_command_prints_nothing_unless_the_owner_types_the_word(
    contract_cmd, capsys, typed
):
    run, asked = contract_cmd
    with FakeGateway(PAPER) as gateway:
        assert run(gateway, typed=typed) == 2
    assert capsys.readouterr().out == ""
    assert asked == [True]


@pytest.mark.parametrize("accounts", [OTHER, f"{PAPER},{NOT_LISTED}", ""])
def test_contract_command_refuses_before_asking_when_the_gateway_report_is_wrong(
    contract_cmd, capsys, accounts
):
    run, asked = contract_cmd
    with FakeGateway(accounts) as gateway:
        assert run(gateway) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert asked == []
    assert OTHER not in captured.err and NOT_LISTED not in captured.err


def test_contract_command_refuses_when_no_gateway_is_listening(contract_cmd, capsys):
    run, asked = contract_cmd
    with FakeGateway(PAPER) as gateway:
        pass  # closed again: nothing listens on that port now
    assert run(gateway) == 2
    assert capsys.readouterr().out == ""
    assert asked == []


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


# --- the hand-off to the engine, and the checks after the run ---------------------------------


@pytest.fixture
def engine_stub(tmp_path, monkeypatch, paper_state):
    """Run the real _run_node with the engine replaced by a clean restart."""
    from meridian import ibkr_node  # imported first: it fixes its paths at import time

    _, _, use = paper_state
    seen: dict = {}
    during: list = []  # callables run in the middle of the stand-in run

    def fake_run(mode, host, port, account, record):
        seen.update(mode=mode, host=host, port=port, account=account)
        record.trader_started(**CLEAN)
        for change in during:
            change()
        record.at_stop(**CLEAN)

    monkeypatch.setattr(ibkr_node, "run", fake_run)
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)

    def start(gateway: FakeGateway, listed=None) -> int:
        use(gateway)
        if listed is not None:
            allowlist(tmp_path, monkeypatch, gateway, listed)
        return ibkr_paper.main(["restart"])

    return start, seen, during


def test_the_engine_gets_the_gated_host_port_and_account(engine_stub, tmp_path):
    start, seen, _ = engine_stub
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
        "paper_checks_passed_before_run": True,
        "paper_checks_passed_after_run": True,
        "allowlist_contract_present": False,
    }


def test_the_record_says_when_an_allowlist_was_used(engine_stub, tmp_path):
    start, _, _ = engine_stub
    with FakeGateway(PAPER) as gateway:
        assert start(gateway, listed=(PAPER,)) == 0
    (evidence,) = (tmp_path / "evidence").iterdir()
    assert json.loads(evidence.read_text(encoding="utf-8"))["boundary"][
        "allowlist_contract_present"
    ]


def test_no_evidence_when_the_gateway_reports_another_account_after_the_run(engine_stub, tmp_path):
    start, seen, _ = engine_stub
    with FakeGateway(PAPER, later_accounts=NOT_LISTED) as gateway:
        assert start(gateway) == 1
    assert seen["account"] == PAPER
    assert not (tmp_path / "evidence").exists()


def test_no_evidence_when_the_gateway_reports_no_account_after_the_run(engine_stub, tmp_path):
    start, _, _ = engine_stub
    with FakeGateway(PAPER, later_accounts="") as gateway:
        assert start(gateway) == 1
    assert not (tmp_path / "evidence").exists()


def test_no_evidence_when_jts_stops_saying_paper_during_the_run(engine_stub, paper_state, tmp_path):
    start, _, during = engine_stub
    jts, _, _ = paper_state
    during.append(lambda: jts.write_text("[Logon]\ntradingMode=l\n", encoding="utf-8"))
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 1
    assert not (tmp_path / "evidence").exists()


def test_no_evidence_when_the_gateway_opens_another_port_during_the_run(
    engine_stub, paper_state, tmp_path
):
    start, _, during = engine_stub
    _, extra_ports, _ = paper_state
    during.append(lambda: extra_ports.add(5000))
    with FakeGateway(PAPER) as gateway:
        assert start(gateway) == 1
    assert not (tmp_path / "evidence").exists()


def test_no_evidence_when_a_contract_appears_during_the_run(engine_stub, monkeypatch, tmp_path):
    start, _, during = engine_stub
    holder: dict = {}

    def add_contract() -> None:
        allowlist(tmp_path, monkeypatch, holder["gateway"], (PAPER,))

    during.append(add_contract)
    with FakeGateway(PAPER) as gateway:
        holder["gateway"] = gateway
        assert start(gateway) == 1
    assert not (tmp_path / "evidence").exists()
