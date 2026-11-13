"""
The sandbox lane cannot send an order to IBKR: its node has one data client and the engine's
sandbox as its only execution client. The build fails if an Interactive Brokers execution
client, any other way to add an execution client, or a way to the IBKR lane's own run appears
in the lane's code, or if the node the lane builds has anything but the sandbox for execution.

It also runs, offline, on a fake data feed: the strategy's orders reach the simulated venue
and only it, nothing is left open at stop, only the lane's own lines reach the terminal, and a
Ctrl-C shortly before the stop fails the run.
The engine supports one node per process and another test builds a real IBKR node, so the real
sandbox node runs in a subprocess here: started only once the structure checks pass, and in an
empty network namespace where the machine allows one.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from meridian import boundary, ib_probe, sandbox_lane

REPO_ROOT = Path(__file__).resolve().parent.parent
# Every module of the lane, so that a new one is read without being listed here.
LANE_FILES = sorted(
    path.relative_to(REPO_ROOT).as_posix() for path in (REPO_ROOT / "meridian").glob("sandbox_*.py")
)
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
    # The execution engine publishes a command for an external client on the message bus
    # instead of sending it to an execution client; a message-bus backing can carry it out.
    "external_clients",
    "LiveExecutionEngineConfig",
    "with_exec_engine_config",
    "MessageBusConfig",
    "with_msgbus_config",
    "with_external_msgbus_factory",
}
# The only builder calls the lane makes; any other fails the structure test.
BUILDER_CALLS = {
    "with_timeout_connection",
    "with_timeout_reconciliation",
    "with_timeout_portfolio",
    "with_timeout_disconnection_secs",
    "with_delay_post_stop_secs",
    "with_reconciliation",
    "add_data_client",
    "add_simulated_exec_client",
    "build",
}
# What the lane may use from the IBKR lane's gate module, which imports no engine, and the
# only meridian modules it may import. The module comes in only as ``from meridian import
# ibkr_paper``, under that name, and is used only to read ``ibkr_paper.<one of these>``; or
# these names are imported from it. Among the rest are the IBKR lane's own run (``_run_node``:
# IB's execution client and an order on the paper account) and its entry point (``main``).
FROM_IBKR_PAPER = {"gate", "scrubbed_json", "bind_note", "RECORD_SCHEMA", "GATEWAY_HINT"}
MERIDIAN_MODULES = {"boundary", "ib_probe", "ibkr_paper", "sandbox_lane", "sandbox_node"}
# The only top-level modules a lane file imports; any other import fails the build until it is
# added here.
LANE_IMPORTS = {
    "__future__",
    "_common",  # upstream's IB helper, vendored and unmodified
    "argparse",
    "collections",
    "contextlib",
    "datetime",
    "decimal",
    "gc",
    "json",
    "meridian",
    "nautilus_trader",
    "os",
    "pathlib",
    "re",
    "sys",
    "threading",
    "time",
    "traceback",
    "typing",
}
# Ways around a name check, flagged wherever the lane's code names them:
# builtins that run a string as code, read a namespace, or import and call what a string names
# (breakpoint, through PYTHONBREAKPOINT), as names only (re.compile is the lane's own);
DYNAMIC_BUILTINS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "breakpoint",
}
# a module or attribute found from a string at run time (importlib's import, the engine's
# import by path in nautilus_trader.live.config and its plugin loader, sys.modules, the import
# system's finders, sys.breakpointhook, typing's forward references, which evaluate a string
# in a named module or the module that owns them), the namespace behind a frame, the
# collector's object lists, and asyncio's and concurrent.futures' ways to start another
# process;
RUN_TIME_LOOKUPS = {
    "import_module",
    "resolve_path",
    "add_plugin",
    "modules",
    "meta_path",
    "path_hooks",
    "path_importer_cache",
    "breakpointhook",
    "ForwardRef",
    "evaluate",
    "evaluate_forward_ref",
    "get_type_hints",
    "get_annotations",
    "_eval_type",
    "_type_check",
    "_type_convert",
    "_getframe",
    "f_globals",
    "f_locals",
    "f_builtins",
    "get_objects",
    "get_referrers",
    "get_referents",
    "create_subprocess_exec",
    "create_subprocess_shell",
    "ProcessPoolExecutor",
}
# os's ways to start another program, on whatever object or under whatever name they are
# reached (``_common.os.system``);
OS_PROCESS = {
    n for n in dir(os) if re.fullmatch(r"system|popen|(exec|spawn|posix_spawn|fork)\w*", n)
} | {"startfile"}  # Windows only
# modules that import, unpickle, evaluate or start code by other routes, a socket of the lane's
# own, and IB's client libraries (also when another module hands them over: ``from _common
# import subprocess``);
FORBIDDEN_MODULES = {
    "importlib",
    "annotationlib",
    "builtins",
    "runpy",
    "pkgutil",
    "pydoc",
    "inspect",
    "pickle",
    "marshal",
    "ctypes",
    "subprocess",
    "multiprocessing",
    "pty",
    "posix",
    "socket",
    "ibapi",
    "ib_async",
    "ib_insync",
}
# and any dunder name but these (``__globals__``, ``__dict__``, ``__builtins__``, ``__spec__``
# and the rest lead from an allowed object to the namespace behind it).
DUNDERS_ALLOWED = {"__name__", "__doc__", "__init__", "__version__"}
LOOKUP_NAMES = EXECUTION_CLIENT_NAMES | RUN_TIME_LOOKUPS | OS_PROCESS | FORBIDDEN_MODULES
# ibkr_paper in a string, other than as ibkr_paper.<allowed name> (a module path for
# subprocess, runpy or a resolver, or code for ``python -c``).
IBKR_PAPER_TEXT = re.compile(r"ibkr_paper(?![.:](?:" + "|".join(sorted(FROM_IBKR_PAPER)) + r")\b)")
GETATTR_FAMILY = {"getattr", "setattr", "delattr", "hasattr"}
IB_VARIABLES = ("IB_V2_", "IB_PYO3_")
FAKE = "DUFAKE0001"


def execution_client_hits(source: str) -> list[str]:
    """Every use of a name that could add an execution client or reach the IBKR lane's run,
    and every way around such a check that the lane's code spells out, as name@line."""
    tree = ast.parse(source)
    # The name ibkr_paper is allowed only where it is read as ibkr_paper.<allowed name>, and
    # getattr and its family only where they are called with the name as a string constant:
    # getattr(x, "name") is x.name, and with a name computed at run time nothing can tell.
    reads = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ibkr_paper"
        and node.attr in FROM_IBKR_PAPER
        and isinstance(node.ctx, ast.Load)
    }
    named_calls = {
        id(node.func): named
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (named := _constant_name(node))
    }
    hits = []
    for node in ast.walk(tree):
        found: list[str] = []
        if isinstance(node, ast.Name):
            if node.id in LOOKUP_NAMES | DYNAMIC_BUILTINS or _is_dunder(node.id):
                found = [node.id]
            if node.id == "ibkr_paper" and id(node) not in reads:
                found.append("ibkr_paper, not as ibkr_paper.<allowed name>")
            if node.id in GETATTR_FAMILY:
                if (named := named_calls.get(id(node))) is None:
                    found.append(f"{node.id}, not with a constant name")
                else:
                    found += _attribute_hits(*named, node.id in ("getattr", "hasattr"))
        elif isinstance(node, ast.Attribute):
            found = _attribute_hits(node.attr, node.value, isinstance(node.ctx, ast.Load))
        elif isinstance(node, ast.MatchClass):  # case object(attr=x) reads the subject's attr
            found = [h for a in node.kwd_attrs for h in _attribute_hits(a, node.cls, True)]
        elif isinstance(node, ast.alias):
            parts = {node.name.split(".")[0], node.name.rsplit(".", 1)[-1], node.asname}
            found = [p for p in parts if p in LOOKUP_NAMES]
        elif isinstance(node, ast.keyword) and node.arg in EXECUTION_CLIENT_NAMES:
            found = [node.arg]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found = [w for w in EXECUTION_CLIENT_NAMES if w in node.value]
            found += [f"'{m.group()}' in a string" for m in IBKR_PAPER_TEXT.finditer(node.value)]
        if isinstance(node, ast.Import | ast.ImportFrom):
            found += _import_hits(node)
        found += [
            n for n in _names(node) if n.startswith("Importable") or n.endswith("from_config")
        ]
        hits += [f"{n}@{getattr(node, 'lineno', '?')}" for n in found]
    return hits


