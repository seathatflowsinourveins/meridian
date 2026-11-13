#!/usr/bin/env bash
# ADR 0005 with/without series. Operator script written for this measurement (not downloaded code).
# Usage: ab.sh ok <a|b> <n> <0|1>   always-on run (+ /context) in a fresh worktree at main; last arg 1 = load the addition
#        ab.sh r1 <a|b> <n> <0|1>   one R1 run, then containment, leak scan, grading and cleanup
#        ab.sh validate             R1 setup and grader check: no change must fail, the reference fix must pass
#        ab.sh details              plugin validate --strict and plugin details (estimate)
# Exit: 0 done; 3 GATEWAY-UP; 4 binary changed; 5 worktree trouble; 6 run invalid (api error / limit / fallback)
set -uo pipefail
# Published copy (docs/adr/data/0005_ab.sh): a record of what ran, not a re-run protocol. It is
# the copy that ran from b-1 on (18,249 bytes, sha256
# 864b142aaa6b8f6a6b1982eee26ad566f6cb001a6525d795f69417b0dde226b7) plus this header, with three
# lines changed to keep the operator's home directory out. As they ran, with <home> for the home
# directory and <user> for the user name, they were:
#   CB=<home>/.local/share/claude/versions/2.1.322
#   the two Read rules in DENY, in single quotes: 'Read(/<home>/src/meridian/**)' 'Read(/<home>/src/meridian-ab/**)'
#   rm_project_dir's case pattern, literal: -home-<user>-src-meridian-worktrees-ab-0005-*)
# Removing this header and restoring those three lines gives 864b142a; dropping the final
# "exit 0" line as well gives 7416fbee. That earlier copy (installed 01:36:41 ET, 18,242 bytes,
# sha256 7416fbeed820f5fa79fee7eaf47ce2bbdafaae3ae3a60be3f0ab57bcb2272645) ran details, validate,
# the six always-on runs a-k1 to b-k3 and a-1; lacking the final "exit 0", it returned 1 after a
# valid run. It was not kept as a file; replaying the measurement session's Write and Edit calls
# reproduces both hashes. guard() ran before each agent start only: no listener on the Gateway's
# port and no process whose command line matched ibgateway (pgrep -f matches any process's argv).
ADR=0005
BASE_OK=9c5daaae9d32acf259f965fd7b95b458604503b6
BASE_R1=27aa964df79d646027d0060eb4d3a14bd49dae8f
TESTS_R1=5d51c9c163c34b689b5066bd931bb45412d69340
D=$HOME/src/ab-plugins/superpowers-v7.0.2
AB=$HOME/src/meridian-ab/$ADR
SCR=$AB/scripts
REPO=$HOME/src/meridian
CB=$HOME/.local/share/claude/versions/2.1.322
WTROOT=$HOME/src/meridian-worktrees
OUT=$AB/misc

log() { printf '%s %s\n' "$(date -Is)" "$*" >> "$OUT/run.log"; printf '%s %s\n' "$(date -Is)" "$*" >&2; }

guard() {
  [ "$(ss -Hltn 'sport = :4002' | wc -l)" = 0 ] && ! pgrep -f ibgateway >/dev/null || {
    echo GATEWAY-UP
    { echo "GATEWAY-UP $(date -Is) listeners_4002=$(ss -Hltn 'sport = :4002' | wc -l)"; pgrep -l -f ibgateway; } >> "$OUT/guard-fired.txt" 2>&1
    return 3; }
  log "guard ok (no :4002 listener, no ibgateway process)"
}

