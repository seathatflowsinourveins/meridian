# ADR 0012, real task R2 on temporary dsh profiles: common settings (sourced, never run).
# Nothing here opens, copies or exports a key: dsh loads its own key from its own home.
# Only the wrapper's AB_* settings are exported; nothing named DSH_* is put into the environment.
N=0012
EV="$HOME/src/meridian-ab/0012/real"           # series folder (new; raw output stays here)
SC="$EV/scripts"                               # copies of these scripts, hashed at setup
SCOUT="$HOME/src/meridian-ab/dsh-scout/scripts" # the scout's wrapper and overlay template
A=ab-0012-a B=ab-0012-b                        # the two temporary profiles, neutral names
WANT_VER=0.2.2-rc.1
PIN=71c2f93be2645351424d2730998f3fa88f432f3f PIN_TREE=7b62f331044d815b92f1f299b2f163f0fdbd08eb
ADD_URL=https://github.com/pf-sjtu/dsh-early-stop-guard.git
URL=https://github.com/seathatflowsinourveins/meridian.git
BASE=96e82e6b521cdb9c7d172176898d20e2658ec50b FIX=39cb68ea3241caeececb6db0521a12ea2fa92fee
BRIEF_SHA=9d0b472a179056bea86dfcaf334754667d0fd3de7aac764abd945da6b952e8ed
ROUNDS=8; export AB_TIMEOUT=1800 AB_KILL_AFTER=60   # the same bounds in both arms
# Amendment 1 (after run a1, before any run that reached the model): /etc/resolv.conf is a link to
# /mnt/wsl/resolv.conf here, so with /mnt hidden no host name resolves; that one file is shown again.
export AB_HIDE="/mnt:/run/WSL:$HOME" AB_SHOW="$HOME/.local:$EV/addition:/mnt/wsl/resolv.conf"   # the same in both arms
GL="$HOME/.cache/meridian-landing/gitleaks/gitleaks"
GUARD="$HOME/.cache/meridian/gateway-guard.sh"
GITC() { GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.https://github.com.helper= "$@"; }
# A tag is the arm letter and a number: a1 b1 b2 a2 a3 b3, then a4 b4 b5 a5 for the extension;
# a re-run of a voided slot takes the next free number of its letter, so every name has one length.
tag_ok() { case "$1" in [ab][1-9]) return 0 ;; *) echo "bad tag $1" >&2; return 1 ;; esac; }
tag2profile() { case "$1" in a*) echo "$A" ;; b*) echo "$B" ;; esac; }
tag2r() { echo "$EV/r/$1"; }                           # run folder (dsh's output, logs, caches)
tag2w() { echo "$EV/w/ab-0012-${1:0:1}-${1:1:1}"; }    # the run's checkout, the agent's cwd
# uv needs a cache the tool sandbox can write: it lives in the run folder's cache/ (an --add-dir).
# pyright 1.1.414 runs from its wheel (bundled dist/, node from nodejs-wheel) and needs no cache;
# PYRIGHT_PYTHON_IGNORE_WARNINGS=1 stops its PyPI version lookup (the brief says connect to nothing).
task_env() { # $1 = folder that holds cache/
  echo "UV_CACHE_DIR=$1/cache/uv" "PYRIGHT_PYTHON_IGNORE_WARNINGS=1"
}
