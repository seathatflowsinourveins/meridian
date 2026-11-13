#!/usr/bin/env bash
# after_run.sh TAG -- after one run: result, usage, what the addition did, containment, scans.
# Prints counts, names, hashes and the run's own commands; never a matched secret (gitleaks runs
# with --redact, the key-shape search prints file names only). Writes $EV/TAG/after.txt,
# usage.json, gitleaks.json, flags.txt and, in the run folder, final.txt, toolcalls.jsonl and
# patch.diff. Opens no credential file.
set -u
. "$(dirname "$0")/common.sh"
tag=$1; D="$EV/$tag"; R="$D/r"; W="$D/wt"
exec > >(tee "$D/after.txt") 2>&1
: >"$D/flags.txt"
FIXROUTE='git[^|;&]*[[:space:]](fetch|pull|clone|ls-remote|remote|bundle)|curl|wget|github\.com|githubusercontent|39cb68e|meridian-worktrees|/src/meridian([^-]|$)|/mnt/|gh (api|repo|pr)'
PLACES='\.env|/\.dsh|DSH_HOME|DSH_PROFILE_DIR|\.ssh|\.codex|auth\.json|Jts|risk/|contract\.json|\.gnupg|credentials'
LANES='meridian\.ibkr_paper|meridian\.sandbox_lane|meridian\.ib_probe|meridian\.boundary[[:space:]]+contract|alpaca|:4002|[[:space:]]4002'

echo "## run $tag, checked $(date -Is)"
echo "## exit and time"; cat "$R/exit.txt"; echo "duration_s=$(cat "$D/duration_s")"
echo "started=$(cat "$D/started") ended=$(cat "$D/ended")"
echo "## versions: dsh $(cat "$D/dsh-version.before") -> $(dsh --version </dev/null); codex $(cat "$D/codex-version.before") -> $(codex --version </dev/null)"
echo "## brief: $(cut -d' ' -f1 "$D/brief.sha256")"
echo "## guard"; cat "$R/guard.log"

