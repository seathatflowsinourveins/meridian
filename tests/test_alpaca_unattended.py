"""The unattended Alpaca lane (M7) on fake keys, directories, clock and node only.

No test runs sudo, installs a unit or starts a service: the units and setup.sh are read as text.
"""

import json
import os
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from order_budget_fixtures import control_rows

from meridian import alpaca_lane, alpaca_node, alpaca_unattended, ibkr_paper
from meridian.alpaca.credentials import PaperKeys
from meridian.alpaca_sessions import NEW_YORK, session_at

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy" / "systemd"
SERVICE = SYSTEMD / "meridian-alpaca-paper@.service"
TIMERS = {"restart": SYSTEMD / "meridian-alpaca-restart.timer"}
TIMERS["order"] = SYSTEMD / "meridian-alpaca-order.timer"
SETUP = ROOT / "deploy" / "wsl" / "setup.sh"
# Monday 2026-11-16, 15:00 UTC is 10:00 in New York (EST).
IN_HOURS = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root can write read-only files")


@pytest.fixture
def unit(tmp_path, monkeypatch):
    """A fake unit: its directories, an owner-held settings file with consent, fake keys."""
    state, config, creds = tmp_path / "state", tmp_path / "config", tmp_path / "creds"
    for path in (state, config, creds):
        path.mkdir()
    rows = control_rows()
    for row in rows:
        row["scope"] = "REVIEWED"
    (config / "rows.json").write_text(json.dumps(rows))
    settings = {
        "order_budget_rows_path": "rows.json",
        "quote_max_age_ns": 42,
        "unattended_orders_enabled": True,
    }
    (config / "alpaca-lane.json").write_text(json.dumps(settings))
    lock_down(config)
    monkeypatch.setattr(alpaca_lane, "load_paper_keys", lambda: PaperKeys("fake-id", "fake-key"))
    monkeypatch.setattr(alpaca_unattended, "_now", lambda: IN_HOURS)
    env = {
        "INVOCATION_ID": "fake",
        "CREDENTIALS_DIRECTORY": str(creds),
        "STATE_DIRECTORY": str(state),
        "CONFIGURATION_DIRECTORY": str(config),
    }
    yield env
    unlock(config)


def lock_down(config: Path) -> None:
    for path in config.iterdir():
        path.chmod(0o444)
    config.chmod(0o555)


def unlock(config: Path) -> None:
    config.chmod(0o755)
    for path in config.iterdir():
        path.chmod(0o644)


def edit_settings(env, **changes) -> None:
    config = Path(env["CONFIGURATION_DIRECTORY"])
    unlock(config)
    path = config / "alpaca-lane.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps({k: v for k, v in data.items() if v != "drop"}))
    lock_down(config)


def fake_node(result: str = "pass"):
    """Stand-in for alpaca_node.run: fills the record as a pass, a fill, or crashes."""
    calls = []

    def run(state, record, log_dir=None):
        calls.append(log_dir)
        if result == "crash":
            raise RuntimeError("private-engine-text")
        record.trader_started(
            instrument_open_orders=0,
            instrument_open_positions=0,
            account_open_orders=0,
            account_open_positions=0,
        )
        order = record.data["mode"] == "order"
        record.at_stop(
            instrument_open_orders=0,
            instrument_open_positions=0,
            instrument_inflight_orders=0,
            execution_healthy=True,
            order_status="CANCELED" if order else None,
            filled=result == "fill",
        )
        if order:
            record.order_built(type="LIMIT", time_in_force="DAY", side="BUY", quantity="1")
            record.event("OrderAccepted", 1)
            record.data["venue_working_seen"] = True  # venue `new` proved routing
            record.event("OrderFilled" if result == "fill" else "OrderCanceled", 2)
        record.reason("fake", "private-engine-text")

    return run, calls


def hold(env) -> Path:
    return Path(env["STATE_DIRECTORY"]) / "hold"


def marker(env) -> Path:
    return Path(env["STATE_DIRECTORY"]) / "run-marker"


# Refusals, each with fixed, value-free text.