def _constant_name(call: ast.Call) -> tuple[str, ast.expr] | None:
    """For ``getattr(x, "name")`` and its family, ``("name", x)``."""
    if isinstance(call.func, ast.Name) and call.func.id in GETATTR_FAMILY and len(call.args) > 1:
        target, name = call.args[0], call.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            return name.value, target
    return None


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and name not in DUNDERS_ALLOWED


def _attribute_hits(attr: str, value: ast.expr, load: bool) -> list[str]:
    """What is wrong with reading (or, without ``load``, setting) ``value.attr``."""
    found = [attr] if attr in LOOKUP_NAMES or _is_dunder(attr) else []
    if attr == "ibkr_paper":  # reached through a package or another module
        found.append("ibkr_paper as an attribute")
    if (
        isinstance(value, ast.Name)
        and value.id == "ibkr_paper"
        and (attr not in FROM_IBKR_PAPER or not load)
    ):
        found.append(f"ibkr_paper.{attr}")
    return found


def _import_hits(node: ast.Import | ast.ImportFrom) -> list[str]:
    """What an import statement brings in that the lane may not have."""
    found: list[str] = []
    if isinstance(node, ast.Import):
        modules = [a.name for a in node.names]
        # Meridian modules come in by from-imports only, which is what this check reads.
        found += [f"import {m}" for m in modules if m.split(".")[0] == "meridian"]
    else:
        module, names = node.module or "", [a.name for a in node.names]
        modules = [module]
        if node.level:
            found.append(f"relative import from {'.' * node.level}{module}")
        if "*" in names:  # binds names this check cannot see
            found.append(f"from {module} import *")
        if module == "meridian":
            found += [f"meridian.{n}" for n in names if n not in MERIDIAN_MODULES]
        elif module.startswith("meridian."):
            if (sub := module.split(".")[1]) not in MERIDIAN_MODULES:
                found.append(module)
            elif sub == "ibkr_paper":
                found += [f"ibkr_paper.{n}" for n in names if n not in FROM_IBKR_PAPER]
    for m in modules:
        top = m.split(".")[0]
        if top in FORBIDDEN_MODULES:
            found.append(m)
        elif top and top not in LANE_IMPORTS:
            found.append(f"{m}, not a module the lane imports")
    for a in node.names:
        # ibkr_paper comes in as ``from meridian import ibkr_paper`` and under no other name.
        if "ibkr_paper" in (a.name.rsplit(".", 1)[-1], a.asname) and not (
            isinstance(node, ast.ImportFrom)
            and (node.level, node.module, a.name) == (0, "meridian", "ibkr_paper")
            and a.asname in (None, "ibkr_paper")
        ):
            found.append(f"ibkr_paper imported as {a.asname or a.name}")
    return found


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
    assert {"meridian/sandbox_lane.py", "meridian/sandbox_node.py"} <= set(LANE_FILES)
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
        "builder.with_exec_engine_config(LiveExecutionEngineConfig(external_clients=[cid]))",
        "builder.with_msgbus_config(MessageBusConfig())",
        "builder.with_external_msgbus_factory(factory)",
    ],
)
def test_the_source_check_catches_an_added_execution_client(planted):
    assert execution_client_hits(planted)


