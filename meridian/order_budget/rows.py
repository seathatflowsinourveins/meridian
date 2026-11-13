"""
The order budget's control rows for the soak and the tests.

The values are the owner's own fixture values from Sextant (``control_rows`` in
``tests/proofs/custody/conftest.py``, see UPSTREAM.md): a request budget of 180 per 60 s window
against Alpaca's limit of 200 requests per minute per account, with a burst of a tenth of the
budget. Every row is ``FIXTURE_ONLY`` and ``UNCALIBRATED``: ``Controls.from_rows`` accepts them
only with ``fixture=True``, so they can never become a lane's runtime authority by accident.
A lane that places orders needs rows the owner has reviewed.
"""

from __future__ import annotations

from typing import Any

from meridian.order_budget.controls import Controls

FIXTURE_VALUES: dict[str, Any] = {
    "request_budget": 180,
    "broker_limit": 200,
    "window_s": "60",
    "burst_fraction": "0.1",
    "cancel_timeout_s": "10",
    "cancel_retry_s": "5",
    "flatten_tick_s": "2",
    "backoff_base_s": "1",
    "backoff_max_s": "30",
    "reserve_per_open_position": 1,
    "reserve_per_exiting_position": 1,
    "observation_reminder_s": "300",
    "observation_max_edges": 500,
    "observation_money_step_fraction": "0.01",
    "observation_leverage_step": "0.01",
    "max_cancel_retries": 3,
}
SOURCE = "TEST ONLY: the owner's Sextant fixture values (see UPSTREAM.md)"


def control_rows(**changes: Any) -> list[dict[str, Any]]:
    """One registry row per control, with any value replaced by ``changes``."""
    return [
        {
            "name": name,
            "value": value,
            "source": SOURCE,
            "unit": "fixture",
            "calibration": "UNCALIBRATED",
            "last_change": "2026-11-06",
            "scope": "FIXTURE_ONLY",
        }
        for name, value in (FIXTURE_VALUES | changes).items()
    ]


def controls(*, slots: int | None = None, **changes: Any) -> Controls:
    """Validated controls built from the fixture rows (``fixture=True``)."""
    return Controls.from_rows(control_rows(**changes), fixture=True, slots=slots)
