"""Owner-attended Alpaca paper lane: restart (read only) or one resting order.

Own design after meridian.ibkr_paper. Session-selected prices only: quote sizes are not carried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from meridian import boundary, ibkr_paper
from meridian.alpaca.commission import PAPER_US_EQUITY_COMMISSION
from meridian.alpaca.credentials import PaperKeys, load_paper_keys
from meridian.alpaca.pacing import load_controls

MODES = ("restart", "order")
INSTRUMENT = "AAPL.ALPACA"  # Same equity as the upstream IBKR stock example.
DEFAULT_SETTINGS = boundary.REPO_ROOT / "local/alpaca-lane.json"


class Refused(ValueError):
    """Only fixed, value-free messages leave the local gate."""


@dataclass(frozen=True)
class Settings:
    rows_path: str = field(repr=False)
    quote_max_age_ns: int = field(repr=False)


@dataclass(frozen=True)
class BudgetAuthority:
    fingerprint: str = field(repr=False)
    paper_defaults: int
    reviewed: int


@dataclass(frozen=True)
class Preflight:
    settings: Settings
    budget: BudgetAuthority
    keys: PaperKeys = field(repr=False)


def _private_path(path: Path) -> Path:
    path = path.resolve()
    root = boundary.REPO_ROOT.resolve()
    if path.is_relative_to(root) and not path.is_relative_to(root / "local"):
        raise Refused("local settings and rows must be outside the tree or under local/")
    return path


def load_settings(path: Path) -> Settings:
    result = None
    try:
        path = _private_path(path)
        row = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(row, dict) and set(row) == {"order_budget_rows_path", "quote_max_age_ns"}:
            rows, age = row["order_budget_rows_path"], row["quote_max_age_ns"]
            if isinstance(rows, str) and rows.strip() and type(age) is int and age > 0:
                rows_path = _private_path(path.parent / rows)
                result = Settings(str(rows_path), age)
    except OSError, ValueError, TypeError:
        pass
    if result is None:
        raise Refused("local settings unavailable or invalid")
    return result


def budget_authority(path: str) -> BudgetAuthority:
    """Use the production loader's scope counts, with an in-memory change fingerprint."""
    result = None
    try:
        before = Path(path).read_bytes()
        loaded = load_controls(path)
        after = Path(path).read_bytes()
        if before == after:
            result = BudgetAuthority(
                hashlib.sha256(after).hexdigest(),
                loaded.paper_default_rows,
                loaded.reviewed_rows,
            )
    except OSError, ValueError, TypeError, KeyError, ArithmeticError:
        pass
    if result is None:
        raise Refused("order budget rows unavailable or invalid")
    return result


def preflight(path: Path) -> Preflight:
    settings = load_settings(path)
    budget = budget_authority(settings.rows_path)
    keys = None
    with suppress(Exception):
        keys = load_paper_keys()
    if keys is None:
        raise Refused("paper credentials unavailable")
    return Preflight(settings, budget, keys)


class RunRecord(ibkr_paper.RunRecord):
    """Reuse the handbook writer and normalised counters, with Alpaca pass criteria."""

    def __init__(self, mode: str, state: Preflight) -> None:
        super().__init__(mode, 0)
        del self.data["gateway"], self.data["boundary"]
        self.data.update(
            milestone="M3",
            lane="alpaca-paper",
            instrument=INSTRUMENT,
            checks_unchanged_after_run=False,
            quote_age_limit_present=True,
            quote_sizes_carried=False,
            session="closed",
            feed=None,
            venue_working_seen=False,
            budget_rows={
                "paper_defaults": state.budget.paper_defaults,
                "reviewed": state.budget.reviewed,
            },
            commission_source=[
                {"url": s.url, "date_read": s.date_read.isoformat()}
                for s in PAPER_US_EQUITY_COMMISSION.sources
            ],
        )

    def problems(self) -> list[str]:
        d, found = self.data, []
        if not d["checks_unchanged_after_run"]:
            found.append("local checks changed or failed after the run")
        if d["engine_error"]:
            found.append("the node stopped with an error")
        if d["orders_refused"]:
            found.append("the lane refused an order")
        start, stop = d["startup_reconciliation"], d["at_stop"]
        if not start["trader_started"]:
            found.append("startup reconciliation did not complete")
        elif (
            start["instrument_open_orders_at_start"] or start["instrument_open_positions_at_start"]
        ):
            found.append("the lane instrument had an open order or position at start")
        if stop is None:
            found.append("no state was captured at stop")
        else:
            if any(
                stop.get(key) != 0
                for key in (
                    "instrument_open_orders",
                    "instrument_inflight_orders",
                    "instrument_open_positions",
                )
            ):
                found.append("the lane instrument was not flat with no working order at stop")
            if stop.get("execution_healthy") is not True:
                found.append("the execution view was incomplete at stop")
        kinds = [event["type"] for event in d["events"]]
        if d["mode"] == "restart":
            if d["order"] is not None or kinds:
                found.append("restart observed an order action")
        else:
            if d["order"] != {
                "type": "LIMIT",
                "time_in_force": "DAY",
                "side": "BUY",
                "quantity": "1",
            }:
                found.append("the run did not submit its one DAY LIMIT BUY of one share")
            if "OrderAccepted" not in kinds or not d["venue_working_seen"]:
                found.append("the venue did not show the order working in this session")
            if not stop or stop.get("order_status") != "CANCELED":
                found.append("the order did not end cancelled")
            if "OrderFilled" in kinds or (stop and stop.get("filled") is not False):
                found.append(
                    "the order filled; inspect the paper account and close any share by hand"
                )
        return found


def run_attended(mode: str, path: Path, state: Preflight) -> int:
    from meridian import alpaca_node

    record = RunRecord(mode, state)
    alpaca_node.run(state, record)
    with suppress(Refused):
        record.data["checks_unchanged_after_run"] = preflight(path) == state
    try:
        passed, _ = record.write([])
    except OSError, ValueError, RuntimeError:
        print("FAIL: run record could not be written", file=sys.stderr)
        return 1
    print(
        "PASS: scrubbed run record written to evidence/"
        if passed
        else "FAIL: inspect the local run record and engine log under runs/"
    )
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    args = parser.parse_args(argv)
    try:
        before = preflight(args.settings)
        print(
            f"Budget rows: {before.budget.paper_defaults} paper defaults, "
            f"{before.budget.reviewed} reviewed; quote-age limit present."
        )
        if args.mode == "order":
            try:
                confirmed = ibkr_paper.owner_confirms("order")
            except EOFError, KeyboardInterrupt:
                confirmed = False
            if not confirmed:
                raise Refused("order mode needs the owner at a terminal typing PAPER")
            if preflight(args.settings) != before:
                raise Refused("local checks changed during confirmation")
    except Refused as exc:
        print(f"REFUSED TO START: {exc}", file=sys.stderr)
        return 2
    return run_attended(args.mode, args.settings, before)


if __name__ == "__main__":
    raise SystemExit(main())
