"""
The order budget's soak: it holds the 180 budget against a simulated venue, after quiet spells
as under steady demand, holds back what is past it, keeps the priority order, and the committed
run record is what the soak produces. Each check is shown to fail on a record or a pacer that
breaks it.
"""

import ast
import copy
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from order_budget_fixtures import controls
from test_public_tree import tracked_files

from meridian.order_budget import pacer as pacer_module
from meridian.order_budget import rows, soak
from meridian.order_budget.controls import SEC, Controls

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def record():
    return soak.run_soak()


def test_the_soak_keeps_to_the_budget_and_holds_back_what_is_past_it(record):
    assert record["result"] == "pass", record["problems"]
    budget, seen = record["budget"], record["observed"]
    assert (budget["request_budget_per_window"], budget["broker_limit_per_window"]) == (180, 200)
    # Never more than the budget in any rolling 60 s window, and the budget used: 179 is the
    # bucket's own cap (its refill interval rounds up).
    assert seen["most_sent_in_any_window"] == 179
    assert budget["cap_per_window_from_the_refill_arithmetic"] == 179
    assert record["simulated_venue"]["most_requests_in_any_window"] <= 180
    assert record["simulated_venue"]["rate_limited_answers"] == 0
    # The simulated caller withdrew its stale entries, and none of them was sent.
    assert seen["withdrawn_by_caller"]["SUBMIT"] > 0
    assert sum(seen["withdrawn_by_caller"].values()) == seen["withdrawn_by_caller"]["SUBMIT"]
    assert seen["lost"] == seen["sent_after_withdrawal"] == seen["sent_twice"] == 0
    assert seen["priority_violations"] == 0


def test_after_each_quiet_spell_the_full_bucket_still_keeps_to_the_budget(record):
    spells = record["observed"]["after_each_quiet_spell"]
    assert len(spells) == 3
    assert all(s["quiet_to_s"] - s["quiet_from_s"] >= 120 for s in spells)
    assert all(s["most_sent_in_a_window_after"] == 179 for s in spells)


def test_steady_demand_gets_the_rest_of_the_budget(record):
    steady = record["observed"]["steady_minutes"]
    assert steady["count"] >= 30
    assert steady["fewest_sent"] >= 180 - 18 - 1  # budget minus burst: the burst is shared


def test_the_action_past_a_full_window_waits_until_the_window_has_room(record):
    full = record["observed"]["when_a_window_first_held_the_cap"]
    window = record["budget"]["window_ns"]
    assert full["waiting"] is not None and full["waiting"]["requested_at_ns"] < full["at_ns"]
    assert full["next_send_at_ns"] >= full["oldest_send_in_window_ns"] + window


def test_withdrawn_entries_never_reach_the_venue():
    run = soak.simulate(seconds=1200)
    received = {ident for _, ident in run.venue.received}
    unsent = [a for a in run.actions if not a.sends]
    assert unsent, "the run should still go past the budget"
    assert all(a.kind == pacer_module.ActionKind.SUBMIT for a in unsent)
    assert received.isdisjoint(a.ident for a in unsent)
    for a in run.actions:
        if a.sent_ns is not None and a.deadline_ns is not None:
            assert a.sent_ns < a.deadline_ns


