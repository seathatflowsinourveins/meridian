"""
Sandbox lane, milestone M2: the engine's sandbox execution client (a simulated venue inside
the engine) fed by Interactive Brokers market data, running upstream's ExecTester strategy.
No broker: no order can reach IBKR.

    uv run python -m meridian.sandbox_lane run     # owner only, attended; about 90 seconds

The IB Gateway, logged in to Paper Trading, supplies market data and nothing else. Order of
events in a run:
  1. the IBKR lane's paper checks (``meridian.ibkr_paper.gate``): the Gateway is a Paper
     Trading login, listens on port 4002 only, and reports one account of the paper form;
     the lane says how that port is bound, as the IBKR lane does, and unless it is loopback
     only asks the owner to check the Gateway's own localhost-only box;
  2. a person at a terminal types the confirmation word, and every check runs again;
  3. the node is built with one data client (IB) and one execution client (the sandbox) and
     runs for a minute; the engine's own output goes to a local log in ``runs/``;
  4. every check runs again after the run;
  5. the run record goes to ``evidence/`` on a pass and to ``runs/`` on a failure.

A run passes when the trader started, the instrument came from IB, quotes arrived, the
strategy's orders went to the simulated venue and nowhere else, and nothing was left open.

This module is own design and uses only the standard library, the boundary checks and the
IBKR lane's gate. The engine is in ``meridian.sandbox_node``, imported only after the gate
has passed, so a refused start never loads it.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian import boundary, ib_probe, ibkr_paper

MODES = ("run",)
RECORD_SCHEMA = ibkr_paper.RECORD_SCHEMA
CONFIRM_WORD = boundary.CONFIRM_WORD
SANDBOX_CLIENT = "SANDBOX"  # the only execution client the node has
SANDBOX_ACCOUNT = "XNAS-SANDBOX-001"  # the simulated account it books orders on
REFUSALS = ("OrderDenied", "OrderRejected")
TERMINAL = ("FILLED", "CANCELED", "EXPIRED")  # denied and rejected fail on their own


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _at_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def owner_confirms() -> bool:
    """A person at a terminal. A pipe or a tool call has no terminal."""
    if not _at_terminal():
        return False
    answer = input(
        "This runs the sandbox lane: market data from the PAPER Gateway, orders to a venue\n"
        "simulated inside the engine, none to IBKR.\n"
        f"Type {CONFIRM_WORD} to go on: "
    )
    return answer.strip() == CONFIRM_WORD


class SandboxRecord:
    """What happened in one run, as normalised fields only (never raw broker text)."""

    def __init__(
        self, gateway_port: int, allowlist_present: bool = False, gateway_bind: str = ""
    ) -> None:
        self.data: dict[str, Any] = {
            "schema": RECORD_SCHEMA,
            "milestone": "M2",
            "lane": "sandbox",
            "mode": "run",
            "run_started_utc": _utc_now(),
            "engine": {},
            # How the Gateway's port is bound ("all interfaces" is its normal bind), never the
            # address itself: the same field as in the IBKR lane's record.
            "gateway": {"port": gateway_port, "bind": gateway_bind, "use": "market data only"},
            "boundary": {
                "paper_checks_passed_before_run": True,
                "paper_checks_passed_after_run": None,
                "allowlist_contract_present": allowlist_present,
            },
            "node": None,
            "strategy": None,
            "trader_started": False,
            "market_data": {"instrument_loaded": False, "quotes_received": 0},
            "orders": [],
            "events": [],
            "at_stop": None,
            "engine_error": False,
        }
        # Free text from the engine. Written to runs/ only, never to evidence/.
        self.local: dict[str, Any] = {"reasons": []}

    def engine_error(self, text: str) -> None:
        self.data["engine_error"] = True
        self.local["engine_error"] = text

    def paper_checks_after_run(self, passed: bool) -> None:
        self.data["boundary"]["paper_checks_passed_after_run"] = passed

    def problems(self) -> list[str]:
        d = self.data
        found: list[str] = []
        if d["boundary"]["paper_checks_passed_after_run"] is not True:
            found.append("after the run the paper checks did not pass again for the same account")
        if d["engine_error"]:
            found.append("the node stopped with an error")
        node = d["node"] or {}
        if node.get("registered_execution_clients") != [SANDBOX_CLIENT]:
            found.append("the engine did not register the sandbox, and only it, for execution")
        if not d["trader_started"]:
            found.append("the trader never started " + ibkr_paper.GATEWAY_HINT)
        if not d["market_data"]["instrument_loaded"]:
            found.append("the instrument never arrived from IB")
        if not d["market_data"]["quotes_received"]:
            found.append("no quote arrived from IB")
        orders = d["orders"]
        if not orders:
            found.append("the strategy placed no order")
        if any(o.get("execution_client") != SANDBOX_CLIENT for o in orders):
            found.append("an order went to an execution client other than the sandbox")
        if any(o.get("account_id") != SANDBOX_ACCOUNT for o in orders):
            found.append("an order was booked on an account other than the simulated one")
        if any(e["type"] in REFUSALS for e in d["events"]):
            found.append("an order was denied or rejected")
        if any(o.get("status") not in TERMINAL for o in orders):
            found.append("an order did not reach a terminal state")
        if orders and "OrderAccepted" not in {e["type"] for e in d["events"]}:
            found.append("the simulated venue accepted no order")
        stop = d["at_stop"]
        if stop is None:
            found.append("no state was captured at stop")
        elif stop.get("open_orders") or stop.get("open_positions"):
            found.append("an order or a position was still open at stop")
        return found

    def write(self, forbidden: list[str], root: Path | None = None) -> tuple[bool, Path]:
        """Write the full record to runs/ and, on a pass, the scrubbed one to evidence/."""
        root = boundary.REPO_ROOT if root is None else root
        problems = self.problems()
        self.data["result"] = "fail" if problems else "pass"
        self.data["problems"] = problems
        self.data["run_ended_utc"] = _utc_now()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"M2-sandbox-{stamp}-run.json"

        local_path = root / "runs" / name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(
            json.dumps({**self.data, "local": self.local}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if problems:
            return False, local_path

        text = ibkr_paper.scrubbed_json(self.data, forbidden)
        evidence_path = root / "evidence" / name
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(text, encoding="utf-8")
        return True, evidence_path


def _run_node(bounds: boundary.IbkrBoundary, account: str) -> int:
    from meridian import sandbox_node  # the engine is loaded only after the gate has passed

    record = SandboxRecord(
        bounds.port, bounds.paper_accounts_sha256 is not None, bounds.gateway_bind
    )
    sandbox_node.run(sandbox_node.ib_data_client(bounds.host, bounds.port), record)

    # Every check again now that the run is over: still a paper login, the same account,
    # and the same contract (or still none)?
    try:
        bounds_after, account_after = ibkr_paper.gate()
        record.paper_checks_after_run(account_after == account and bounds_after == bounds)
    except boundary.BoundaryError, ib_probe.ProbeError:
        record.paper_checks_after_run(False)

    passed, path = record.write([account, boundary.account_hash(account)])
    shown = path.relative_to(boundary.REPO_ROOT)
    if passed:
        print(f"PASS: scrubbed run record written to {shown}")
        return 0
    print("FAIL:", file=sys.stderr)
    for problem in record.data["problems"]:
        print(f"  - {problem}", file=sys.stderr)
    print(f"Full local record (not for commit): {shown}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meridian.sandbox_lane",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode", choices=MODES)
    parser.parse_args(argv)

    try:
        bounds, account = ibkr_paper.gate()
    except (boundary.BoundaryError, ib_probe.ProbeError) as e:
        print(f"REFUSED TO START: {e}", file=sys.stderr)
        return 2
    print(
        "Paper checks passed: the Gateway's jts.ini says Paper Trading, the Gateway listens "
        f"only on port {bounds.port}, and it reports one account of the paper form."
    )
    print(ibkr_paper.bind_note(bounds.gateway_bind))
    if not owner_confirms():
        print(
            "REFUSED TO START: the sandbox lane needs the owner at a terminal, typing "
            f"{CONFIRM_WORD} to confirm.",
            file=sys.stderr,
        )
        return 2
    # The prompt can wait for any length of time: check everything again, and refuse unless
    # nothing changed (the same Gateway process and socket, login mode, account and contract).
    try:
        bounds_now, account_now = ibkr_paper.gate()
    except (boundary.BoundaryError, ib_probe.ProbeError) as e:
        print(f"REFUSED TO START: after the confirmation, {e}", file=sys.stderr)
        return 2
    if (bounds_now, account_now) != (bounds, account):
        print(
            "REFUSED TO START: the Gateway changed while the confirmation was pending.",
            file=sys.stderr,
        )
        return 2
    return _run_node(bounds, account)


if __name__ == "__main__":
    raise SystemExit(main())
