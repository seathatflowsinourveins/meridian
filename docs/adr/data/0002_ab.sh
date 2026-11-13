#!/usr/bin/env bash
# ADR 0002 (pyright-lsp) with/without series. Operator script written for this measurement (not downloaded code).
# Method: method-claude.verify.json (verified 2026-11-12) + 0002 fact sheet (verified 2026-11-13).
# Usage: ab.sh ok <a|b> <n> <0|1>   always-on run (+ /context) in a fresh worktree at main; last arg 1 = load the addition
#        ab.sh r1 <a|b> <n> <0|1>   one R1 run, then containment, leak scan, grading and cleanup
#        ab.sh validate             R1 setup and grader check: no change must fail, the reference fix must pass
#        ab.sh details              plugin validate --strict and plugin details (estimate)
# Exit: 0 done; 3 GATEWAY-UP; 4 binary changed; 5 worktree trouble; 6 run invalid (api error / limit / fallback)
set -uo pipefail
# Published copy (docs/adr/data/0002_ab.sh). The operator's home directory is written as $HOME
# in CB, in the two Read deny rules and in rm_project_dir's pattern, and leak_scan was corrected after
# the series (below); otherwise as run (sha256 of the copy that ran, which names the home directory:
# d1338c2b83d37b89cf4c59d90b22dd2299b8240dd9abdb8db31aed07dd144efe).
# $SCR/deny.json is 0002-deny.json (home written as ~), $SCR/brief-R1.txt is 0002-brief-R1.txt and
# $SCR/leak-patterns.txt is 0002-leak-patterns.txt. lsp_markers counts the fact sheet's wording
# 'Starting LSP server instance: pyright', which 2.1.322 does not print; 0002_collect_r2.sh counts
# the 2.1.322 wording, 'Starting LSP server instance: plugin:pyright-lsp:pyright'.
# leak_scan, corrected for later series. As run it kept {name,input} with sort -u over the stream and the
# transcript; 2.1.322's transcript held a second copy of each call in 5 of the 6 R1 runs, a Bash command with a
# 'cd <worktree> && ' prefix and an Edit with its input keys in another order, so those were counted twice.
# And its patterns named the Gateway's process and port but not its folder, ~/Jts.
# Now: one line per tool_use id, and 'Jts|jts\.ini' added. 0002_rescan.py recounts this series' runs that way.
ADR=0002
BASE_OK=9c5daaae9d32acf259f965fd7b95b458604503b6
BASE_R1=27aa964df79d646027d0060eb4d3a14bd49dae8f
TESTS_R1=5d51c9c163c34b689b5066bd931bb45412d69340
D=$HOME/src/ab-plugins/pyright-lsp-f75f5b2
AB=$HOME/src/meridian-ab/$ADR
SCR=$AB/scripts
REPO=$HOME/src/meridian
CB=$HOME/.local/share/claude/versions/2.1.322
WTROOT=$HOME/src/meridian-worktrees
OUT=$AB/misc
mkdir -p "$OUT"

log() { printf '%s %s\n' "$(date -Is)" "$*" >> "$OUT/run.log"; printf '%s %s\n' "$(date -Is)" "$*" >&2; }

