"""The runner: one `BacktestNode` per parameter set, on one catalog, with the engine's reports.

`uv run python -m meridian.sim [--copies N] [--calendar ROWS.json]`. Upstream pattern
(NautilusTrader v2.0.0rc9): `docs/getting_started/backtest_high_level.py:205-261` (data
configs on the catalog, a run config, `node.build()`, a strategy added to the run,
`node.run()`), and `docs/concepts/backtesting/apis-and-runs.md:287-306`: rc9's node takes one
run config (`crates/backtest/src/node.rs:427-433`), so independent parameter sets are one node each,
created and disposed in turn. Reports: `BacktestNode.generate_*_report` and
`nautilus_trader.analysis.tearsheet.create_tearsheet` with the node's result.

Deterministic: fixed synthetic data from a fixed start, fixed fill-model seeds, the engine's
deterministic trade ids; no wall clock. Every value is synthetic or a placeholder and every
result goes under `runs/` (ignored by git): no tuned value, no claim of profit.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import nautilus_trader
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestNode,
    BacktestRunConfig,
)
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.model import (
    ClientOrderId,
    InstrumentId,
    NautilusDataType,
    OrderType,
    TimeInForce,
    Venue,
)
from nautilus_trader.persistence import DataCatalogConfig

from meridian import boundary
from meridian.alpaca.universe import UniverseTimeline
from meridian.strategy_template.params import TemplateParams
from meridian.strategy_template.report import _finite, require_research
from meridian.strategy_template.sim import SCENARIOS, SIM_PARAMS, path, synthetic_universe
from meridian.strategy_template.sim import problems as template_problems

from . import budget, catalog
from .strategies import BracketProbe, GatedBreakout
from .venue import SETS, VenueModels, risk_config, venue_config

# The bracket's symbol: flat, then a rise through its take-profit. Synthetic.
BRACKET = InstrumentId.from_str(f"BRACKET.{catalog.VENUE}")
BRACKET_BIDS = path("70.00", ("0", 8), ("0.05", 30, "0.01"))
BRACKET_ARGS: dict[str, Any] = {
    "quantity": 10,
    "take_profit": Decimal("0.50"),
    "stop_loss": Decimal("0.50"),
    "wait": 6,
}

Inspect = Callable[[BacktestNode, str, GatedBreakout, BracketProbe], None]


def write_catalog(
    folder: Path,
    *,
    copies: int = 1,
    start_ns: int = catalog.START_NS,
    calendar: catalog.Calendar | None = None,
) -> Path:
    """The catalog, and beside it the placeholder order-budget rows the pacer loads."""
    path = folder / "catalog"
    path.mkdir(parents=True, exist_ok=True)
    bracket = {BRACKET: catalog.quotes(BRACKET, BRACKET_BIDS, start_ns)}
    catalog.write(path, copies=copies, start_ns=start_ns, extra=bracket, calendar=calendar)
    budget.write_rows(folder)
    return path


def run_config(
    models: VenueModels, catalog_path: Path, ids: list[InstrumentId]
) -> BacktestRunConfig:
    store = DataCatalogConfig(path=str(catalog_path))
    data = [
        BacktestDataConfig(data_type=kind, catalog=store, instrument_ids=ids)
        for kind in (NautilusDataType.InstrumentStatus, NautilusDataType.QuoteTick)
    ]
    return BacktestRunConfig(
        venues=[venue_config(models, catalog.VENUE)],
        data=data,
        engine=BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.OFF, bypass_logging=True),
            risk_engine=risk_config(models),
        ),
        dispose_on_completion=False,  # read the reports first, then dispose
    )


def run_set(
    models: VenueModels,
    catalog_path: Path,
    *,
    copies: int = 1,
    params: TemplateParams | None = None,
    report_dir: Path | None = None,
    inspect: Inspect | None = None,
    template_type: type[GatedBreakout] = GatedBreakout,
    calendar: catalog.Calendar | None = None,
    start_ns: int = catalog.START_NS,
    universe: UniverseTimeline | None = None,
) -> dict[str, Any]:
    """One node, one run, one parameter set; the result as plain data.

    `calendar` must be the rows the catalog was written with: the strategies' session rule
    and DAY expiry read them, the venue reads the statuses made from them.

    The template enters only symbols on a mover list received before the entry
    (`meridian/alpaca/universe.py`). By default that list comes from synthetic screener
    responses read at `start_ns`, the catalog's first quote (the template's own
    `synthetic_universe`: the same parser and selector as the read-only client, no network).
    """
    ids = catalog.instrument_ids(SCENARIOS, copies)
    config = run_config(models, catalog_path, [*ids, BRACKET])
    node = BacktestNode([config])
    try:
        node.build()
        inputs = {name: spec[1:] for name, spec in SCENARIOS.items()}
        rows = catalog_path.parent / budget.ROWS_FILE if models.order_budget else None
        template = template_type(
            params or TemplateParams.from_config(SIM_PARAMS),
            [*ids],
            inputs,
            calendar=calendar,
            budget_rows=rows,
        )
        template.universe = universe or synthetic_universe([*ids], read_at_ns=start_ns)
        bracket = BracketProbe(BRACKET, **BRACKET_ARGS, calendar=calendar)
        node.add_strategy(config.id, template)
        node.add_strategy(config.id, bracket)
        (result,) = node.run()
        cache = node.get_engine_cache(config.id)
        orders = cache.orders()
        fills = node.generate_fills_report(config.id)
        data: dict[str, Any] = {
            "set": models.name,
            "models": {k: str(v) for k, v in asdict(models).items()},
            "symbols": {str(i): b.report() for i, b in template.books.items()},
            "actions": template.actions.summary(),
            "bracket": {
                leg: order.status.name if (order := cache.order(ClientOrderId(oid))) else None
                for leg, oid in bracket.order_ids.items()
            },
            "session_refusals": template.session_refusals + bracket.session_refusals,
            "day_expiries": template.day_expiries + bracket.day_expiries,
            # Orders filled in more than one part: Alpaca paper's random partial fills.
            "orders_partly_filled": int((fills.groupby("client_order_id").size() > 1).sum())
            if len(fills)
            else 0,
            "budget": {
                "paced": len(template.paced),
                "deferred": sum(1 for _, asked, sent in template.paced if sent > asked),
                "refusals": template.budget_refusals,
            },
            "orders_total": len(orders),
            # The template's own orders at the venue: every one a DAY LIMIT, as in the lanes.
            "orders_not_day_limit": sum(
                1
                for o in orders
                if o.strategy_id == template.strategy_id
                and not o.is_emulated
                and (o.order_type != OrderType.LIMIT or o.time_in_force != TimeInForce.DAY)
            ),
            "orders_denied": sum(1 for o in orders if o.status.name == "DENIED"),
            "orders_rejected": sum(1 for o in orders if o.status.name == "REJECTED"),
            "commissions_usd": str(
                sum((Decimal(str(c).split()[0]) for c in fills["commission"]), Decimal(0))
                if len(fills)
                else Decimal(0)
            ),
            "statistics": _finite(
                {
                    "pnls": result.stats_pnls,
                    "returns": result.stats_returns,
                    "general": result.stats_general,
                    "total_positions": result.total_positions,
                    "total_orders": result.total_orders,
                }
            ),
        }
        data["problems"] = problems(data, copies)
        if report_dir is not None:
            data["report"] = write_report(node, config.id, result, report_dir, data)
        if inspect is not None:
            inspect(node, config.id, template, bracket)
    finally:
        node.dispose()
    return data


def problems(data: dict[str, Any], copies: int = 1) -> list[str]:
    """The template's scenarios happened, the bracket closed by its take-profit, none refused."""
    found = template_problems(data, copies)
    if data["bracket"] != {"entry": "FILLED", "stop_loss": "CANCELED", "take_profit": "FILLED"}:
        found.append(f"the bracket did not fill its entry and take-profit: {data['bracket']}")
    if data["session_refusals"]:
        found.append(f"session refusals in a regular session: {data['session_refusals']}")
    if data["budget"]["refusals"]:
        found.append(f"the order budget refused: {data['budget']['refusals']}")
    return found