@pytest.mark.parametrize(
    "planted",
    [
        # The IBKR lane's own run and its entry point, imported by name or with the module
        # under another name.
        "from meridian.ibkr_paper import _run_node\n_run_node(bounds, account)",
        "from meridian.ibkr_paper import _run_node as ibkr_lane_run\nOTHER_RUN = ibkr_lane_run",
        "from meridian.ibkr_paper import main as other_main",
        "from meridian.ibkr_paper import *",
        "import meridian.ibkr_paper as p\np._run_node(bounds, account)",
        "import meridian.ibkr_paper\nmeridian.ibkr_paper._run_node(bounds, account)",
        "import meridian\nlane = meridian.ibkr_paper",
        "from meridian import ibkr_paper as p\np._run_node(b, a)",
        "from meridian import *",
        "from meridian.sandbox_lane import ibkr_paper as p",
        "from . import ibkr_paper as p",
        "from .ibkr_paper import _run_node",
        # ibkr_paper other than read as ibkr_paper.<allowed name>.
        "lane = ibkr_paper\nlane._run_node(b, a)",
        "getattr(ibkr_paper, '_run_node')(b, a)",
        "vars(ibkr_paper)['_run_node'](b, a)",
        "ibkr_paper.gate = lambda: (bounds, account)",
        "sandbox_lane.ibkr_paper._run_node(b, a)",
        "ibkr_paper.gate.__globals__['_run_node'](b, a)",
        "globals()['ibkr_paper']",
        "match sandbox_lane:\n    case object(ibkr_paper=lane):\n        lane._run_node(b, a)",
        # A module or an attribute found from a string at run time, or behind an object.
        "sys.modules['meridian.ibkr_paper']",
        "from sys import modules",
        "getattr(sys, 'modules')",
        "getattr(sys, name)",
        "list(map(getattr, [sandbox_lane], [name]))",
        "match sys:\n    case object(modules=found):\n        pass",
        "typing.ForwardRef(name, module=path).evaluate()",
        "typing.get_args(typing.List[name])[0].evaluate(owner=sandbox_lane)",
        "typing._eval_type(typing._type_check(name, '', module=path), None, None)",
        "typing.evaluate_forward_ref(ref)",
        "from typing import get_type_hints",
        "os.environ['PYTHONBREAKPOINT'] = path\nbreakpoint(bounds, account)",
        "sys.breakpointhook(bounds, account)",
        "node.add_plugin(path, 'Plugin')",
        "__import__('meridian.ibkr_paper')",
        "builtins.__import__(name)",
        "__builtins__['__import__'](name)",
        "from importlib import import_module",
        "config.import_module(name)",
        "from nautilus_trader.live.config import resolve_path",
        "live_config.resolve_path(path)(bounds, account)",
        "node.add_strategy_from_config(config)",
        "from _common import add_strategy_from_config",
        "import operator",
        "sys.meta_path[0].find_spec(name, None)",
        "__spec__.loader",
        "().__class__.__base__.__subclasses__()",
        "sys._getframe().f_back",
        "frame.f_globals",
        "gc.get_referrers(boundary)",
        "path = 'meridian.ibkr_paper:_run_node'",
        # Another process running the IBKR lane.
        "subprocess.run(command)",
        "from _common import subprocess",
        "os.execv(sys.executable, args)",
        "os.system(command)",
        "_common.os.system(command)",
        "import os as o\no.posix_spawn(path, args, env)",
        "from os import posix_spawn",
        "asyncio.create_subprocess_exec(*command)",
        "concurrent.futures.ProcessPoolExecutor()",
        "command = [sys.executable, '-m', 'meridian.ibkr_paper', 'order']",
        # IB's API spoken over a socket of the lane's own.
        "ib_probe.socket.create_connection((host, port))",
        "from _common import socket",
    ],
)
def test_the_source_check_catches_a_way_to_the_ibkr_lanes_run(planted):
    assert execution_client_hits(planted)


