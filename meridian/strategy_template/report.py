"""Export rc9's own backtest analysis; see docs/adr/data/m5-engine-stats.md."""

from __future__ import annotations

import json
import math
from importlib.util import find_spec
from typing import Any
from uuid import uuid4

import nautilus_trader
from nautilus_trader.backtest import BacktestEngine

from meridian import boundary


class ReportUnavailable(RuntimeError):
    """The optional reporting dependencies are absent."""


def require_research() -> None:
    missing = [name for name in ("pandas", "plotly") if find_spec(name) is None]
    if missing:
        raise ReportUnavailable(
            f"Simulation report needs {', '.join(missing)}; `uv sync --locked` installs the "
            "default dev and research groups. A sync that excludes research can omit these "
            "dependencies; sync with defaults, then rerun with --report."
        )


def _finite(value: Any) -> Any:
    """JSON has no NaN/Infinity: preserve undefined engine values as null."""
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    return None if isinstance(value, float) and not math.isfinite(value) else value


def write_report(engine: BacktestEngine) -> dict[str, Any]:
    """Read the completed engine before disposal, writing only under ignored runs/."""
    require_research()
    from nautilus_trader.analysis.tearsheet import create_tearsheet

    result = engine.get_result()  # Internally calls portfolio.statistics(), its analyzer snapshot.
    statistics = _finite(
        {
            "pnls": result.stats_pnls,
            "returns": result.stats_returns,
            "general": result.stats_general,
            "total_positions": result.total_positions,
            "total_orders": result.total_orders,
        }
    )
    relative = f"runs/M5-template-{uuid4().hex}"
    folder = boundary.REPO_ROOT / relative
    folder.mkdir(parents=True)
    record = {
        "engine": nautilus_trader.__version__,
        "data_source": "synthetic quotes; uncalibrated fixture parameters; no evidence of edge",
        "undefined_statistics": "null means the engine returned a non-finite value",
        "statistics": statistics,
    }
    (folder / "statistics.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    engine.generate_orders_report().to_csv(folder / "orders.csv")
    engine.generate_fills_report().to_csv(folder / "fills.csv")
    engine.generate_positions_report().to_csv(folder / "positions.csv")
    # rc9 calls Figure.write_html with defaults: Plotly JS is embedded, not loaded from a CDN.
    create_tearsheet(
        engine,
        output_path=str(folder / "tearsheet.html"),
        title="Strategy template: synthetic, uncalibrated simulation",
    )
    return {"directory": relative, "statistics": statistics}
