"""Owner-held order-budget rows; no production values are supplied by this repository.

M2's unchanged Controls validates rows after the paper-default scope is mapped for that call.
Failures leave this module as fixed text, with no file path, row value or exception chain.
"""

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from meridian.order_budget.controls import Controls
from meridian.order_budget.pacer import AccountPacer

# Source: UPSTREAM.md, "Alpaca Trading API rate limit" (requests per minute).
VENUE_LIMIT = {"broker_limit": 200, "window_s": 60}


@dataclass(frozen=True)
class LoadedControls:
    controls: Controls = field(repr=False)
    paper_default_rows: int
    reviewed_rows: int


def load_controls(path: str | None) -> LoadedControls:
    text = None
    if path is not None:
        with suppress(OSError, ValueError, TypeError):
            text = Path(path).read_text(encoding="utf-8")
    if text is None:
        raise ValueError("order budget rows file unavailable")

    loaded = None
    try:
        rows = json.loads(text)
        if isinstance(rows, list) and all(
            isinstance(row, dict) and row.get("scope") in {"PAPER_DEFAULT", "REVIEWED"}
            for row in rows
        ):
            # Check original scopes first: a fixture must never be promoted here.
            controls = Controls.from_rows(
                [
                    row | {"scope": "REVIEWED"} if row["scope"] == "PAPER_DEFAULT" else row
                    for row in rows
                ]
            )
            if all(controls[name] == value for name, value in VENUE_LIMIT.items()):
                loaded = LoadedControls(
                    controls,
                    sum(row["scope"] == "PAPER_DEFAULT" for row in rows),
                    sum(row["scope"] == "REVIEWED" for row in rows),
                )
    except ValueError, TypeError, KeyError, ArithmeticError:
        pass
    # Outside the except block: even __context__ must not retain an owner's value.
    if loaded is None:
        raise ValueError("order budget rows invalid")
    return loaded


def build_pacer(path: str | None, now_ns: Callable[[], int]) -> AccountPacer:
    pacer = AccountPacer(load_controls(path).controls, now_ns)
    # No request is issued to spend the initial burst. Anchor here so the first
    # token arrives one full interval after construction, including on reconnect.
    pacer.bucket.tokens, pacer.bucket.anchor = 0, now_ns()
    return pacer
