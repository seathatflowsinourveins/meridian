# common.sh -- shared settings of the ADR 0009 real-task series (sourced, never run).
# Nothing here opens, copies or exports ~/.dsh/.env or any other secret file.
EV="$HOME/src/meridian-ab/0009/real"; S="$EV/scripts"
BASE=96e82e6b521cdb9c7d172176898d20e2658ec50b
FIX=39cb68ea3241caeececb6db0521a12ea2fa92fee
REPO_URL=https://github.com/seathatflowsinourveins/meridian.git
DSH_WANT=0.2.2-rc.1
CODEX_WANT="codex-cli 0.167.2"
ROUNDS=4            # cap on dsh goal rounds (overlay goal.defaultMaxGoalRounds), both arms
WALL=1800           # seconds, every run of every arm
KILL_AFTER=60
GUARD="$HOME/.cache/meridian/gateway-guard.sh"
GITLEAKS="$HOME/.cache/meridian-landing/gitleaks/gitleaks"
# Folders and files that become empty inside a run's mount namespace (those that exist):
# Windows drives and interop, every other checkout and run folder (the main checkout and the
# grading clone hold the fix), and the owner's other sign-ins.
HIDE="/mnt:/run/WSL:$HOME/src:$HOME/Jts:$HOME/.ssh:$HOME/.gnupg:$HOME/.claude:$HOME/.claude.json:$HOME/.gemini:$HOME/.config/gh:$HOME/.npmrc"
# Made visible again, read-only: the addition's clone; the owner's Codex config file, so that
# no Codex process started by a run can rewrite it; and the resolver file, because in this
# distro /etc/resolv.conf is a link into /mnt/wsl and hiding /mnt would end name resolution
# (seen in the first Codex check: every request timed out).
SHOW="$EV/addition:$HOME/.codex/config.toml:/mnt/wsl/resolv.conf"
GITC() { GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.https://github.com.helper= "$@"; }
guard() {  # guard LOGFILE : exit 3 when the Gateway is up
  local out rc; out=$(bash "$GUARD"); rc=$?
  echo "$(date -Is) rc=$rc $out" >>"$1"
  [ "$rc" -eq 0 ] || { echo "blocked: the IB Gateway came up: $out"; return 3; }
}
