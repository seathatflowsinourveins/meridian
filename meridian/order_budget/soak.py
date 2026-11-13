"""
Soak run of the order budget against a simulated venue, fully offline.

    uv run python -m meridian.order_budget.soak     # one simulated hour; record to evidence/

The budget is the harvested pacer (``meridian.order_budget.pacer``), called the way the Alpaca
adapter calls it: ``request()`` for every action, ``drain()`` again whenever a refill is due.
The clock, the venue and the demand are simulated: no socket is opened and no engine is built,
so the run takes seconds and gives the same counts every time (the demand is seeded).

The simulated venue stands for one account at Alpaca: it answers 429 to a request past 200 in
any rolling 60 s window. The demand asks for more than the budget: a backlog of 240 actions at
the start, then about 210 a minute, mixed over the five kinds, broken by three quiet spells of
two to five minutes, in which the bucket fills up again, each ending in another backlog of 240.
An entry (SUBMIT) is withdrawn by its caller if it has not been sent 30 s after it was
requested, as a strategy gives up on a stale entry; the other kinds wait until they are sent.

A run passes when:
  - no rolling 60 s window holds more paced requests than the budget (180), after a quiet
    spell as at any other time, and windows reach 179, so the budget is used;
  - under steady demand above the budget, every whole minute sends at least 161;
  - the action past the budget is held, not sent: when a window first holds the bucket's cap,
    an action is waiting, and nothing more is sent until the window's oldest send has left it.
    The pacer never refuses an action for being over the budget; an entry is left unsent only
    when its caller withdraws it (here, after 30 s), and no withdrawn entry reaches the venue;
  - every send follows CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, first in first out within a
    kind, judged from the soak's own record of what is waiting, not from the pacer's;
  - the venue never answers 429;
  - every action is either sent exactly once or withdrawn by its caller; nothing else is lost.

What the budget counts: every request it lets through, of all five kinds, because Alpaca's
200 a minute counts queries too. An entry that would eat the protection reserve waits, as
anything past the budget does. Not in the soak, and covered by the harvested tests: an entry
whose reserve reaches the burst is refused; one whose reserve cannot be worked out is dropped
silently.
The soak keeps one record in ``evidence/``: a passing run replaces the earlier one, and git
keeps the history.

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
RECORD_GLOB = "M2-order-budget-*-soak.json"
SEED = 20261112
SOAK_SECONDS = 3600
BACKLOG = 240
DEMAND_PER_MINUTE = 210
ENTRY_PATIENCE_S = 30
QUIET_EVERY_S = 1200  # one quiet spell in each 20 minutes of the run
QUIET_S = (120, 300)  # its length, seeded within this range
# Shares of the steady demand, by kind; each backlog is split evenly.
DEMAND_MIX = {
    ActionKind.CANCEL: 0.10,
    ActionKind.REDUCE: 0.10,
    ActionKind.MODIFY: 0.15,
    ActionKind.QUERY: 0.25,
    ActionKind.SUBMIT: 0.40,
}
# The required order, by name: what the soak judges against, not the pacer's own numbering.
PRIORITY = ("CANCEL", "REDUCE", "MODIFY", "QUERY", "SUBMIT")
RANK = {name: rank for rank, name in enumerate(PRIORITY)}
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
    withdrawn_ns: int | None = None  # when the pacer first asked and its caller said no
    sends: int = 0


@dataclass(frozen=True)
class Demand:
    script: list[tuple[int, ActionKind]]  # (request time ns, kind), in time order
    quiet: list[tuple[int, int]]  # (start ns, end ns) of each quiet spell
    backlogs: list[int]  # when each backlog arrives: at 0 and at the end of each quiet spell


@dataclass
class Soak:
    """Everything one simulated run leaves behind, for the record and for the tests."""

    seed: int
    seconds: int
    controls: Controls
    cap: int
    pacer: AccountPacer
    venue: SimulatedVenue
    plan: Demand
    actions: list[Action] = field(default_factory=list)
    sends: list[int] = field(default_factory=list)  # send times, in order
    priority_violations: int = 0
    sent_after_withdrawal: int = 0
    # The first time a window held the bucket's cap: its oldest send, what was waiting, and
    # (through the index into sends) the send that came next.
    cap_at_send: int | None = None
    cap_oldest_ns: int | None = None
    waiting_at_cap: Action | None = None
    ended_ns: int = 0  # the simulated time when the last action was sent or dropped


def demand(seed: int = SEED, seconds: int = SOAK_SECONDS) -> Demand:
    """The seeded demand script, its quiet spells and its backlogs."""
    rng = random.Random(seed)
    slot = QUIET_EVERY_S * SEC
    quiet = []
    for n in range(seconds // QUIET_EVERY_S):
        length = rng.randint(*QUIET_S) * SEC
        start = rng.randint(n * slot + slot // 4, (n + 1) * slot - slot // 4 - length)
        quiet.append((start, start + length))

    def backlog(at: int) -> list[tuple[int, ActionKind]]:
        kinds = [kind for kind in ActionKind for _ in range(BACKLOG // len(ActionKind))]
        rng.shuffle(kinds)
        return [(at, kind) for kind in kinds]

    script, backlogs = backlog(0), [0]
    kinds, weights = list(DEMAND_MIX), list(DEMAND_MIX.values())
    spells = iter(quiet)
    spell = next(spells, None)
    t = 0
    while True:
        t += max(1, int(rng.expovariate(DEMAND_PER_MINUTE / 60) * SEC))
        if spell is not None and t >= spell[0]:
            t = spell[1]  # nothing during the spell; a backlog at its end
            script += backlog(t)
            backlogs.append(t)
            spell = next(spells, None)
            continue
        if t >= seconds * SEC:
            return Demand(script, quiet, backlogs)
        script.append((t, rng.choices(kinds, weights)[0]))


def cap_per_window(controls: Controls) -> int:
    """The most the harvested bucket admits in any 60 s window, worked out from the controls
    with its own refill formula: a full burst, then one refill per interval. 179 for 180 and
    a burst of 18, because the interval rounds up."""
    window = controls.ns("window_s")
    interval = window // (controls["request_budget"] - controls.burst) + 1
    return controls.burst + (window - 1) // interval


def simulate(seed: int = SEED, seconds: int = SOAK_SECONDS) -> Soak:
    """Drive the pacer with the demand script until every action is sent or withdrawn."""
    clock = SimClock()
    # Fixture rows: the soak is a simulation (see rows.py).
    controls = Controls.from_rows(rows.control_rows(), fixture=True)
    pacer = AccountPacer(controls, clock.now)
    window_ns = controls.ns("window_s")
    venue = SimulatedVenue(controls["broker_limit"], window_ns)
    plan = demand(seed, seconds)
    soak = Soak(seed, seconds, controls, cap_per_window(controls), pacer, venue, plan)
    waiting: dict[str, deque[Action]] = {name: deque() for name in PRIORITY}
    trailing: deque[int] = deque()

    def admissible(action: Action) -> bool:
        return action.deadline_ns is None or clock.now() < action.deadline_ns

    def asks(action: Action) -> bool:
        """The admission the pacer calls: it notes when the caller first withdraws the action,
        so an action the pacer drops while its caller still wants it counts as lost."""
        if admissible(action):
            return True
        if action.withdrawn_ns is None:
            action.withdrawn_ns = clock.now()
        return False

    def oldest_waiting(name: str) -> Action | None:
        queue = waiting[name]
        while queue and not admissible(queue[0]):  # its caller has withdrawn it
            queue.popleft()
        return queue[0] if queue else None

    def make_send(action: Action) -> Callable[[Callable[[], None]], None]:
        def send(mark: Callable[[], None]) -> None:
            mark()  # the pacer's on-wire hook: one admitted action, one request
            now = clock.now()
            action.sends += 1
            action.sent_ns = now
            soak.sends.append(now)
            if not admissible(action):
                soak.sent_after_withdrawal += 1
            # Judged from the soak's own waiting lists: a more urgent kind, or an older
            # action of the same kind, still waiting is a violation.
            mine = action.kind.name
            for name in PRIORITY[: RANK[mine] + 1]:
                first = oldest_waiting(name)
                if (
                    first is not None
                    and first is not action
                    and (name != mine or first.ident < action.ident)
                ):
                    soak.priority_violations += 1
                    break
            if action in waiting[mine]:
                waiting[mine].remove(action)
            if venue.receive(action.ident, now) == RATE_LIMITED:
                pacer.on_rate_limited()
            else:
                pacer.on_success()
            trailing.append(now)
            while trailing[0] <= now - window_ns:
                trailing.popleft()
            if soak.cap_at_send is None and len(trailing) >= soak.cap:
                soak.cap_at_send, soak.cap_oldest_ns = len(soak.sends) - 1, trailing[0]
                soak.waiting_at_cap = next(
                    (a for a in map(oldest_waiting, PRIORITY) if a is not None), None
                )

        return send

    script = plan.script
    steps, step_limit = 0, 50 * (len(script) + 100)
    i = 0
    while i < len(script) or pacer.queue:
        steps += 1
        if steps > step_limit or clock.t > (seconds + 3600) * SEC:
            raise RuntimeError(
                "the soak stopped making progress: the pacer neither sent nor dropped"
            )
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
            waiting[kind.name].append(action)
            pacer.request(kind, make_send(action), admission=lambda a=action: asks(a))
        else:
            assert due is not None
            clock.t = due
            pacer.drain()
    soak.ended_ns = clock.t
    return soak


def window_counts(times: list[int], window_ns: int) -> list[int]:
    """For each time, how many of the times fall in the window (t - window, t] ending at it."""
    return [i - bisect.bisect_right(times, t - window_ns) + 1 for i, t in enumerate(times)]


def _seconds(ns: int) -> float:
    return round(ns / SEC, 6)


def _steady_minutes(soak: Soak) -> list[int]:
    """Sends in each whole minute of steady demand: at least a minute after a backlog, before
    the next quiet spell, and before the demand stops."""
    window_ns = soak.controls.ns("window_s")
    quiet_starts = [start for start, _ in soak.plan.quiet] + [soak.seconds * SEC]
    counts = []
    for m in range(soak.seconds // 60):
        lo, hi = m * window_ns, (m + 1) * window_ns
        last_backlog = max(b for b in soak.plan.backlogs if b <= lo)
        next_quiet = min(q for q in quiet_starts if q > last_backlog)
        if lo >= last_backlog + window_ns and hi <= next_quiet:
            counts.append(bisect.bisect_left(soak.sends, hi) - bisect.bisect_left(soak.sends, lo))
    return counts


def record_data(soak: Soak) -> dict[str, Any]:
    """The run record's fields, all from the simulation (no wall-clock field)."""
    controls, pacer, venue = soak.controls, soak.pacer, soak.venue
    window_ns = controls.ns("window_s")
    counts = window_counts(soak.sends, window_ns)
    venue_times = [t for t, _ in venue.received]
    order_actions = sorted(
        a.sent_ns for a in soak.actions if a.sent_ns is not None and a.kind != ActionKind.QUERY
    )
    after_quiet = []
    for start, end in soak.plan.quiet:
        lo = bisect.bisect_left(soak.sends, end)
        hi = bisect.bisect_left(soak.sends, end + 2 * window_ns)
        after_quiet.append(
            {
                "quiet_from_s": _seconds(start),
                "quiet_to_s": _seconds(end),
                "most_sent_in_a_window_after": max(counts[lo:hi], default=0),
            }
        )
    steady = _steady_minutes(soak)
    requested = Counter(a.kind.name for a in soak.actions)
    sent = Counter(a.kind.name for a in soak.actions if a.sends)
    withdrawn = Counter(
        a.kind.name for a in soak.actions if not a.sends and a.withdrawn_ns is not None
    )
    longest: dict[str, int] = {}
    for a in soak.actions:
        if a.sent_ns is not None:
            longest[a.kind.name] = max(longest.get(a.kind.name, 0), a.sent_ns - a.requested_ns)
    cap_at, waiting = soak.cap_at_send, soak.waiting_at_cap
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
            "cap_per_window_from_the_refill_arithmetic": soak.cap,
            "priority": " > ".join(PRIORITY) + ", first in first out within a kind",
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
            "backlog_size": BACKLOG,
            "backlogs_at_s": [_seconds(b) for b in soak.plan.backlogs],
            "quiet_spells_s": [[_seconds(s), _seconds(e)] for s, e in soak.plan.quiet],
            "steady_per_minute": DEMAND_PER_MINUTE,
            "steady_mix": {kind.name: share for kind, share in DEMAND_MIX.items()},
            "entry_withdrawn_if_unsent_after_s": ENTRY_PATIENCE_S,
            "requested": {name: requested[name] for name in PRIORITY},
        },
        "observed": {
            "sent": {name: sent[name] for name in PRIORITY},
            "withdrawn_by_caller": {name: withdrawn[name] for name in PRIORITY},
            "lost": len(soak.actions) - sum(sent.values()) - sum(withdrawn.values()),
            "sent_after_withdrawal": soak.sent_after_withdrawal,
            "sent_twice": sum(1 for a in soak.actions if a.sends > 1),
            "priority_violations": soak.priority_violations,
            "most_sent_in_any_window": max(counts, default=0),
            "most_order_actions_in_any_window": max(
                window_counts(order_actions, window_ns), default=0
            ),
            "sent_in_the_first_minute": bisect.bisect_left(soak.sends, window_ns),
            "after_each_quiet_spell": after_quiet,
            "steady_minutes": {
                "count": len(steady),
                "fewest_sent": min(steady, default=0),
                "most_sent": max(steady, default=0),
            },
            "when_a_window_first_held_the_cap": None
            if cap_at is None
            else {
                "at_ns": soak.sends[cap_at],
                "oldest_send_in_window_ns": soak.cap_oldest_ns,
                "waiting": None
                if waiting is None
                else {"kind": waiting.kind.name, "requested_at_ns": waiting.requested_ns},
                "next_send_at_ns": soak.sends[cap_at + 1] if cap_at + 1 < len(soak.sends) else None,
            },
            "longest_wait_s": {n: _seconds(longest[n]) for n in PRIORITY if n in longest},
            "wire_counters": pacer.to_state("simulated"),
        },
    }