@pytest.mark.parametrize(
    "missing",
    ["INVOCATION_ID", "CREDENTIALS_DIRECTORY", "STATE_DIRECTORY", "CONFIGURATION_DIRECTORY"],
)
@pytest.mark.parametrize("mode", ["restart", "order"])
def test_outside_the_unit_refuses(unit, monkeypatch, capsys, missing, mode):
    monkeypatch.setattr(alpaca_node, "run", lambda *a: pytest.fail("ran outside the unit"))
    env = {k: v for k, v in unit.items() if k != missing}
    assert alpaca_unattended.main([mode], env) == 2
    err = capsys.readouterr().err
    assert err == f"REFUSED TO START: {alpaca_unattended.NOT_UNDER_UNIT}\n"


def test_missing_credentials_refuse(unit, monkeypatch, capsys):
    def missing():
        raise RuntimeError("private-credential-text")

    monkeypatch.setattr(alpaca_lane, "load_paper_keys", missing)
    monkeypatch.setattr(alpaca_node, "run", lambda *a: pytest.fail("ran without keys"))
    assert alpaca_unattended.main(["order"], unit) == 2
    assert capsys.readouterr().err == "REFUSED TO START: paper credentials unavailable\n"


@pytest.mark.parametrize("writable", ["settings", "config", "rows"])
@pytest.mark.parametrize("mode", ["restart", "order"])
def test_settings_the_service_user_could_write_refuse(unit, monkeypatch, capsys, writable, mode):
    config = Path(unit["CONFIGURATION_DIRECTORY"])
    target = {"settings": config / "alpaca-lane.json", "config": config}.get(
        writable, config / "rows.json"
    )
    target.chmod(0o755 if target.is_dir() else 0o644)
    monkeypatch.setattr(alpaca_node, "run", lambda *a: pytest.fail("ran on writable settings"))
    assert alpaca_unattended.main([mode], unit) == 2
    assert capsys.readouterr().err == f"REFUSED TO START: {alpaca_unattended.NOT_OWNER_HELD}\n"


@pytest.mark.parametrize("consent", [None, False, "drop"])
def test_order_needs_the_owners_consent_and_restart_does_not(unit, monkeypatch, capsys, consent):
    edit_settings(unit, unattended_orders_enabled=consent)
    run, calls = fake_node()
    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["order"], unit) == 2
    assert capsys.readouterr().err == f"REFUSED TO START: {alpaca_unattended.NO_CONSENT}\n"
    assert not calls and not hold(unit).exists()
    assert alpaca_unattended.main(["restart"], unit) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("consent", ["yes", 1, "true"])
def test_consent_is_only_the_literal_true(unit, capsys, consent):
    edit_settings(unit, unattended_orders_enabled=consent)
    assert alpaca_unattended.main(["order"], unit) == 2
    assert "local settings unavailable or invalid" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("now", "inside"),
    [
        (datetime(2026, 11, 16, 15, 0, tzinfo=UTC), True),  # Monday 10:00 New York, regular
        (datetime(2026, 11, 16, 14, 29, tzinfo=UTC), True),  # 09:29, pre-market
        (datetime(2026, 11, 17, 0, 59, tzinfo=UTC), True),  # Monday 19:59, after hours
        (datetime(2026, 11, 16, 3, 0, tzinfo=UTC), True),  # Sunday 22:00, overnight
        (datetime(2026, 11, 14, 15, 0, tzinfo=UTC), False),  # Saturday 10:00
        (datetime(2026, 11, 14, 1, 0, tzinfo=UTC), False),  # Friday 20:00, the week's end
        (datetime(2026, 11, 16, 0, 59, tzinfo=UTC), False),  # Sunday 19:59
        (datetime(2026, 7, 13, 14, 0, tzinfo=UTC), True),  # Monday 10:00 EDT
    ],
)
def test_order_runs_only_in_the_24_5_window(unit, monkeypatch, capsys, now, inside):
    monkeypatch.setattr(alpaca_unattended, "_now", lambda: now)
    run, calls = fake_node()
    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["order"], unit) == (0 if inside else 2)
    assert bool(calls) == inside
    if not inside:
        assert capsys.readouterr().err == f"REFUSED TO START: {alpaca_unattended.OUTSIDE_HOURS}\n"
    # restart keeps no window
    assert alpaca_unattended.main(["restart"], unit) == 0


def test_the_window_is_one_function_with_one_caller_on_the_session_module():
    source = Path(alpaca_unattended.__file__).read_text()
    assert source.count("order_window_open(") == 2  # the definition and the gate
    assert source.count("session_at(") == 1 and "in_regular_hours" not in source
    assert "ibkr_paper" not in source


