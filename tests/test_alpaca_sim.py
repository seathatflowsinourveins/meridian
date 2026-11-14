"""Run the native simulation with Linux blocking socket syscalls, including Rust's."""

import builtins
import ctypes
import json
import platform
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def block_sockets():
    # Linux UAPI: linux/{filter,seccomp,prctl}.h and asm/unistd_64.h.
    # This repository targets x86_64 WSL2. Fail closed on a different platform.
    assert sys.platform == "linux" and platform.machine() == "x86_64"

    class Filter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]

    # Load seccomp_data.nr; trap socket(41) and socketpair(53), allow other calls.
    rules = (Filter * 5)(
        Filter(0x20, 0, 0, 0),
        Filter(0x15, 1, 0, 41),
        Filter(0x15, 0, 1, 53),
        Filter(0x06, 0, 0, 0x00030000),
        Filter(0x06, 0, 0, 0x7FFF0000),
    )
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(38, 1, 0, 0, 0) == 0  # PR_SET_NO_NEW_PRIVS
    assert libc.prctl(22, 2, ctypes.byref(Program(len(rules), rules)), 0, 0) == 0


@pytest.mark.parametrize("fill", [False, True], ids=["cancel-pass", "fill-fails"])
def test_native_simulation_without_sockets_or_evidence(tmp_path, fill):
    # Prove the filter kills even a direct libc socket call, not only Python sockets.
    probe = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "probe"],
        capture_output=True,
        check=False,
    )
    assert probe.returncode == -signal.SIGSYS
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(tmp_path), str(fill)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == (1 if fill else 0), result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert not result.stderr
    assert lines[0].startswith("SIMULATION; not a lane; no typed word")
    assert "synthetic" in lines[0].lower()
    assert "strategy and engine order flow" in lines[1]
    for omitted in ("Alpaca adapter", "order budget", "credentials", "streams", "venue"):
        assert omitted in lines[2]
    assert ("FAIL" if fill else "PASS") in lines[-2]
    files = list(tmp_path.rglob("*"))
    assert all(p.relative_to(tmp_path).parts[0] == "runs" for p in files)
    records = list((tmp_path / "runs").glob("*-simulation.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["simulation"] is True
    assert (
        record["data_source"] == "synthetic quotes generated in process; no market or recorded data"
    )
    assert record["passed"] is not fill
    assert record["orders_total"] == 1
    assert record["order"] == dict(type="LIMIT", time_in_force="DAY", side="BUY", quantity="1")
    events = [event["type"] for event in record["events"]]
    assert events.count("OrderAccepted") == 1
    if fill:
        assert "OrderFilled" in events
        assert record["at_stop"]["filled"] is True
        assert record["at_stop"]["instrument_open_positions"] == 1
        assert record["problems"]
    else:
        assert events.index("OrderAccepted") < events.index("OrderCanceled")
        assert "OrderFilled" not in events
        assert record["at_stop"]["order_status"] == "CANCELED"
        assert record["at_stop"]["filled"] is False
        assert record["at_stop"]["instrument_open_positions"] == 0
        assert record["at_stop"]["instrument_open_orders"] == 0
        assert record["at_stop"]["instrument_inflight_orders"] == 0
        assert record["problems"] == []


if __name__ == "__main__":
    block_sockets()  # Before importing Meridian or the native engine; inherited by threads.
    if sys.argv[1] == "probe":
        ctypes.CDLL(None).socket(2, 1, 0)
        raise AssertionError("socket syscall was not blocked")

    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            name = args[0].decode() if isinstance(args[0], bytes) else args[0]
            parts = Path(name).parts
            assert not set(parts) & {
                "evidence",
                "Jts",
                ".env",
                ".ssh",
                ".dsh",
                "credstore",
                "credstore.encrypted",
                "alpaca-paper-key-id",
                "alpaca-paper-secret-key",
            }, "simulation attempted protected file access"

    def no_prompt(*_):
        raise AssertionError("simulation requested typed confirmation")

    sys.addaudithook(audit)
    builtins.input = no_prompt
    sys.path.insert(0, str(ROOT))
    from meridian import alpaca_sim, boundary

    boundary.REPO_ROOT = Path(sys.argv[1])
    raise SystemExit(alpaca_sim.main(fill_before_cancel=sys.argv[2] == "True"))