@pytest.mark.parametrize(
    "allowed",
    [
        "from meridian import boundary, ib_probe, ibkr_paper\nbounds, account = ibkr_paper.gate()",
        "from meridian.ibkr_paper import bind_note, gate as paper_gate",
        "text = ibkr_paper.scrubbed_json(data, [account]) + ibkr_paper.GATEWAY_HINT",
        "'the paper checks (``meridian.ibkr_paper.gate``)'",
        "REGISTERED = re.compile(r'Registered')",
        "name, version = type(event).__name__, nautilus_trader.__version__",
        "reason = getattr(event, 'reason', None)",
        "os.dup2(log, 1)\nos.environ.pop('IB_V2_X', None)",
        "super().__init__()",
        "if __name__ == '__main__':\n    raise SystemExit(main())",
    ],
)
def test_the_source_check_passes_what_the_lane_uses(allowed):
    assert execution_client_hits(allowed) == []


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


def structure_problems() -> list[str]:
    """Build the lane's node with a recording builder (nothing real is built, nothing runs)
    and say what is wrong with it; empty when the sandbox is its only execution client."""
    from nautilus_trader.adapters import interactive_brokers as ib
    from nautilus_trader.adapters.sandbox import SandboxExecutionClientFactory
    from nautilus_trader.common import Environment

    from meridian import sandbox_node

    found = [
        f"source: {hit}"
        for name in LANE_FILES
        for hit in execution_client_hits((REPO_ROOT / name).read_text(encoding="utf-8"))
    ]
    started, builder = [], RecordingBuilder()

    def start(name, trader, environment):
        started.append(environment)
        return builder

    with pytest.MonkeyPatch.context() as mp:  # puts back the engine and the environment
        for name in [n for n in os.environ if n.startswith(IB_VARIABLES)]:
            mp.delenv(name)
        mp.setenv("IB_V2_MARKET_DATA_TYPE", "realtime")  # must not survive into the run
        mp.setattr(sandbox_node, "LiveNode", SimpleNamespace(builder=start))
        sandbox_node.build(sandbox_node.ib_data_client("127.0.0.1", 4002))
        if [n for n in os.environ if n.startswith(IB_VARIABLES)]:
            found.append("IB_V2_ variables survive into the run")

    if started != [Environment.SANDBOX]:
        found.append(f"environment {started}")
    if extra := {name for name, _ in builder.calls} - BUILDER_CALLS:
        found.append(f"builder calls outside the lane's own: {sorted(extra)}")
    if builder.named("with_reconciliation") != [(False,)]:
        found.append("reconciliation is not off")
    sims = builder.named("add_simulated_exec_client")
    if len(sims) != 1 or sims[0][0] != "SANDBOX":
        found.append(f"simulated execution clients: {[s[0] for s in sims]}")
    elif not isinstance(sims[0][1], SandboxExecutionClientFactory) or (
        str(sims[0][2].venue) != "XNAS"  # the instrument's venue: its orders route here
    ):
        found.append("the simulated execution client is not the sandbox on XNAS")
    datas = builder.named("add_data_client")
    if len(datas) != 1 or not isinstance(datas[0][1], ib.InteractiveBrokersDataClientFactory):
        found.append("the node does not have exactly one data client, IB's")
    else:
        config = datas[0][2]
        if (config.host, config.port, config.client_id) != ("127.0.0.1", 4002, 1521):
            found.append("the data client is not on the given endpoint with client id 1521")
        if config.max_reconnect_attempts != 0:
            found.append("the data client reconnects on its own after a drop")
        if config.market_data_type != ib.MarketDataType.DELAYED_FROZEN:
            found.append("the shell chose the market data type")
    strategies = builder.node.strategies
    if [s[0] for s in strategies] != ["ExecTester"] or strategies[0][1].client_id is not None:
        found.append("the strategy is not one ExecTester that routes its orders by venue")
    elif (str(strategies[0][1].instrument_id), str(strategies[0][1].order_qty)) != (
        "AAPL.XNAS",
        "1",
    ):
        found.append("the strategy does not trade 1 share of AAPL.XNAS")
    return found