def test_the_gate_asks_only_the_window_function(unit, monkeypatch):
    run, calls = fake_node()
    monkeypatch.setattr(alpaca_node, "run", run)
    monkeypatch.setattr(alpaca_unattended, "_now", lambda: datetime(2026, 11, 14, tzinfo=UTC))
    monkeypatch.setattr(alpaca_unattended, "order_window_open", lambda now: True)
    assert alpaca_unattended.main(["order"], unit) == 0 and calls


def test_a_second_run_at_once_refuses(unit, monkeypatch, capsys):
    run, _ = fake_node()
    monkeypatch.setattr(alpaca_node, "run", run)
    state = Path(unit["STATE_DIRECTORY"])
    with alpaca_unattended.lane_lock(state):
        assert alpaca_unattended.main(["restart"], unit) == 2
    assert capsys.readouterr().err == f"REFUSED TO START: {alpaca_unattended.BUSY}\n"
    assert alpaca_unattended.main(["restart"], unit) == 0


# The hold file's life cycle.


def test_a_passing_order_leaves_no_hold_and_its_record_in_the_state_directory(
    unit, monkeypatch, capsys
):
    run, calls = fake_node()
    seen = []

    def watched(state, record, log_dir=None):
        seen.append(json.loads(marker(unit).read_text()))  # marked while the engine runs
        run(state, record, log_dir)

    monkeypatch.setattr(alpaca_node, "run", watched)
    before = sorted(p.name for p in (ROOT / "evidence").iterdir())
    assert alpaca_unattended.main(["order"], unit) == 0
    assert capsys.readouterr().out.startswith("PASS")
    state = Path(unit["STATE_DIRECTORY"])
    assert seen and seen[0]["mode"] == "order"
    assert not hold(unit).exists() and not marker(unit).exists()
    assert calls == [state / "runs"]
    (public,) = (state / "evidence").iterdir()
    text = public.read_text()
    data = json.loads(text)
    assert data["result"] == "pass" and data["unattended"] is True and data["mode"] == "order"
    assert "private-engine-text" not in text and "local" not in data
    assert sorted(p.name for p in (ROOT / "evidence").iterdir()) == before


@pytest.mark.parametrize("result", ["fill", "crash"])
def test_a_failed_order_holds_and_later_orders_refuse_until_removed(
    unit, monkeypatch, capsys, result
):
    # A failure that reaches the end writes the hold; a crash or kill leaves the run marker.
    left, refusal = (marker, alpaca_unattended.MARKED) if result == "crash" else (hold, None)
    refusal = refusal or alpaca_unattended.HELD
    run, calls = fake_node(result)
    monkeypatch.setattr(alpaca_node, "run", run)
    with pytest.raises(RuntimeError) if result == "crash" else nullcontext():
        assert alpaca_unattended.main(["order"], unit) == 1
    written = json.loads(left(unit).read_text())
    assert written["mode"] == "order"
    assert "private" not in left(unit).read_text()
    assert not (marker if left is hold else hold)(unit).exists()
    # Held: order refuses; restart still runs and keeps the file.
    good, _ = fake_node()
    monkeypatch.setattr(alpaca_node, "run", good)
    capsys.readouterr()
    assert alpaca_unattended.main(["order"], unit) == 2
    assert capsys.readouterr().err == f"REFUSED TO START: {refusal}\n"
    assert alpaca_unattended.main(["restart"], unit) == 0
    assert json.loads(left(unit).read_text()) == written
    # The owner removes it; the next order runs.
    left(unit).unlink()
    assert alpaca_unattended.main(["order"], unit) == 0
    assert not hold(unit).exists() and not marker(unit).exists()


def test_a_failed_restart_writes_a_hold(unit, monkeypatch, capsys):
    run, _ = fake_node()

    def unclean(state, record, log_dir=None):
        run(state, record, log_dir)
        record.data["startup_reconciliation"]["instrument_open_orders_at_start"] = 1

    monkeypatch.setattr(alpaca_node, "run", unclean)
    assert alpaca_unattended.main(["restart"], unit) == 1
    written = json.loads(hold(unit).read_text())
    assert written["mode"] == "restart" and written["record"].endswith("-restart.json")
    assert not (Path(unit["STATE_DIRECTORY"]) / "evidence").exists()
    assert alpaca_unattended.main(["order"], unit) == 2