codex_events() {  # codex_events FILE : usage, commands, web searches of one Codex event stream
  local E=$1 tid roll
  echo "# codex stream ${E#"$R"/}: $(wc -c <"$E") bytes"
  echo "events: $(jq -r '.type' "$E" 2>/dev/null | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  echo "items: $(jq -r 'select(.type=="item.completed") | .item.type' "$E" 2>/dev/null | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  echo "turn usage: $(jq -c 'select(.type=="turn.completed") | .usage' "$E" 2>/dev/null | tr '\n' ' ')"
  echo "errors: $(jq -c 'select(.type=="error" or .type=="turn.failed") | (.message // .error.message // .)' "$E" 2>/dev/null | cut -c1-300 | tr '\n' ' ')"
  tid=$(jq -r 'select(.type=="thread.started") | .thread_id' "$E" 2>/dev/null | head -n 1); echo "thread: ${tid:-none}"
  if [ -n "$tid" ]; then
    roll=$(find "$HOME/.codex/sessions" -name "rollout-*-$tid.jsonl" 2>/dev/null | head -n 1)
    if [ -n "$roll" ]; then  # four fields of this run's own transcript, nothing else
      echo "rollout turn context: $(jq -c 'select(.type=="turn_context") | {model: .payload.model, effort: .payload.effort, approval: .payload.approval_policy, sandbox: (.payload.sandbox_policy.type // .payload.sandbox_policy)}' "$roll" 2>/dev/null | sort -u | tr '\n' ' ')"
    else echo "rollout: not found"; fi
  fi
  jq -r 'select(.type=="item.completed" and .item.type=="command_execution") | .item.command' "$E" 2>/dev/null >"$E.commands.txt"
  jq -c 'select(.type=="item.completed" and (.item.type|test("web|mcp|search"))) | .item' "$E" 2>/dev/null | cut -c1-600 >"$E.web.txt"
  jq -c 'select(.type=="item.completed" and .item.type=="file_change") | .item.changes' "$E" 2>/dev/null >"$E.filechanges.txt"
  echo "commands: $(wc -l <"$E.commands.txt"); web or mcp items: $(wc -l <"$E.web.txt"); file-change items: $(wc -l <"$E.filechanges.txt")"
  grep -n -E "$FIXROUTE" "$E.commands.txt" "$E.web.txt" | cut -c1-400 | sed "s|^|FIXROUTE codex ${E#"$R"/} |" >>"$D/flags.txt"
  grep -n -E "$PLACES" "$E.commands.txt" | cut -c1-400 | sed "s|^|PLACES codex ${E#"$R"/} |" >>"$D/flags.txt"
  grep -n -E -i "$LANES" "$E.commands.txt" | cut -c1-400 | sed "s|^|LANES codex ${E#"$R"/} |" >>"$D/flags.txt"
}

if [ -f "$R/out.jsonl" ]; then
  echo "## dsh result"
  jq -c 'select(.type=="final") | {reason: .reason.kind, chars: (.text|length)}' "$R/out.jsonl"
  jq -r 'select(.type=="final") | .text' "$R/out.jsonl" >"$R/final.txt"
  echo "stream: $(jq -r '.type + (if .phase then ":"+.phase else "" end)' "$R/out.jsonl" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  echo "stderr bytes: $(wc -c <"$R/stderr.txt")"; head -c 600 "$R/stderr.txt"
  mapfile -t L < <(find "$R/sessions" -name 'session.v4.jsonl' 2>/dev/null | sort)
  echo "session logs: ${#L[@]}"
  jq -s '[.[] | select(.type=="status" and .phase=="step_end")] | {turns: (map(.turn) | unique | length), steps: length, steps_without_usage: (map(select(.usage == null)) | length), input: (map(.usage.inputTokens // 0) | add // 0), cache_read: (map(.usage.cacheReadTokens // 0) | add // 0), cache_write: (map(.usage.cacheWriteTokens // 0) | add // 0), output: (map(.usage.outputTokens // 0) | add // 0)} | .billed = (.input + .cache_read + .cache_write + .output)' "$R/out.jsonl" >"$D/usage.stream.json"
  echo "usage, root agent stream: $(jq -c . "$D/usage.stream.json")"
  jq -c 'select(.type=="status" and .phase=="step_end" and .turn==1 and .step==1) | .usage | {first_call_prompt_tokens: ((.inputTokens // 0) + (.cacheReadTokens // 0) + (.cacheWriteTokens // 0)), input: .inputTokens, cache_read: .cacheReadTokens, cache_write: .cacheWriteTokens}' "$R/out.jsonl" >"$D/usage.first-call.json"
  echo "first model call, prompt tokens as DeepSeek counts them: $(jq -c . "$D/usage.first-call.json")"
  if [ "${#L[@]}" -gt 0 ]; then
    jq -s '{model_calls: ([.[] | select(.type=="assistant/message")] | length), calls_without_usage: ([.[] | select(.type=="assistant/message" and .data.usage == null)] | length), usage_entries_by_type: ([.[] | select(.data.usage? != null) | .type] | group_by(.) | map({(.[0]): length}) | add), input: ([.[] | .data.usage?.inputTokens // 0] | add), cache_read: ([.[] | .data.usage?.cacheReadTokens // 0] | add), cache_write: ([.[] | .data.usage?.cacheWriteTokens // 0] | add), output: ([.[] | .data.usage?.outputTokens // 0] | add), turns: ([.[] | select(.type=="turn/start")] | length), steps: ([.[] | select(.type=="step/start")] | length), compactions: ([.[] | select(.type | test("compact"))] | length)} | .billed = (.input + .cache_read + .cache_write + .output)' "${L[@]}" >"$D/usage.sessions.json"
    echo "usage, all session logs: $(jq -c . "$D/usage.sessions.json")"
    for l in "${L[@]}"; do echo "  session $(basename "$(dirname "$l")"): $(jq -s -c '{calls: ([.[] | select(.type=="assistant/message")] | length), billed: ([.[] | .data.usage? | select(. != null) | (.inputTokens // 0) + (.cacheReadTokens // 0) + (.cacheWriteTokens // 0) + (.outputTokens // 0)] | add)}' "$l")"; done
    echo "model: $(jq -c 'select(.type=="request/context") | {provider: .data.provider, model: .data.model}' "${L[@]}" | sort -u | tr '\n' ' ')"
    echo "policy: $(jq -c 'select(.type | test("permission/preset|sandbox/mode|approval/policy")) | .data' "${L[@]}" | tr '\n' ' ')"
    echo "tools offered: $(jq -c 'select(.type=="request/header") | .data.header.tools | map(.name)' "${L[@]}" | head -n 1 | jq -c '{count: length, codex: map(select(startswith("codex_")))}')"
    jq -c 'select(.type=="tool/call") | .data' "${L[@]}" >"$R/toolcalls.jsonl"
    echo "tool calls: $(wc -l <"$R/toolcalls.jsonl"); by name: $(jq -r '.name // .call.name // .tool // "?"' "$R/toolcalls.jsonl" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
    echo "tool results that are errors: $(jq -c 'select(.type=="tool/result") | select(.data.message.isError == true) | .type' "${L[@]}" 2>/dev/null | wc -l)"
    grep -n -E "$FIXROUTE" "$R/toolcalls.jsonl" | cut -c1-400 | sed 's|^|FIXROUTE dsh toolcall |' >>"$D/flags.txt"
    grep -n -E "$PLACES" "$R/toolcalls.jsonl" | cut -c1-400 | sed 's|^|PLACES dsh toolcall |' >>"$D/flags.txt"
    grep -n -E -i "$LANES" "$R/toolcalls.jsonl" | cut -c1-400 | sed 's|^|LANES dsh toolcall |' >>"$D/flags.txt"
    echo "tool calls that name the dsh home: $(grep -c -E '/\.dsh|DSH_HOME|DSH_PROFILE_DIR' "$R/toolcalls.jsonl")"
  fi
  echo "## the addition (Codex children started through it)"
  if [ -d "$R/peer-state" ]; then
    echo "state folder entries: $(find "$R/peer-state" -mindepth 1 | wc -l)"
    if [ -f "$R/peer-state/runs.ndjson" ]; then
      jq -c '{runId, mode, sandbox, model, launcher, status, exitCode, durationMs, usage, label}' "$R/peer-state/runs.ndjson"
      jq -s '{codex_runs: length, codex_tokens_input_plus_output: (map(.usage.totalTokens // 0) | add), cached_input: (map(.usage.cachedInputTokens // 0) | add), reasoning_output: (map(.usage.reasoningOutputTokens // 0) | add)}' "$R/peer-state/runs.ndjson" >"$D/usage.codex.json"
      echo "codex usage: $(jq -c . "$D/usage.codex.json")"
    else echo "no Codex run recorded"; fi
    for m in "$R"/peer-state/runs/*/meta.json; do [ -f "$m" ] || continue; echo "meta $(basename "$(dirname "$m")"): $(jq -c '{launcher, status, exitCode, argv: (.argv | map(if test("^/") then (split("/") | last) else . end)), notes, errors}' "$m" | cut -c1-900)"; done
    for E in "$R"/peer-state/runs/*/events.jsonl; do [ -f "$E" ] && codex_events "$E"; done
    for f in "$R"/peer-state/runs/*/stderr.txt; do [ -s "$f" ] && { echo "codex stderr $(basename "$(dirname "$f")"): $(wc -c <"$f") bytes"; head -c 400 "$f"; echo; }; done
  else echo "no state folder (the profile has no addition, or it did not load)"; fi
fi

if [ -f "$R/events.jsonl" ]; then
  echo "## codex reference run"
  echo "answer bytes: $(wc -c <"$R/answer.md" 2>/dev/null || echo 0); stderr bytes: $(wc -c <"$R/stderr.txt")"; head -c 600 "$R/stderr.txt"; echo
  codex_events "$R/events.jsonl"
  jq -s '[.[] | select(.type=="turn.completed") | .usage] | {turns: length, input: (map(.input_tokens // 0) | add // 0), cached_input: (map(.cached_input_tokens // 0) | add // 0), output: (map(.output_tokens // 0) | add // 0), reasoning_output: (map(.reasoning_output_tokens // 0) | add // 0)} | .codex_tokens_input_plus_output = (.input + .output)' "$R/events.jsonl" >"$D/usage.codex.json"
  echo "codex usage: $(jq -c . "$D/usage.codex.json")"
fi

echo "## containment"
echo "checkout HEAD $(git -C "$W" rev-parse HEAD), commits $(git -C "$W" rev-list --all | wc -l), fix object present: $(git -C "$W" cat-file -e "$FIX" 2>/dev/null && echo YES || echo no)"
git --no-optional-locks -C "$W" status --porcelain=v1 --ignored >"$D/status.after"
if cmp -s "$D/status.before" "$D/status.after"; then echo "checkout status (ignored files included): unchanged"; else echo "checkout status CHANGED:"; diff "$D/status.before" "$D/status.after"; echo "CHECKOUT-CHANGED" >>"$D/flags.txt"; fi
git -C "$W" diff >"$R/patch.diff"; echo "patch bytes: $(wc -c <"$R/patch.diff")"
echo "new top-level names in the home directory: $(ls -A "$HOME" | diff "$D/home.before" - | grep -c '^[<>]')"
ls -A "$HOME" | diff "$D/home.before" - | grep '^[<>]'
echo "names under the home directory newer than the run start (depth 3; without .dsh, .codex, .cache/uv, src, .claude*, .orca, .local/share, .npm):"
find "$HOME" -maxdepth 3 -xdev \( -path "$HOME/.dsh" -o -path "$HOME/.codex" -o -path "$HOME/.cache/uv" -o -path "$HOME/src" -o -path "$HOME/.claude" -o -path "$HOME/.orca" -o -path "$HOME/orca" -o -path "$HOME/.local/share" -o -path "$HOME/.npm" \) -prune -o -newer "$D/started" -printf '  %P\n' 2>/dev/null | grep -v -E '^  (\.claude\.json.*|)$' | head -n 40
echo "run folder's scratch home entries: $(ls -A "$R/home" 2>/dev/null | wc -l); agents-home entries: $(ls -A "$R/agents-home" 2>/dev/null | wc -l)"
echo "dsh home listing, every changed line:"
find "$HOME/.dsh" -printf '%P\t%y\t%s\t%TY-%Tm-%Td %TH:%TM:%TS\n' | sort | diff "$D/dsh-listing.before" - | grep '^[<>]' | cut -c1-200
if sha256sum -c --quiet "$D/codex-config.sha256.before" >/dev/null 2>&1; then echo "~/.codex/config.toml: unchanged"; else echo "~/.codex/config.toml: CHANGED"; echo "CODEX-CONFIG-CHANGED" >>"$D/flags.txt"; fi
echo "names under ~/.codex newer than the run start (depth 2, names only):"; find "$HOME/.codex" -maxdepth 2 -newer "$D/started" -printf '  %P\n' | sort | head -n 60
echo "processes left with a working directory in the run folder:"
n=0; for d in /proc/[0-9]*; do c=$(readlink "$d/cwd" 2>/dev/null) || continue; case "$c" in "$D"|"$D"/*) echo "  pid ${d#/proc/} $(cat "$d/comm" 2>/dev/null) cwd $c"; n=$((n+1));; esac; done; echo "  count $n"; [ "$n" -eq 0 ] || echo "PROCESS-LEFT $n" >>"$D/flags.txt"

echo "## scans of the run folder"
"$GITLEAKS" dir --redact --no-banner --report-format json --report-path "$D/gitleaks.json" "$R" >/dev/null 2>&1; echo "gitleaks exit $?; findings: $(jq 'length' "$D/gitleaks.json" 2>/dev/null)"
jq -r '.[] | "\(.RuleID) \(.File):\(.StartLine)"' "$D/gitleaks.json" 2>/dev/null | sed "s|$R/||" | sort | uniq -c | head -n 20
[ "$(jq 'length' "$D/gitleaks.json" 2>/dev/null)" = 0 ] || echo "GITLEAKS-HIT" >>"$D/flags.txt"
k=$(grep -rlE 'sk-[0-9a-f]{32}' "$R" 2>/dev/null | wc -l); echo "files holding a key-shaped token: $k"; grep -rlE 'sk-[0-9a-f]{32}' "$R" 2>/dev/null | sed "s|$R/||"
[ "$k" -eq 0 ] || echo "KEYSHAPE-HIT $k" >>"$D/flags.txt"
new=$(diff "$D/status.before" "$D/status.after" | sed -n 's/^> ...//p'); if [ -n "$new" ]; then echo "new paths in the checkout:"; echo "$new"; fi

echo "## flags to review: $(wc -l <"$D/flags.txt")"; cat "$D/flags.txt"
rm -rf -- "$R/tmp"