def test_the_node_has_ib_data_and_the_sandbox_as_its_only_execution_client():
    assert structure_problems() == []


def test_the_structure_check_catches_another_execution_client(monkeypatch):
    from meridian import sandbox_node

    real = sandbox_node.build

    def build(data_client):
        built = real(data_client)
        live: Any = sandbox_node.LiveNode  # the recording builder, inside the check
        live.builder("X", None, None).add_exec_client("IB", None, None)
        return built

    monkeypatch.setattr(sandbox_node, "build", build)
    assert "builder calls outside the lane's own: ['add_exec_client']" in structure_problems()


def test_the_structure_check_catches_a_data_client_that_reconnects(monkeypatch):
    from nautilus_trader.adapters import interactive_brokers as ib

    real = ib.InteractiveBrokersDataClientConfig

    def reconnecting(**kw: Any) -> Any:
        kw["max_reconnect_attempts"] = 5
        return real(**kw)

    monkeypatch.setattr(ib, "InteractiveBrokersDataClientConfig", reconnecting)
    assert "the data client reconnects on its own after a drop" in structure_problems()


# --- offline run on the fake feed ----------------------------------------------------------

RUNNER = textwrap.dedent(
    """
    import json, os, signal, sys, threading
    from pathlib import Path
    tmp, repo, ctrl_c_after = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])
    sys.path[:0] = [str(repo), str(repo / "tests")]
    from meridian import boundary, sandbox_lane, sandbox_node
    from fake_market_data import fake_data_client
    boundary.REPO_ROOT = tmp
    record = sandbox_lane.SandboxRecord(4002)
    if ctrl_c_after:  # a Ctrl-C at the keyboard is a SIGINT to the process
        ctrl_c = threading.Timer(ctrl_c_after, os.kill, (os.getpid(), signal.SIGINT))
        ctrl_c.daemon = True
        ctrl_c.start()
    sandbox_node.run(fake_data_client(sandbox_node.DATA_CLIENT_NAME), record, seconds=6)
    record.paper_checks_after_run(True)
    passed, path = record.write([], root=tmp)
    out = {"passed": passed, "path": str(path), "data": record.data, "local": record.local}
    print(json.dumps(out))
    """
)


def network_fence() -> list[str]:
    """An empty network namespace where the machine allows one (this distro does; a CI runner
    may not), so the offline run could not reach a Gateway even if it tried."""
    if shutil.which("unshare") is None:
        return []
    probe = subprocess.run(["unshare", "-rn", "true"], capture_output=True, check=False)
    return ["unshare", "-rn"] if probe.returncode == 0 else []