def test_status_prints_outcomes_and_the_hold_without_free_text(unit, monkeypatch, capsys):
    run, _ = fake_node("fill")
    monkeypatch.setattr(alpaca_node, "run", run)
    alpaca_unattended.main(["order"], unit)
    capsys.readouterr()
    state = unit["STATE_DIRECTORY"]
    assert alpaca_unattended.main(["status", "--state", state], {}) == 0
    out = capsys.readouterr().out
    assert re.search(r"M3-alpaca-paper-\d{8}T\d{6}Z-order\.json: fail ", out)
    assert "the order filled" in out and "HOLD since" in out
    assert "private" not in out


def test_status_of_an_empty_state(tmp_path, capsys):
    assert alpaca_unattended.main(["status", "--state", str(tmp_path)], {}) == 0
    assert capsys.readouterr().out == "no run records\nno hold file\n"


# The attended path is unchanged.


def test_attended_order_still_needs_the_typed_word_with_consent_set(tmp_path, monkeypatch):
    rows = control_rows()
    for row in rows:
        row["scope"] = "REVIEWED"
    (tmp_path / "rows.json").write_text(json.dumps(rows))
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "order_budget_rows_path": "rows.json",
                "quote_max_age_ns": 42,
                "unattended_orders_enabled": True,
            }
        )
    )
    monkeypatch.setattr(alpaca_lane, "load_paper_keys", lambda: PaperKeys("fake-id", "fake-key"))
    monkeypatch.setattr(alpaca_lane, "run_attended", lambda *a: pytest.fail("ran unconfirmed"))
    monkeypatch.setattr(ibkr_paper, "_at_terminal", lambda: False)
    assert alpaca_lane.main(["order", "--settings", str(settings)]) == 2
    monkeypatch.setattr(ibkr_paper, "_at_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert alpaca_lane.main(["order", "--settings", str(settings)]) == 2
    with pytest.raises(SystemExit):
        alpaca_lane.main(["--unattended", "order"])


# What the units and the script contain.


def unit_rows(path: Path) -> list[tuple[str, str, str]]:
    section, rows = "", []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line
            continue
        key, _, value = line.partition("=")
        rows.append((section, key, value))
    return rows


def test_the_service_is_a_oneshot_with_unit_directories_and_no_install():
    rows = unit_rows(SERVICE)
    settings = {key: value for _, key, value in rows}
    assert settings["Type"] == "oneshot" and settings["User"] == "paper"
    assert settings["StateDirectory"] == "meridian-alpaca-paper"
    assert settings["ConfigurationDirectory"] == "meridian-alpaca-paper"
    assert settings["StateDirectoryMode"] == "0700"
    assert settings["WorkingDirectory"] == "/opt/meridian/current"
    assert "TimeoutStartSec" in settings and settings.get("Restart", "no") == "no"
    for key in ("ProtectSystem", "ProtectHome", "NoNewPrivileges", "CapabilityBoundingSet"):
        assert key in settings
    assert settings["ProtectSystem"] == "strict" and settings["ProtectHome"] == "yes"
    for path in (SERVICE, *TIMERS.values()):
        assert "[Install]" not in {section for section, _, _ in unit_rows(path)}, path.name


@pytest.mark.parametrize("mode", ["restart", "order"])
def test_each_timer_starts_its_instance_inside_the_24_5_week(mode):
    rows = unit_rows(TIMERS[mode])
    assert ("[Timer]", "Unit", f"meridian-alpaca-paper@{mode}.service") in rows
    calendars = [value for _, key, value in rows if key == "OnCalendar"]
    assert calendars and all(c.endswith(" America/New_York") for c in calendars)
    assert "Persistent" not in {key for _, key, _ in rows}  # a missed run is not caught up
    if mode == "order":
        # Each line fires only in a real-time session: regular (IEX) or overnight. Pre-market
        # and after-hours quotes are delayed SIP and age at least 15 minutes.
        sessions = set()
        for calendar in calendars:
            days, clock, _ = calendar.split()
            hour, minute = map(int, clock.split(":"))
            for day in WEEK:
                if day.strftime("%a") in expand(days):
                    when = datetime.combine(day, time(hour, minute), NEW_YORK)
                    session = session_at(when)
                    assert session is not None, (calendar, day)
                    sessions.add(session.name)
        assert sessions == {"regular", "overnight"}


# Sunday 2026-11-15 to Saturday 2026-11-21, one of each weekday.
WEEK = [date(2026, 11, 15) + timedelta(days=n) for n in range(7)]
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def expand(spec: str) -> set[str]:
    out = set()
    for part in spec.split(","):
        first, _, last = part.partition("..")
        i, j = DAYS.index(first), DAYS.index(last or first)
        assert i <= j, f"systemd weekday ranges do not wrap: {part}"
        out.update(DAYS[i : j + 1])
    return out


def function_body(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", script, re.S | re.M)
    assert match, name
    return match.group(1)


def test_setup_enables_only_timers_and_its_checks_are_read_only():
    script = SETUP.read_text()
    assert re.search(r"^  unattended\) cmd_unattended ;;$", script, re.M)
    assert re.search(r"^  unattended-check\) cmd_unattended_check ;;$", script, re.M)
    body = function_body(script, "cmd_unattended")
    assert 'git -C "${src}" archive' in body and "--locked" in body
    assert "sudo test -e" in body  # settings files are created only if absent
    # It starts timers only, never a lane service, and never runs the lane or reads a key.
    for line in body.splitlines():
        if re.search(r"systemctl (enable|start|add-wants|restart)", line):
            assert '"${timer}"' in line, line
        assert "alpaca_unattended" not in line and "alpaca_lane" not in line, line
        assert "credstore" not in line and "systemd-creds" not in line, line
    assert "unattended_orders_enabled" not in script  # consent is never set by the step
    for name in ("check_unattended", "cmd_unattended_check"):
        check = function_body(script, name)
        assert not re.search(r"systemctl (enable|start|add-wants|daemon-reload|stop)", check)
        assert "install " not in check and "rm " not in check and "alpaca-lane.json" not in check
    assert "check_unattended" in function_body(script, "cmd_check")
    for path in TIMERS.values():
        assert path.name in script


# Review fixes (Codex, P2): a killed restart holds; status never hides an unreadable state.


def test_a_restart_marks_while_it_runs_and_a_crash_or_kill_leaves_the_marker(unit, monkeypatch):
    run, _ = fake_node()
    seen = []

    def watched(state, record, log_dir=None):
        seen.append(json.loads(marker(unit).read_text()))  # marked while reconciliation runs
        run(state, record, log_dir)

    monkeypatch.setattr(alpaca_node, "run", watched)
    assert alpaca_unattended.main(["restart"], unit) == 0
    assert seen and seen[0]["mode"] == "restart"
    assert not marker(unit).exists()  # a pass removes the run's own marker
    crash, _ = fake_node("crash")  # what the unit's timeout kill leaves: no code after the engine
    monkeypatch.setattr(alpaca_node, "run", crash)
    with pytest.raises(RuntimeError):
        alpaca_unattended.main(["restart"], unit)
    assert json.loads(marker(unit).read_text())["mode"] == "restart"
    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["order"], unit) == 2  # the next order stays refused
    assert alpaca_unattended.main(["restart"], unit) == 0  # a later restart keeps that marker
    assert marker(unit).exists()


# Codex review of the fitted branch (P2): an owner's hold written during a run survives it.


@pytest.mark.parametrize("mode", ["restart", "order"])
@pytest.mark.parametrize("replace", [False, True])
def test_a_hold_written_during_a_passing_run_survives_it(unit, monkeypatch, capsys, mode, replace):
    run, _ = fake_node()
    if replace:  # a hold already there for a restart, replaced by the owner mid-run
        hold(unit).write_text('{"reason": "an earlier hold"}\n')

    def owner_stops(state, record, log_dir=None):
        hold(unit).write_text('{"reason": "the owner stops the lane"}\n')
        run(state, record, log_dir)

    monkeypatch.setattr(alpaca_node, "run", owner_stops)
    if replace and mode == "order":
        assert alpaca_unattended.main([mode], unit) == 2  # an existing hold refuses order
        return
    assert alpaca_unattended.main([mode], unit) == 0
    assert hold(unit).read_text() == '{"reason": "the owner stops the lane"}\n'
    assert not marker(unit).exists()
    capsys.readouterr()
    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["order"], unit) == 2
    assert capsys.readouterr().err == f"REFUSED TO START: {alpaca_unattended.HELD}\n"


