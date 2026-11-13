"""
Soak run of the order budget against a simulated venue, fully offline.

    uv run python -m meridian.order_budget.soak     # one simulated hour; record to evidence/

The budget is the harvested pacer (``meridian.order_budget.pacer``), called the way the Alpaca
adapter calls it: ``request()`` for every action, ``drain()`` again whenever a refill is due.
The clock, the venue and the demand are simulated: no socket is opened and no engine is built,
so the run takes seconds and gives the same counts every time (the demand is seeded).

The simulated venue stands for one account at Alpaca: it answers 429 to a request past 200 in
any rolling 60 s window. The demand asks for more than the budget: a backlog of 240 actions at
the start, then about 210 a minute for an hour, mixed over the five kinds. An entry (SUBMIT)
is withdrawn by its caller if it has not been sent 30 s after it was requested, as a strategy
gives up on a stale entry; the other kinds wait until they are sent.

A run passes when:
  - no rolling 60 s window holds more paced requests than the budget (180), and some window
    comes within one of it, so the budget was used to the full;
  - the action past the budget is refused: when a window is full, the next action is not sent
    until the window has room, and every withdrawn entry is dropped without reaching the venue;
  - every send follows CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, first in first out within a kind;
  - the venue never answers 429;
  - every action is either sent exactly once or refused unsent, and every CANCEL and REDUCE is
    sent.

What the budget counts: every request it lets through, of all five kinds, because Alpaca's
200 a minute counts queries too. The pacer raises ``PacerRefused`` only for an entry that would
eat the protection reserve; the harvested tests cover that path.

This module is own design (see UPSTREAM.md) and uses only the standard library and the pacer.
"""

from __future__ import annotations

import argparse
import bisect
import json
import random
import sys
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian.order_budget import rows
from meridian.order_budget.controls import SEC, Controls
from meridian.order_budget.pacer import AccountPacer, ActionKind

RECORD_SCHEMA = "meridian.run-record/1"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED = 20261112
SOAK_SECONDS = 3600
BACKLOG_AT_START = 240
DEMAND_PER_MINUTE = 210
ENTRY_PATIENCE_S = 30
# Shares of the demand after the start, by kind; the backlog at the start is split evenly.
DEMAND_MIX = {
    ActionKind.CANCEL: 0.10,
    ActionKind.REDUCE: 0.10,
    ActionKind.MODIFY: 0.15,
    ActionKind.QUERY: 0.25,
    ActionKind.SUBMIT: 0.40,
}
PROTECTIVE = (ActionKind.CANCEL, ActionKind.REDUCE)
OK, RATE_LIMITED = 200, 429
# Wall-clock fields: the only part of a record that differs between two runs.
WALL_CLOCK_FIELDS = ("run_started_utc", "run_ended_utc")


class SimClock:
    """Integer nanoseconds, moved forward only by the soak."""

    def __init__(self) -> None:
        self.t = 0

    def now(self) -> int:
        return self.t


class SimulatedVenue:
    """One account at a simulated broker: 429 past ``limit`` requests in any rolling window."""

    def __init__(self, limit: int, window_ns: int) -> None:
        self.limit, self.window_ns = limit, window_ns
        self.recent: deque[int] = deque()
        self.received: list[tuple[int, int]] = []  # (arrival ns, action id)
        self.rate_limited = 0

    def receive(self, action_id: int, now: int) -> int:
        while self.recent and self.recent[0] <= now - self.window_ns:
            self.recent.popleft()
        if len(self.recent) >= self.limit:
            self.rate_limited += 1
            return RATE_LIMITED
        self.recent.append(now)
        self.received.append((now, action_id))
        return OK


@dataclass
class Action:
    ident: int  # equals the pacer's sequence number: one request() call per action, in order
    kind: ActionKind
    requested_ns: int
    deadline_ns: int | None  # an entry's caller withdraws it at this time if still unsent
    sent_ns: int | None = None
    sends: int = 0


