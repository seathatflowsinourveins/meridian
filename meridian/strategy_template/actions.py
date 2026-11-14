"""Every order action the template takes, counted so a lane's budget can pace it.

Venue actions use M2's `ActionKind` (the kinds the Alpaca adapter paces: a buy is SUBMIT, a
sell is REDUCE, a cancel is CANCEL; `meridian/alpaca/execution.py`). Local actions never reach
a venue: placing or changing an emulated order is handled inside the engine's OrderEmulator.
The template sets no budget of its own; the lane's pacer is the budget (`docs/HANDBOOK.md`,
"Rate budgets"), and `listeners` let a lane see each action as it is taken.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from meridian.order_budget.pacer import ActionKind

NS_PER_SECOND = 1_000_000_000
LOCAL = "LOCAL"  # an emulated order placed or changed in the engine; no venue request


@dataclass(frozen=True, slots=True)
class Action:
    ts_ns: int
    kind: str  # an ActionKind name, or LOCAL
    symbol: str
    what: str  # entry, protect, release, reprice, cancel-entry, cancel-exit


@dataclass(slots=True)
class ActionLog:
    actions: list[Action] = field(default_factory=list)
    listeners: list[Callable[[Action], None]] = field(default_factory=list)

    def record(self, ts_ns: int, kind: ActionKind | str, symbol: str, what: str) -> None:
        name = kind.name if isinstance(kind, ActionKind) else kind
        action = Action(ts_ns, name, symbol, what)
        self.actions.append(action)
        for listener in self.listeners:
            listener(action)

    def venue(self) -> list[Action]:
        return [a for a in self.actions if a.kind != LOCAL]

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(a.kind for a in self.actions).items()))

    def max_in_window(self, window_ns: int) -> int:
        """The most venue actions in any window of this length (sliding, by event time)."""
        times = sorted(a.ts_ns for a in self.venue())
        best, start = 0, 0
        for end, ts in enumerate(times):
            while ts - times[start] >= window_ns:
                start += 1
            best = max(best, end - start + 1)
        return best

    def summary(self) -> dict[str, object]:
        return {
            "counts": self.counts(),
            "venue_actions": len(self.venue()),
            "max_venue_actions_per_second": self.max_in_window(NS_PER_SECOND),
            "max_venue_actions_per_minute": self.max_in_window(60 * NS_PER_SECOND),
        }