def test_a_failing_run_never_replaces_the_owners_hold(unit, monkeypatch):
    run, _ = fake_node()

    def unclean(state, record, log_dir=None):
        hold(unit).write_text('{"reason": "the owner stops the lane"}\n')
        run(state, record, log_dir)
        record.data["startup_reconciliation"]["instrument_open_orders_at_start"] = 1

    monkeypatch.setattr(alpaca_node, "run", unclean)
    assert alpaca_unattended.main(["restart"], unit) == 1
    assert hold(unit).read_text() == '{"reason": "the owner stops the lane"}\n'


# The lead: a closed venue is a skip, not a failure.


def closed_node(calendar: str):
    """The record a node leaves when nothing was sent: the calendar was read and said closed
    ("closed"), or the read failed and the node stopped with an error ("unread")."""

    def run(state, record, log_dir=None):
        record.trader_started(
            instrument_open_orders=0,
            instrument_open_positions=0,
            account_open_orders=0,
            account_open_positions=0,
        )
        if calendar == "closed":
            record.data.update(session="closed", venue_closed=True)
        else:
            record.engine_error("node failed or interrupted; inspect the local engine log")
        record.at_stop(
            instrument_open_orders=0,
            instrument_open_positions=0,
            instrument_inflight_orders=0,
            execution_healthy=True,
            order_status=None,
            filled=False,
        )

    return run


