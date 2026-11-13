"""
The order budget's soak: it holds the 180 budget against a simulated venue, refuses what is
past it, keeps the priority order, and the committed run record is what the soak produces.
"""

import copy
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from meridian.order_budget import controls as controls_module
from meridian.order_budget import pacer as pacer_module
from meridian.order_budget import rows, soak
from meridian.order_budget.controls import SEC, Controls

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def record():
    return soak.run_soak()


def test_the_soak_holds_the_budget_and_refuses_what_is_past_it(record):
    assert record["result"] == "pass", record["problems"]
    budget, seen = record["budget"], record["observed"]
    assert budget["request_budget_per_window"] == 180
    assert budget["broker_limit_per_window"] == 200
    # Never more than the budget in any rolling 60 s window: 179 is the bucket's own cap.
    assert seen["most_sent_in_any_window"] == budget["cap_per_window_from_the_refill_arithmetic"]
    assert seen["most_sent_in_any_window"] <= 180
    assert record["simulated_venue"]["most_requests_in_any_window"] <= 180
    assert record["simulated_venue"]["rate_limited_answers"] == 0
    # The demand went past the budget, and what was past it never reached the venue.
    assert seen["refused_unsent"]["SUBMIT"] > 0
    assert seen["refused_unsent"]["CANCEL"] == seen["refused_unsent"]["REDUCE"] == 0
    assert seen["priority_violations"] == 0
    assert seen["sent_twice"] == seen["left_in_queue"] == 0


def test_the_action_past_a_full_window_waits_until_the_window_has_room(record):
    full = record["observed"]["when_a_window_was_first_full"]
    assert full["sent_in_window"] == record["observed"]["most_sent_in_any_window"]
    assert record["budget"]["window_ns"] == 60 * SEC
    room_at = full["oldest_send_in_window_ns"] + record["budget"]["window_ns"]
    assert full["next_action"]["requested_at_ns"] < full["at_ns"]  # it was already waiting
    assert full["next_action"]["sent_at_ns"] >= room_at


def test_withdrawn_entries_never_reach_the_venue():
    run = soak.simulate(seconds=600)
    received = {ident for _, ident in run.venue.received}
    refused = [a for a in run.actions if not a.sends]
    assert refused, "the short run should still go past the budget"
    assert all(a.kind == pacer_module.ActionKind.SUBMIT for a in refused)
    assert received.isdisjoint(a.ident for a in refused)
    assert all(
        a.sent_ns is None or a.deadline_ns is None or a.sent_ns < a.deadline_ns for a in run.actions
    )
    assert len(received) == sum(1 for a in run.actions if a.sends)


