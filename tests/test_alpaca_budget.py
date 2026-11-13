"""
The adapter's order-budget types are M2's own: M2's real pacer fits the adapter's `Protocol`
(pyright checks `fits` below, as it checks all of `tests/`), and a refusal it raises is the
`PacerRefused` that the account gateway catches. Offline: the account is `FakeVenue`.
"""

import asyncio

import pytest
from alpaca_fakes import FakeVenue
from order_budget_fixtures import controls

from meridian.alpaca import budget
from meridian.alpaca.wire import AccountGateway
from meridian.order_budget import pacer as m2


def fits(pacer: m2.AccountPacer) -> budget.AccountPacer:
    return pacer  # a type error if M2's pacer no longer fits the adapter's Protocol


def test_the_adapter_uses_m2s_action_kinds_and_refusal():
    assert budget.ActionKind is m2.ActionKind
    assert budget.PacerRefused is m2.PacerRefused


def test_a_refusal_from_m2s_pacer_is_not_sent_and_reaches_the_caller():
    """The fixture burst is 18 and each open position reserves 1, so a SUBMIT with 17 open
    positions needs a reserve of 18 and M2's pacer refuses it inside `request()`."""
    venue = FakeVenue()

    async def scenario():
        gw = AccountGateway(venue, fits(m2.AccountPacer(controls(), lambda: 0)), lambda: (17, 0))
        wired = []
        with pytest.raises(ValueError, match="entry-reserve-exceeds-burst"):
            await gw.call(
                budget.ActionKind.SUBMIT, "post", "/orders", {}, on_wire=lambda: wired.append(1)
            )
        return wired

    assert asyncio.run(scenario()) == [] and venue.calls == []
