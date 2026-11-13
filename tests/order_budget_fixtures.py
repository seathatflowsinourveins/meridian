"""
The order budget's test helpers, as Sextant's custody conftest has them: ``SEC``, the fixture
control rows, and controls built from them with ``fixture=True``. They live here, under
``tests/``, so the package itself never passes ``fixture=True`` (the soak does, in plain view).
"""

from typing import Any

from meridian.order_budget.controls import SEC, Controls
from meridian.order_budget.rows import control_rows

__all__ = ["SEC", "control_rows", "controls"]


def controls(*, slots: int | None = None, **changes: Any) -> Controls:
    rows = control_rows(**changes)
    if slots is None:
        return Controls.from_rows(rows, fixture=True)
    return Controls.from_rows(rows, fixture=True, slots=slots)
