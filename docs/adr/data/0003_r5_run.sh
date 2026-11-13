#!/usr/bin/env bash
# Published copy (docs/adr/data/0003_r5_run.sh): ran on 2026-11-13 as scripts/r5_run.sh in the operator's
# work folder, written here as $WORK (a Windows temp folder, seen from WSL under /mnt/c; set WORK
# before running); the operator's home directory is written as $HOME. Otherwise unchanged.
# R5 run: r5_run.sh LETTER N WITH(0|1)
L=$1; N=$2; WITH=$3
. $WORK/scripts/common.sh
preflight
TAG="$L-$N"
WT="$HOME/src/meridian-worktrees/ab-$ADR-$TAG"; OUT="$ABROOT/$TAG"; MEM="$HOME/.cache/claude-ab-mem/$ADR-$TAG"
TMPR="$HOME/.cache/claude-ab-tmp/$ADR-$TAG"; PLUG="$HOME/.cache/claude-ab-plug/$ADR-$TAG"
BRIEF="$ABROOT/briefs/R5.txt"
[ -e "$OUT" ] && die "$OUT exists"
[ "$(sha256sum "$BRIEF" | cut -d' ' -f1)" = "$(cat "$ABROOT/briefs/R5.sha256")" ] || die "brief changed"
mkdir -p "$OUT" "$MEM" && install -d -m 0700 "$TMPR"
wt_add "$WT" "$OUT/wt-add.err" || die "worktree add failed: $(cat "$OUT/wt-add.err")"
ADD=()
[ "$WITH" = 1 ] && ADD=(--plugin-dir "$(plug_copy "$PLUG" supply-chain-risk-auditor)")
flags "$MEM"
env | cut -d= -f1 | grep -E '^(CLAUDE|ANTHROPIC|DISABLE|ORCA|TMPDIR|UV_|GH_|GITHUB_)' | sort > "$OUT/env-names.txt"
git -C "$WT" rev-parse HEAD > "$OUT/head.txt"
git -C "$WT" status --porcelain=v1 --untracked-files=all > "$OUT/wt-status-pre.txt"
# pre-run snapshots (names only)
ls -A /tmp | sort > "$OUT/pre-tmp.txt"
ls -A "$HOME" | sort > "$OUT/pre-home.txt"
ls -A "$HOME/.cache" | sort > "$OUT/pre-cache.txt"
ls -A "$HOME/.cache/uv" 2>/dev/null | sort > "$OUT/pre-uv.txt"
for d in "$HOME"/.cache/uv/environments-v*; do [ -d "$d" ] && ls -A "$d" | sed "s#^#$(basename "$d")/#"; done | sort > "$OUT/pre-uv-envs.txt"
git -C "$HOME/src/meridian" worktree list --porcelain | grep '^worktree ' | sort > "$OUT/pre-worktrees.txt"
date -Is > "$OUT/t0.txt"; touch "$OUT/.t0"; sleep 1
guard
SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/sid.txt"
( cd "$WT" && env TMPDIR="$TMPR" UV_CACHE_DIR="$TMPR/uv-cache" npm_config_cache="$TMPR/npm-cache" "${RUN[@]}" -p "$(cat "$BRIEF")" "${FLAGS[@]}" "${ADD[@]}" --max-turns 100 --session-id "$SID" "${DENY[@]}" </dev/null >"$OUT/stream.jsonl" 2>"$OUT/stderr.txt" ); echo "exit=$?" > "$OUT/exit.txt"
date -Is > "$OUT/t1.txt"
sleep 5
# processes left behind (cwd or command line inside this run's paths)
for p in /proc/[0-9]*; do
  pid=${p#/proc/}; cwd=$(readlink "$p/cwd" 2>/dev/null) || continue
  cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)
  case "$cwd $cmd" in *"$WT"*|*"$TMPR"*|*"$PLUG"*|*"$SID"*) echo "$pid cwd=$cwd cmd=$cmd" ;; esac