wt_add() { # path base
  git -C "$REPO" worktree add --detach "$1" "$2" >> "$OUT/run.log" 2>&1 && return 0
  log "worktree add failed for $1; waiting 5 s and trying once more"; sleep 5
  git -C "$REPO" worktree add --detach "$1" "$2" >> "$OUT/run.log" 2>&1 || { log "worktree add failed twice: $1"; return 5; }
}
wt_rm() { # path
  [ -e "$1" ] || return 0
  git -C "$REPO" worktree remove --force "$1" >> "$OUT/run.log" 2>&1 && return 0
  log "worktree remove failed for $1; waiting 5 s and trying once more"; sleep 5
  git -C "$REPO" worktree remove --force "$1" >> "$OUT/run.log" 2>&1 || log "worktree remove failed twice: $1"
}

prep() { # sets RUN FLAGS ADD DENY; needs OUT MEM WITH
  [ "$(readlink -f "$HOME/.local/bin/claude")" = "$CB" ] || { log "launcher target changed"; exit 4; }
  jq -n --arg m "$MEM" --slurpfile d "$SCR/deny.json" '{autoMemoryDirectory:$m, permissions:{deny:$d[0]}}' > "$OUT/settings.json"
  RUN=(env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_CODE_SUBAGENT_EFFORT -u ANTHROPIC_MODEL DISABLE_AUTOUPDATER=1 SUPERPOWERS_DISABLE_TELEMETRY=1 "$CB")
  FLAGS=(--model claude-opus-5-5 --effort high --permission-mode bypassPermissions --settings "$OUT/settings.json" --output-format stream-json --verbose)
  ADD=(); [ "$WITH" = 1 ] && ADD=(--plugin-dir "$D")
  # The ibgateway rule lives only in settings.json so that no argv carries that word (the guard greps argv).
  DENY=(--disallowedTools 'Bash(*meridian.ibkr_paper*)' 'Bash(*meridian.ib_probe*)' 'Bash(*meridian.boundary contract*)' "Read(/$HOME/src/meridian/**)" "Read(/$HOME/src/meridian-ab/**)" 'Bash(*poetry *)' 'Bash(*npm install*)' 'Bash(*gh issue*)' 'Bash(*start-server.sh*)')
  env | cut -d= -f1 | grep -E '^(CLAUDE|ANTHROPIC|DISABLE|ORCA|SUPERPOWERS)' | sort > "$OUT/env-names.txt"
  "$CB" --version > "$OUT/cc-version.txt" 2>&1
}