def test_the_soak_opens_no_socket(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the soak tried to open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert soak.run_soak(seconds=1200)["result"] == "pass"


def test_the_committed_record_is_what_the_soak_produces(record):
    # What git sees, new files included and deleted ones left out, as the public-tree scan.
    paths = sorted(p for p in tracked_files() if Path(p).match(f"evidence/{soak.RECORD_GLOB}"))
    assert len(paths) == 1, f"keep exactly one soak record in evidence/, found {paths}"
    text = (REPO_ROOT / paths[0]).read_text(encoding="utf-8")
    committed = json.loads(text)
    # Written the way the M1 records are: sorted keys, two spaces, one trailing newline.
    assert text == json.dumps(committed, indent=2, sort_keys=True) + "\n"
    for name in soak.WALL_CLOCK_FIELDS:
        assert committed.pop(name)
    assert committed == json.loads(json.dumps(record))


def test_a_pass_replaces_the_earlier_record_and_a_failure_goes_to_runs(tmp_path, record):
    (tmp_path / "evidence").mkdir()
    older = tmp_path / "evidence" / "M2-order-budget-20200101T000000Z-soak.json"
    older.write_text("{}\n", encoding="utf-8")
    keep = tmp_path / "evidence" / "M1-ibkr-paper-20200101T000000Z-order.json"
    keep.write_text("{}\n", encoding="utf-8")
    passed, path = soak.write_record(copy.deepcopy(record), root=tmp_path)
    assert passed and path.parent == tmp_path / "evidence"
    assert not older.exists() and keep.exists()
    failing = copy.deepcopy(record) | {"result": "fail", "problems": ["x"]}
    passed, failed = soak.write_record(failing, root=tmp_path)
    assert not passed and failed.parent == tmp_path / "runs" and path.exists()


# --- each check fails a record that breaks it -----------------------------------------------


def change(path, value):
    def apply(data):
        *keys, last = path
        target = data
        for key in keys:
            target = target[key]
        target[last] = value(target[last]) if callable(value) else value

    return apply


def first_spell_at(count):
    return lambda spells: [spells[0] | {"most_sent_in_a_window_after": count}, *spells[1:]]


FULL = ("observed", "when_a_window_first_held_the_cap")
RECORD_FAILURES = {
    "over the budget": (change(("observed", "most_sent_in_any_window"), 181), "over the budget"),
    "budget unused": (change(("observed", "most_sent_in_any_window"), 150), "within one of"),
    "cap over budget": (
        change(("budget", "cap_per_window_from_the_refill_arithmetic"), 181),
        "not the bucket's cap",
    ),
    "after a quiet spell": (
        change(("observed", "after_each_quiet_spell"), first_spell_at(181)),
        "after the quiet spell",
    ),
    "a slow steady minute": (
        change(("observed", "steady_minutes", "fewest_sent"), 150),
        "a minute of steady demand sent only 150",
    ),
    "no steady minute": (change(("observed", "steady_minutes", "count"), 0), "no whole minute"),
    "a 429": (change(("simulated_venue", "rate_limited_answers"), 1), "answered 429"),
    "the venue saw too much": (
        change(("simulated_venue", "most_requests_in_any_window"), 181),
        "more requests in a window",
    ),
    "wire count": (change(("simulated_venue", "requests_received"), 1), "wire count differs"),
    "priority": (change(("observed", "priority_violations"), 1), "more urgent or older"),
    "sent twice": (change(("observed", "sent_twice"), 1), "more than once"),
    "a withdrawn entry sent": (
        change(("observed", "sent_after_withdrawal"), 1),
        "after its caller had withdrawn it",
    ),
    "an action lost": (change(("observed", "lost"), 1), "neither sent nor withdrawn"),
    "nothing withdrawn": (
        change(("observed", "withdrawn_by_caller", "SUBMIT"), 0),
        "the withdrawal path went untested",
    ),
    "the cap never held": (change(FULL, None), "no window ever held"),
    "nothing waiting at the cap": (change((*FULL, "waiting"), None), "nothing was waiting"),
    "the next send into a full window": (
        change((*FULL, "next_send_at_ns"), lambda t: t - SEC),
        "sent while the window was full",
    ),
}


@pytest.mark.parametrize("name", sorted(RECORD_FAILURES))
def test_each_check_fails_a_record_that_breaks_it(record, name):
    apply, expected = RECORD_FAILURES[name]
    data = copy.deepcopy(record)
    apply(data)
    found = soak.problems(data)
    assert any(expected in p for p in found), (name, found)


# --- and a pacer that breaks it --------------------------------------------------------------


def test_the_soak_fails_a_bucket_that_lets_everything_through(monkeypatch):
    monkeypatch.setattr(pacer_module.TokenBucket, "take", lambda self, now: True)
    found = soak.run_soak(seconds=1200)["problems"]
    assert any("over the budget" in p for p in found)
    assert "the simulated venue answered 429" in found


def test_the_soak_fails_a_bucket_that_overfills_while_quiet(monkeypatch):
    def refill_without_cap(self, now):  # the harvested refill, minus its min(burst, ...)
        if self.anchor is None:
            self.anchor = now
            return
        credits = max(0, (now - self.anchor) // self.interval_ns)
        if credits:
            self.tokens += credits
            self.anchor += credits * self.interval_ns

    monkeypatch.setattr(pacer_module.TokenBucket, "refill", refill_without_cap)
    found = soak.run_soak(seconds=1200)["problems"]
    assert any("after the quiet spell" in p for p in found), found


def test_the_soak_fails_a_slow_bucket(monkeypatch):
    original = pacer_module.TokenBucket.__init__

    def slow(self, limit, window_ns, burst):
        original(self, limit, window_ns, burst)
        self.interval_ns *= 2

    monkeypatch.setattr(pacer_module.TokenBucket, "__init__", slow)
    found = soak.run_soak(seconds=1200)["problems"]
    assert any("within one of" in p for p in found)
    assert any("a minute of steady demand sent only" in p for p in found)


def test_the_soak_fails_a_queue_that_ignores_priority(monkeypatch):
    # First come, first served instead of the pacer's (kind, sequence) heap.
    fifo = SimpleNamespace(
        heappush=lambda heap, item: heap.append(item), heappop=lambda heap: heap.pop(0)
    )
    monkeypatch.setattr(pacer_module, "heapq", fifo)
    found = soak.run_soak(seconds=1200)["problems"]
    assert "an action was sent while a more urgent or older one was still waiting" in found


def test_the_soak_fails_a_pacer_that_ignores_a_withdrawal(monkeypatch):
    request = pacer_module.AccountPacer.request

    def deaf(self, kind, send, **kwargs):
        return request(self, kind, send, **{**kwargs, "admission": lambda: True})

    monkeypatch.setattr(pacer_module.AccountPacer, "request", deaf)
    found = soak.run_soak(seconds=1200)["problems"]
    assert "an entry reached the venue after its caller had withdrawn it" in found


def test_the_soak_stops_on_a_pacer_that_makes_no_progress(monkeypatch):
    monkeypatch.setattr(pacer_module.AccountPacer, "drain", lambda self: None)
    with pytest.raises(RuntimeError, match="stopped making progress"):
        soak.simulate(seconds=120)


# --- the pacer's 429 pause, the venue and the rows ---------------------------------------------


def test_a_429_holds_every_request_for_the_backoff_even_with_tokens_left():
    clock = [0]
    p = pacer_module.AccountPacer(controls(), lambda: clock[0])
    p.on_rate_limited()  # the first 429: a pause of backoff_base_s, 1 s
    p.bucket.tokens = p.bucket.burst  # tokens are back; only the pause can hold the request
    sent = []
    p.request(pacer_module.ActionKind.CANCEL, lambda mark: (mark(), sent.append(clock[0])))
    clock[0] = SEC - 1
    p.drain()
    assert sent == []
    clock[0] = SEC
    p.drain()
    assert sent == [SEC]
    p.on_rate_limited()  # a second 429 in a row doubles the pause
    assert p.paused_until == SEC + 2 * SEC
    p.on_success()
    assert p.consecutive_429 == 0


def test_the_simulated_venue_answers_429_past_its_limit():
    venue = soak.SimulatedVenue(limit=3, window_ns=60 * SEC)
    assert [venue.receive(i, i * SEC) for i in range(4)] == [200, 200, 200, 429]
    assert venue.receive(4, 60 * SEC) == 200  # the first request has left the window
    assert venue.rate_limited == 1 and len(venue.received) == 4


def test_the_budget_cannot_be_set_above_the_broker_limit():
    with pytest.raises(ValueError, match="exceeds broker limit"):
        controls(request_budget=201)


def test_fixture_rows_are_refused_as_a_lanes_authority():
    with pytest.raises(ValueError, match="fixture is not deployment authority"):
        Controls.from_rows(rows.control_rows())


def fixture_true_calls(source: str) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.keyword)
        and node.arg == "fixture"
        and not (isinstance(node.value, ast.Constant) and node.value.value is False)
    )


def test_the_package_itself_builds_controls_from_fixture_rows_only_in_the_soak():
    package = REPO_ROOT / "meridian" / "order_budget"
    callers = {
        p.name: n
        for p in sorted(package.glob("*.py"))
        if (n := fixture_true_calls(p.read_text(encoding="utf-8")))
    }
    assert callers == {"soak.py": 1}  # the simulation, in plain view
    assert fixture_true_calls("Controls.from_rows(rows, fixture=True)") == 1
    assert fixture_true_calls("Controls.from_rows(rows, fixture=flag)") == 1
    assert fixture_true_calls("Controls.from_rows(rows)") == 0