def problems(data: dict[str, Any]) -> list[str]:
    """What, if anything, makes this soak a failure."""
    found: list[str] = []
    budget = data["budget"]["request_budget_per_window"]
    burst = data["budget"]["burst"]
    cap = data["budget"]["cap_per_window_from_the_refill_arithmetic"]
    seen, venue = data["observed"], data["simulated_venue"]
    most = seen["most_sent_in_any_window"]
    if most > budget:
        found.append(f"a 60 s window held {most} requests, over the budget of {budget}")
    if most < budget - 1:
        found.append(f"no window came within one of the budget (most {most} of {budget})")
    if most != cap:
        found.append(f"the busiest window held {most} requests, not the bucket's cap of {cap}")
    for spell in seen["after_each_quiet_spell"]:
        after = spell["most_sent_in_a_window_after"]
        if not budget - 1 <= after <= budget:
            found.append(f"after the quiet spell to {spell['quiet_to_s']} s a window held {after}")
    steady = seen["steady_minutes"]
    if not steady["count"]:
        found.append("no whole minute of steady demand to measure")
    elif steady["fewest_sent"] < budget - burst - 1:
        found.append(f"a minute of steady demand sent only {steady['fewest_sent']}")
    if venue["rate_limited_answers"]:
        found.append("the simulated venue answered 429")
    if venue["most_requests_in_any_window"] > budget:
        found.append("the simulated venue saw more requests in a window than the budget")
    if venue["requests_received"] != seen["wire_counters"]["requests"]:
        found.append("the pacer's wire count differs from what the venue received")
    if seen["priority_violations"]:
        found.append("an action was sent while a more urgent or older one was still waiting")
    if seen["sent_twice"]:
        found.append("an action was sent more than once")
    if seen["sent_after_withdrawal"]:
        found.append("an entry reached the venue after its caller had withdrawn it")
    if seen["lost"]:
        found.append("an action was neither sent nor withdrawn by its caller")
    if not seen["withdrawn_by_caller"][ActionKind.SUBMIT.name]:
        found.append("no entry was withdrawn, so the withdrawal path went untested")
    full = seen["when_a_window_first_held_the_cap"]
    if full is None:
        found.append("no window ever held the bucket's cap")
    else:
        if full["waiting"] is None:
            found.append("nothing was waiting when a window first held the cap")
        room_at = full["oldest_send_in_window_ns"] + data["budget"]["window_ns"]
        if full["next_send_at_ns"] is not None and full["next_send_at_ns"] < room_at:
            found.append("the action past the budget was sent while the window was full")
    return found


def run_soak(seed: int = SEED, seconds: int = SOAK_SECONDS) -> dict[str, Any]:
    """Simulate and return the record (result and problems included), timestamps aside."""
    data = record_data(simulate(seed, seconds))
    found = problems(data)
    return {**data, "result": "fail" if found else "pass", "problems": found}


def write_record(record: dict[str, Any], root: Path | None = None) -> tuple[bool, Path]:
    """A pass goes to evidence/ and replaces the earlier soak record; a failure goes to the
    ignored runs/ folder."""
    root = REPO_ROOT if root is None else root
    passed = record["result"] == "pass" and not record["problems"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = root / ("evidence" if passed else "runs")
    path = folder / RECORD_GLOB.replace("*", stamp)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if passed:
        for older in folder.glob(RECORD_GLOB):
            if older != path:
                older.unlink()
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
        f"{sum(seen['withdrawn_by_caller'].values())} stale entries withdrawn unsent; "
        f"{record['simulated_venue']['rate_limited_answers']} answered 429. "
        f"Record: {path.relative_to(REPO_ROOT)}"
    )
    for problem in record["problems"]:
        print(f"  - {problem}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
