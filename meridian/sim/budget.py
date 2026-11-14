"""The lane's order budget in the simulated loop: the same rows, loader and account pacer.

In the Alpaca lane every broker request passes M2's `AccountPacer`, built by
`meridian.alpaca.pacing.build_pacer` from the owner's rows file (the 16 rows of
`deploy/alpaca-order-budget.template.json`); a SUBMIT or REDUCE the bucket cannot pay for now
stays queued and is sent by a later `drain()`, which the gateway calls after waiting one
token interval (`meridian/alpaca/wire.py`, `AccountGateway.call`). Here the strategies hand
each venue order to that same pacer (`strategies.Paced`), built by the same function, on the
simulation clock.

The rows have the lane's shape and scope `PAPER_DEFAULT`, which the lane's loader accepts.
Their values are placeholders: the order budget's fixture values
(`meridian/order_budget/rows.py`), never an owner-reviewed row. `broker_limit` and `window_s`
are Alpaca's 200 requests a minute, which the loader requires (`VENUE_LIMIT`, UPSTREAM.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from meridian.alpaca.pacing import build_pacer
from meridian.order_budget.controls import NAMES
from meridian.order_budget.pacer import AccountPacer
from meridian.order_budget.rows import FIXTURE_VALUES

ROWS_FILE = "order-budget-rows.json"
SOURCE = "placeholder for the simulation: the order budget's fixture values, not reviewed"


def paper_default_rows(**changes: Any) -> list[dict[str, Any]]:
    """One row per control, in the lane's rows-file shape, scope PAPER_DEFAULT."""
    values = FIXTURE_VALUES | changes
    return [
        {
            "name": name,
            "value": values[name],
            "source": SOURCE,
            "unit": "placeholder",
            "last_change": "2026-11-14",
            "calibration": "UNCALIBRATED",
            "scope": "PAPER_DEFAULT",
        }
        for name in sorted(NAMES)
    ]


def write_rows(folder: Path, rows: list[dict[str, Any]] | None = None) -> Path:
    path = folder / ROWS_FILE
    path.write_text(json.dumps(rows or paper_default_rows(), indent=1) + "\n", encoding="utf-8")
    return path


def pacer(rows_path: Path, now_ns: Callable[[], int]) -> AccountPacer:
    """The lane's own construction: rows loaded and checked, no initial burst."""
    return build_pacer(str(rows_path), now_ns)
