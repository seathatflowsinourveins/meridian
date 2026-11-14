"""Exercise the test tools on the lane's existing pure session predicate."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
import time_machine
from hypothesis import given
from hypothesis import strategies as st

from meridian.ibkr_paper import in_regular_hours


@given(
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
        timezones=st.just(UTC),
    ),
    st.integers(min_value=-12, max_value=14),
)
def test_session_predicate_is_invariant_to_timezone_representation(instant, offset):
    local = instant.astimezone(timezone(timedelta(hours=offset)))
    assert in_regular_hours(instant) == in_regular_hours(local)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2024-07-01T13:29:59Z", False),
        ("2024-07-01T13:30:00Z", True),
        ("2024-07-01T19:54:59Z", True),
        ("2024-07-01T19:55:00Z", False),
        ("2024-07-06T14:00:00Z", False),
    ],
)
def test_session_predicate_uses_the_frozen_clock(instant, expected):
    with time_machine.travel(instant, tick=False):
        assert in_regular_hours() is expected
