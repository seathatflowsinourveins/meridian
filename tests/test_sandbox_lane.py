"""
The sandbox lane cannot send an order to IBKR: its node has one data client and the engine's
sandbox as its only execution client. The build fails if an Interactive Brokers execution
client, or any other way to add an execution client, appears in the lane's code.

It also runs, offline, on a fake data feed: the strategy's orders reach the simulated venue
and only it, and nothing is left open at stop. The engine supports one node per process and
another test builds a real IBKR node, so the real sandbox node runs in a subprocess here.
"""

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from meridian import boundary, ib_probe, sandbox_lane

REPO_ROOT = Path(__file__).resolve().parent.parent
LANE_FILES = ["meridian/sandbox_lane.py", "meridian/sandbox_node.py"]
# Names that build or add an execution client other than the sandbox. In the lane's code each
# fails the build as an identifier, an attribute, an import or a keyword argument, and inside a
# string too (``getattr(builder, "add_exec_client")``).
EXECUTION_CLIENT_NAMES = {
    "InteractiveBrokersExecutionClientFactory",
    "InteractiveBrokersExecutionClientConfig",
    "build_ib_live_node",  # upstream's helper: it adds IB's execution client given an account
    "ibkr_node",  # the IBKR lane's engine side, which builds IB's execution client
    "add_exec_client",
    "exec_factories",
    "exec_clients",
    "LiveNodeConfig",
    "LiveNodeBuilder",  # its from_config takes execution factories
    "LiveExecClientConfig",
    "from_config",
}
# Ways around a name check: dynamic code (as calls of the builtins), and IB's client libraries.
DYNAMIC_BUILTINS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_MODULES = {"importlib", "ibapi", "ib_async", "ib_insync"}
# What the lane may use from the IBKR lane's gate module, which imports no engine, and the
# only meridian modules it may import.
FROM_IBKR_PAPER = {"gate", "scrubbed_json", "RECORD_SCHEMA", "GATEWAY_HINT"}
MERIDIAN_MODULES = {"boundary", "ib_probe", "ibkr_paper", "sandbox_lane", "sandbox_node"}
FAKE = "DUFAKE0001"


def execution_client_hits(source: str) -> list[str]:
    """Every use of a name that could add an execution client, as name@line."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        found: list[str] = []
        if isinstance(node, ast.Name):
            found = [node.id] if node.id in EXECUTION_CLIENT_NAMES | DYNAMIC_BUILTINS else []
        elif isinstance(node, ast.Attribute):
            found = [node.attr] if node.attr in EXECUTION_CLIENT_NAMES else []
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "ibkr_paper"
                and node.attr not in FROM_IBKR_PAPER
            ):
                found.append(f"ibkr_paper.{node.attr}")
        elif isinstance(node, ast.alias):
            parts = {node.name.split(".")[0], node.name.rsplit(".", 1)[-1], node.asname}
            found = [p for p in parts if p in EXECUTION_CLIENT_NAMES | FORBIDDEN_MODULES]
        elif isinstance(node, ast.keyword) and node.arg in EXECUTION_CLIENT_NAMES:
            found = [node.arg]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found = [w for w in EXECUTION_CLIENT_NAMES if w in node.value]
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in FORBIDDEN_MODULES:
                found.append(module)
            if module == "meridian":
                found += [
                    f"meridian.{a.name}" for a in node.names if a.name not in MERIDIAN_MODULES
                ]
            elif module.startswith("meridian.") and module.split(".")[1] not in MERIDIAN_MODULES:
                found.append(module)
        found += [n for n in _names(node) if n.startswith("Importable")]
        hits += [f"{n}@{getattr(node, 'lineno', '?')}" for n in found]
    return hits


def _names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.alias):
        return [node.name.rsplit(".", 1)[-1]]
    return []


# --- structure ------------------------------------------------------------------------------


def test_no_lane_file_can_add_an_execution_client_other_than_the_sandbox():
    for name in LANE_FILES:
        source = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert execution_client_hits(source) == [], name


@pytest.mark.parametrize(
    "planted",
    [
        "builder.add_exec_client(None, ib.InteractiveBrokersExecutionClientFactory(), config)",
        "from _common import build_ib_live_node",
        "from nautilus_trader.adapters.interactive_brokers import "
        "InteractiveBrokersExecutionClientConfig",
        "node = LiveNode.build('x', config, exec_factories={'IB': factory})",
        "builder = LiveNodeBuilder.from_config('x', LiveNodeConfig())",
        "getattr(builder, 'add_exec_client')(None, factory, config)",
        "from meridian import ibkr_node",
        "from meridian.ibkr_node import build",
        "ibkr_paper._run_node(bounds, account)",
        "from meridian import paper_orders",
        "eval('builder.add_' + 'exec_client')",
        "import importlib",
        "from ibapi.client import EClient",
        "config = ImportableExecClientConfig(path='x')",
    ],
)
def test_the_source_check_catches_an_added_execution_client(planted):
    assert execution_client_hits(planted)


class RecordingBuilder:
    """Stands in for the engine's node builder and records every call the lane makes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.node = SimpleNamespace(
            actors=[], strategies=[], add_actor=None, add_builtin_strategy=None
        )
        self.node.add_actor = self.node.actors.append
        self.node.add_builtin_strategy = lambda name, config: self.node.strategies.append(
            (name, config)
        )

    def __getattr__(self, name: str):
        def method(*args, **kwargs):
            self.calls.append((name, args))
            return self.node if name == "build" else self

        return method

    def named(self, name: str) -> list[tuple]:
        return [args for called, args in self.calls if called == name]


