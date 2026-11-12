"""
IBKR paper lane, milestone M1: one DAY LIMIT order placed by the engine.

    uv run python -m meridian.ibkr_paper order      # reconcile, place one DAY LIMIT, stop
    uv run python -m meridian.ibkr_paper restart    # reconcile only; places nothing

This module is the gate and the run record. It is own design and uses only the standard
library. The engine is in ``meridian.ibkr_node``, which is imported only after the gate
has passed, so a refused start never loads it.

Order of events in every run (the checks are described in ``meridian.boundary``):
  1. read the optional ``risk/boundary.contract.json`` (owner-created, if at all);
  2. refuse unless the Gateway's jts.ini says Paper Trading and the Gateway listens only
     on the paper port;
  3. ask the Gateway which accounts it manages, and refuse unless that is exactly one
     account of the paper form (and on the allowlist, if there is one);
  4. in order mode, refuse unless a person at a terminal types the confirmation word, then
     run every check again and refuse if anything changed while the prompt waited;
  5. only then build and run the node, with the account the Gateway reported; the engine's
     own output goes to a local log in ``runs/``, not to the terminal;
  6. run every check again after the run, and write no evidence if anything changed.

A run passes only on the path M1 uses: the order is accepted, then cancelled without a
fill. A fill is reported as a failure, because this lane has no second order to close it.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian import boundary, ib_probe

MODES = ("order", "restart")
# Client id for the account probe. Distinct from the node's data and execution clients.
PROBE_CLIENT_ID = 1599
RECORD_SCHEMA = "meridian.run-record/1"
CONFIRM_WORD = boundary.CONFIRM_WORD
GATEWAY_HINT = (
    "(check that the Gateway is running and logged in to Paper Trading, that its API "
    "socket port is 4002, and that Read-Only API is unticked in Configure > Settings > API)"
)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ns_to_utc(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def gate(contract_path: Path | None = None) -> tuple[boundary.IbkrBoundary, str]:
    """Return the boundary and the one allowed account, or raise. Builds no engine."""
    bounds = boundary.local_paper_checks(contract_path)  # before any connection
    reported = ib_probe.managed_accounts(bounds.host, bounds.port, PROBE_CLIENT_ID)
    return bounds, boundary.allowed_account(reported, bounds)


def _at_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def owner_confirms() -> bool:
    """Order mode needs a person at a terminal. A pipe or a tool call has no terminal."""
    if not _at_terminal():
        return False
    answer = input(
        "This places ONE DAY LIMIT BUY of 1 share on the PAPER account, then cancels it.\n"
        f"Type {CONFIRM_WORD} to go on: "
    )
    return answer.strip() == CONFIRM_WORD


def scrubbed_json(data: dict[str, Any], forbidden: list[str]) -> str:
    """Serialise a record for ``evidence/``; refuse if it contains a forbidden string."""
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    lowered = text.lower()
    for value in forbidden:
        if value and value.lower() in lowered:
            raise RuntimeError("the run record contains an account identifier; not written")
    return text


class RunRecord:
    """What happened in one run, as normalised fields only (never raw broker text)."""

    def __init__(self, mode: str, gateway_port: int, allowlist_present: bool = False) -> None:
        self.data: dict[str, Any] = {
            "schema": RECORD_SCHEMA,
            "milestone": "M1",
            "lane": "ibkr-paper",
            "mode": mode,
            "run_started_utc": _utc_now(),
            "engine": {},
            "gateway": {"port": gateway_port},
            # Observed, not assumed: every paper check before the run and again after it.
            "boundary": {
                "paper_checks_passed_before_run": True,
                "paper_checks_passed_after_run": None,
                "allowlist_contract_present": allowlist_present,
            },
            "startup_reconciliation": {"requested": True, "trader_started": False},
            "engine_error": False,
            "order": None,
            "events": [],
            "at_stop": None,
        }
        # Free text from the broker or the engine. Written to runs/ only, never to evidence/.
        self.local: dict[str, Any] = {"reasons": []}

    def trader_started(
        self,
        *,
        instrument_open_orders: int,
        instrument_open_positions: int,
        account_open_orders: int,
        account_open_positions: int,
    ) -> None:
        self.data["startup_reconciliation"].update(
            trader_started=True,
            instrument_open_orders_at_start=instrument_open_orders,
            instrument_open_positions_at_start=instrument_open_positions,
            account_open_orders_at_start=account_open_orders,
            account_open_positions_at_start=account_open_positions,
        )

    def order_built(self, **fields: str) -> None:
        self.data["order"] = fields

    def event(self, kind: str, ts_ns: int, **fields: Any) -> None:
        self.data["events"].append({"type": kind, "ts_event_utc": ns_to_utc(ts_ns), **fields})

    def reason(self, kind: str, text: str) -> None:
        self.local["reasons"].append({"type": kind, "reason": text})

    def at_stop(self, **fields: Any) -> None:
        self.data["at_stop"] = fields

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

        start = d["startup_reconciliation"]
        if not start["trader_started"]:
            found.append(
                "the trader never started: the connection or startup reconciliation failed "
                + GATEWAY_HINT
            )
        elif (
            start["instrument_open_orders_at_start"] or start["instrument_open_positions_at_start"]
        ):
            found.append(
                "the account already had an open order or position in the lane's instrument "
                "at start"
            )

        stop = d["at_stop"]
        if stop is None:
            found.append("no state was captured at stop")
        else:
            if stop.get("instrument_open_orders") != 0:
                found.append("an order in the lane's instrument was still open at stop")
            if stop.get("instrument_open_positions") != 0:
                found.append("the position in the lane's instrument was not flat at stop")

        if d["mode"] == "order":
            order = d["order"]
            kinds = [e["type"] for e in d["events"]]
            if order is None:
                found.append("no order was submitted")
            elif order.get("type") != "LIMIT" or order.get("time_in_force") != "DAY":
                found.append("the order was not a DAY LIMIT order")
            if order is not None and "OrderAccepted" not in kinds:
                found.append("the venue never accepted the order " + GATEWAY_HINT)
            status = None if stop is None else stop.get("order_status")
            if "OrderFilled" in kinds or status == "FILLED":
                found.append(
                    "the order filled: one share is open in the paper account and has to be "
                    "closed by hand"
                )
            elif order is not None and status != "CANCELED":
                found.append("the order did not reach a terminal state")
        return found

    def write(self, forbidden: list[str], root: Path | None = None) -> tuple[bool, Path]:
        """Write the full record to runs/ and, on a pass, the scrubbed one to evidence/."""
        root = boundary.REPO_ROOT if root is None else root
        problems = self.problems()
        self.data["result"] = "fail" if problems else "pass"
        self.data["problems"] = problems
        self.data["run_ended_utc"] = _utc_now()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"M1-ibkr-paper-{stamp}-{self.data['mode']}.json"

        local_path = root / "runs" / name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(
            json.dumps({**self.data, "local": self.local}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if problems:
            return False, local_path

        text = scrubbed_json(self.data, forbidden)
        evidence_path = root / "evidence" / name
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(text, encoding="utf-8")
        return True, evidence_path


def _run_node(mode: str, bounds: boundary.IbkrBoundary, account: str) -> int:
    from meridian import ibkr_node  # the engine is loaded only after the gate has passed

    record = RunRecord(mode, bounds.port, bounds.paper_accounts_sha256 is not None)
    ibkr_node.run(mode, bounds.host, bounds.port, account, record)

    # Every check again now that the run is over: still a paper login, the same account,
    # and the same contract (or still none)?
    try:
        bounds_after, account_after = gate()
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
        prog="meridian.ibkr_paper",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode", choices=MODES)
    args = parser.parse_args(argv)

    try:
        bounds, account = gate()
    except (boundary.BoundaryError, ib_probe.ProbeError) as e:
        print(f"REFUSED TO START: {e}", file=sys.stderr)
        return 2
    allowlisted = ", on the owner's allowlist" if bounds.paper_accounts_sha256 is not None else ""
    print(
        "Paper checks passed: the Gateway's jts.ini says Paper Trading, the Gateway listens "
        f"only on port {bounds.port}, and it reports one account of the paper form{allowlisted}."
    )
    try:
        contract = boundary.CONTRACT_PATH.relative_to(boundary.REPO_ROOT)
    except ValueError:  # a contract path outside the repository (tests use one)
        contract = boundary.CONTRACT_PATH
    if bounds.paper_accounts_sha256 is None:
        print(f"Allowlist: none (no file at {contract}).")
    else:
        print(f"Allowlist: {contract}.")

    if args.mode == "order":
        if not owner_confirms():
            print(
                "REFUSED TO START: order mode needs the owner at a terminal, typing "
                f"{CONFIRM_WORD} to confirm.",
                file=sys.stderr,
            )
            return 2
        # The prompt can wait for any length of time: check everything again, right before
        # the engine connects, and refuse unless nothing changed (the same Gateway process
        # and socket, login mode, account and contract).
        try:
            bounds_now, account_now = gate()
        except (boundary.BoundaryError, ib_probe.ProbeError) as e:
            print(f"REFUSED TO START: after the confirmation, {e}", file=sys.stderr)
            return 2
        if (bounds_now, account_now) != (bounds, account):
            print(
                "REFUSED TO START: the Gateway changed while the confirmation was pending.",
                file=sys.stderr,
            )
            return 2
    return _run_node(args.mode, bounds, account)


if __name__ == "__main__":
    raise SystemExit(main())