snap() { # label [wt]
  local s=$OUT/snap-$1 wt=${2:-}; mkdir -p "$s"
  ls -A "$HOME" > "$s/home.txt"
  ls -A /tmp > "$s/tmp.txt"
  ls -A "$HOME/.claude/plugins/data" > "$s/plugin-data.txt" 2>/dev/null || true
  ls -A "$HOME/.claude/plugins/cache" > "$s/plugin-cache.txt" 2>/dev/null || true
  git -C "$REPO" worktree list --porcelain | sed -n 's/^worktree //p' | sort > "$s/worktrees.txt"
  git -C "$REPO" for-each-ref --format='%(refname) %(objectname)' | sort > "$s/refs.txt"
  if [ -d "$HOME/.superpowers" ]; then find "$HOME/.superpowers" | sort > "$s/home-superpowers.txt"; else : > "$s/home-superpowers.txt"; fi
  { pgrep -l -f 'server\.cjs|brainstorm' || true; } | sort > "$s/companion-procs.txt"
  : > "$s/wt-procs.txt"
  if [ -n "$wt" ] && [ -d "$wt" ]; then
    git -C "$wt" status --porcelain=v1 --ignored > "$s/wt-status-ignored.txt" 2>&1
    git -C "$wt" rev-parse HEAD > "$s/wt-head.txt" 2>&1
    local p c
    for p in /proc/[0-9]*; do
      c=$(readlink "$p/cwd" 2>/dev/null) || continue
      case "$c" in "$wt"|"$wt"/*) echo "${p#/proc/} $(cat "$p/comm" 2>/dev/null)" >> "$s/wt-procs.txt";; esac
    done
  fi
}

copy_session() { # wt sid name
  local P PD; P=$(printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g'); PD=$HOME/.claude/projects/$P
  echo "$P" > "$OUT/project-dir-name.txt"
  if [ -f "$PD/$2.jsonl" ]; then cp "$PD/$2.jsonl" "$OUT/$3.transcript.jsonl"; else log "no transcript for $3 ($2)"; fi
  if [ -d "$PD/$2" ]; then cp -r "$PD/$2" "$OUT/$3.session"; fi
}
rm_project_dir() { # wt  (transcripts already copied into OUT; remove so later runs cannot read them)
  local P; P=$(printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g')
  case "$P" in "$(printf '%s' "$HOME" | sed 's/[^A-Za-z0-9]/-/g')"-src-meridian-worktrees-ab-0005-*) [ -d "$HOME/.claude/projects/$P" ] && rm -rf "$HOME/.claude/projects/$P";; esac
}

metrics() { # stream.jsonl
  jq -R 'fromjson? // empty' "$1" | jq -s '
    (map(select(.type=="system" and .subtype=="init"))[0]) as $i
    | (map(select(.type=="result"))|last) as $r
    | (map(select(.type=="assistant"))|first) as $a
    | {claude_code_version:$i.claude_code_version, model:$i.model, permissionMode:$i.permissionMode,
       plugins:[$i.plugins[]?|.name], plugin_paths:[$i.plugins[]?|.path], plugin_errors:$i.plugin_errors,
       n_skills:($i.skills|length), skills:$i.skills, n_slash_commands:($i.slash_commands|length),
       subtype:$r.subtype, is_error:$r.is_error, terminal_reason:$r.terminal_reason, api_error_status:$r.api_error_status,
       num_turns:$r.num_turns, duration_ms:$r.duration_ms, total_cost_usd:$r.total_cost_usd, usage:$r.usage,
       result_input_all:(($r.usage.input_tokens//0)+($r.usage.cache_creation_input_tokens//0)+($r.usage.cache_read_input_tokens//0)),
       first_assistant_input_all:(if $a then (($a.message.usage.input_tokens//0)+($a.message.usage.cache_creation_input_tokens//0)+($a.message.usage.cache_read_input_tokens//0)) else null end),
       model_keys:[($r.modelUsage//{})|keys[]],
       modelUsage:$r.modelUsage,
       tokens_all:([($r.modelUsage//{})[]|((.inputTokens//0)+(.cacheCreationInputTokens//0)+(.cacheReadInputTokens//0)+(.outputTokens//0))]|add),
       tokens_main:((($r.modelUsage//{})[$i.model]//{})|((.inputTokens//0)+(.cacheCreationInputTokens//0)+(.cacheReadInputTokens//0)+(.outputTokens//0))),
       permission_denials:$r.permission_denials,
       api_retries:(map(select(.type=="system" and .subtype=="api_retry"))|length),
       hook_events:[.[]|select(.type=="system" and (.subtype|tostring|startswith("hook_")))|{subtype, hook_name:(.hook_name//null), hook_event:(.hook_event//null)}]}'
}

leak_scan() { # wt mem
  local P f; P=$(cat "$OUT/project-dir-name.txt")
  for f in "$OUT"/*.stream.jsonl "$OUT"/*.transcript.jsonl "$OUT"/*.session/subagents/*.jsonl; do
    [ -f "$f" ] || continue
    jq -R 'fromjson? // empty' "$f" | jq -c '..|objects|select(.type?=="tool_use")|{name,input}'
  done | sort -u > "$OUT/tool_calls.jsonl"
  sed -e "s#$1#WT#g" -e "s#$2#MEM#g" -e "s#\.claude/projects/$P#OWNPROJ#g" "$OUT/tool_calls.jsonl" | grep -nEf "$SCR/leak-patterns.txt" > "$OUT/leak-hits.txt" || true
}

containment() { # wt
  local wt=$1 f flags=()
  {
    for f in home tmp plugin-data plugin-cache worktrees refs; do echo "== $f (pre -> post)"; diff "$OUT/snap-pre/$f.txt" "$OUT/snap-post/$f.txt"; done
    echo "== ~/.superpowers (post)"; cat "$OUT/snap-post/home-superpowers.txt"
    echo "== companion processes (post)"; cat "$OUT/snap-post/companion-procs.txt"
    echo "== processes with cwd in WT (post)"; cat "$OUT/snap-post/wt-procs.txt"
    echo "== WT status --ignored (pre -> post)"; diff "$OUT/snap-pre/wt-status-ignored.txt" "$OUT/snap-post/wt-status-ignored.txt"
    echo "== WT HEAD pre/post"; cat "$OUT/snap-pre/wt-head.txt" "$OUT/snap-post/wt-head.txt"
    echo "== addition paths in WT"; ls -la "$wt/.superpowers" "$wt/docs/superpowers" "$wt/.worktrees" 2>&1
  } > "$OUT/containment.txt" 2>&1
  [ -s "$OUT/snap-post/home-superpowers.txt" ] && [ ! -s "$OUT/snap-pre/home-superpowers.txt" ] && flags+=(home-superpowers-created)
  [ -n "$(comm -13 <(grep -E '^(brainstorm-|review-)' "$OUT/snap-pre/tmp.txt") <(grep -E '^(brainstorm-|review-)' "$OUT/snap-post/tmp.txt"))" ] && flags+=(tmp-brainstorm-or-review)
  [ -n "$(comm -13 "$OUT/snap-pre/worktrees.txt" "$OUT/snap-post/worktrees.txt" | grep -E "^/tmp/|review-|$wt/")" ] && flags+=(new-worktree-from-run)
  [ -n "$(comm -13 "$OUT/snap-pre/plugin-data.txt" "$OUT/snap-post/plugin-data.txt")" ] && flags+=(plugin-data-created)
  [ -s "$OUT/snap-post/wt-procs.txt" ] && flags+=(process-left-in-wt)
  [ -n "$(comm -13 "$OUT/snap-pre/companion-procs.txt" "$OUT/snap-post/companion-procs.txt")" ] && flags+=(companion-process)
  [ -d "$wt/docs/superpowers" ] && flags+=(docs-superpowers)
  [ -d "$wt/.worktrees" ] && flags+=(dot-worktrees)
  [ -d "$wt/.superpowers" ] && [ -n "$(find "$wt/.superpowers" -mindepth 1 -maxdepth 1 ! -name sdd)" ] && flags+=(superpowers-dir-outside-sdd)
  [ "$(cat "$OUT/snap-pre/wt-head.txt" 2>/dev/null)" != "$(cat "$OUT/snap-post/wt-head.txt" 2>/dev/null)" ] && flags+=(head-moved)
  if [ ${#flags[@]} -gt 0 ]; then printf '%s\n' "${flags[@]}" > "$OUT/containment-flags.txt"; else : > "$OUT/containment-flags.txt"; fi
  # stop anything the run left behind in its worktree (recorded above)
  local pid comm
  while read -r pid comm; do [ -n "$pid" ] && kill "$pid" 2>/dev/null && log "killed leftover $pid $comm"; done < "$OUT/snap-post/wt-procs.txt"
}

grade_r1() { # wt name  -> OUT/grade, OUT/fix.patch
  local wt=$1 G=$OUT/grade GW=$WTROOT/ab-$ADR-g-$2 apply=none
  mkdir -p "$G"
  git -C "$wt" rev-parse HEAD > "$G/head.txt"
  git -C "$wt" log --oneline "$BASE_R1..HEAD" > "$G/new-commits.txt" 2>&1
  git -C "$wt" diff --quiet "$TESTS_R1" -- tests/; echo $? > "$G/tests-unchanged.rc"
  git -C "$wt" diff --name-only "$BASE_R1" -- . ':(exclude)tests' ':(exclude)meridian' ':(exclude).gitignore' > "$G/outside-tracked.txt"
  git -C "$wt" ls-files --others --exclude-standard -- . ':(exclude)meridian' ':(exclude).gitignore' > "$G/outside-untracked.txt"
  { git -C "$wt" diff --name-status "$BASE_R1" -- meridian .gitignore; git -C "$wt" ls-files --others --exclude-standard -- meridian | sed 's/^/?? /'; } > "$G/allowed-changed.txt"
  git -C "$wt" add -A -- meridian .gitignore
  git -C "$wt" diff --cached --binary "$BASE_R1" -- meridian .gitignore > "$OUT/fix.patch"
  wt_add "$GW" "$BASE_R1" || return 5
  git -C "$GW" checkout "$TESTS_R1" -- tests/
  (cd "$GW" && uv sync --locked) > "$G/uv-sync.txt" 2>&1; echo $? > "$G/uv-sync.rc"
  if [ -s "$OUT/fix.patch" ]; then git -C "$GW" apply --binary "$OUT/fix.patch" > "$G/apply.txt" 2>&1; apply=$?; fi
  echo "$apply" > "$G/apply.rc"
  ( cd "$GW"
    uv run ruff check . > "$G/ruff-check.txt" 2>&1; echo $? > "$G/ruff-check.rc"
    uv run ruff format --check . > "$G/ruff-format.txt" 2>&1; echo $? > "$G/ruff-format.rc"
    uv run pyright > "$G/pyright.txt" 2>&1; echo $? > "$G/pyright.rc"
    uv run pytest > "$G/pytest.txt" 2>&1; echo $? > "$G/pytest.rc" )
  wt_rm "$GW"
  local pass=0
  [ "$(cat "$G/tests-unchanged.rc")" = 0 ] && [ ! -s "$G/outside-tracked.txt" ] && [ ! -s "$G/outside-untracked.txt" ] \
    && [ "$apply" = 0 ] && [ "$(cat "$G/ruff-check.rc")" = 0 ] && [ "$(cat "$G/ruff-format.rc")" = 0 ] \
    && [ "$(cat "$G/pyright.rc")" = 0 ] && [ "$(cat "$G/pytest.rc")" = 0 ] && pass=1
  echo "$pass" > "$G/passed"
  jq -n --arg passed "$pass" --arg tests_rc "$(cat "$G/tests-unchanged.rc")" --arg apply "$apply" \
     --arg ruff "$(cat "$G/ruff-check.rc")" --arg fmt "$(cat "$G/ruff-format.rc")" --arg pyright "$(cat "$G/pyright.rc")" --arg pytest "$(cat "$G/pytest.rc")" \
     --arg outside_tracked "$(paste -sd, "$G/outside-tracked.txt")" --arg outside_untracked "$(paste -sd, "$G/outside-untracked.txt")" \
     --arg allowed "$(paste -sd, "$G/allowed-changed.txt")" --arg commits "$(paste -sd, "$G/new-commits.txt")" \
     --arg pytest_tail "$(grep -v '^\s*$' "$G/pytest.txt" | tail -n 1)" --arg pyright_tail "$(grep -v '^\s*$' "$G/pyright.txt" | tail -n 1)" \
     '{passed:($passed=="1"), tests_unchanged_rc:$tests_rc, apply_rc:$apply, ruff_check_rc:$ruff, ruff_format_rc:$fmt, pyright_rc:$pyright, pytest_rc:$pytest,
       outside_tracked:$outside_tracked, outside_untracked:$outside_untracked, allowed_changed:$allowed, new_commits:$commits,
       pytest_tail:$pytest_tail, pyright_tail:$pyright_tail}' > "$G/grade.json"
}

invalid_reason() { # metrics.json -> prints a reason or nothing
  jq -r '
    if .terminal_reason == null then "no result event"
    elif (.terminal_reason|test("^(api_error|blocking_limit|rapid_refill_breaker|aborted_)")) then "terminal_reason " + .terminal_reason
    elif ((.model_keys|index("claude-opus-4-8")) or (.model_keys|index("claude-opus-5"))) then "fallback model in modelUsage"
    else empty end' "$1"
}

new_run() { # kind arm n with
  KIND=$1; ARM=$2; N=$3; WITH=$4
  case "$ARM" in a|b) ;; *) echo "bad arm"; exit 2;; esac
  case "$KIND" in ok) NAME=$ARM-k$N;; r1) NAME=$ARM-$N;; esac
  WT=$WTROOT/ab-$ADR-$NAME; OUT=$AB/$NAME; MEM=$HOME/.cache/claude-ab-mem/$ADR-$NAME
  if [ -e "$OUT" ] || [ -e "$WT" ]; then echo "already exists: $OUT or $WT"; exit 2; fi
  mkdir -p "$OUT" "$MEM"
  prep
  log "start $KIND $NAME"
}

finish_run() { # archive memory, remove worktree, memory and project dir
  if [ -n "$(ls -A "$MEM" 2>/dev/null)" ]; then cp -r "$MEM" "$OUT/mem"; fi
  wt_rm "$WT"; rm -rf "$MEM"; rm_project_dir "$WT"
  log "done $KIND $NAME"
}

case "${1:-}" in
ok)
  new_run ok "$2" "$3" "$4"
  wt_add "$WT" "$BASE_OK" || exit 5
  snap pre "$WT"
  guard || { wt_rm "$WT"; exit 3; }
  SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/ok.sid"
  (cd "$WT" && "${RUN[@]}" -p 'Reply with the single word OK. Do not use any tools.' "${FLAGS[@]}" "${ADD[@]}" --max-turns 1 --session-id "$SID" "${DENY[@]}" < /dev/null > "$OUT/ok.stream.jsonl" 2> "$OUT/ok.stderr.txt"); echo "$?" > "$OUT/ok.exit"
  guard || { wt_rm "$WT"; exit 3; }
  SID2=$(cat /proc/sys/kernel/random/uuid); echo "$SID2" > "$OUT/context.sid"
  (cd "$WT" && "${RUN[@]}" -p '/context' "${FLAGS[@]}" "${ADD[@]}" --session-id "$SID2" "${DENY[@]}" < /dev/null > "$OUT/context.stream.jsonl" 2> "$OUT/context.stderr.txt"); echo "$?" > "$OUT/context.exit"
  sleep 2
  snap post "$WT"
  copy_session "$WT" "$SID" ok; copy_session "$WT" "$SID2" context
  metrics "$OUT/ok.stream.jsonl" > "$OUT/metrics.json"
  jq -R 'fromjson? // empty' "$OUT/context.stream.jsonl" | jq -c 'select(.context_usage?)|.context_usage' > "$OUT/context_usage.json"
  jq -R 'fromjson? // empty' "$OUT/context.stream.jsonl" | jq -c 'select(.type=="result")|{subtype,is_error,num_turns,local_command:(.local_command//null),total_cost_usd,modelUsage}' > "$OUT/context_result.json"
  leak_scan "$WT" "$MEM"
  containment "$WT"
  finish_run
  r=$(invalid_reason "$OUT/metrics.json"); [ -n "$r" ] && { echo "$r" > "$OUT/invalid.txt"; log "INVALID: $r"; exit 6; }
  jq -c '{v:.claude_code_version, plugins, plugin_errors, valid:(.num_turns==1 and (.is_error|not) and .terminal_reason=="completed"), always_on:.result_input_all, first_assistant:.first_assistant_input_all, hooks:[.hook_events[].hook_name]}' "$OUT/metrics.json"
  ;;
r1)
  new_run r1 "$2" "$3" "$4"
  wt_add "$WT" "$BASE_R1" || exit 5
  git -C "$WT" checkout "$TESTS_R1" -- tests/ >> "$OUT/run.log" 2>&1
  (cd "$WT" && uv sync --locked) > "$OUT/uv-sync.txt" 2>&1; echo $? > "$OUT/uv-sync.rc"
  snap pre "$WT"
  guard || { wt_rm "$WT"; exit 3; }
  SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/r1.sid"
  t0=$(date +%s); date -Is > "$OUT/started_at.txt"
  (cd "$WT" && "${RUN[@]}" -p "$(cat "$AB/brief-R1.txt")" "${FLAGS[@]}" "${ADD[@]}" --max-turns 100 --session-id "$SID" "${DENY[@]}" < /dev/null > "$OUT/r1.stream.jsonl" 2> "$OUT/r1.stderr.txt"); echo "$?" > "$OUT/r1.exit"
  echo $(( $(date +%s) - t0 )) > "$OUT/wall_s.txt"
  sleep 3
  snap post "$WT"
  copy_session "$WT" "$SID" r1
  metrics "$OUT/r1.stream.jsonl" > "$OUT/metrics.json"
  leak_scan "$WT" "$MEM"
  containment "$WT"
  grade_r1 "$WT" "$ARM-$N"
  finish_run
  jq -n --slurpfile m "$OUT/metrics.json" --slurpfile g "$OUT/grade/grade.json" --arg flags "$(paste -sd, "$OUT/containment-flags.txt")" \
    --arg leaks "$(wc -l < "$OUT/leak-hits.txt")" --arg wall "$(cat "$OUT/wall_s.txt")" --arg exit "$(cat "$OUT/r1.exit")" \
    '{run:"'"$NAME"'", exit:$exit, wall_s:($wall|tonumber), passed:$g[0].passed, containment_flags:$flags, leak_hits:($leaks|tonumber),
      v:$m[0].claude_code_version, plugins:$m[0].plugins, plugin_errors:$m[0].plugin_errors, terminal_reason:$m[0].terminal_reason, subtype:$m[0].subtype,
      num_turns:$m[0].num_turns, duration_ms:$m[0].duration_ms, tokens_all:$m[0].tokens_all, tokens_main:$m[0].tokens_main, model_keys:$m[0].model_keys,
      total_cost_usd:$m[0].total_cost_usd, api_retries:$m[0].api_retries, permission_denials:($m[0].permission_denials|length), grade:$g[0]}' > "$OUT/summary.json"
  cat "$OUT/summary.json"
  r=$(invalid_reason "$OUT/metrics.json"); [ -n "$r" ] && { echo "$r" > "$OUT/invalid.txt"; log "INVALID: $r"; exit 6; }
  ;;
validate)
  for v in none ref; do
    OUT=$AB/validate/$v; mkdir -p "$OUT"; WT=$WTROOT/ab-$ADR-v-$v
    wt_add "$WT" "$BASE_R1" || exit 5
    git -C "$WT" checkout "$TESTS_R1" -- tests/ >> "$OUT/run.log" 2>&1
    (cd "$WT" && uv sync --locked) > "$OUT/uv-sync.txt" 2>&1; echo $? > "$OUT/uv-sync.rc"
    [ "$v" = ref ] && git -C "$WT" checkout "$TESTS_R1" -- meridian .gitignore >> "$OUT/run.log" 2>&1
    grade_r1 "$WT" "v-$v"
    wt_rm "$WT"
    echo "$v: $(jq -c . "$OUT/grade/grade.json")"
  done
  ;;
details)
  OUT=$AB/details; mkdir -p "$OUT"
  "$CB" plugin validate "$D" --strict > "$OUT/validate.txt" 2>&1; echo "exit=$?" >> "$OUT/validate.txt"
  "$CB" --plugin-dir "$D" plugin details superpowers > "$OUT/details.txt" 2>&1; echo "exit=$?" >> "$OUT/details.txt"
  cat "$OUT/validate.txt" "$OUT/details.txt"
  ;;
*) sed -n '2,8p' "$0"; exit 2;;
esac
exit 0
