#!/bin/bash
# One R4 run of ADR 0007's series in distro meridian, resumed series (a2, a3). usage: bash r4_run2.sh a <n>
# Identical to eco/work/0007-measure/scripts/r4_run.sh (run a1) in setup, flags and brief, except:
#  - the guard is ~/.cache/meridian/gateway-guard.sh (process names and executables, never command
#    lines), logged with the time to the run folder's guard.log;
#  - a run folder, clone or stand-in home that already exists is never removed or reused;
#  - extra containment lines (worktree list, processes whose cwd is in the run's dirs).
# Published copy (docs/adr/data/0007_r4_run2.sh): the Windows work folder is written as $WORK (seen from
# WSL under /mnt/c; set WORK before running; its scripts/run_summary.py is 0007_run_summary.py
# here), and the 4 lines below, added on publishing. Otherwise byte for byte the file that ran.
# NOT A RERUN HARNESS: the record of runs a2 and a3. codex exec below ran in the owner's ~/.codex
# without the run-only trust flag -c "projects={\"$WT\"={trust_level=\"trusted\"}}", so it wrote a
# [projects."$WT"] table into config.toml, a thread into Codex's state databases and a rollout, and it
# recorded nothing of that home. A run name that exists stops it (exit 7).
set -u
ARM=$1; N=$2
[ "$ARM" = a ] || { echo "only arm a is runnable on this machine"; exit 8; }
GITC() { GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.https://github.com.helper= "$@"; }
REALHOME=$HOME
A=$REALHOME/src/meridian-ab/0007
WSRC=$WORK
RUN=ab-0007-$ARM-$N
WT=$A/wt/$RUN
OUT=$A/out/$RUN
FH=$A/fh/$RUN
BASE=96e82e6b521cdb9c7d172176898d20e2658ec50b
FIX=39cb68ea3241caeececb6db0521a12ea2fa92fee
for d in "$OUT" "$WT" "$FH"; do [ -e "$d" ] && { echo "exists, not overwritten: $d"; exit 7; }; done
mkdir -p "$OUT" "$FH/.config"
guard() {
  local msg rc
  msg=$(bash "$REALHOME/.cache/meridian/gateway-guard.sh" 2>&1); rc=$?
  echo "$(date -Is) [$1] rc=$rc $msg" >> "$OUT/guard.log"
  [ "$rc" = 0 ] || { echo "GUARD-STOP rc=$rc $msg"; exit 3; }
}
guard setup
[ "$(sha256sum < "$A/briefs/R4.txt" | cut -d' ' -f1)" = 56e5c8ac4175feaed5a14cf0dc221ad3a15f9616bf497533db69ddbc6653b3b8 ] || { echo "brief hash mismatch"; exit 6; }
# Setup: a repository holding only BASE and its ancestors, so no tool call can reach the fix.
git init -q "$WT" && GITC -C "$WT" fetch -q --no-tags https://github.com/seathatflowsinourveins/meridian "$BASE" \
  && git -C "$WT" checkout -q --detach FETCH_HEAD && rm -f "$WT/.git/FETCH_HEAD" || { echo "setup failed"; exit 4; }
git -C "$WT" rev-parse HEAD > "$OUT/head.txt"
if git -C "$WT" cat-file -e "$FIX" 2>/dev/null; then echo "fix object present" >> "$OUT/head.txt"; else echo "fix object absent" >> "$OUT/head.txt"; fi
(cd "$WT" && uv sync --locked -q) > "$OUT/uv-sync.txt" 2>&1 || { echo "uv sync failed"; exit 5; }
git -C "$WT" status --porcelain --ignored=no > "$OUT/status-before.txt"
# Seatbelt: the agent gets a HOME without Jts, .ssh, .gnupg, .codex credentials paths or other homes.
for f in .profile .bashrc .bash_logout .local .cache; do ln -s "$REALHOME/$f" "$FH/$f"; done
ln -s "$REALHOME/.config/uv" "$FH/.config/uv"
ls -A "$REALHOME" > "$OUT/home-before.txt"; ls -A /tmp > "$OUT/tmp-before.txt"
git -C "$REALHOME/src/meridian" worktree list > "$OUT/worktrees-before.txt"
codex --version < /dev/null > "$OUT/version.txt"
guard run
date -Is > "$OUT/start.txt"; start=$(date +%s)
HOME="$FH" CODEX_HOME="$REALHOME/.codex" timeout --signal=INT 60m codex exec --json --color never -m gpt-6-astra \
  -c model_reasoning_effort=high --dangerously-bypass-approvals-and-sandbox -C "$WT" -o "$OUT/last-message.md" \
  --disable hooks - < "$A/briefs/R4.txt" > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
echo "exit=$rc seconds=$(( $(date +%s) - start ))" > "$OUT/run.txt"
date -Is > "$OUT/end.txt"
codex --version < /dev/null >> "$OUT/version.txt"
TID=$(jq -r 'select(.type=="thread.started")|.thread_id' "$OUT/events.jsonl" | head -1)
R=$(find "$REALHOME/.codex/sessions" -name "rollout-*-$TID.jsonl" | head -1)
[ -n "$R" ] && cp "$R" "$OUT/rollout-main.jsonl"
i=0
while IFS= read -r -d '' f; do
  sid=$(head -c 200000 "$f" | jq -r 'select(.type=="session_meta")|.payload.session_id // empty' 2>/dev/null | head -1)
  if [ "$sid" = "$TID" ]; then i=$((i+1)); cp "$f" "$OUT/sub-$i.jsonl"; fi
done < <(find "$REALHOME/.codex/sessions" -name 'rollout-*.jsonl' -newer "$OUT/start.txt" ! -name "*$TID.jsonl" -print0)
echo "thread=$TID subagents=$i" >> "$OUT/run.txt"
OWN_WT="$WT" python3 -I "$WSRC/scripts/run_summary.py" "$OUT/events.jsonl" "$OUT/rollout-main.jsonl" $(ls "$OUT"/sub-*.jsonl 2>/dev/null) > "$OUT/summary.json"
# Containment
git -C "$WT" status --porcelain --ignored=no > "$OUT/status-after.txt"
ls -A "$REALHOME" > "$OUT/home-after.txt"; ls -A /tmp > "$OUT/tmp-after.txt"
git -C "$REALHOME/src/meridian" worktree list > "$OUT/worktrees-after.txt"
{
  echo "worktree changes (before vs after):"; diff "$OUT/status-before.txt" "$OUT/status-after.txt" && echo none
  echo "worktree HEAD now: $(git -C "$WT" rev-parse HEAD)"
  echo "main checkout worktrees naming 0007: $(git -C "$REALHOME/src/meridian" worktree list | grep -c 0007)"
  echo "main checkout worktree list (before vs after):"; diff "$OUT/worktrees-before.txt" "$OUT/worktrees-after.txt" && echo unchanged
  echo "new in home:"; comm -13 "$OUT/home-before.txt" "$OUT/home-after.txt"
  echo "new in /tmp:"; comm -13 <(sort "$OUT/tmp-before.txt") <(sort "$OUT/tmp-after.txt")
  echo "new in fake home:"; ls -A "$FH" | grep -vxE '\.profile|\.bashrc|\.bash_logout|\.local|\.cache|\.config'
  echo "processes naming the run:"; pgrep -af "$RUN" | grep -v -e pgrep -e r4_run2.sh || echo none
  echo "processes whose cwd is in the run's clone or stand-in home:"
  n=0; for d in /proc/[0-9]*; do c=$(readlink "$d/cwd" 2>/dev/null) || continue
    case "$c" in "$WT"*|"$FH"*) [ "${d#/proc/}" = "$$" ] || { n=$((n+1)); echo "pid ${d#/proc/} $(cat "$d/comm" 2>/dev/null)"; };; esac; done
  [ "$n" = 0 ] && echo none
} > "$OUT/containment.txt" 2>&1
cat "$OUT/run.txt" "$OUT/head.txt" "$OUT/version.txt" "$OUT/guard.log" "$OUT/containment.txt" "$OUT/summary.json"
