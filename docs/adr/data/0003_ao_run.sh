#!/usr/bin/env bash
# Published copy (docs/adr/data/0003_ao_run.sh): ran on 2026-11-13 as scripts/ao_run.sh in the operator's
# work folder, written here as $WORK (a Windows temp folder, seen from WSL under /mnt/c; set WORK
# before running); the operator's home directory is written as $HOME. Otherwise unchanged.
# Always-on run: ao_run.sh LETTER N MODE(none|scra|pbt) CONTEXT(0|1)
L=$1; N=$2; MODE=$3; CTX=${4:-0}
. $WORK/scripts/common.sh
preflight
TAG="ao-$L-$N"
WT="$HOME/src/meridian-worktrees/ab-$ADR-$TAG"; OUT="$ABROOT/$TAG"; MEM="$HOME/.cache/claude-ab-mem/$ADR-$TAG"; PLUG="$HOME/.cache/claude-ab-plug/$ADR-$TAG"
[ -e "$OUT" ] && die "$OUT exists"
mkdir -p "$OUT" "$MEM"
wt_add "$WT" "$OUT/wt-add.err" || die "worktree add failed: $(cat "$OUT/wt-add.err")"
ADD=()
case "$MODE" in
  scra) ADD=(--plugin-dir "$(plug_copy "$PLUG" supply-chain-risk-auditor)") ;;
  pbt)  ADD=(--plugin-dir "$(plug_copy "$PLUG" property-based-testing)") ;;
esac
flags "$MEM"
env | cut -d= -f1 | grep -E '^(CLAUDE|ANTHROPIC|DISABLE|ORCA|TMPDIR|UV_|GH_|GITHUB_)' | sort > "$OUT/env-names.txt"
git -C "$WT" rev-parse HEAD > "$OUT/head.txt"
guard
SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/sid.txt"
( cd "$WT" && "${RUN[@]}" -p 'Reply with the single word OK. Do not use any tools.' "${FLAGS[@]}" "${ADD[@]}" --max-turns 1 --session-id "$SID" "${DENY[@]}" </dev/null >"$OUT/ok.jsonl" 2>"$OUT/ok.stderr" ); echo "exit=$?" > "$OUT/ok.exit"
metrics "$OUT/ok.jsonl" > "$OUT/ok.metrics.json"
if [ "$CTX" = 1 ]; then
  guard
  SID2=$(cat /proc/sys/kernel/random/uuid); echo "$SID2" > "$OUT/sid-context.txt"
  ( cd "$WT" && "${RUN[@]}" -p '/context' "${FLAGS[@]}" "${ADD[@]}" --session-id "$SID2" "${DENY[@]}" </dev/null >"$OUT/context.jsonl" 2>"$OUT/context.stderr" ); echo "exit=$?" > "$OUT/context.exit"
  jq -c 'select(.type=="assistant" and .context_usage)|.context_usage|{total_tokens, used:[.categories[]|select(.kind=="used")|{name,tokens}], skills, memory_files}' "$OUT/context.jsonl" > "$OUT/context.summary.json"
  jq -c 'select(.type=="result")|{subtype, num_turns, total_cost_usd, modelUsage}' "$OUT/context.jsonl" >> "$OUT/context.summary.json"
fi
# containment
git -C "$WT" status --porcelain=v1 --untracked-files=all > "$OUT/wt-status.txt"
P=$(printf '%s' "$WT" | sed 's/[^A-Za-z0-9]/-/g')
[ -f "$HOME/.claude/projects/$P/$SID.jsonl" ] && cp "$HOME/.claude/projects/$P/$SID.jsonl" "$OUT/transcript.jsonl"
git -C "$HOME/src/meridian" worktree remove --force "$WT" && echo removed > "$OUT/wt-removed.txt"
rm -rf "$MEM" "$PLUG"
jq -c --arg tag "$TAG" --arg mode "$MODE" '{tag:$tag, mode:$mode, version, plugins:[.plugins[]?.name], plugin_errors, n_skills, num_turns, is_error, terminal_reason, always_on, usage, fallback}' "$OUT/ok.metrics.json"
echo "wt-status lines: $(wc -l < "$OUT/wt-status.txt")"
