"""`setup.sh unattended` and `unattended-check` on a fake root: fake sudo, systemctl and uv.

Nothing here runs the real sudo, installs a real unit or starts a service. The step runs from a
throwaway git checkout holding copies of the files it installs.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COPIED = [
    "deploy/wsl/setup.sh",
    "deploy/alpaca-lane.template.json",
    "deploy/alpaca-order-budget.template.json",
    "deploy/systemd/meridian-alpaca-paper@.service",
    "deploy/systemd/meridian-alpaca-restart.timer",
    "deploy/systemd/meridian-alpaca-order.timer",
]
TIMERS = ("meridian-alpaca-restart.timer", "meridian-alpaca-order.timer")
FAKES = {
    "sudo": r"""echo "sudo $*" >> "$FAKE_LOG"
[ "$1" = -n ] && shift
args=(); skip=0
for a in "$@"; do
  if [ "$skip" = 1 ]; then skip=0; continue; fi
  case "$a" in -o|-g) skip=1 ;; *) args+=("$a") ;; esac
done
exec "${args[@]}"
""",
    "id": '[ "$1" = paper ] && exit 0\nexec /usr/bin/id "$@"\n',
    "systemctl": r"""echo "systemctl $*" >> "$FAKE_LOG"
active="$MERIDIAN_FAKE_ROOT/.fake-active"
case "$1" in
  add-wants)
    mkdir -p "$MERIDIAN_FAKE_ROOT/etc/systemd/system/$2.wants"
    ln -s "../$3" "$MERIDIAN_FAKE_ROOT/etc/systemd/system/$2.wants/$3" ;;
  start) echo "$2" >> "$active" ;;
  is-active) grep -qx "$2" "$active" 2>/dev/null && echo active || { echo inactive; exit 3; } ;;
  show) echo fake ;;
esac
""",
}
UV = r"""echo "uv $*" >> "$FAKE_LOG"
project="${@: -1}"
mkdir -p "$project/.venv/bin" && touch "$project/.venv/bin/python"
"""
MUTATING = ("daemon-reload", "add-wants", "systemctl start", "uv ", "install ", "ln ", "tar ")

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture
def fake(tmp_path):
    repo, root, home, bin_dir = (tmp_path / n for n in ("repo", "root", "home", "bin"))
    for name in COPIED:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, repo / name)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "fake"], check=True)
    (root / "etc/systemd/system").mkdir(parents=True)
    (root / "var/lib").mkdir(parents=True)
    bin_dir.mkdir()
    for name, body in {**FAKES, "uv": UV}.items():
        path = (home / ".local/bin/uv") if name == "uv" else bin_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)
    log = tmp_path / "log"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MERIDIAN_FAKE_ROOT": str(root),
        "FAKE_LOG": str(log),
    }

    def run(*args: str) -> tuple[str, list[str]]:
        log.write_text("")
        done = subprocess.run(
            ["bash", str(repo / "deploy/wsl/setup.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout, log.read_text().splitlines()

    return repo, root, run


def snapshot(root: Path) -> dict[str, tuple]:
    found = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        target = os.readlink(path) if path.is_symlink() else None
        found[str(path.relative_to(root))] = (info.st_mode, info.st_mtime_ns, target)
    return found


def test_install_enables_the_timers_and_a_second_run_changes_nothing(fake):
    repo, root, run = fake
    out, calls = run("unattended")
    assert sum(c.startswith("uv sync --locked --no-dev") for c in calls) == 1
    assert "systemctl daemon-reload" in calls
    for timer in TIMERS:
        assert f"systemctl add-wants timers.target {timer}" in calls
        assert f"systemctl start {timer}" in calls
        assert f"{timer}: enabled, active" in out
    current = root / "opt/meridian/current"
    assert current.is_symlink() and (current / ".venv/bin/python").exists()
    for name in ("alpaca-lane", "alpaca-order-budget"):
        installed = root / f"etc/meridian-alpaca-paper/{name}.json"
        assert installed.read_text() == (repo / f"deploy/{name}.template.json").read_text()
    assert (root / "var/lib/meridian-alpaca-paper").is_dir()
    assert "hold file: none" in out
    # Nothing that runs the lane: no service started, no lane module invoked.
    started = [c for c in calls if c.startswith("systemctl start ")]
    assert sorted(started) == sorted(f"systemctl start {timer}" for timer in TIMERS)
    before = snapshot(root)
    out, calls = run("unattended")
    assert not [c for c in calls if any(m in c for m in MUTATING)], calls
    assert snapshot(root) == before


def test_the_step_never_overwrites_settings_the_owner_filled(fake):
    _, root, run = fake
    run("unattended")
    settings = root / "etc/meridian-alpaca-paper/alpaca-lane.json"
    settings.write_text('{"filled": "by the owner"}\n')
    run("unattended")
    assert settings.read_text() == '{"filled": "by the owner"}\n'


def test_check_mode_reports_and_changes_nothing(fake):
    _, root, run = fake
    out, _ = run("unattended-check")
    assert "release: not installed" in out and "hold file: unknown" in out
    assert all(f"{timer}: not enabled" in out for timer in TIMERS)
    run("unattended")
    (root / "var/lib/meridian-alpaca-paper/hold").write_text("{}\n")
    before = snapshot(root)
    out, calls = run("unattended-check")
    assert "hold file: PRESENT" in out
    assert "meridian-alpaca-paper@order.service: last result fake" in out
    assert not [c for c in calls if any(m in c for m in MUTATING)], calls
    assert not [c for c in calls if "alpaca-lane.json" in c or "credstore" in c]
    assert snapshot(root) == before


def test_a_dirty_checkout_refuses(fake):
    repo, root, run = fake
    (repo / "stray").write_text("x")
    with pytest.raises(subprocess.CalledProcessError):
        run("unattended")
    assert not (root / "opt").exists()
