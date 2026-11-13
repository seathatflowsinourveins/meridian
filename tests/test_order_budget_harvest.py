"""
The order budget's harvested files are the owner's Sextant files, changed only in the import
lines that name Sextant's module paths. The blob ids are git's, as listed in UPSTREAM.md; the
source is ``seathatflowsinourveins/sextant`` at ``33cdee7b65d53c93ab106b7b3196fc790b14a5a8``.

A deliberate change to one of these files (a defect fix) updates its row here and in
UPSTREAM.md in the same commit, with the reason.
"""

from pathlib import Path

import pytest
from test_upstream_unmodified import git_blob_id

REPO_ROOT = Path(__file__).resolve().parent.parent

# file here: (path in sextant, git blob id there, {text here: the text it replaced})
HARVESTED = {
    "meridian/order_budget/controls.py": (
        "src/sextant/risk/controls.py",
        "d7fed7b1c9252d425a8ec32ec985560a39231273",
        {},
    ),
    "meridian/order_budget/pacer.py": (
        "src/sextant/execution/pacer.py",
        "49a30e965aac62dea17cb3d6b4c09fee685e9742",
        {"from meridian.order_budget.controls import": "from sextant.risk.controls import"},
    ),
    "tests/test_order_budget_pacer.py": (
        "tests/proofs/custody/test_pacer.py",
        "97c32c1016f1343b929bd5f20ba7cd39c0677a3b",
        {
            "import pytest\n"
            "from order_budget_fixtures import SEC, controls\n"
            "\n"
            "from meridian.order_budget.pacer import AccountPacer, ActionKind, PacerRefused\n": (
                "import pytest\n"
                "\n"
                "from sextant.execution.pacer import AccountPacer, ActionKind, PacerRefused\n"
                "\n"
                "from .conftest import SEC, controls\n"
            )
        },
    ),
}


@pytest.mark.parametrize("name", sorted(HARVESTED))
def test_a_harvested_file_is_the_source_but_for_its_import_lines(name):
    _, blob, changes = HARVESTED[name]
    text = (REPO_ROOT / name).read_bytes().decode("utf-8")
    for here, there in changes.items():
        assert text.count(here) == 1, f"{name}: the changed lines are not as listed"
        text = text.replace(here, there)
    assert git_blob_id(text.encode("utf-8")) == blob


def test_nothing_in_the_harvested_files_still_names_sextant():
    for name in HARVESTED:
        assert "sextant" not in (REPO_ROOT / name).read_text(encoding="utf-8").lower(), name


# The values of control_rows() in Sextant's tests/proofs/custody/conftest.py, git blob
# 0bdc6ac9cab4a154a4c661c95d59e8e5a716c129, copied by hand: meridian/order_budget/rows.py must
# carry exactly these.
CONFTEST_BLOB = "0bdc6ac9cab4a154a4c661c95d59e8e5a716c129"
CONFTEST_VALUES = {
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


def test_the_fixture_rows_carry_sextants_conftest_values():
    from meridian.order_budget import controls, rows

    assert rows.FIXTURE_VALUES == CONFTEST_VALUES
    assert set(CONFTEST_VALUES) == controls.NAMES
    first = rows.control_rows()[0]
    assert (first["scope"], first["calibration"]) == ("FIXTURE_ONLY", "UNCALIBRATED")
