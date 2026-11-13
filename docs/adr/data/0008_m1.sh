# M1 (run 2): always-on tokens, owner's signed-in ~/.codex, one ctx path for both arms, fresh clone per run.
# usage: bash m1.sh <letter> <n> <omx 0|1>     (the letter is neutral; the key is kept outside the run folders)
set -u
. "$HOME/src/meridian-ab/0008/run2/scripts/common2.sh"
L=$1; N=$2; WITH=$3
WT=$WTD/ab-0008-ctx
OUT=$R2/m1/$L-$N
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 2; }
mkdir -p "$OUT"
mkclone "$WT" "$MAIN" || exit 1
if [ "$WITH" = 1 ]; then omx_project_setup "$WT" "m1-$L-$N" > "$OUT/setup.log" 2>&1 || { echo "setup failed"; exit 1; }; fi
snapdir "$WT" | grep -v -E '^\.git/' > "$OUT/clone-pre.txt"
git -C "$WT" status --porcelain --ignored > "$OUT/clone-status-pre.txt"
python3 -I "$R2/scripts/trust_keys.py" "$HOME/.codex/config.toml" > "$OUT/trust-pre.txt"
snaphome "$OUT/home-pre"
codex_flags "$WT"
codex --version > "$OUT/version.txt"
guard "$OUT" || { echo "BLOCKED: the IB Gateway came up"; exit 3; }
start=$(date +%s)
codex exec "${FLAGS[@]}" "$P_CTX" < /dev/null > "$OUT/ctx.jsonl" 2> "$OUT/ctx.stderr"
rc=$?
echo "exit=$rc seconds=$(( $(date +%s) - start ))" > "$OUT/run.txt"
codex --version >> "$OUT/version.txt"
sleep 2
snaphome "$OUT/home-post"
python3 -I "$R2/scripts/trust_keys.py" "$HOME/.codex/config.toml" > "$OUT/trust-post.txt"
TID=$(jq -r 'select(.type=="thread.started")|.thread_id' "$OUT/ctx.jsonl")
RO=$(find "$HOME/.codex/sessions" -name "rollout-*-$TID.jsonl" 2>/dev/null | head -1)
[ -n "$RO" ] && cp "$RO" "$OUT/rollout.jsonl"
python3 -I "$R2/scripts/codex_ab_summary.py" "$OUT/ctx.jsonl" "$HOME/.codex" > "$OUT/summary.json" 2> "$OUT/summary.stderr"
# containment
git -C "$WT" status --porcelain --ignored > "$OUT/clone-status-post.txt"
snapdir "$WT" | grep -v -E '^\.git/' > "$OUT/clone-post.txt"
{ echo "## clone status diff"; diff "$OUT/clone-status-pre.txt" "$OUT/clone-status-post.txt";
  echo "## clone new paths"; diff <(cut -f1 "$OUT/clone-pre.txt") <(cut -f1 "$OUT/clone-post.txt") | grep '^[<>]' | head -30;
  echo "## home diff"; diffhome "$OUT/home-pre" "$OUT/home-post";
  echo "## trust keys"; diff "$OUT/trust-pre.txt" "$OUT/trust-post.txt" && echo unchanged;
  echo "## procs in clone"; for p in /proc/[0-9]*; do c=$(readlink "$p/cwd" 2>/dev/null); case "$c" in "$WT"*) echo "${p#/proc/} $c";; esac; done;
  echo "## hook procs"; pgrep -af 'codex-native-hook|oh-my-codex' | grep -v pgrep || echo none;
} > "$OUT/containment.txt" 2>&1
items=$(jq -r 'select(.type=="item.completed")|.item.type' "$OUT/ctx.jsonl" | sort | uniq -c | tr -s ' \n' ' ')
usage=$(jq -c 'select(.type=="turn.completed")|.usage' "$OUT/ctx.jsonl")
tur=$([ -n "$RO" ] && jq -s '[.[]|select(.type=="token_usage_record")]|length' "$RO")
eff=$([ -n "$RO" ] && jq -r 'select(.type=="turn_context")|.payload|"\(.model)/\(.effort)"' "$RO" | sort -u | tr '\n' ' ')
xenv=$([ -n "$RO" ] && grep -c 'Execution environment' "$RO")
echo "$L-$N rc=$rc tid=$TID usage=$usage items=$items records=$tur model_effort=$eff exec_env_lines=$xenv"
rm -rf "$WT" "$T/home-m1-$L-$N" "$T/codex-setup-m1-$L-$N"
