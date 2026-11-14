"""Owner-held order-budget rows; no production values are supplied by this repository.

M2's unchanged Controls validates all rows, including their provenance and scope.
Failures leave this module as fixed text, with no file path, row value or exception chain.
"""

import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from meridian.order_budget.controls import Controls
from meridian.order_budget.pacer import AccountPacer


def load_controls(path: str | None) -> Controls:
    text = None
    if path is not None:
        with suppress(OSError, ValueError, TypeError):
            text = Path(path).read_text(encoding="utf-8")
    if text is None:
        raise ValueError("order budget rows file unavailable")

    controls = None
    try:
        rows = json.loads(text)
        if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
            controls = Controls.from_rows(rows)
    except ValueError, TypeError, KeyError, ArithmeticError:
        pass
    # Outside the except block: even __context__ must not retain an owner's value.
    if controls is None:
        raise ValueError("order budget rows invalid")
    return controls


def build_pacer(path: str | None, now_ns: Callable[[], int]) -> AccountPacer:
    pacer = AccountPacer(load_controls(path), now_ns)
    # No request is issued to spend the initial burst. Anchor here so the first
    # token arrives one full interval after construction, including on reconnect.
    pacer.bucket.tokens, pacer.bucket.anchor = 0, now_ns()
    return pacer