def test_the_node_has_ib_data_and_the_sandbox_as_its_only_execution_client(monkeypatch):
    from nautilus_trader.adapters import interactive_brokers as ib
    from nautilus_trader.adapters.sandbox import SandboxExecutionClientFactory
    from nautilus_trader.common import Environment

    from meridian import sandbox_node

    started = []
    builder = RecordingBuilder()

    def start(name, trader, environment):
        started.append(environment)
        return builder

    monkeypatch.setattr(sandbox_node, "LiveNode", SimpleNamespace(builder=start))
    sandbox_node.build(sandbox_node.ib_data_client("127.0.0.1", 4002))

    assert started == [Environment.SANDBOX]
    called = {name for name, _ in builder.calls}
    assert called <= {"add_data_client", "add_simulated_exec_client", "build"} | {
        n for n in called if n.startswith("with_")
    }
    assert builder.named("add_exec_client") == []
    ((name, factory, config),) = builder.named("add_simulated_exec_client")
    assert name == "SANDBOX" and isinstance(factory, SandboxExecutionClientFactory)
    assert str(config.venue) == "XNAS"  # the instrument's venue: its orders route here
    ((data_name, data_factory, data_config),) = builder.named("add_data_client")
    assert data_name == "IB" and isinstance(data_factory, ib.InteractiveBrokersDataClientFactory)
    assert (data_config.host, data_config.port, data_config.client_id) == ("127.0.0.1", 4002, 1521)
    assert builder.named("with_reconciliation") == [(False,)]
    assert builder.named("with_risk_engine_config") == []  # the risk engine is not bypassed
    ((strategy, tester),) = builder.node.strategies
    assert strategy == "ExecTester" and tester.client_id is None  # its orders route by venue
    assert str(tester.instrument_id) == "AAPL.XNAS" and str(tester.order_qty) == "1"


# --- offline run on the fake feed ----------------------------------------------------------