guard() {
  [ "$(ss -Hltn 'sport = :4002' | wc -l)" = 0 ] && ! pgrep -f ibgateway >/dev/null || {
    echo GATEWAY-UP
    { echo "GATEWAY-UP $(date -Is) listeners_4002=$(ss -Hltn 'sport = :4002' | wc -l)"; pgrep -a -f ibgateway | cut -c1-300; } >> "$OUT/guard-fired.txt" 2>&1
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

prep() { # sets RUN FLAGS ADD DENY; needs OUT MEM WITH WT
  [ "$(readlink -f "$HOME/.local/bin/claude")" = "$CB" ] || { log "launcher target changed"; exit 4; }
  jq -n --arg m "$MEM" --slurpfile d "$SCR/deny.json" '{autoMemoryDirectory:$m, permissions:{deny:$d[0]}}' > "$OUT/settings.json"
  # Both arms: the worktree venv first on PATH, so pyright-langserver (pyright[nodejs] 1.1.414 from uv.lock) is found.
  RUN=(env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_CODE_SUBAGENT_EFFORT -u ANTHROPIC_MODEL -u VIRTUAL_ENV DISABLE_AUTOUPDATER=1 "PATH=$WT/.venv/bin:$PATH" "$CB")
  FLAGS=(--model claude-opus-5-5 --effort high --permission-mode bypassPermissions --settings "$OUT/settings.json" --output-format stream-json --verbose)
  ADD=(); [ "$WITH" = 1 ] && ADD=(--plugin-dir "$D")
  # The gateway rule lives only in settings.json so that no argv carries that word (the guard greps argv).
  DENY=(--disallowedTools 'Bash(*meridian.ibkr_paper*)' 'Bash(*meridian.ib_probe*)' 'Bash(*meridian.boundary contract*)' "Read(/$HOME/src/meridian/**)" "Read(/$HOME/src/meridian-ab/**)" 'Bash(*npm install*)' 'Bash(*pip install*)' 'Bash(*pipx install*)')
  env | cut -d= -f1 | grep -E '^(CLAUDE|ANTHROPIC|DISABLE|ORCA|VIRTUAL|PYRIGHT)' | sort > "$OUT/env-names.txt"
  "$CB" --version > "$OUT/cc-version.txt" 2>&1
}

langserver_check() { # wt -> which pyright-langserver the run's PATH resolves
  env "PATH=$1/.venv/bin:$PATH" bash -c 'command -v pyright-langserver || echo NOT-FOUND' > "$OUT/langserver-path.txt" 2>&1
}

snap() { # label [wt]
  local s=$OUT/snap-$1 wt=${2:-}; mkdir -p "$s"
  ls -A "$HOME" > "$s/home.txt"
  ls -A /tmp > "$s/tmp.txt"
  ls -A "$HOME/.cache" > "$s/cache.txt" 2>/dev/null || true
  ls -A "$HOME/.claude/plugins/data" > "$s/plugin-data.txt" 2>/dev/null || true
  ls -A "$HOME/.claude/plugins/cache" > "$s/plugin-cache.txt" 2>/dev/null || true
  ls -A "$HOME/.claude/plugins/marketplaces" > "$s/plugin-marketplaces.txt" 2>/dev/null || true
  { sha256sum "$HOME/.claude/settings.json" "$HOME/.claude/plugins/installed_plugins.json" "$HOME/.claude/plugins/known_marketplaces.json" 2>&1 | sed "s#$HOME#~#"; } > "$s/plugin-records.sha256"
  jq -r 'keys[]' "$HOME/.claude.json" > "$s/claude-json-keys.txt" 2>/dev/null || true   # key names only
  if [ -d "$HOME/.claude/debug" ]; then echo present; else echo absent; fi > "$s/debug-dir.txt"
  git -C "$REPO" worktree list --porcelain | sed -n 's/^worktree //p' | sort > "$s/worktrees.txt"
  git -C "$REPO" for-each-ref --format='%(refname) %(objectname)' | sort > "$s/refs.txt"
  { pgrep -a -f 'pyright-langserver|langserver\.index' | cut -c1-200 || true; } | sort > "$s/langserver-procs.txt"
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
  case "$P" in "$(printf '%s' "$HOME" | sed 's/[^A-Za-z0-9]/-/g')"-src-meridian-worktrees-ab-0002-*) [ -d "$HOME/.claude/projects/$P" ] && rm -rf "$HOME/.claude/projects/$P";; esac
}

metrics() { # stream.jsonl
  jq -R 'fromjson? // empty' "$1" | jq -s '
    (map(select(.type=="system" and .subtype=="init"))[0]) as $i
    | (map(select(.type=="result"))|last) as $r
    | (map(select(.type=="assistant"))|first) as $a
    | {claude_code_version:$i.claude_code_version, model:$i.model, permissionMode:$i.permissionMode,
       plugins:[$i.plugins[]?|.name], plugin_paths:[$i.plugins[]?|.path], plugin_errors:$i.plugin_errors,
       n_tools:($i.tools|length), tools:$i.tools, n_skills:($i.skills|length), n_slash_commands:($i.slash_commands|length),
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

lsp_markers() { # debug file -> json counts (fact sheet validity markers)
  local f=$1
  jq -n --arg l "$(grep -cF 'LSP server(s) from plugin: pyright-lsp' "$f" 2>/dev/null)" \
        --arg l1 "$(grep -cF 'Loaded 1 LSP server(s) from plugin: pyright-lsp' "$f" 2>/dev/null)" \
        --arg s "$(grep -cF 'Starting LSP server instance: pyright' "$f" 2>/dev/null)" \
        --arg d "$(grep -cF 'LSP Diagnostics: Delivering' "$f" 2>/dev/null)" \
        --arg e "$(grep -ciE 'lsp.*(error|fail)' "$f" 2>/dev/null)" \
     '{loaded_any:($l|tonumber? // 0), loaded_1:($l1|tonumber? // 0), started:($s|tonumber? // 0), delivering:($d|tonumber? // 0), lsp_error_lines:($e|tonumber? // 0)}'
}

leak_scan() { # wt mem  (corrected after the series: see the header)
  local P f; P=$(cat "$OUT/project-dir-name.txt")
  for f in "$OUT"/*.stream.jsonl "$OUT"/*.transcript.jsonl "$OUT"/*.session/subagents/*.jsonl; do
    [ -f "$f" ] || continue
    jq -R 'fromjson? // empty' "$f" | jq -c '..|objects|select(.type?=="tool_use")|{id,name,input}'
  done | jq -s -c 'unique_by(.id)[]|{name,input}' > "$OUT/tool_calls.jsonl"
  sed -e "s#$1#WT#g" -e "s#$2#MEM#g" -e "s#\.claude/projects/$P#OWNPROJ#g" "$OUT/tool_calls.jsonl" | grep -nE -f "$SCR/leak-patterns.txt" -e 'Jts|jts\.ini' > "$OUT/leak-hits.txt" || true
}

containment() { # wt
  local wt=$1 f flags=()
  {
    for f in home tmp cache plugin-data plugin-cache plugin-marketplaces worktrees refs claude-json-keys debug-dir langserver-procs; do echo "== $f (pre -> post)"; diff "$OUT/snap-pre/$f.txt" "$OUT/snap-post/$f.txt"; done
    echo "== plugin records sha256 (pre -> post)"; diff "$OUT/snap-pre/plugin-records.sha256" "$OUT/snap-post/plugin-records.sha256"
    echo "== processes with cwd in WT (post)"; cat "$OUT/snap-post/wt-procs.txt"
    echo "== WT status --ignored (pre -> post)"; diff "$OUT/snap-pre/wt-status-ignored.txt" "$OUT/snap-post/wt-status-ignored.txt"
    echo "== WT HEAD pre/post"; cat "$OUT/snap-pre/wt-head.txt" "$OUT/snap-post/wt-head.txt"
  } > "$OUT/containment.txt" 2>&1
  [ -n "$(comm -13 "$OUT/snap-pre/plugin-data.txt" "$OUT/snap-post/plugin-data.txt" | grep -iE 'pyright|lsp|inline')" ] && flags+=(plugin-data-created)
  diff -q "$OUT/snap-pre/plugin-cache.txt" "$OUT/snap-post/plugin-cache.txt" >/dev/null || flags+=(plugin-cache-changed)
  diff -q "$OUT/snap-pre/plugin-marketplaces.txt" "$OUT/snap-post/plugin-marketplaces.txt" >/dev/null || flags+=(marketplaces-changed)
  diff -q "$OUT/snap-pre/plugin-records.sha256" "$OUT/snap-post/plugin-records.sha256" >/dev/null || flags+=(plugin-records-or-settings-changed)
  [ -n "$(comm -13 <(sort "$OUT/snap-pre/claude-json-keys.txt") <(sort "$OUT/snap-post/claude-json-keys.txt"))" ] && flags+=(claude-json-new-keys)
  [ "$(cat "$OUT/snap-post/debug-dir.txt")" = present ] && [ "$(cat "$OUT/snap-pre/debug-dir.txt")" = absent ] && flags+=(debug-dir-created)
  [ -n "$(comm -13 <(sort "$OUT/snap-pre/home.txt") <(sort "$OUT/snap-post/home.txt") | grep -iE 'pyright|lsp|langserver|node|npm')" ] && flags+=(home-entry-from-addition)
  [ -n "$(comm -13 <(sort "$OUT/snap-pre/tmp.txt") <(sort "$OUT/snap-post/tmp.txt") | grep -iE 'pyright|lsp|langserver|node|npm')" ] && flags+=(tmp-entry-from-addition)
  [ -n "$(comm -13 <(sort "$OUT/snap-pre/cache.txt") <(sort "$OUT/snap-post/cache.txt") | grep -iE 'pyright|lsp|langserver|node|npm')" ] && flags+=(cache-entry-from-addition)
  [ -n "$(comm -13 "$OUT/snap-pre/worktrees.txt" "$OUT/snap-post/worktrees.txt" | grep -E "^/tmp/|$wt/|ab-$ADR")" ] && flags+=(new-worktree-from-run)
  [ -s "$OUT/snap-post/wt-procs.txt" ] && flags+=(process-left-in-wt)
  [ -n "$(comm -13 "$OUT/snap-pre/langserver-procs.txt" "$OUT/snap-post/langserver-procs.txt")" ] && flags+=(langserver-left-running)
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
  (cd "$WT" && uv sync --locked) > "$OUT/uv-sync.txt" 2>&1; echo $? > "$OUT/uv-sync.rc"
  langserver_check "$WT"
  snap pre "$WT"
  guard || { wt_rm "$WT"; exit 3; }
  SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/ok.sid"
  (cd "$WT" && "${RUN[@]}" -p 'Reply with the single word OK. Do not use any tools.' "${FLAGS[@]}" "${ADD[@]}" --debug-file "$OUT/ok.debug.txt" --max-turns 1 --session-id "$SID" "${DENY[@]}" < /dev/null > "$OUT/ok.stream.jsonl" 2> "$OUT/ok.stderr.txt"); echo "$?" > "$OUT/ok.exit"
  guard || { wt_rm "$WT"; exit 3; }
  SID2=$(cat /proc/sys/kernel/random/uuid); echo "$SID2" > "$OUT/context.sid"
  (cd "$WT" && "${RUN[@]}" -p '/context' "${FLAGS[@]}" "${ADD[@]}" --debug-file "$OUT/context.debug.txt" --session-id "$SID2" "${DENY[@]}" < /dev/null > "$OUT/context.stream.jsonl" 2> "$OUT/context.stderr.txt"); echo "$?" > "$OUT/context.exit"
  sleep 5
  snap post "$WT"
  copy_session "$WT" "$SID" ok; copy_session "$WT" "$SID2" context
  metrics "$OUT/ok.stream.jsonl" > "$OUT/metrics.json"
  lsp_markers "$OUT/ok.debug.txt" > "$OUT/lsp-markers.json"
  jq -R 'fromjson? // empty' "$OUT/context.stream.jsonl" | jq -c 'select(.context_usage?)|.context_usage' > "$OUT/context_usage.json"
  jq -R 'fromjson? // empty' "$OUT/context.stream.jsonl" | jq -c 'select(.type=="result")|{subtype,is_error,num_turns,local_command:(.local_command//null),total_cost_usd,modelUsage}' > "$OUT/context_result.json"
  leak_scan "$WT" "$MEM"
  containment "$WT"
  finish_run
  r=$(invalid_reason "$OUT/metrics.json"); [ -n "$r" ] && { echo "$r" > "$OUT/invalid.txt"; log "INVALID: $r"; exit 6; }
  jq -c --slurpfile l "$OUT/lsp-markers.json" --arg flags "$(paste -sd, "$OUT/containment-flags.txt")" '{v:.claude_code_version, plugins, plugin_errors, n_tools, valid:(.num_turns==1 and (.is_error|not) and .terminal_reason=="completed"), always_on:.result_input_all, first_assistant:.first_assistant_input_all, lsp:$l[0], flags:$flags}' "$OUT/metrics.json"
  ;;
r1)
  new_run r1 "$2" "$3" "$4"
  wt_add "$WT" "$BASE_R1" || exit 5
  git -C "$WT" checkout "$TESTS_R1" -- tests/ >> "$OUT/run.log" 2>&1
  (cd "$WT" && uv sync --locked) > "$OUT/uv-sync.txt" 2>&1; echo $? > "$OUT/uv-sync.rc"
  langserver_check "$WT"
  snap pre "$WT"
  guard || { wt_rm "$WT"; exit 3; }
  SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/r1.sid"
  t0=$(date +%s); date -Is > "$OUT/started_at.txt"
  (cd "$WT" && "${RUN[@]}" -p "$(cat "$SCR/brief-R1.txt")" "${FLAGS[@]}" "${ADD[@]}" --debug-file "$OUT/r1.debug.txt" --max-turns 100 --session-id "$SID" "${DENY[@]}" < /dev/null > "$OUT/r1.stream.jsonl" 2> "$OUT/r1.stderr.txt"); echo "$?" > "$OUT/r1.exit"
  echo $(( $(date +%s) - t0 )) > "$OUT/wall_s.txt"
  sleep 5
  snap post "$WT"
  copy_session "$WT" "$SID" r1
  metrics "$OUT/r1.stream.jsonl" > "$OUT/metrics.json"
  lsp_markers "$OUT/r1.debug.txt" > "$OUT/lsp-markers.json"
  leak_scan "$WT" "$MEM"
  containment "$WT"
  grade_r1 "$WT" "$ARM-$N"
  finish_run
  jq -n --slurpfile m "$OUT/metrics.json" --slurpfile g "$OUT/grade/grade.json" --slurpfile l "$OUT/lsp-markers.json" --arg flags "$(paste -sd, "$OUT/containment-flags.txt")" \
    --arg leaks "$(wc -l < "$OUT/leak-hits.txt")" --arg wall "$(cat "$OUT/wall_s.txt")" --arg exit "$(cat "$OUT/r1.exit")" \
    '{run:"'"$NAME"'", exit:$exit, wall_s:($wall|tonumber), passed:$g[0].passed, containment_flags:$flags, leak_hits:($leaks|tonumber), lsp:$l[0],
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
    langserver_check "$WT"
    [ "$v" = ref ] && git -C "$WT" checkout "$TESTS_R1" -- meridian .gitignore >> "$OUT/run.log" 2>&1
    grade_r1 "$WT" "v-$v"
    wt_rm "$WT"
    echo "$v: $(jq -c . "$OUT/grade/grade.json") langserver=$(cat "$OUT/langserver-path.txt")"
  done
  ;;
details)
  OUT=$AB/details; mkdir -p "$OUT"
  "$CB" plugin validate "$D" --strict > "$OUT/validate.txt" 2>&1; echo "exit=$?" >> "$OUT/validate.txt"
  "$CB" --plugin-dir "$D" plugin details pyright-lsp > "$OUT/details.txt" 2>&1; echo "exit=$?" >> "$OUT/details.txt"
  cat "$OUT/validate.txt" "$OUT/details.txt"
  ;;
*) sed -n '2,9p' "$0"; exit 2;;
esac
exit 0
