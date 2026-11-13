# R1 (run 2): one real-task run, then containment, grade and void scan; removes its clones at the end.
# usage: bash r1.sh <letter> <n> <omx 0|1>
set -u
. "$HOME/src/meridian-ab/0008/run2/scripts/common2.sh"
L=$1; N=$2; WITH=$3
WT=$WTD/ab-0008-$L-$N
G=$WTD/ab-0008-g$L$N
OUT=$R2/r1/$L-$N
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 2; }
mkdir -p "$OUT"
printf '%s' "$(cat "$R2/scripts/r1-brief.txt")" > "$OUT/brief.txt"
[ "$(sha256sum < "$OUT/brief.txt" | cut -c1-64)" = 789791805eceb05d233fb1fc0d1c0ebefaed5d84d8f95612476bacb4a4feabc4 ] || { echo "brief sha mismatch"; exit 1; }

prep() {  # clone at base, tests from the fix commit, locked env
  local wt=$1 log=$2
  mkclone "$wt" "$R1_BASE" || return 1
  git -C "$wt" checkout -q "$R1_TESTS" -- tests/ || return 1
  { (cd "$wt" && uv sync --locked --offline) || (cd "$wt" && uv sync --locked); } > "$log" 2>&1
}
prep "$WT" "$OUT/uv-sync.log" || { echo "prep failed"; exit 1; }
if [ "$WITH" = 1 ]; then omx_project_setup "$WT" "r1-$L-$N" > "$OUT/setup.log" 2>&1 || { echo "setup failed"; exit 1; }; fi
cp "$WT/.gitignore" "$OUT/ref-gitignore"; cp "$WT/AGENTS.md" "$OUT/ref-AGENTS.md"
git -C "$WT" ls-files --others --exclude-standard | LC_ALL=C sort > "$OUT/untracked-pre.txt"
(cd "$WT" && PYTHONDONTWRITEBYTECODE=1 uv run --frozen pytest -q -p no:cacheprovider) > "$OUT/pytest-before.txt" 2>&1
echo "pytest-before: $(tail -1 "$OUT/pytest-before.txt")"
git -C "$WT" status --porcelain | LC_ALL=C sort > "$OUT/status-pre.txt"
python3 -I "$R2/scripts/trust_keys.py" "$HOME/.codex/config.toml" > "$OUT/trust-pre.txt"
snaphome "$OUT/home-pre"
codex_flags "$WT"
codex --version > "$OUT/version.txt"
guard "$OUT" || { echo "BLOCKED: the IB Gateway came up"; exit 3; }
echo "start $(date -Is)"
start=$(date +%s)
timeout --signal=INT 60m codex exec "${FLAGS[@]}" -o "$OUT/last-message.md" - < "$OUT/brief.txt" > "$OUT/events.jsonl" 2> "$OUT/stderr.log"
rc=$?
secs=$(( $(date +%s) - start ))
echo "exit=$rc seconds=$secs" > "$OUT/run.txt"
codex --version >> "$OUT/version.txt"
sleep 3
snaphome "$OUT/home-post"
python3 -I "$R2/scripts/trust_keys.py" "$HOME/.codex/config.toml" > "$OUT/trust-post.txt"
TID=$(jq -r 'select(.type=="thread.started")|.thread_id' "$OUT/events.jsonl" | head -1)
RO=$(find "$HOME/.codex/sessions" -name "rollout-*-$TID.jsonl" 2>/dev/null | head -1)
[ -n "$RO" ] && cp "$RO" "$OUT/rollout.jsonl"
python3 -I "$R2/scripts/codex_ab_summary.py" "$OUT/events.jsonl" "$HOME/.codex" > "$OUT/summary.json" 2> "$OUT/summary.stderr"
SUBS=$(jq -r '.subagents[].path' "$OUT/summary.json" 2>/dev/null)
mkdir -p "$OUT/sub"; for s in $SUBS; do cp "$s" "$OUT/sub/"; done
python3 -I "$R2/scripts/scan_run.py" "$OUT/events.jsonl" "ab-0008-$L-$N" "$OUT/rollout.jsonl" $(ls "$OUT"/sub/*.jsonl 2>/dev/null) > "$OUT/scan.json" 2>&1

# own-clone checks and the agent's change set
git -C "$WT" diff --quiet "$R1_TESTS" -- tests/; t_unch=$?
t_untr=$(git -C "$WT" ls-files --others --exclude-standard -- tests/ | wc -l)
git -C "$WT" diff --name-only "$R1_BASE" -- . ':(exclude)tests' | LC_ALL=C sort > "$OUT/changed-tracked.txt"
git -C "$WT" ls-files --others --exclude-standard | LC_ALL=C sort > "$OUT/untracked-post.txt"
git -C "$WT" status --porcelain --ignored > "$OUT/status-post-ignored.txt"
git -C "$WT" diff "$R1_BASE" -- meridian .gitignore > "$OUT/agent-tracked.diff"
outside=$(grep -v -E '^(meridian/|\.gitignore$|AGENTS\.md$)' "$OUT/changed-tracked.txt" | wc -l)
agents_ok=$(cmp -s "$WT/AGENTS.md" "$OUT/ref-AGENTS.md" && echo yes || echo NO)
new_untracked=$(comm -13 "$OUT/untracked-pre.txt" "$OUT/untracked-post.txt" | grep -v '^meridian/' | wc -l)
comm -13 "$OUT/untracked-pre.txt" "$OUT/untracked-post.txt" > "$OUT/untracked-new.txt"
gone_untracked=$(comm -23 "$OUT/untracked-pre.txt" "$OUT/untracked-post.txt" | wc -l)
{ echo "tests_unchanged_exit=$t_unch tests_untracked=$t_untr tracked_outside_allowed=$outside agents_md_equal_to_post_setup=$agents_ok new_untracked_outside_meridian=$new_untracked pre_untracked_removed=$gone_untracked"
  echo "## home diff"; diffhome "$OUT/home-pre" "$OUT/home-post"
  echo "## trust keys"; diff "$OUT/trust-pre.txt" "$OUT/trust-post.txt" && echo unchanged
  echo "## procs in clone"; for p in /proc/[0-9]*; do c=$(readlink "$p/cwd" 2>/dev/null); case "$c" in "$WT"*) echo "${p#/proc/} $c $(tr '\0' ' ' < "$p/cmdline" | cut -c1-120)";; esac; done
  echo "## hook procs"; pgrep -af 'codex-native-hook|oh-my-codex' | grep -v pgrep || echo none
} > "$OUT/containment.txt" 2>&1

# grade: the agent's meridian/ and .gitignore on a fresh clone set up the same way (without the addition)
prep "$G" "$OUT/grade-uv-sync.log" || echo "grade prep failed" >> "$OUT/grade.txt"
rm -rf "$G/meridian"; cp -a "$WT/meridian" "$G/meridian"; find "$G/meridian" -name __pycache__ -prune -exec rm -rf {} +
if [ "$WITH" = 1 ]; then
  python3 -I - "$OUT/ref-gitignore" "$WT/.gitignore" "$G/.gitignore" <<'PY'
import sys
ref, final, base_path = (open(p, encoding="utf-8").read().splitlines() for p in sys.argv[1:4])
added = list(ref)
for l in base_path:
    if l in added:
        added.remove(l)
out = []
for l in final:
    if l in added:
        added.remove(l)
        continue
    out.append(l)
open(sys.argv[3], "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
else
  cp "$WT/.gitignore" "$G/.gitignore"
fi
git -C "$G" diff "$R1_BASE" -- meridian .gitignore > "$OUT/graded.patch"
git -C "$G" ls-files --others --exclude-standard -- meridian >> "$OUT/graded-untracked.txt"
r1=99; r2=99; r3=99; r4=99
{ cd "$G" && uv run --frozen ruff check . > "$OUT/g-ruff.txt" 2>&1; r1=$?
  uv run --frozen ruff format --check . > "$OUT/g-format.txt" 2>&1; r2=$?
  uv run --frozen pyright > "$OUT/g-pyright.txt" 2>&1; r3=$?
  PYTHONDONTWRITEBYTECODE=1 uv run --frozen pytest -q -p no:cacheprovider > "$OUT/g-pytest.txt" 2>&1; r4=$?
  cd "$HOME"; }
echo "ruff=$r1 format=$r2 pyright=$r3 pytest=$r4 pytest_tail=$(tail -1 "$OUT/g-pytest.txt")" >> "$OUT/grade.txt"
pass=no; [ "$rc" = 0 ] && [ $r1 = 0 ] && [ $r2 = 0 ] && [ $r3 = 0 ] && [ $r4 = 0 ] && [ $t_unch = 0 ] && [ "$t_untr" = 0 ] && [ "$outside" = 0 ] && [ "$agents_ok" = yes ] && [ "$new_untracked" = 0 ] && pass=yes
echo "pass=$pass" >> "$OUT/grade.txt"
usage=$(jq -c 'select(.type=="turn.completed")|.usage' "$OUT/events.jsonl" | tail -1)
allu=$(jq -c '.all_threads_request_usage' "$OUT/summary.json" 2>/dev/null)
limits=$(grep -c -i -E 'usage limit|rate limit|429|quota' "$OUT/events.jsonl" "$OUT/stderr.log" | tr '\n' ' ' | sed "s|$OUT/||g")
echo "$L-$N rc=$rc secs=$secs pass=$pass limit_hits=[$limits] $(head -1 "$OUT/containment.txt") grade: $(head -1 "$OUT/grade.txt") usage_root_turn=$usage all_threads=$allu subagents=$(echo "$SUBS" | grep -c . ) hooks=$(jq -c .hook_text_counts "$OUT/scan.json") flagged=$(jq '.flagged|length' "$OUT/scan.json") tools=$(jq -c .tool_calls "$OUT/scan.json")"
rm -rf "$WT" "$G" "$T/home-r1-$L-$N" "$T/codex-setup-r1-$L-$N"
echo "clones removed: $([ -e "$WT" ] || [ -e "$G" ] && echo NO || echo yes)"