@dataclass
class Soak:
    """Everything one simulated run leaves behind, for the record and for the tests."""

    seed: int
    seconds: int
    controls: Controls
    pacer: AccountPacer
    venue: SimulatedVenue
    actions: list[Action] = field(default_factory=list)
    sends: list[int] = field(default_factory=list)  # send times, in order
    priority_violations: int = 0
    # When the trailing window first held the run's largest count: its oldest send, and the
    # action that was waiting at that moment.
    full_at_ns: int | None = None
    full_count: int = 0
    full_oldest_ns: int | None = None
    waiting_when_full: Action | None = None


def demand(seed: int = SEED, seconds: int = SOAK_SECONDS) -> list[tuple[int, ActionKind]]:
    """The seeded demand script: (request time in ns, kind), in time order."""
    rng = random.Random(seed)
    backlog = [kind for kind in ActionKind for _ in range(BACKLOG_AT_START // len(ActionKind))]
    rng.shuffle(backlog)
    script = [(0, kind) for kind in backlog]
    kinds, weights = list(DEMAND_MIX), list(DEMAND_MIX.values())
    rate_per_s = DEMAND_PER_MINUTE / 60
    t = 0
    while True:
        t += max(1, int(rng.expovariate(rate_per_s) * SEC))
        if t >= seconds * SEC:
            return script
        script.append((t, rng.choices(kinds, weights)[0]))


def simulate(seed: int = SEED, seconds: int = SOAK_SECONDS) -> Soak:
    """Drive the pacer with the demand script until every action is sent or refused."""
    clock = SimClock()
    controls = rows.controls()
    pacer = AccountPacer(controls, clock.now)
    window_ns = controls.ns("window_s")
    soak = Soak(seed, seconds, controls, pacer, SimulatedVenue(controls["broker_limit"], window_ns))
    by_send: dict[Callable[..., Any], Action] = {}
    trailing: deque[int] = deque()

    def admissible(action: Action) -> bool:
        return action.deadline_ns is None or clock.now() < action.deadline_ns

    def make_send(action: Action) -> Callable[[Callable[[], None]], None]:
        def send(mark: Callable[[], None]) -> None:
            mark()  # the pacer's on-wire hook: one admitted action, one request
            now = clock.now()
            action.sends += 1
            action.sent_ns = now
            soak.sends.append(now)
            head = pacer.queue[0] if pacer.queue else None
            # Checked against every waiting action, not trusted to the pacer's heap.
            if any(
                (q.kind, q.sequence) < (int(action.kind), action.ident)
                and admissible(by_send[q.send])
                for q in pacer.queue
            ):
                soak.priority_violations += 1  # something more urgent was still waiting
            if soak.venue.receive(action.ident, now) == RATE_LIMITED:
                pacer.on_rate_limited()
            else:
                pacer.on_success()
            trailing.append(now)
            while trailing[0] <= now - window_ns:
                trailing.popleft()
            if len(trailing) > soak.full_count:
                soak.full_at_ns, soak.full_count = now, len(trailing)
                soak.full_oldest_ns = trailing[0]
                waiting = None if head is None else by_send.get(head.send)
                soak.waiting_when_full = (
                    waiting if waiting is not None and admissible(waiting) else None
                )

        return send

    script = demand(seed, seconds)
    i = 0
    while i < len(script) or pacer.queue:
        # The next event: a request from the script, or the moment the bucket can admit again.
        due = None
        if pacer.queue:
            anchor = clock.t if pacer.bucket.anchor is None else pacer.bucket.anchor
            due = max(clock.t, pacer.paused_until, anchor + pacer.bucket.interval_ns)
        arrival = script[i][0] if i < len(script) else None
        if arrival is not None and (due is None or arrival <= due):
            clock.t = arrival
            kind = script[i][1]
            i += 1
            deadline = arrival + ENTRY_PATIENCE_S * SEC if kind == ActionKind.SUBMIT else None
            action = Action(len(soak.actions), kind, arrival, deadline)
            soak.actions.append(action)
            send = make_send(action)
            by_send[send] = action
            pacer.request(kind, send, admission=lambda a=action: admissible(a))
        else:
            assert due is not None
            clock.t = due
            pacer.drain()
        if clock.t > (seconds + 3600) * SEC:
            raise RuntimeError("the soak did not drain within an hour after its demand stopped")
    return soak


def _seconds(ns: int) -> float:
    return round(ns / SEC, 6)


def cap_per_window(controls: Controls, interval_ns: int) -> int:
    """The most the bucket can admit in any 60 s window: a full burst, then one refill per
    interval. With 180 and a burst of 18 this is 179, because the interval rounds up."""
    return controls.burst + (controls.ns("window_s") - 1) // interval_ns


def window_counts(times: list[int], window_ns: int) -> list[int]:
    """For each time, how many of the times fall in the window (t - window, t] ending at it."""
    return [i - bisect.bisect_right(times, t - window_ns) + 1 for i, t in enumerate(times)]


def record_data(soak: Soak) -> dict[str, Any]:
    """The run record's fields, all from the simulation (no wall-clock field)."""
    controls, pacer, venue = soak.controls, soak.pacer, soak.venue
    window_ns = controls.ns("window_s")
    venue_times = [t for t, _ in venue.received]
    per_minute = [
        bisect.bisect_left(soak.sends, (m + 1) * 60 * SEC)
        - bisect.bisect_left(soak.sends, m * 60 * SEC)
        for m in range(soak.seconds // 60)
    ]
    names = [kind.name for kind in ActionKind]
    actions_only = [
        a.sent_ns for a in soak.actions if a.sent_ns is not None and a.kind != ActionKind.QUERY
    ]
    requested = Counter(a.kind.name for a in soak.actions)
    sent = Counter(a.kind.name for a in soak.actions if a.sends)
    refused = Counter(a.kind.name for a in soak.actions if not a.sends)
    waits: dict[str, int] = {}
    for a in soak.actions:
        if a.sent_ns is not None:
            waits[a.kind.name] = max(waits.get(a.kind.name, 0), a.sent_ns - a.requested_ns)
    waiting = soak.waiting_when_full
    return {
        "schema": RECORD_SCHEMA,
        "milestone": "M2",
        "lane": "order-budget",
        "mode": "soak",
        "offline": True,
        "component": {
            "pacer": "meridian.order_budget.pacer.AccountPacer (harvested; see UPSTREAM.md)",
            "control_rows": "meridian.order_budget.rows (FIXTURE_ONLY, UNCALIBRATED)",
            "control_rows_sha256": controls.params_hash,
        },
        "budget": {
            "request_budget_per_window": controls["request_budget"],
            "broker_limit_per_window": controls["broker_limit"],
            "window_ns": window_ns,
            "burst": controls.burst,
            "refill_interval_ns": pacer.bucket.interval_ns,
            "cap_per_window_from_the_refill_arithmetic": cap_per_window(
                controls, pacer.bucket.interval_ns
            ),
            "priority": "CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, FIFO within a kind",
        },
        "simulated_venue": {
            "limit_per_window": venue.limit,
            "window_ns": venue.window_ns,
            "requests_received": len(venue.received),
            "rate_limited_answers": venue.rate_limited,
            "most_requests_in_any_window": max(window_counts(venue_times, window_ns), default=0),
        },
        "demand": {
            "seed": soak.seed,
            "simulated_seconds": soak.seconds,
            "backlog_at_start": BACKLOG_AT_START,
            "per_minute_after_start": DEMAND_PER_MINUTE,
            "mix_after_start": {kind.name: share for kind, share in DEMAND_MIX.items()},
            "entry_withdrawn_if_unsent_after_s": ENTRY_PATIENCE_S,
            "requested": {name: requested[name] for name in names},
        },
        "observed": {
            "sent": {name: sent[name] for name in names},
            "refused_unsent": {name: refused[name] for name in names},
            "most_sent_in_any_window": max(window_counts(soak.sends, window_ns), default=0),
            "most_order_actions_in_any_window": max(
                window_counts(sorted(actions_only), window_ns), default=0
            ),
            "sent_per_minute": {
                "first_minute": per_minute[0] if per_minute else 0,
                "later_minutes_min": min(per_minute[1:], default=0),
                "later_minutes_max": max(per_minute[1:], default=0),
            },
            "when_a_window_was_first_full": None
            if soak.full_at_ns is None
            else {
                "at_ns": soak.full_at_ns,
                "sent_in_window": soak.full_count,
                "oldest_send_in_window_ns": soak.full_oldest_ns,
                "next_action": None
                if waiting is None
                else {
                    "kind": waiting.kind.name,
                    "requested_at_ns": waiting.requested_ns,
                    "sent_at_ns": waiting.sent_ns,
                },
            },
            "longest_wait_s": {name: _seconds(waits[name]) for name in names if name in waits},
            "priority_violations": soak.priority_violations,
            "sent_twice": sum(1 for a in soak.actions if a.sends > 1),
            "left_in_queue": len(pacer.queue),
            "wire_counters": pacer.to_state("simulated"),
        },
    }


def problems(data: dict[str, Any]) -> list[str]:
    """What, if anything, makes this soak a failure."""
    found: list[str] = []
    budget = data["budget"]["request_budget_per_window"]
    seen, venue = data["observed"], data["simulated_venue"]
    cap = data["budget"]["cap_per_window_from_the_refill_arithmetic"]
    most = seen["most_sent_in_any_window"]
    if most > budget or cap > budget:
        found.append(f"a 60 s window can hold {max(most, cap)} requests, over the budget {budget}")
    if most != cap:
        found.append(f"the busiest window held {most} requests, not the bucket's cap of {cap}")
    if venue["rate_limited_answers"]:
        found.append("the simulated venue answered 429")
    if venue["most_requests_in_any_window"] > budget:
        found.append("the simulated venue saw more requests in a window than the budget")
    if venue["requests_received"] != seen["wire_counters"]["requests"]:
        found.append("the pacer's wire count differs from what the venue received")
    if seen["priority_violations"]:
        found.append("an action was sent while a more urgent one was still waiting")
    if seen["sent_twice"]:
        found.append("an action was sent more than once")
    if seen["left_in_queue"]:
        found.append("actions were left in the queue at the end")
    for name, count in data["demand"]["requested"].items():
        if seen["sent"][name] + seen["refused_unsent"][name] != count:
            found.append(f"{name}: requested, sent and refused do not add up")
    for kind in PROTECTIVE:
        if seen["refused_unsent"][kind.name]:
            found.append(f"a {kind.name} was refused; protective actions must always be sent")
    if not seen["refused_unsent"][ActionKind.SUBMIT.name]:
        found.append("no entry was refused: the demand never went past the budget")
    full = seen["when_a_window_was_first_full"]
    if full is None or full["next_action"] is None:
        found.append("no action was waiting when a window was first full")
    else:
        # The waiting action may go out only once the window's oldest send has left it.
        room_at = full["oldest_send_in_window_ns"] + data["budget"]["window_ns"]
        sent_at = full["next_action"]["sent_at_ns"]
        if sent_at is not None and sent_at < room_at:
            found.append("the action past the budget was sent while the window was full")
    return found


def run_soak(seed: int = SEED, seconds: int = SOAK_SECONDS) -> dict[str, Any]:
    """Simulate and return the record (result and problems included), timestamps aside."""
    data = record_data(simulate(seed, seconds))
    found = problems(data)
    return {**data, "result": "fail" if found else "pass", "problems": found}


def write_record(record: dict[str, Any], root: Path | None = None) -> tuple[bool, Path]:
    """Write the record: to evidence/ on a pass, to the ignored runs/ folder on a failure."""
    root = REPO_ROOT if root is None else root
    passed = record["result"] == "pass" and not record["problems"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / ("evidence" if passed else "runs") / f"M2-order-budget-{stamp}-soak.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return passed, path


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meridian.order_budget.soak",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.parse_args(argv)
    started = _utc_now()
    record = run_soak()
    record.update(run_started_utc=started, run_ended_utc=_utc_now())
    passed, path = write_record(record)
    seen = record["observed"]
    print(
        f"{'PASS' if passed else 'FAIL'}: at most {seen['most_sent_in_any_window']} requests in "
        f"any 60 s window (budget {record['budget']['request_budget_per_window']}); "
        f"{sum(seen['refused_unsent'].values())} refused unsent; "
        f"{record['simulated_venue']['rate_limited_answers']} answered 429. "
        f"Record: {path.relative_to(REPO_ROOT)}"
    )
    for problem in record["problems"]:
        print(f"  - {problem}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