def test_the_soak_opens_no_socket(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the soak tried to open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert soak.run_soak(seconds=120)["result"] == "pass"


def test_the_committed_record_is_what_the_soak_produces(record):
    paths = sorted((REPO_ROOT / "evidence").glob("M2-order-budget-*-soak.json"))
    assert len(paths) == 1, "keep exactly one soak record in evidence/: the latest"
    path = paths[0]
    committed = json.loads(path.read_text(encoding="utf-8"))
    for name in soak.WALL_CLOCK_FIELDS:
        assert committed.pop(name)
    assert committed == json.loads(json.dumps(record))
    # The file is written the way the M1 records are: sorted keys, two spaces, one newline.
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_a_record_is_written_to_evidence_only_on_a_pass(tmp_path, record):
    passed, path = soak.write_record(copy.deepcopy(record), root=tmp_path)
    assert passed and path.parent == tmp_path / "evidence"
    failing = copy.deepcopy(record) | {"result": "fail", "problems": ["x"]}
    passed, path = soak.write_record(failing, root=tmp_path)
    assert not passed and path.parent == tmp_path / "runs"


# --- the soak's checks can fail ------------------------------------------------------------


def failing(change):
    def apply(data):
        change(data)
        return data

    return apply


RECORD_FAILURES = {
    "a window over the budget": failing(
        lambda d: d["observed"].update(most_sent_in_any_window=181)
    ),
    "a cap over the budget": failing(
        lambda d: d["budget"].update(cap_per_window_from_the_refill_arithmetic=181)
    ),
    "the budget never used": failing(lambda d: d["observed"].update(most_sent_in_any_window=150)),
    "a 429": failing(lambda d: d["simulated_venue"].update(rate_limited_answers=1)),
    "the venue saw too much": failing(
        lambda d: d["simulated_venue"].update(most_requests_in_any_window=181)
    ),
    "wire count differs": failing(lambda d: d["simulated_venue"].update(requests_received=1)),
    "priority inverted": failing(lambda d: d["observed"].update(priority_violations=1)),
    "sent twice": failing(lambda d: d["observed"].update(sent_twice=1)),
    "left queued": failing(lambda d: d["observed"].update(left_in_queue=1)),
    "an action lost": failing(lambda d: d["demand"]["requested"].update(QUERY=1)),
    "a cancel refused": failing(lambda d: d["observed"]["refused_unsent"].update(CANCEL=1)),
    "a reduce refused": failing(lambda d: d["observed"]["refused_unsent"].update(REDUCE=1)),
    "nothing refused": failing(lambda d: d["observed"]["refused_unsent"].update(SUBMIT=0)),
    "nothing waiting when full": failing(
        lambda d: d["observed"]["when_a_window_was_first_full"].update(next_action=None)
    ),
    "the next action sent into a full window": failing(
        lambda d: d["observed"]["when_a_window_was_first_full"]["next_action"].update(
            sent_at_ns=d["observed"]["when_a_window_was_first_full"]["at_ns"]
        )
    ),
}


@pytest.mark.parametrize("name", sorted(RECORD_FAILURES))
def test_each_check_fails_a_record_that_breaks_it(record, name):
    data = RECORD_FAILURES[name](copy.deepcopy(record))
    assert soak.problems(data), name


def test_the_soak_fails_when_the_bucket_lets_everything_through(monkeypatch):
    monkeypatch.setattr(pacer_module.TokenBucket, "take", lambda self, now: True)
    found = soak.run_soak(seconds=120)["problems"]
    assert any("over the budget" in p for p in found)
    assert "the simulated venue answered 429" in found


def test_the_soak_fails_when_the_queue_ignores_priority(monkeypatch):
    # First come, first served instead of the pacer's (kind, sequence) heap.
    fifo = SimpleNamespace(
        heappush=lambda heap, item: heap.append(item), heappop=lambda heap: heap.pop(0)
    )
    monkeypatch.setattr(pacer_module, "heapq", fifo)
    found = soak.run_soak(seconds=120)["problems"]
    assert "an action was sent while a more urgent one was still waiting" in found


# --- the venue and the rows ---------------------------------------------------------------


def test_the_simulated_venue_answers_429_past_its_limit():
    venue = soak.SimulatedVenue(limit=3, window_ns=60 * SEC)
    assert [venue.receive(i, i * SEC) for i in range(4)] == [200, 200, 200, 429]
    assert venue.receive(4, 60 * SEC) == 200  # the first request has left the window
    assert venue.rate_limited == 1 and len(venue.received) == 4


def test_the_budget_cannot_be_set_above_the_broker_limit():
    with pytest.raises(ValueError, match="exceeds broker limit"):
        rows.controls(request_budget=201)


def test_fixture_rows_are_never_runtime_authority():
    with pytest.raises(ValueError, match="fixture is not deployment authority"):
        Controls.from_rows(rows.control_rows())


def test_the_rows_are_the_owners_fixture_values():
    c = rows.controls()
    assert (c["request_budget"], c["broker_limit"], c.ns("window_s"), c.burst) == (
        180,
        200,
        60 * SEC,
        18,
    )
    assert set(rows.FIXTURE_VALUES) == controls_module.NAMES