def test_a_closed_venue_skips_without_a_hold(unit, monkeypatch, capsys):
    monkeypatch.setattr(alpaca_node, "run", closed_node("closed"))
    assert alpaca_unattended.main(["order"], unit) == 0
    assert capsys.readouterr().out == (
        "SKIPPED: the venue is closed; nothing was sent, no hold written\n"
    )
    assert not hold(unit).exists() and not marker(unit).exists()
    state = Path(unit["STATE_DIRECTORY"])
    (record,) = (state / "runs").glob("*-order.json")
    data = json.loads(record.read_text())
    assert data["result"] == alpaca_unattended.SKIPPED and data["problems"] == []
    assert not (state / "evidence").exists()  # a skip is not a pass
    assert alpaca_unattended.main(["status", "--state", str(state)], {}) == 0
    assert f": {alpaca_unattended.SKIPPED}" in capsys.readouterr().out
    run, _ = fake_node()
    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["order"], unit) == 0  # the next session's order runs


def test_a_calendar_that_could_not_be_read_holds(unit, monkeypatch):
    monkeypatch.setattr(alpaca_node, "run", closed_node("unread"))
    assert alpaca_unattended.main(["order"], unit) == 1
    assert json.loads(hold(unit).read_text())["reason"] == "the unattended order run failed"


@pytest.mark.parametrize("change", ["order", "event", "not_flat", "unhealthy", "unknown"])
def test_closed_with_anything_else_wrong_still_holds(unit, monkeypatch, change):
    closed = closed_node("closed")

    def run(state, record, log_dir=None):
        closed(state, record, log_dir)
        if change == "order":
            record.order_built(type="LIMIT", time_in_force="DAY", side="BUY", quantity="1")
        elif change == "event":
            record.event("OrderRejected", 1)
        elif change == "not_flat":
            record.data["at_stop"]["instrument_open_positions"] = 1
        elif change == "unhealthy":
            record.data["at_stop"]["execution_healthy"] = False
        else:
            del record.data["venue_closed"]  # "closed" only from the quote guard, not the venue

    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["order"], unit) == 1
    assert hold(unit).exists()


def test_a_restart_is_never_a_skip(unit, monkeypatch):
    run = closed_node("closed")
    monkeypatch.setattr(alpaca_node, "run", run)
    assert alpaca_unattended.main(["restart"], unit) == 0  # a clean restart passes, as before
    data = json.loads(next((Path(unit["STATE_DIRECTORY"]) / "runs").glob("*.json")).read_text())
    assert data["result"] == "pass"


def test_status_of_an_unreadable_state_fails_instead_of_reporting_no_hold(unit, capsys):
    state = Path(unit["STATE_DIRECTORY"])
    alpaca_unattended.write_hold(state, "order", "fixed reason")
    state.chmod(0o000)
    try:
        assert alpaca_unattended.main(["status", "--state", str(state)], {}) == 1
    finally:
        state.chmod(0o700)
    captured = capsys.readouterr()
    assert captured.err == "state not readable\n"
    assert "no hold file" not in captured.out and "no run records" not in captured.out
