"""Unattended Alpaca paper lane: the owner-enabled units' entry point (M7), and a status reader.

Own design. The engine, strategy, gate and record are the attended lane's (`meridian.alpaca_lane`);
what differs is who consents. No word is typed: the owner's standing consent is the settings
field `unattended_orders_enabled`, in a file the service user cannot write, together with the
timers the owner enabled. Only the units in `deploy/systemd/` start `restart` or `order`.

Fail closed: an order run writes the hold file before the engine starts and removes it only after
a pass; any failure, refusal inside the run, crash or kill leaves it. A failed restart writes one
too. While it exists `order` refuses; `restart` still runs, so the records keep showing the account.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian import ibkr_paper
from meridian.alpaca_lane import Preflight, Refused, RunRecord, preflight

RUN_MODES = ("restart", "order")
SETTINGS_NAME = "alpaca-lane.json"
HOLD_NAME = "hold"
LOCK_NAME = "lock"
# Where the unit's StateDirectory= lives (systemd.exec(5), system units: below /var/lib/).
DEFAULT_STATE = Path("/var/lib/meridian-alpaca-paper")

NOT_UNDER_UNIT = "unattended runs start only from the systemd units, with both credentials loaded"
NOT_OWNER_HELD = "unattended settings and rows must not be writable by the service user"
NO_CONSENT = "unattended orders are not enabled in the owner's settings"
HELD = "a hold file is present: the owner inspects the last record, then removes the hold"
OUTSIDE_HOURS = "the unattended order window is closed now"
BUSY = "another unattended run holds the lane lock"

_now: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731 (replaced by tests)


def order_window_open(now: datetime) -> bool:
    """The one place the unattended order window is decided; `gate` is its only caller.

    Today the regular session the IBKR lane's fill mode uses: weekdays 09:30 to 15:55 New York
    time, with no holiday calendar. For 24/5, point this at the session module's function.
    """
    return ibkr_paper.in_regular_hours(now)


def service_dirs(environ: Mapping[str, str]) -> tuple[Path, Path]:
    """(state, configuration) directories that systemd created and named for this unit."""
    # systemd.exec(5): $INVOCATION_ID is set for every unit; the directory variables come from
    # StateDirectory= and ConfigurationDirectory=, the credentials from LoadCredentialEncrypted=.
    names = ("INVOCATION_ID", "CREDENTIALS_DIRECTORY", "STATE_DIRECTORY", "CONFIGURATION_DIRECTORY")
    if not all(environ.get(name) for name in names):
        raise Refused(NOT_UNDER_UNIT)
    state, config = Path(environ["STATE_DIRECTORY"]), Path(environ["CONFIGURATION_DIRECTORY"])
    if ":" in str(state) or ":" in str(config) or not state.is_dir() or not config.is_dir():
        raise Refused(NOT_UNDER_UNIT)
    return state, config


def owner_held(settings: Path, state: Preflight) -> None:
    rows = Path(state.settings.rows_path)
    for path in (settings, settings.parent, rows, rows.parent):
        if os.access(path, os.W_OK):
            raise Refused(NOT_OWNER_HELD)


@contextmanager
def lane_lock(state_dir: Path) -> Iterator[None]:
    fd = os.open(state_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused(BUSY) from None
        yield
    finally:
        os.close(fd)


def write_hold(state_dir: Path, mode: str, reason: str, record: str | None = None) -> None:
    """Fixed, value-free text only: the mode, the time, a reason from this module, a file name."""
    hold = {
        "mode": mode,
        "written_utc": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "record": record,
    }
    (state_dir / HOLD_NAME).write_text(json.dumps(hold, sort_keys=True) + "\n", encoding="utf-8")


def gate(mode: str, environ: Mapping[str, str]) -> tuple[Path, Path, Preflight]:
    state_dir, config_dir = service_dirs(environ)
    settings = config_dir / SETTINGS_NAME
    state = preflight(settings)
    owner_held(settings, state)
    if mode == "order":
        if not state.settings.unattended_orders_enabled:
            raise Refused(NO_CONSENT)
        if (state_dir / HOLD_NAME).exists():
            raise Refused(HELD)
        if not order_window_open(_now()):
            raise Refused(OUTSIDE_HOURS)
    return state_dir, settings, state


def run_unattended(mode: str, state_dir: Path, settings: Path, state: Preflight) -> int:
    from meridian import alpaca_node

    if mode == "order":
        write_hold(state_dir, mode, "an unattended order run started and has not passed")
    record = RunRecord(mode, state)
    record.data["unattended"] = True
    alpaca_node.run(state, record, state_dir / "runs")  # it catches the engine's own failures
    with suppress(Refused):
        record.data["checks_unchanged_after_run"] = preflight(settings) == state
    passed, name = False, None
    try:
        # The attended writer, rooted at the state directory: the full record to runs/, and on a
        # pass the scrubbed one to evidence/ there. Never the repository's evidence/.
        passed, path = record.write([], root=state_dir)
        name = path.name
    except OSError, ValueError, RuntimeError:
        print("FAIL: run record could not be written", file=sys.stderr)
    if passed:
        if mode == "order":
            (state_dir / HOLD_NAME).unlink()
        print("PASS: scrubbed run record written to the state directory")
        return 0
    if mode == "order" or not (state_dir / HOLD_NAME).exists():
        write_hold(state_dir, mode, f"the unattended {mode} run failed", name)
    print("FAIL: hold file written; inspect the run record in the state directory")
    return 1


def status(state_dir: Path, last: int) -> int:
    """Read only: the last records' outcomes and the hold file, without any free text."""
    try:
        names = sorted(p for p in (state_dir / "runs").glob("*.json"))[-last:]
        for path in names:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            problems = "; ".join(str(p) for p in data.get("problems", []))
            print(f"{path.name}: {data.get('result')} {problems}".rstrip())
        if not names:
            print("no run records")
        hold = state_dir / HOLD_NAME
        if hold.exists():
            data = json.loads(hold.read_text(encoding="utf-8"))
            print(f"HOLD since {data.get('written_utc')}: {data.get('reason')}")
        else:
            print("no hold file")
    except OSError, ValueError:
        print("state directory unreadable or a record is malformed", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None, environ: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=(*RUN_MODES, "status"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="status only")
    parser.add_argument("--last", type=int, default=5, help="status only")
    args = parser.parse_args(argv)
    if args.mode == "status":
        return status(args.state, max(1, args.last))
    try:
        state_dir, _ = service_dirs(environ)
        with lane_lock(state_dir):
            state_dir, settings, state = gate(args.mode, environ)
            return run_unattended(args.mode, state_dir, settings, state)
    except Refused as exc:
        print(f"REFUSED TO START: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