def run_offline(tmp: Path, ctrl_c_after: float = 0) -> tuple[Any, dict]:
    """The lane's node on the fake feed for 6 seconds, in a process of its own; with
    ``ctrl_c_after``, interrupted that many seconds in."""
    # Never start a node whose structure is wrong: an IB execution client in it could connect
    # to a Gateway on this machine before the structure test had said anything.
    if problems := structure_problems():
        pytest.fail(f"not started, the lane's node is not sandbox-only: {problems}")
    proc = subprocess.run(
        [
            *network_fence(),
            *(sys.executable, "-c", RUNNER, str(tmp), str(REPO_ROOT), str(ctrl_c_after)),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return proc, json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sandbox")
    return *run_offline(tmp), tmp


def test_offline_the_strategys_orders_reach_the_sandbox_and_only_it(offline_run):
    _, out, tmp = offline_run
    data = out["data"]
    assert out["passed"], data["problems"]
    assert data["node"]["configured_execution_clients"] == ["SANDBOX"]
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
    assert data["engine_error"] is False
    assert Path(out["path"]).parent == tmp / "evidence"


def test_offline_only_the_lanes_lines_reach_the_terminal(offline_run):
    proc, _, tmp = offline_run
    assert proc.stderr == ""
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 2 and lines[0].startswith("Engine output goes to runs/M2-sandbox-")
    assert sorted(p.name for p in tmp.iterdir()) == ["evidence", "runs"]
    (log,) = (tmp / "runs").glob("M2-sandbox-*-engine.log")
    assert oct(log.stat().st_mode & 0o777) == "0o600"
    text = log.read_text(encoding="utf-8", errors="replace")
    assert text.count("Registered ExecutionClient-") == 1
    assert "Registered ExecutionClient-SANDBOX" in text


def test_offline_a_ctrl_c_shortly_before_the_stop_fails_the_run(tmp_path):
    # About 1.5 seconds before the lane's timer. The node takes 3 seconds to stop, so the timer
    # still fires while it does: only the time the node stopped the lane's actor shows that the
    # stop was early.
    proc, out = run_offline(tmp_path, ctrl_c_after=4.5)
    assert not out["passed"] and Path(out["path"]).parent == tmp_path / "runs"
    assert not (tmp_path / "evidence").exists()
    assert out["data"]["engine_error"] is True
    assert "the node stopped with an error" in out["data"]["problems"]
    assert out["local"]["engine_error"].startswith("interrupted")
    # Here too only the lane's lines reach the terminal: its first line and the error line.
    assert len(proc.stdout.strip().splitlines()) == 2
    (line,) = proc.stderr.strip().splitlines()
    assert line.startswith("The node stopped with an error (interrupted); details in runs/")


# --- the engine side, without an engine ---------------------------------------------------


class TalkativeNode:
    """Stands in for the engine's node. It writes the account the way the engine can (to file
    descriptors 1 and 2, and through Python), and whatever else it is given to say. It stops
    when its handle is told to, or at once if ``early``, and then stops the lane's actor,
    unless told not to.

    The engine's logger writes out what it still holds when the node is dropped, so this
    node writes its last words when it is dropped. Its handle and the actor hold it, and it
    holds the actor (a cycle), so it is dropped only when the lane has let go of all of them
    and collected."""

    environment = SimpleNamespace(name="SANDBOX")
    cache = SimpleNamespace(
        instrument=lambda iid: None, orders=list, orders_open=list, positions_open=list
    )

    def __init__(self, early: bool, says: str, stops_actor: bool, last_words: str) -> None:
        self.early, self.says, self.stops_actor = early, says, stops_actor
        self.last_words, self.stopped = last_words, threading.Event()
        self.counter = SimpleNamespace(started=True, quotes=0, stopped_at=None, node=self)

    def handle(self):
        return SimpleNamespace(stop=self.stop)

    def stop(self) -> None:
        self.stopped.set()
        time.sleep(0.2)  # the lane's timer thread is still in here when run() returns

    def run(self) -> None:
        os.write(1, f"AccountState(account_id=IB-{FAKE})\n".encode())
        os.write(2, f"native stderr {FAKE}\n".encode())
        print(f"python stdout {FAKE}")
        print(f"python stderr {FAKE}", file=sys.stderr)
        print(self.says)
        if not self.early:
            assert self.stopped.wait(10), "the lane's timer never stopped the node"
        if self.stops_actor:
            self.counter.stopped_at = time.monotonic()

    def __del__(self) -> None:
        os.write(1, f"{self.last_words} {FAKE}\n".encode())


@pytest.fixture
def talkative(tmp_path, monkeypatch):
    """sandbox_node.run() on a TalkativeNode instead of the engine, and that node's last
    words (its own: a node another test left behind would say something else)."""
    from meridian import sandbox_node

    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    last_words = f"last words of the node in {tmp_path.name}"

    def run(early: bool, says: str = "", stops_actor: bool = True) -> sandbox_lane.SandboxRecord:
        def build(data_client):
            node = TalkativeNode(early, says, stops_actor, last_words)
            return node, node.counter

        monkeypatch.setattr(sandbox_node, "build", build)
        record = sandbox_lane.SandboxRecord(4002)
        sandbox_node.run(("IB", None, None), record, seconds=1)
        return record

    return SimpleNamespace(run=run, last_words=last_words)


@pytest.mark.parametrize(
    ("early", "stops_actor"),
    [(False, True), (True, True), (False, False)],
    ids=["stopped-by-the-timer", "stopped-early", "actor-never-stopped"],
)
def test_the_engine_output_goes_to_the_log_and_an_early_stop_fails(
    tmp_path, talkative, capfd, early, stops_actor
):
    record = talkative.run(early, stops_actor=stops_actor)
    out, err = capfd.readouterr()
    assert FAKE not in out + err  # nothing the engine wrote reaches the terminal
    (log,) = (tmp_path / "runs").glob("*-engine.log")
    text = log.read_text(encoding="utf-8")
    for piece in ("AccountState", "native stderr", "python stdout", "python stderr"):
        assert piece in text
    # The node was dropped while its output still went to the log, not after the terminal
    # was put back.
    assert talkative.last_words in text
    fails = early or not stops_actor
    assert record.data["engine_error"] is fails
    assert ("stopped before its time" in record.local.get("engine_error", "")) is fails
    assert FAKE not in json.dumps(record.data)


def test_the_registered_clients_in_the_record_are_read_from_the_engines_log(talkative):
    record = talkative.run(
        early=True,
        says="Registered ExecutionClient-SANDBOX\nRegistered DataClient-IB\n"
        "Registered ExecutionClient-IB",
    )
    assert record.data["node"]["registered_execution_clients"] == ["SANDBOX", "IB"]
    assert record.data["node"]["registered_data_clients"] == ["IB"]
    assert (
        "the engine did not register the sandbox, and only it, for execution" in record.problems()
    )


class StubOrder:
    def __init__(self, cid: str, status: str, account: str | None) -> None:
        self.client_order_id, self.account_id = cid, account
        self.side = self.order_type = self.time_in_force = SimpleNamespace(name="X")
        self.status = SimpleNamespace(name=status)
        self.quantity = self.filled_qty = "1"

    def events(self) -> list:
        return []


def test_capture_records_what_the_cache_holds():
    from meridian import sandbox_node

    orders = [StubOrder("O-1", "CANCELED", "IB-X"), StubOrder("O-2", "SUBMITTED", None)]
    cache = SimpleNamespace(
        instrument=lambda iid: None,
        orders=lambda: orders,
        client_id=lambda cid: "IB" if cid == "O-1" else "SANDBOX",
        orders_open=lambda: [orders[1]],
        positions_open=lambda: [object()],
    )
    node: Any = SimpleNamespace(environment=SimpleNamespace(name="SANDBOX"), cache=cache)
    counter: Any = SimpleNamespace(started=False, quotes=0)
    record = sandbox_lane.SandboxRecord(4002)
    sandbox_node.capture(node, counter, ("IB", None, None), record)
    assert [(o["execution_client"], o["account_id"]) for o in record.data["orders"]] == [
        ("IB", "IB-X"),
        ("SANDBOX", None),
    ]
    assert record.data["trader_started"] is False
    assert record.data["at_stop"] == {"open_orders": 1, "open_positions": 1}
    registered = sandbox_node.registered_clients(
        "Registered ExecutionClient-SANDBOX\nRegistered DataClient-IB\n"
        "Registered ExecutionClient-IB\n"
    )
    assert registered == (["SANDBOX", "IB"], ["IB"])
    record.data["node"]["registered_execution_clients"] = registered[0]
    found = record.problems()
    assert any(problem.startswith("the trader never started") for problem in found)
    for expected in (
        "the engine did not register the sandbox, and only it, for execution",
        "the instrument never arrived from IB",
        "no quote arrived from IB",
        "an order went to an execution client other than the sandbox",
        "an order was booked on an account other than the simulated one",
        "an order did not reach a terminal state",
        "an order or a position was still open at stop",
    ):
        assert expected in found


# --- the gate before and after a run ------------------------------------------------------


def fake_bounds(**changes: Any) -> boundary.IbkrBoundary:
    """Bounds as the gate returns them, in the gate's own type. A changed field (a restarted
    Gateway, a contract) makes them unequal."""
    fields: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 4012,  # not 4002, so a test can see where the data client is sent
        "paper_accounts_sha256": None,
        "gateway_identity": frozenset({"pid 100", "listen 127.0.0.1:4012"}),
        "gateway_bind": "all interfaces",  # the Gateway's normal bind
    }
    return boundary.IbkrBoundary(**(fields | changes))


CHANGES = {
    "account": (fake_bounds(), "DUFAKE0002"),
    "restart": (
        fake_bounds(gateway_identity=frozenset({"pid 101", "listen 127.0.0.1:4012"})),
        FAKE,
    ),
    "contract": (fake_bounds(paper_accounts_sha256=frozenset({"ab" * 32})), FAKE),
}


@pytest.fixture
def gated(monkeypatch, tmp_path):
    """A gate that passes with a fake paper account, and a node that never runs."""
    bounds = fake_bounds()
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


@pytest.mark.parametrize(
    ("typed", "goes_on"), [("yes", False), ("paper", False), ("", False), ("PAPER", True)]
)
def test_the_lane_goes_on_only_when_the_owner_types_the_word(monkeypatch, gated, typed, goes_on):
    monkeypatch.setattr(sandbox_lane, "_at_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: typed)
    assert sandbox_lane.main(["run"]) == (0 if goes_on else 2)
    assert gated.runs == ([(gated.bounds, FAKE)] if goes_on else [])


@pytest.mark.parametrize(
    ("bind", "asks"),
    [("all interfaces", True), ("loopback", False)],
    ids=["every-interface", "loopback-only"],
)
def test_before_the_prompt_the_lane_says_how_the_port_is_bound(
    monkeypatch, gated, capsys, bind, asks
):
    gated.answers[0] = (fake_bounds(gateway_bind=bind), FAKE)
    printed_by_then = []

    def prompt(text):
        printed_by_then.append(capsys.readouterr().out)  # all the owner has read when asked
        return ""  # no confirmation: the lane stops here

    monkeypatch.setattr(sandbox_lane, "_at_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", prompt)
    assert sandbox_lane.main(["run"]) == 2
    assert gated.runs == []
    (out,) = printed_by_then  # the prompt was asked, once
    assert f"bound to {bind}" in out
    # The lane cannot read the Gateway's localhost-only box: it asks the owner to check it,
    # unless the port is bound to loopback only.
    assert ('"Allow connections from localhost only"' in out) is asks


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_gateway_change_during_the_prompt_refuses(monkeypatch, gated, change):
    def confirm():
        gated.answers[0] = CHANGES[change]  # what the gate sees by the time the owner answers
        return True

    monkeypatch.setattr(sandbox_lane, "owner_confirms", confirm)
    assert sandbox_lane.main(["run"]) == 2
    assert gated.runs == []


@pytest.fixture
def lane_run(monkeypatch, tmp_path):
    """_run_node with the engine replaced by a clean run, noting where it was sent."""
    from meridian import sandbox_node

    sent = []
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sandbox_node, "ib_data_client", lambda host, port: sent.append((host, port)) or ("IB",)
    )
    monkeypatch.setattr(sandbox_node, "run", lambda data_client, record: fill(record))
    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", lambda: (fake_bounds(), FAKE))
    return SimpleNamespace(sent=sent, tmp=tmp_path)


@pytest.mark.parametrize(
    "bind", ["all interfaces", "a specific address"], ids=["every-interface", "one-address"]
)
def test_a_clean_run_goes_to_the_gated_endpoint_and_writes_evidence(monkeypatch, lane_run, bind):
    bounds = fake_bounds(gateway_bind=bind)
    # The gate finds the same Gateway after the run.
    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", lambda: (bounds, FAKE))
    assert sandbox_lane._run_node(bounds, FAKE) == 0
    assert lane_run.sent == [(bounds.host, bounds.port)]
    (evidence,) = (lane_run.tmp / "evidence").glob("M2-sandbox-*-run.json")
    # How the port was bound, as the gate read it, is in the record, as in the IBKR lane's;
    # no address is.
    assert json.loads(evidence.read_text(encoding="utf-8"))["gateway"] == {
        "port": bounds.port,
        "bind": bind,
        "use": "market data only",
    }


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_gateway_change_during_the_run_fails_it(monkeypatch, lane_run, change):
    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", lambda: CHANGES[change])
    seen = []
    original = sandbox_lane.SandboxRecord.write

    def write(self, forbidden, root=None):
        written = original(self, forbidden, root)
        seen.extend(self.data["problems"])
        return written

    monkeypatch.setattr(sandbox_lane.SandboxRecord, "write", write)
    assert sandbox_lane._run_node(fake_bounds(), FAKE) == 1
    assert seen == ["after the run the paper checks did not pass again for the same account"]
    assert not (lane_run.tmp / "evidence").exists()


def test_a_probe_failure_after_the_run_fails_it(monkeypatch, lane_run):
    def probe_fails():
        raise ib_probe.ProbeError("no answer")

    monkeypatch.setattr(sandbox_lane.ibkr_paper, "gate", probe_fails)
    assert sandbox_lane._run_node(fake_bounds(), FAKE) == 1
    assert not (lane_run.tmp / "evidence").exists()


@pytest.mark.parametrize("echoed", [FAKE, boundary.account_hash(FAKE)], ids=["account", "hash"])
def test_the_record_is_scrubbed_of_the_gated_account(monkeypatch, lane_run, echoed):
    from meridian import sandbox_node

    def leaky(data_client, record):
        fill(record)
        record.data["orders"][0]["client_order_id"] = f"O-{echoed}"  # the engine echoed it

    monkeypatch.setattr(sandbox_node, "run", leaky)
    with pytest.raises(RuntimeError):
        sandbox_lane._run_node(fake_bounds(), FAKE)
    assert not (lane_run.tmp / "evidence").exists()


# --- the record ----------------------------------------------------------------------------


def fill(record: sandbox_lane.SandboxRecord) -> sandbox_lane.SandboxRecord:
    """A record as a clean run leaves it."""
    record.data.update(
        engine={"nautilus_trader": "2.0.0rc9"},
        node={
            "environment": "SANDBOX",
            "configured_data_clients": ["IB"],
            "configured_execution_clients": ["SANDBOX"],
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
    "no node captured": lambda r: r.data.update(node=None),
    "the engine registered no client": lambda r: r.data["node"].update(
        registered_execution_clients=[]
    ),
    "the engine registered another client": lambda r: r.data["node"].update(
        registered_execution_clients=["SANDBOX", "IB"]
    ),
    "trader never started": lambda r: r.data.update(trader_started=False),
    "no instrument": lambda r: r.data["market_data"].update(instrument_loaded=False),
    "no quote": lambda r: r.data["market_data"].update(quotes_received=0),
    "no order": lambda r: r.data.update(orders=[]),
    "an order claimed by IB": lambda r: r.data["orders"][0].update(execution_client="IB"),
    "an order on another account": lambda r: r.data["orders"][0].update(account_id="IB-X"),
    "an order not terminal": lambda r: r.data["orders"][0].update(status="SUBMITTED"),
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
