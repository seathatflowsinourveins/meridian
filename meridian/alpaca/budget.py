"""
The order budget as this adapter calls it.

`ActionKind` and `PacerRefused` are M2's own, imported from `meridian.order_budget.pacer`, so
`wire.py`'s `except PacerRefused` catches the refusal M2's pacer raises. The `Protocol` below
states the members of M2's `AccountPacer` this adapter uses (`request/drain/on_rate_limited/
on_success`, `.bucket.interval_ns`, `.controls[...]`) and implements none of them;
`tests/test_alpaca_budget.py` has pyright check that M2's pacer still fits it. No pacer is wired
yet. A new M2 pacer starts with a full burst and the client builds one at every connect, so the
lane should start its pacer empty.

How the adapter uses it (`wire.py`): every REST request, reads included, is one `request()`
of one kind; the pacer calls `send(before_wire)`, and `before_wire()` runs once, on the event
loop, just before the request leaves. Priority is CANCEL > REDUCE > MODIFY > QUERY > SUBMIT
(plan 9.1); the budget is 180 order actions per minute against Alpaca's 200 requests per
minute per account. A refusal is "not sent", never "sent and lost".
"""

from collections.abc import Callable
from typing import Any, Protocol

from meridian.order_budget.pacer import ActionKind, PacerRefused

__all__ = ["AccountPacer", "ActionKind", "ControlsView", "PacerRefused", "TokenBucketView"]


class TokenBucketView(Protocol):
    @property
    def interval_ns(self) -> int: ...


class ControlsView(Protocol):
    def __getitem__(self, key: str, /) -> Any: ...


class AccountPacer(Protocol):
    """The members of M2's `AccountPacer` this adapter relies on."""

    @property
    def bucket(self) -> TokenBucketView: ...

    @property
    def controls(self) -> ControlsView: ...

    def request(
        self,
        kind: ActionKind,
        send: Callable,
        *,
        admission: Callable[[], bool] = ...,
        open_positions: int = 0,
        exiting_positions: int = 0,
        position_counts: Callable[[], tuple[int, int]] | None = None,
        refuse: Callable[[str], None] | None = None,
        snapshot_reads: int = 0,
        entry_positions: Callable[[], int] | None = None,
    ) -> None: ...

    def drain(self) -> None: ...

    def on_rate_limited(self, reset_after_ns: int | None = None) -> None: ...

    def on_success(self) -> None: ...