done > "$OUT/post-procs.txt"
# stop anything this run left running (recorded above first)
cut -d' ' -f1 "$OUT/post-procs.txt" | while read -r pid; do [ -n "$pid" ] && [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null && echo "killed $pid"; done > "$OUT/post-procs-killed.txt"
# transcript and subagent files
P=$(printf '%s' "$WT" | sed 's/[^A-Za-z0-9]/-/g')
[ -f "$HOME/.claude/projects/$P/$SID.jsonl" ] && cp "$HOME/.claude/projects/$P/$SID.jsonl" "$OUT/transcript.jsonl"
[ -d "$HOME/.claude/projects/$P/$SID" ] && cp -r "$HOME/.claude/projects/$P/$SID" "$OUT/session"
metrics "$OUT/stream.jsonl" > "$OUT/metrics.json"
jq -r 'select(.type=="result")|.result // empty' "$OUT/stream.jsonl" > "$OUT/final.md"
# every tool call (stream, transcript, subagents) and the leak scan
for f in "$OUT/stream.jsonl" "$OUT/transcript.jsonl" "$OUT"/session/subagents/*.jsonl; do
  [ -f "$f" ] && jq -c '..|objects|select(.type?=="tool_use")|{name,input}' "$f" 2>/dev/null
done | sort -u > "$OUT/tool_calls.jsonl"
sed -e "s#$WT#WT#g" -e "s#$MEM#MEM#g" -e "s#$TMPR#TMPR#g" -e "s#$PLUG#PLUG#g" -e "s#\.claude/projects/$P/$SID#OWN#g" "$OUT/tool_calls.jsonl" \
  | grep -nE 'src/meridian/|meridian-worktrees/|meridian-ab|claude-ab-mem|claude-ab-tmp|claude-ab-plug|\.claude/projects/|/\.git/|\.\./ab-|scratchpad|AppData|/mnt/c|ibgateway|:4002|ibkr_paper|ib_probe|boundary contract|alpaca|\.env\b|credentials|auth\.json|/\.ssh|/\.gnupg|Jts' > "$OUT/leak-hits.txt"
# containment
git -C "$WT" status --porcelain=v1 --untracked-files=all > "$OUT/wt-status.txt"
git -C "$WT" status --porcelain=v1 --ignored --untracked-files=all | grep '^!!' > "$OUT/wt-ignored.txt"
git -C "$WT" diff --stat HEAD > "$OUT/wt-diffstat.txt"
git -C "$HOME/src/meridian" worktree list --porcelain | grep '^worktree ' | sort > "$OUT/post-worktrees.txt"
find /tmp -mindepth 1 -maxdepth 2 -newer "$OUT/.t0" 2>/dev/null | sort > "$OUT/post-tmp-new.txt"
find "$HOME" -mindepth 1 -maxdepth 3 -newer "$OUT/.t0" \
  -not -path "$HOME/src/meridian-ab/*" -not -path "$HOME/.claude/projects/*" 2>/dev/null | sort > "$OUT/post-home-new.txt"
ls -A "$HOME/.cache/uv" 2>/dev/null | sort > "$OUT/post-uv.txt"
for d in "$HOME"/.cache/uv/environments-v*; do [ -d "$d" ] && ls -A "$d" | sed "s#^#$(basename "$d")/#"; done | sort > "$OUT/post-uv-envs.txt"
comm -13 "$OUT/pre-uv-envs.txt" "$OUT/post-uv-envs.txt" > "$OUT/new-uv-envs.txt"
comm -13 "$OUT/pre-tmp.txt" <(ls -A /tmp | sort) > "$OUT/new-tmp-names.txt"
comm -13 "$OUT/pre-home.txt" <(ls -A "$HOME" | sort) > "$OUT/new-home-names.txt"
comm -13 "$OUT/pre-cache.txt" <(ls -A "$HOME/.cache" | sort) > "$OUT/new-cache-names.txt"
[ -d "$PLUG" ] && find "$PLUG" -newer "$OUT/.t0" | sort > "$OUT/plug-changed.txt"
find "$TMPR" -maxdepth 3 | sort > "$OUT/tmpr-listing.txt"
mkdir -p "$OUT/tmpr" && cp -a "$TMPR/." "$OUT/tmpr/" 2>/dev/null
du -sh "$WT/.venv" 2>/dev/null > "$OUT/wt-venv.txt"
# cleanup of everything this run created
git -C "$HOME/src/meridian" worktree remove --force "$WT" && echo removed > "$OUT/wt-removed.txt"
rm -rf "$MEM" "$TMPR" "$PLUG"
jq -c --arg tag "$TAG" '{tag:$tag, version, plugins:[.plugins[]?.name], plugin_errors, subtype, is_error, terminal_reason, api_error_status, num_turns, duration_ms, tokens_all, tokens_main, fallback, permission_denials, api_retries, skill_calls, total_cost_usd}' "$OUT/metrics.json"
for f in wt-status leak-hits post-procs new-uv-envs new-tmp-names new-home-names new-cache-names post-tmp-new; do printf '%s=%s ' "$f" "$(wc -l < "$OUT/$f.txt")"; done; echo
echo "final.md chars: $(wc -c < "$OUT/final.md")"
