"""
The order budget as this adapter calls it.

Milestone M2 harvests the earlier Sextant line's account pacer as its own tested component and
keeps its public interface (`meridian/order_budget/`, branch `m2/order-budget`, a pull request
of its own). This adapter's pull request does not build on that branch: it stays independent,
against main. So this module states the part of the interface the adapter uses, exactly as it
is in `seathatflowsinourveins/sextant-paper@a991b73a:src/sextant/execution/pacer.py`
(`ActionKind`, `PacerRefused`, `AccountPacer.request/drain/on_rate_limited/on_success`,
`.bucket.interval_ns`, `.controls[...]`), and implements none of it.

Once the order-budget pull request is merged, a follow-up makes this module import `ActionKind`
and `PacerRefused` from `meridian.order_budget.pacer` and keeps the `Protocol`, which then
checks that M2's pacer still fits. Names, signatures and enum values are the same there
(compared on 2026-11-13), but until then they are separate classes: pyright rejects M2's pacer
for this `Protocol`, and `wire.py`'s `except PacerRefused` would not catch the one M2's pacer
raises. A new M2 pacer starts with a full burst and the client builds one at every connect, so
the lane should start its pacer empty.

How the adapter uses it (`wire.py`): every REST request, reads included, is one `request()`
of one kind; the pacer calls `send(before_wire)`, and `before_wire()` runs once, on the event
loop, just before the request leaves. Priority is CANCEL > REDUCE > MODIFY > QUERY > SUBMIT
(plan 9.1); the budget is 180 order actions per minute against Alpaca's 200 requests per
minute per account. A refusal is "not sent", never "sent and lost".
"""

from collections.abc import Callable
from enum import IntEnum
from typing import Any, Protocol


class ActionKind(IntEnum):
    CANCEL = 0
    REDUCE = 1
    MODIFY = 2
    QUERY = 3
    SUBMIT = 4


class PacerRefused(RuntimeError):
    """The account pacer did not admit a broker call; the caller must fail closed."""

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason)


class TokenBucketView(Protocol):
    @property
    def interval_ns(self) -> int: ...


class ControlsView(Protocol):
    def __getitem__(self, key: str, /) -> Any: ...


class AccountPacer(Protocol):
    """The members of the earlier line's `AccountPacer` this adapter relies on."""

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