def write_report(node: BacktestNode, run_id: str, result: Any, folder: Path, data: dict) -> str:
    """The engine's reports and tearsheet, as `report.write_report` writes them for an engine.

    That function takes a `BacktestEngine`; a node gives its reports by run config id.
    """
    require_research()
    from nautilus_trader.analysis.tearsheet import create_tearsheet

    folder.mkdir(parents=True, exist_ok=True)
    node.generate_orders_report(run_id).to_csv(folder / "orders.csv")
    node.generate_fills_report(run_id).to_csv(folder / "fills.csv")
    node.generate_positions_report(run_id).to_csv(folder / "positions.csv")
    node.generate_account_report(run_id, venue=Venue(catalog.VENUE)).to_csv(folder / "account.csv")
    (folder / "statistics.json").write_text(
        json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    create_tearsheet(
        result,
        output_path=str(folder / "tearsheet.html"),
        title=f"Meridian simulation, set {data['set']}: synthetic, placeholder values",
        node=node,
        run_config_id=run_id,
    )
    return str(folder.relative_to(boundary.REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="End-to-end simulation on the engine's own API.")
    parser.add_argument("--copies", type=int, default=1, help="copies of each scenario")
    parser.add_argument(
        "--calendar",
        type=Path,
        help="calendar rows (JSON) covering the synthetic dates; default: the weekly window",
    )
    args = parser.parse_args(argv)
    copies = max(args.copies, 1)
    calendar = catalog.load_calendar(args.calendar) if args.calendar else None
    print("SIMULATION; not a lane; synthetic data and placeholder values only.", flush=True)
    folder = boundary.REPO_ROOT / "runs" / f"M5-sim-{uuid4().hex}"
    folder.mkdir(parents=True)
    catalog_path = write_catalog(folder, copies=copies, calendar=calendar)
    record: dict[str, Any] = {
        "schema": "meridian.simulation-record/1",
        "milestone": "M5",
        "simulation": True,
        "data_source": catalog.DATA_SOURCE,
        "engine": {"name": "NautilusTrader BacktestNode", "version": nautilus_trader.__version__},
        "copies": copies,
        "calendar": "rows given" if calendar is not None else "weekly window only",
        "sets": [],
    }
    failed = False
    for models in SETS:
        data = run_set(
            models, catalog_path, copies=copies, report_dir=folder / models.name, calendar=calendar
        )
        record["sets"].append(data)
        stats = data["statistics"]
        print(
            f"set {models.name}: orders {data['orders_total']}, denied {data['orders_denied']},"
            f" rejected {data['orders_rejected']}, commissions {data['commissions_usd']} USD,"
            f" bracket {data['bracket']}, partly filled {data['orders_partly_filled']},"
            f" paced {data['budget']['paced']} (deferred {data['budget']['deferred']}),"
            f" DAY expiries {len(data['day_expiries'])}"
        )
        for group in ("pnls", "returns", "general"):
            values = stats[group].get("USD", {}) if group == "pnls" else stats[group]
            shown = ", ".join(f"{k} {_short(v)}" for k, v in sorted(values.items()))
            print(f"  {group}: {shown or '-'}")
        print(f"  report: {data['report']}/  (tearsheet.html, orders, fills, positions)")
        if data["problems"]:
            failed = True
            print("  FAIL: " + "; ".join(data["problems"]))
    (folder / "record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print("FAIL" if failed else "PASS")
    print(f"Simulation record: {folder.relative_to(boundary.REPO_ROOT)}/record.json")
    return 1 if failed else 0


def _short(value: Any) -> str:
    return f"{value:.6g}" if isinstance(value, float) else str(value)