RUNNER = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    tmp, repo = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path[:0] = [str(repo), str(repo / "tests")]
    from meridian import boundary, sandbox_lane, sandbox_node
    from fake_market_data import fake_data_client
    boundary.REPO_ROOT = tmp
    record = sandbox_lane.SandboxRecord(4002)
    sandbox_node.run(fake_data_client(sandbox_node.DATA_CLIENT_NAME), record, seconds=6)
    record.paper_checks_after_run(True)
    passed, path = record.write([], root=tmp)
    print(json.dumps({"passed": passed, "path": str(path), "data": record.data}))
    """
)


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sandbox")
    proc = subprocess.run(
        [sys.executable, "-c", RUNNER, str(tmp), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1]), tmp


def test_offline_the_strategys_orders_reach_the_sandbox_and_only_it(offline_run):
    out, tmp = offline_run
    data = out["data"]
    assert out["passed"], data["problems"]
    assert data["node"]["execution_clients"] == ["SANDBOX"]
    assert data["node"]["registered_execution_clients"] == ["SANDBOX"]  # from the engine's log
    assert data["node"]["registered_data_clients"] == ["IB"]
    assert data["orders"] and {o["execution_client"] for o in data["orders"]} == {"SANDBOX"}
    assert {o["account_id"] for o in data["orders"]} == {"XNAS-SANDBOX-001"}
    # Buy at market, rest a LIMIT buy, then on stop cancel it and sell the share.
    assert sorted((o["side"], o["type"], o["status"]) for o in data["orders"]) == [
        ("BUY", "LIMIT", "CANCELED"),
        ("BUY", "MARKET", "FILLED"),
        ("SELL", "MARKET", "FILLED"),
    ]
    kinds = {e["type"] for e in data["events"]}
    assert {"OrderSubmitted", "OrderAccepted", "OrderFilled", "OrderCanceled"} <= kinds
    assert "OrderDenied" not in kinds and "OrderRejected" not in kinds
    assert data["at_stop"] == {"open_orders": 0, "open_positions": 0}
    assert data["market_data"]["instrument_loaded"] and data["market_data"]["quotes_received"] > 0
    assert data["engine"]["nautilus_trader"] == "2.0.0rc9"
    assert Path(out["path"]).parent == tmp / "evidence"


def test_offline_the_engine_output_stays_in_the_local_log(offline_run):
    out, tmp = offline_run
    (log,) = (tmp / "runs").glob("M2-sandbox-*-engine.log")
    assert oct(log.stat().st_mode & 0o777) == "0o600"
    text = log.read_text(encoding="utf-8", errors="replace")
    assert text.count("Registered ExecutionClient-") == 1
    assert "Registered ExecutionClient-SANDBOX" in text


# --- the gate before and after a run ------------------------------------------------------


@pytest.fixture
def gated(monkeypatch, tmp_path):
    """A gate that passes with a fake paper account, and a node that never runs."""
    bounds: Any = SimpleNamespace(host="127.0.0.1", port=4002, paper_accounts_sha256=None)
    answers = [(bounds, FAKE)]
    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", lambda: answers[0])
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    runs = []
    monkeypatch.setattr(sandbox_lane, "_run_node", lambda b, a: runs.append((b, a)) or 0)
    return SimpleNamespace(bounds=bounds, answers=answers, runs=runs)


def test_a_refused_gate_starts_nothing(monkeypatch, gated):
    def refuse():
        raise boundary.BoundaryError("not a paper login")

    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", refuse)
    assert sandbox_lane.main(["run"]) == 2
    assert gated.runs == []


def test_without_a_terminal_the_lane_refuses(monkeypatch, gated):
    monkeypatch.setattr(sandbox_lane, "_at_terminal", lambda: False)  # a pipe or a tool call
    assert sandbox_lane.main(["run"]) == 2
    assert gated.runs == []


def test_the_owner_confirms_and_the_gate_runs_again(monkeypatch, gated):
    monkeypatch.setattr(sandbox_lane, "owner_confirms", lambda: True)
    assert sandbox_lane.main(["run"]) == 0
    assert gated.runs == [(gated.bounds, FAKE)]


def test_a_gateway_change_during_the_prompt_refuses(monkeypatch, gated):
    def confirm():
        gated.answers[0] = (gated.bounds, "DUFAKE0002")  # another account by the time it answers
        return True

    monkeypatch.setattr(sandbox_lane, "owner_confirms", confirm)
    assert sandbox_lane.main(["run"]) == 2
    assert gated.runs == []


def test_the_paper_checks_run_again_after_the_run(monkeypatch, tmp_path):
    from meridian import sandbox_node

    bounds: Any = SimpleNamespace(host="127.0.0.1", port=4002, paper_accounts_sha256=None)
    after = iter([(bounds, "DUFAKE0002")])  # the Gateway reports another account afterwards
    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", lambda: next(after))
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sandbox_node, "ib_data_client", lambda host, port: ("IB", None, None))
    monkeypatch.setattr(sandbox_node, "run", lambda data_client, record: fill(record))
    assert sandbox_lane._run_node(bounds, FAKE) == 1
    assert not (tmp_path / "evidence").exists()


def test_a_probe_failure_after_the_run_fails_it(monkeypatch, tmp_path):
    from meridian import sandbox_node

    def probe_fails():
        raise ib_probe.ProbeError("no answer")

    bounds: Any = SimpleNamespace(host="127.0.0.1", port=4002, paper_accounts_sha256=None)
    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", probe_fails)
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sandbox_node, "ib_data_client", lambda host, port: ("IB", None, None))
    monkeypatch.setattr(sandbox_node, "run", lambda data_client, record: fill(record))
    assert sandbox_lane._run_node(bounds, FAKE) == 1


# --- the record ----------------------------------------------------------------------------


def fill(record: sandbox_lane.SandboxRecord) -> sandbox_lane.SandboxRecord:
    """A record as a clean run leaves it."""
    record.data.update(
        engine={"nautilus_trader": "2.0.0rc9"},
        node={
            "environment": "SANDBOX",
            "data_clients": ["IB"],
            "execution_clients": ["SANDBOX"],
            "registered_execution_clients": ["SANDBOX"],
            "registered_data_clients": ["IB"],
        },
        trader_started=True,
        market_data={"instrument_loaded": True, "quotes_received": 20},
        orders=[
            {
                "client_order_id": "O-1",
                "status": "CANCELED",
                "execution_client": "SANDBOX",
                "account_id": "XNAS-SANDBOX-001",
            }
        ],
        events=[
            {"type": "OrderSubmitted", "client_order_id": "O-1", "ts_event_utc": "t"},
            {"type": "OrderAccepted", "client_order_id": "O-1", "ts_event_utc": "t"},
            {"type": "OrderCanceled", "client_order_id": "O-1", "ts_event_utc": "t"},
        ],
        at_stop={"open_orders": 0, "open_positions": 0},
    )
    return record


def clean() -> sandbox_lane.SandboxRecord:
    record = fill(sandbox_lane.SandboxRecord(4002))
    record.paper_checks_after_run(True)
    return record


def test_a_clean_run_passes_and_is_written_scrubbed(tmp_path):
    record = clean()
    record.local["reasons"].append({"type": "OrderCanceled", "reason": f"account {FAKE}"})
    passed, path = record.write([FAKE], root=tmp_path)
    assert passed and path.parent == tmp_path / "evidence"
    assert FAKE not in path.read_text(encoding="utf-8")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["lane"] == "sandbox" and written["milestone"] == "M2"
    assert written["schema"] == "meridian.run-record/1" and written["result"] == "pass"


def test_a_record_holding_the_account_is_not_written(tmp_path):
    record = clean()
    record.data["orders"][0]["client_order_id"] = f"X-{FAKE}"
    with pytest.raises(RuntimeError):
        record.write([FAKE], root=tmp_path)
    assert not (tmp_path / "evidence").exists()


FAILURES = {
    "paper checks failed after": lambda r: r.paper_checks_after_run(False),
    "no check after": lambda r: r.data["boundary"].update(paper_checks_passed_after_run=None),
    "engine error": lambda r: r.engine_error("RuntimeError: disconnected"),
    "another execution client": lambda r: r.data["node"].update(
        execution_clients=["SANDBOX", "IB"]
    ),
    "trader never started": lambda r: r.data.update(trader_started=False),
    "no instrument": lambda r: r.data["market_data"].update(instrument_loaded=False),
    "no quote": lambda r: r.data["market_data"].update(quotes_received=0),
    "no order": lambda r: r.data.update(orders=[]),
    "an order claimed by IB": lambda r: r.data["orders"][0].update(execution_client="IB"),
    "an order on another account": lambda r: r.data["orders"][0].update(account_id="IB-X"),
    "the engine registered another client": lambda r: r.data["node"].update(
        registered_execution_clients=["SANDBOX", "IB"]
    ),
    "a rejected order": lambda r: r.data["events"].append(
        {"type": "OrderRejected", "client_order_id": "O-2", "ts_event_utc": "t"}
    ),
    "a denied order": lambda r: r.data["events"].append(
        {"type": "OrderDenied", "client_order_id": "O-2", "ts_event_utc": "t"}
    ),
    "never accepted": lambda r: r.data.update(
        events=[e for e in r.data["events"] if e["type"] != "OrderAccepted"]
    ),
    "no state at stop": lambda r: r.data.update(at_stop=None),
    "order open at stop": lambda r: r.data["at_stop"].update(open_orders=1),
    "position open at stop": lambda r: r.data["at_stop"].update(open_positions=1),
}


@pytest.mark.parametrize("name", sorted(FAILURES))
def test_a_run_that_misses_a_condition_fails_and_writes_no_evidence(tmp_path, name):
    record = clean()
    FAILURES[name](record)
    passed, path = record.write([FAKE], root=tmp_path)
    assert not passed and path.parent == tmp_path / "runs"
    assert not (tmp_path / "evidence").exists()
