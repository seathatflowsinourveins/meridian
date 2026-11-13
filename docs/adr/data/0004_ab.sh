#!/usr/bin/env bash
# ADR 0004 with/without series: mattpocock/skills tdd + diagnosing-bugs at d1478fc, copy route.
# Operator script written for this measurement (not downloaded code). Runs in WSL distro meridian.
# Usage: ab0004.sh ok <a|b> <n> <0|1>                 always-on run (+ /context) at main; last arg 1 = with the copies
#        ab0004.sh run <r1|r2|r3> <a|b> <n> <0|1>     one task run, then containment, leak scan, grading, cleanup
#        ab0004.sh series <kind> <arm:n:with> ...     kind ok|r1|r2|r3; stops on gateway, binary change, invalid run
#        ab0004.sh validate <r1|r2|r3>                setup and grader check (no change fails, reference passes)
# Exit: 0 done; 3 GATEWAY-UP; 4 binary changed; 5 worktree trouble; 6 run invalid (api error / limit / fallback)
set -uo pipefail
# Published copy (docs/adr/data/0004_ab.sh): the operator's home directory is written as $HOME, or as
# $REAL_HOME where HOME points elsewhere; otherwise as run on 2026-11-13.
ADR=0004
REAL_HOME=$HOME
BASE_OK=9c5daaae9d32acf259f965fd7b95b458604503b6
C27=27aa964df79d646027d0060eb4d3a14bd49dae8f
C5D=5d51c9c163c34b689b5066bd931bb45412d69340
C96=96e82e6b521cdb9c7d172176898d20e2658ec50b
C39=39cb68ea3241caeececb6db0521a12ea2fa92fee
AB=$HOME/src/meridian-ab/$ADR
ADDN=$AB/addition
SCR=$AB/scripts
REPO=$HOME/src/meridian
CB=$HOME/.local/share/claude/versions/2.1.322
WTROOT=$HOME/src/meridian-worktrees
LOG=$AB/run.log
SKILLS=(tdd diagnosing-bugs)
FAKEHOME=$AB/fakehome   # grading runs agent-written tests; a fake HOME keeps them away from ~/Jts
EXCL_COPIES=(':(exclude).claude/skills/tdd' ':(exclude).claude/skills/diagnosing-bugs')

pyt() { # uv run pytest under the fake HOME (uv cache and pythons from the real home)
  mkdir -p "$FAKEHOME"
  HOME="$FAKEHOME" UV_CACHE_DIR="$REAL_HOME/.cache/uv" UV_PYTHON_INSTALL_DIR="$REAL_HOME/.local/share/uv/python" uv run pytest -p no:cacheprovider "$@"
}

log() { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; printf '%s %s\n' "$(date -Is)" "$*" >&2; }

guard() { # the owner's guard, verbatim condition
  [ "$(ss -Hltn 'sport = :4002' | wc -l)" = 0 ] && ! pgrep -f ibgateway >/dev/null || {
    echo GATEWAY-UP
    { echo "GATEWAY-UP $(date -Is) listeners_4002=$(ss -Hltn 'sport = :4002' | wc -l)"; pgrep -l -f ibgateway; } >> "$AB/guard-fired.txt" 2>&1
    return 3; }
  log "guard ok"
}

wt_add() { # path base
  git -C "$REPO" worktree add --detach "$1" "$2" >> "$LOG" 2>&1 && return 0
  log "worktree add failed for $1; waiting 5 s and trying once more"; sleep 5
  git -C "$REPO" worktree add --detach "$1" "$2" >> "$LOG" 2>&1 || { log "worktree add failed twice: $1"; return 5; }
}
wt_rm() { # path
  [ -e "$1" ] || return 0
  git -C "$REPO" worktree remove --force "$1" >> "$LOG" 2>&1 && return 0
  log "worktree remove failed for $1; waiting 5 s and trying once more"; sleep 5
  git -C "$REPO" worktree remove --force "$1" >> "$LOG" 2>&1 || log "worktree remove failed twice: $1"
}

task_setup() { # task -> BASE TESTS
  case "$1" in
    r1) BASE=$C27; TESTS=$C5D;;
    r2) BASE=$C96; TESTS=$C39;;
    r3) BASE=$C96; TESTS=;;
    *) echo "bad task $1"; exit 2;;
  esac
}

place_addition() { # wt mode(ok|task)
  local wt=$1 s
  if [ "$2" = ok ]; then
    for s in "${SKILLS[@]}"; do cp -R "$ADDN/$s" "$wt/.agents/skills/$s"; ln -s "../../.agents/skills/$s" "$wt/.claude/skills/$s"; done
  else
    mkdir -p "$wt/.claude/skills"
    for s in "${SKILLS[@]}"; do cp -R "$ADDN/$s" "$wt/.claude/skills/$s"; done
  fi
}
check_copies() { # wt mode -> prints mismatches (empty = all 7 blobs as pinned)
  local root=$1/.claude/skills h f
  [ "$2" = ok ] && root=$1/.agents/skills
  while read -r h f; do
    [ "$(git hash-object "$root/$f" 2>/dev/null)" = "$h" ] || echo "MISMATCH $f"
  done < "$ADDN/hashes.txt"
  for s in "${SKILLS[@]}"; do
    [ "$(find "$root/$s" -type f | wc -l)" = "$(grep -c " $s/" "$ADDN/hashes.txt")" ] || echo "FILECOUNT $s"
  done
}

prep() { # sets RUN FLAGS DENY; needs OUT MEM
  [ "$(readlink -f "$HOME/.local/bin/claude")" = "$CB" ] || { log "launcher target changed"; exit 4; }
  jq -n --arg m "$MEM" --slurpfile d "$SCR/deny.json" --argjson x "${EXTRA_SET:-{\}}" '{autoMemoryDirectory:$m, permissions:{deny:$d[0]}} + $x' > "$OUT/settings.json"
  RUN=(env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_CODE_SUBAGENT_EFFORT -u ANTHROPIC_MODEL DISABLE_AUTOUPDATER=1 timeout --kill-after=30 5400 "$CB")
  FLAGS=(--model claude-opus-5-5 --effort high --permission-mode bypassPermissions --settings "$OUT/settings.json" --output-format stream-json --verbose)
  # The gateway rule lives only in settings.json, so that no argv carries that word (the guard greps argv).
  DENY=(--disallowedTools 'Bash(*meridian.ibkr_paper*)' 'Bash(*meridian.ib_probe*)' 'Bash(*meridian.boundary contract*)' "Read(/$HOME/src/meridian/**)" "Read(/$HOME/src/meridian-ab/**)")
  env | cut -d= -f1 | grep -E '^(CLAUDE|ANTHROPIC|DISABLE|ORCA)' | sort > "$OUT/env-names.txt"
  "$CB" --version > "$OUT/cc-version.txt" 2>&1
}

snap() { # label wt
  local s=$OUT/snap-$1 wt=$2 p c; mkdir -p "$s"
  ls -A "$HOME" > "$s/home.txt"
  ls -A /tmp > "$s/tmp.txt"
  { ls -A "$HOME/.claude/skills" 2>/dev/null; echo "--"; ls -A "$HOME/.agents" 2>/dev/null; echo "--"; ls -A "$HOME/.agents/skills" 2>/dev/null; echo "--"; ls -A "$HOME/.codex/skills" 2>/dev/null; } > "$s/user-skills.txt"
  stat -c '%n %Y %s' "$HOME/.claude/settings.json" > "$s/settings-stat.txt" 2>&1
  ls -A "$HOME/.claude/plugins/data" > "$s/plugin-data.txt" 2>/dev/null || true
  git -C "$REPO" worktree list --porcelain | sed -n 's/^worktree //p' | sort > "$s/worktrees.txt"
  git -C "$REPO" for-each-ref --format='%(refname) %(objectname)' | sort > "$s/refs.txt"
  : > "$s/wt-procs.txt"; : > "$s/wt-status-ignored.txt"; : > "$s/wt-head.txt"; : > "$s/wt-gitstate.txt"
  if [ -d "$wt" ]; then
    git -C "$wt" status --porcelain=v1 --ignored --untracked-files=all > "$s/wt-status-ignored.txt" 2>&1
    git -C "$wt" rev-parse HEAD > "$s/wt-head.txt" 2>&1
    git -C "$wt" for-each-ref --format='%(refname)' refs/bisect refs/worktree refs/stash > "$s/wt-gitstate.txt" 2>&1
    local gd; gd=$(git -C "$wt" rev-parse --absolute-git-dir)
    for p in BISECT_LOG MERGE_HEAD REBASE_HEAD; do [ -e "$gd/$p" ] && echo "$p" >> "$s/wt-gitstate.txt"; done
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
rm_project_dir() { # wt (transcripts already copied into OUT; removed so later runs cannot read them)
  local P; P=$(printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g')
  case "$P" in "$(printf '%s' "$WTROOT" | sed 's/[^A-Za-z0-9]/-/g')-ab-0004-"*) [ -d "$HOME/.claude/projects/$P" ] && rm -rf "$HOME/.claude/projects/$P";; esac
}

metrics() { # stream.jsonl
  jq -R 'fromjson? // empty' "$1" | jq -s '
    (map(select(.type=="system" and .subtype=="init"))[0]) as $i
    | (map(select(.type=="result"))|last) as $r
    | {claude_code_version:$i.claude_code_version, model:$i.model, permissionMode:$i.permissionMode,
       plugins:[$i.plugins[]?|.name], plugin_errors:$i.plugin_errors, skills:$i.skills,
       subtype:$r.subtype, is_error:$r.is_error, terminal_reason:$r.terminal_reason, api_error_status:$r.api_error_status,
       num_turns:$r.num_turns, duration_ms:$r.duration_ms, total_cost_usd:$r.total_cost_usd, usage:$r.usage,
       result_input_all:(($r.usage.input_tokens//0)+($r.usage.cache_creation_input_tokens//0)+($r.usage.cache_read_input_tokens//0)),
       model_keys:[($r.modelUsage//{})|keys[]], modelUsage:$r.modelUsage,
       tokens_all:([($r.modelUsage//{})[]|((.inputTokens//0)+(.cacheCreationInputTokens//0)+(.cacheReadInputTokens//0)+(.outputTokens//0))]|add),
       tokens_main:((($r.modelUsage//{})[$i.model]//{})|((.inputTokens//0)+(.cacheCreationInputTokens//0)+(.cacheReadInputTokens//0)+(.outputTokens//0))),
       output_tokens_all:([($r.modelUsage//{})[]|(.outputTokens//0)]|add),
       permission_denials:$r.permission_denials,
       api_retries:(map(select(.type=="system" and .subtype=="api_retry"))|length),
       final_text:($r.result // ""),
       hook_events:([.[]|select(.type=="system" and (.subtype|tostring|startswith("hook_")))|(.hook_event//.hook_name//.subtype)]|unique)}'
}

leak_scan() { # wt mem
  local P f; P=$(cat "$OUT/project-dir-name.txt")
  for f in "$OUT"/*.stream.jsonl "$OUT"/*.transcript.jsonl "$OUT"/*.session/subagents/*.jsonl; do
    [ -f "$f" ] || continue
    jq -R 'fromjson? // empty' "$f" | jq -c '..|objects|select(.type?=="tool_use")|{name,input}'
  done | sort -u > "$OUT/tool_calls.jsonl"
  sed -e "s#$1#WT#g" -e "s#$2#MEM#g" -e "s#\.claude/projects/$P#OWNPROJ#g" "$OUT/tool_calls.jsonl" | grep -nEf "$SCR/leak-patterns.txt" > "$OUT/leak-hits.txt" || true
  grep -nE 'Jts|risk/boundary\.contract|/runs/|\.env\b|credentials' "$OUT/tool_calls.jsonl" > "$OUT/sensitive-hits.txt" || true
  grep -c '/tmp' "$OUT/tool_calls.jsonl" > "$OUT/tmp-mentions.txt" || true
}

skill_use() { # -> skill-use.json from tool_calls.jsonl
  jq -s '{skill_tool:[.[]|select(.name=="Skill")|(.input.skill // .input.command // .input.name // tostring)],
          skill_file_reads:[.[]|select(.name=="Read")|(.input.file_path // "")|select(test("skills/(tdd|diagnosing-bugs)/"))]}' "$OUT/tool_calls.jsonl" > "$OUT/skill-use.json"
}

containment() { # wt mode
  local wt=$1 f flags=()
  {
    for f in home tmp user-skills settings-stat plugin-data worktrees refs; do echo "== $f (pre -> post)"; diff "$OUT/snap-pre/$f.txt" "$OUT/snap-post/$f.txt"; done
    echo "== processes with cwd in WT (post)"; cat "$OUT/snap-post/wt-procs.txt"
    echo "== WT status --ignored (pre -> post)"; diff "$OUT/snap-pre/wt-status-ignored.txt" "$OUT/snap-post/wt-status-ignored.txt"
    echo "== WT HEAD pre/post"; cat "$OUT/snap-pre/wt-head.txt" "$OUT/snap-post/wt-head.txt"
    echo "== WT git state (post)"; cat "$OUT/snap-post/wt-gitstate.txt"
    echo "== addition copies"; cat "$OUT/copies-post.txt" 2>/dev/null
    echo "== addition-style artifacts in WT"; ls -d "$wt/GLOSSARY.md" "$wt/CONTEXT.md" "$wt/docs/agents" "$wt/docs/adr" "$wt/.scratch" 2>&1
    echo "== tool calls mentioning /tmp: $(cat "$OUT/tmp-mentions.txt" 2>/dev/null)"
  } > "$OUT/containment.txt" 2>&1
  [ -n "$(comm -13 "$OUT/snap-pre/home.txt" "$OUT/snap-post/home.txt")" ] && flags+=(home-new-entry)
  [ -n "$(comm -13 "$OUT/snap-pre/tmp.txt" "$OUT/snap-post/tmp.txt")" ] && [ "$(cat "$OUT/tmp-mentions.txt" 2>/dev/null || echo 0)" != 0 ] && flags+=(tmp-new-entry-and-run-used-tmp)
  diff -q "$OUT/snap-pre/user-skills.txt" "$OUT/snap-post/user-skills.txt" >/dev/null || flags+=(user-skills-changed)
  diff -q "$OUT/snap-pre/settings-stat.txt" "$OUT/snap-post/settings-stat.txt" >/dev/null || flags+=(user-settings-changed)
  [ -n "$(comm -13 "$OUT/snap-pre/plugin-data.txt" "$OUT/snap-post/plugin-data.txt")" ] && flags+=(plugin-data-created)
  [ -n "$(comm -13 "$OUT/snap-pre/worktrees.txt" "$OUT/snap-post/worktrees.txt" | grep -vE "^$WTROOT/ab-[0-9]{4}-[a-z]+-")" ] && flags+=(new-worktree)
  [ -n "$(comm -13 "$OUT/snap-pre/worktrees.txt" "$OUT/snap-post/worktrees.txt" | grep -E "^$WTROOT/ab-$ADR-")" ] && flags+=(new-worktree-0004)
  diff -q "$OUT/snap-pre/refs.txt" "$OUT/snap-post/refs.txt" >/dev/null || flags+=(repo-refs-changed)
  [ -s "$OUT/snap-post/wt-procs.txt" ] && flags+=(process-left-in-wt)
  [ -s "$OUT/snap-post/wt-gitstate.txt" ] && flags+=(wt-git-state-left)
  [ "$(cat "$OUT/snap-pre/wt-head.txt")" != "$(cat "$OUT/snap-post/wt-head.txt")" ] && flags+=(head-moved)
  [ -s "$OUT/copies-post.txt" ] && flags+=(addition-copies-changed)
  for f in GLOSSARY.md CONTEXT.md docs/agents docs/adr .scratch; do [ -e "$wt/$f" ] && flags+=("artifact-$f"); done
  if [ ${#flags[@]} -gt 0 ]; then printf '%s\n' "${flags[@]}" > "$OUT/containment-flags.txt"; else : > "$OUT/containment-flags.txt"; fi
  local pid comm
  while read -r pid comm; do [ -n "$pid" ] && kill "$pid" 2>/dev/null && log "killed leftover $pid $comm"; done < "$OUT/snap-post/wt-procs.txt"
}

pytest_line() { grep -E '(passed|failed|error|no tests ran)' "$1" | tail -n 1; }

grade_r12() { # task wt label -> OUT/grade/grade.json, OUT/fix.patch
  local task=$1 wt=$2 G=$OUT/grade GW=$WTROOT/ab-$ADR-g-$3 apply=none allowed
  task_setup "$task"; mkdir -p "$G"
  if [ "$task" = r1 ]; then allowed=(meridian .gitignore); else allowed=(meridian/boundary.py); fi
  local ex=(); for f in "${allowed[@]}"; do ex+=(":(exclude)$f"); done
  git -C "$wt" rev-parse HEAD > "$G/head.txt"
  git -C "$wt" diff --quiet "$TESTS" -- tests/; echo $? > "$G/tests-unchanged.rc"
  git -C "$wt" diff --name-only "$BASE" -- . ':(exclude)tests' "${ex[@]}" > "$G/outside-tracked.txt"
  git -C "$wt" ls-files --others --exclude-standard -- . "${ex[@]}" "${EXCL_COPIES[@]}" > "$G/outside-untracked.txt"
  git -C "$wt" add -A -- "${allowed[@]}"
  git -C "$wt" diff --cached --binary "$BASE" -- "${allowed[@]}" > "$OUT/fix.patch"
  git -C "$wt" diff --cached --name-status "$BASE" -- "${allowed[@]}" > "$G/allowed-changed.txt"
  grep -c '^+.*\[DEBUG-' "$OUT/fix.patch" > "$G/debug-tags.txt"
  wt_add "$GW" "$BASE" || return 5
  git -C "$GW" checkout "$TESTS" -- tests/
  (cd "$GW" && uv sync --locked) > "$G/uv-sync.txt" 2>&1; echo $? > "$G/uv-sync.rc"
  if [ -s "$OUT/fix.patch" ]; then git -C "$GW" apply --binary "$OUT/fix.patch" > "$G/apply.txt" 2>&1; apply=$?; fi
  echo "$apply" > "$G/apply.rc"
  ( cd "$GW"
    uv run ruff check . > "$G/ruff-check.txt" 2>&1; echo $? > "$G/ruff-check.rc"
    uv run ruff format --check . > "$G/ruff-format.txt" 2>&1; echo $? > "$G/ruff-format.rc"
    uv run pyright > "$G/pyright.txt" 2>&1; echo $? > "$G/pyright.rc"
    pyt > "$G/pytest.txt" 2>&1; echo $? > "$G/pytest.rc" )
  wt_rm "$GW"
  local pass=0
  [ "$(cat "$G/tests-unchanged.rc")" = 0 ] && [ ! -s "$G/outside-tracked.txt" ] && [ ! -s "$G/outside-untracked.txt" ] \
    && [ "$apply" = 0 ] && [ "$(cat "$G/ruff-check.rc")" = 0 ] && [ "$(cat "$G/ruff-format.rc")" = 0 ] \
    && [ "$(cat "$G/pyright.rc")" = 0 ] && [ "$(cat "$G/pytest.rc")" = 0 ] && pass=1
  echo "$pass" > "$G/passed"
  jq -n --arg passed "$pass" --arg tests_rc "$(cat "$G/tests-unchanged.rc")" --arg apply "$apply" \
     --arg ruff "$(cat "$G/ruff-check.rc")" --arg fmt "$(cat "$G/ruff-format.rc")" --arg pyright "$(cat "$G/pyright.rc")" --arg pytest "$(cat "$G/pytest.rc")" \
     --arg outside_tracked "$(paste -sd, "$G/outside-tracked.txt")" --arg outside_untracked "$(paste -sd, "$G/outside-untracked.txt")" \
     --arg allowed "$(paste -sd, "$G/allowed-changed.txt")" --arg dbg "$(cat "$G/debug-tags.txt")" \
     --arg pytest_tail "$(pytest_line "$G/pytest.txt")" --arg pyright_tail "$(grep -E 'errors?,' "$G/pyright.txt" | tail -n 1)" \
     '{passed:($passed=="1"), passed_strict:($passed=="1"), tests_unchanged_rc:$tests_rc, apply_rc:$apply, ruff_check_rc:$ruff, ruff_format_rc:$fmt, pyright_rc:$pyright, pytest_rc:$pytest,
       outside_tracked:$outside_tracked, outside_untracked:$outside_untracked, allowed_changed:$allowed, debug_tags_added:($dbg|tonumber),
       pytest_tail:$pytest_tail, pyright_tail:$pyright_tail}' > "$G/grade.json"
}

grade_r3() { # wt label -> OUT/grade/grade.json, OUT/tests.patch
  local wt=$1 G=$OUT/grade GW=$WTROOT/ab-$ADR-g-$2 apply=none new rc39=na rc96=na
  mkdir -p "$G"
  git -C "$wt" status --porcelain=v1 --untracked-files=all -- . ':(exclude)tests' "${EXCL_COPIES[@]}" > "$G/outside.txt"
  git -C "$wt" add -A -- tests
  git -C "$wt" diff --cached --binary "$C96" -- tests > "$OUT/tests.patch"
  git -C "$wt" diff --cached --name-status "$C96" -- tests > "$G/tests-changed.txt"
  git -C "$wt" diff --cached --name-only --diff-filter=AM "$C96" -- tests | grep -E '(^|/)(test_[^/]*|[^/]*_test)\.py$' > "$G/new-test-files.txt"
  grep -c '^+.*\[DEBUG-' "$OUT/tests.patch" > "$G/debug-tags.txt"
  mapfile -t new < "$G/new-test-files.txt"
  wt_add "$GW" "$C96" || return 5
  (cd "$GW" && uv sync --locked) > "$G/uv-sync.txt" 2>&1; echo $? > "$G/uv-sync.rc"
  if [ -s "$OUT/tests.patch" ]; then git -C "$GW" apply --binary "$OUT/tests.patch" > "$G/apply.txt" 2>&1; apply=$?; fi
  echo "$apply" > "$G/apply.rc"
  if [ ${#new[@]} -gt 0 ] && [ "$apply" = 0 ]; then
    ( cd "$GW"
      git checkout "$C39" -- meridian/boundary.py
      pyt -q -rf "${new[@]}" > "$G/pytest-39cb68e.txt" 2>&1; echo $? > "$G/rc39"
      git checkout "$C96" -- meridian/boundary.py
      pyt -q -rf "${new[@]}" > "$G/pytest-96e82e6.txt" 2>&1; echo $? > "$G/rc96"
      pyt -q > "$G/pytest-full-96e82e6.txt" 2>&1; echo $? > "$G/rc-full96"
      uv run ruff check "${new[@]}" > "$G/ruff-check.txt" 2>&1; echo $? > "$G/ruff-check.rc"
      uv run ruff format --check "${new[@]}" > "$G/ruff-format.txt" 2>&1; echo $? > "$G/ruff-format.rc"
      uv run pyright "${new[@]}" > "$G/pyright.txt" 2>&1; echo $? > "$G/pyright.rc" )
    rc39=$(cat "$G/rc39"); rc96=$(cat "$G/rc96")
  fi
  wt_rm "$GW"
  local pass=0 strict=0
  [ ${#new[@]} -gt 0 ] && [ "$apply" = 0 ] && [ "$rc39" = 0 ] && [ "$rc96" = 1 ] && pass=1
  [ "$pass" = 1 ] && [ ! -s "$G/outside.txt" ] && strict=1
  echo "$pass" > "$G/passed"
  jq -n --arg passed "$pass" --arg strict "$strict" --arg apply "$apply" --arg rc39 "$rc39" --arg rc96 "$rc96" \
     --arg new "$(paste -sd, "$G/new-test-files.txt")" --arg changed "$(paste -sd, "$G/tests-changed.txt")" --arg outside "$(paste -sd, "$G/outside.txt")" \
     --arg t39 "$(pytest_line "$G/pytest-39cb68e.txt" 2>/dev/null)" --arg t96 "$(pytest_line "$G/pytest-96e82e6.txt" 2>/dev/null)" \
     --arg ruff "$(cat "$G/ruff-check.rc" 2>/dev/null)" --arg fmt "$(cat "$G/ruff-format.rc" 2>/dev/null)" --arg pyright "$(cat "$G/pyright.rc" 2>/dev/null)" \
     --arg dbg "$(cat "$G/debug-tags.txt")" \
     '{passed:($passed=="1"), passed_strict:($strict=="1"), apply_rc:$apply, rc_on_39cb68e:$rc39, rc_on_96e82e6:$rc96, new_test_files:$new, tests_changed:$changed,
       outside_tests:$outside, pytest_39cb68e:$t39, pytest_96e82e6:$t96, ruff_check_rc:$ruff, ruff_format_rc:$fmt, pyright_rc:$pyright, debug_tags_added:($dbg|tonumber)}' > "$G/grade.json"
}

invalid_reason() { # metrics.json -> prints a reason or nothing
  jq -r '
    if .terminal_reason == null then "no result event"
    elif (.terminal_reason|test("^(api_error|blocking_limit|rapid_refill_breaker|aborted_)")) then "terminal_reason " + .terminal_reason
    elif ((.model_keys|index("claude-opus-4-8")) or (.model_keys|index("claude-opus-5"))) then "fallback model in modelUsage"
    elif .claude_code_version != "2.1.322" then "claude_code_version " + (.claude_code_version|tostring)
    else empty end' "$1"
}

new_run() { # kind arm n with
  KIND=$1; ARM=$2; N=$3; WITH=$4
  case "$ARM" in a|b) ;; *) echo "bad arm"; exit 2;; esac
  case "$WITH" in 0|1) ;; *) echo "bad with"; exit 2;; esac
  case "$KIND" in ok) NAME=$ARM-k$N;; *) NAME=$ARM-$KIND-$N;; esac
  WT=$WTROOT/ab-$ADR-$NAME; OUT=$AB/$NAME; MEM=$HOME/.cache/claude-ab-mem/$ADR-$NAME
  if [ -e "$OUT" ] || [ -e "$WT" ]; then echo "already exists: $OUT or $WT"; exit 2; fi
  mkdir -p "$OUT" "$MEM"
  prep
  log "start $KIND $NAME"
}

finish_run() {
  if [ -n "$(ls -A "$MEM" 2>/dev/null)" ]; then cp -r "$MEM" "$OUT/mem"; fi
  wt_rm "$WT"; rm -rf "$MEM"; rm_project_dir "$WT"
  log "done $KIND $NAME"
}

do_ok() { # arm n with
  new_run ok "$1" "$2" "$3"
  wt_add "$WT" "$BASE_OK" || exit 5
  [ "$WITH" = 1 ] && place_addition "$WT" ok
  if [ "$WITH" = 1 ]; then check_copies "$WT" ok > "$OUT/copies-pre.txt"; else : > "$OUT/copies-pre.txt"; fi
  ls -la "$WT/.claude/skills" "$WT/.agents/skills" > "$OUT/skills-layout.txt" 2>&1
  snap pre "$WT"
  guard || { wt_rm "$WT"; exit 3; }
  SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/ok.sid"
  (cd "$WT" && "${RUN[@]}" -p 'Reply with the single word OK. Do not use any tools.' "${FLAGS[@]}" --max-turns 1 --session-id "$SID" "${DENY[@]}" < /dev/null > "$OUT/ok.stream.jsonl" 2> "$OUT/ok.stderr.txt"); echo "$?" > "$OUT/ok.exit"
  guard || { wt_rm "$WT"; exit 3; }
  SID2=$(cat /proc/sys/kernel/random/uuid); echo "$SID2" > "$OUT/context.sid"
  (cd "$WT" && "${RUN[@]}" -p '/context' "${FLAGS[@]}" --session-id "$SID2" "${DENY[@]}" < /dev/null > "$OUT/context.stream.jsonl" 2> "$OUT/context.stderr.txt"); echo "$?" > "$OUT/context.exit"
  sleep 2
  if [ "$WITH" = 1 ]; then check_copies "$WT" ok > "$OUT/copies-post.txt"; else : > "$OUT/copies-post.txt"; fi
  snap post "$WT"
  copy_session "$WT" "$SID" ok; copy_session "$WT" "$SID2" context
  metrics "$OUT/ok.stream.jsonl" > "$OUT/metrics.json"
  jq -R 'fromjson? // empty' "$OUT/context.stream.jsonl" | jq -c 'select(.context_usage?)|.context_usage' > "$OUT/context_usage.json"
  jq -R 'fromjson? // empty' "$OUT/context.stream.jsonl" | jq -c 'select(.type=="result")|{subtype,is_error,num_turns,local_command:(.local_command//null),total_cost_usd,modelUsage}' > "$OUT/context_result.json"
  leak_scan "$WT" "$MEM"
  containment "$WT" ok
  finish_run
  r=$(invalid_reason "$OUT/metrics.json"); [ -n "$r" ] && { echo "$r" > "$OUT/invalid.txt"; log "INVALID: $r"; exit 6; }
  jq -c '{v:.claude_code_version, skills, valid:(.num_turns==1 and (.is_error|not) and .terminal_reason=="completed"), always_on:.result_input_all, hooks:.hook_events}' "$OUT/metrics.json"
  jq -c '{total_tokens, skills_row:([.categories[]|select(.name=="Skills")|.tokens]|first), cats:[.categories[]|{(.name):.tokens}]|add}' "$OUT/context_usage.json" 2>/dev/null
  echo "containment: $(paste -sd, "$OUT/containment-flags.txt")"
}

do_task() { # task arm n with
  local task=$1; task_setup "$task"
  new_run "$task" "$2" "$3" "$4"
  wt_add "$WT" "$BASE" || exit 5
  [ -n "$TESTS" ] && git -C "$WT" checkout "$TESTS" -- tests/ >> "$LOG" 2>&1
  (cd "$WT" && uv sync --locked) > "$OUT/uv-sync.txt" 2>&1; echo $? > "$OUT/uv-sync.rc"
  [ "$WITH" = 1 ] && place_addition "$WT" task
  if [ "$WITH" = 1 ]; then check_copies "$WT" task > "$OUT/copies-pre.txt"; else : > "$OUT/copies-pre.txt"; fi
  cp "$AB/briefs/$task.txt" "$OUT/brief.txt"; sha256sum "$OUT/brief.txt" > "$OUT/brief.sha256"
  snap pre "$WT"
  guard || { wt_rm "$WT"; exit 3; }
  SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/run.sid"
  t0=$(date +%s); date -Is > "$OUT/started_at.txt"
  (cd "$WT" && "${RUN[@]}" -p "$(cat "$AB/briefs/$task.txt")" "${FLAGS[@]}" --max-turns 100 --session-id "$SID" "${DENY[@]}" < /dev/null > "$OUT/run.stream.jsonl" 2> "$OUT/run.stderr.txt"); echo "$?" > "$OUT/run.exit"
  echo $(( $(date +%s) - t0 )) > "$OUT/wall_s.txt"
  sleep 3
  if [ "$WITH" = 1 ]; then check_copies "$WT" task > "$OUT/copies-post.txt"; else : > "$OUT/copies-post.txt"; fi
  snap post "$WT"
  copy_session "$WT" "$SID" run
  metrics "$OUT/run.stream.jsonl" > "$OUT/metrics.json"
  leak_scan "$WT" "$MEM"
  skill_use
  containment "$WT" task
  git -C "$WT" status --porcelain=v1 --untracked-files=all > "$OUT/wt-status-final.txt" 2>&1
  if [ "$task" = r3 ]; then grade_r3 "$WT" "$NAME"; else grade_r12 "$task" "$WT" "$NAME"; fi
  finish_run
  jq -n --slurpfile m "$OUT/metrics.json" --slurpfile g "$OUT/grade/grade.json" --slurpfile s "$OUT/skill-use.json" \
    --arg flags "$(paste -sd, "$OUT/containment-flags.txt")" --arg leaks "$(wc -l < "$OUT/leak-hits.txt")" --arg sens "$(wc -l < "$OUT/sensitive-hits.txt")" \
    --arg wall "$(cat "$OUT/wall_s.txt")" --arg exit "$(cat "$OUT/run.exit")" --arg name "$NAME" --arg task "$task" \
    '{run:$name, task:$task, exit:$exit, wall_s:($wall|tonumber), passed:$g[0].passed, passed_strict:$g[0].passed_strict, containment_flags:$flags,
      leak_hits:($leaks|tonumber), sensitive_hits:($sens|tonumber), skill_use:$s[0],
      v:$m[0].claude_code_version, skills:$m[0].skills, terminal_reason:$m[0].terminal_reason, subtype:$m[0].subtype,
      num_turns:$m[0].num_turns, duration_ms:$m[0].duration_ms, tokens_all:$m[0].tokens_all, tokens_main:$m[0].tokens_main, model_keys:$m[0].model_keys,
      total_cost_usd:$m[0].total_cost_usd, api_retries:$m[0].api_retries, permission_denials:($m[0].permission_denials|length),
      final_text_ends_with_question:($m[0].final_text|rtrimstr("\n")|rtrimstr(" ")|endswith("?")), grade:$g[0]}' > "$OUT/summary.json"
  jq -c 'del(.skills)' "$OUT/summary.json"
  r=$(invalid_reason "$OUT/metrics.json"); [ -n "$r" ] && { echo "$r" > "$OUT/invalid.txt"; log "INVALID: $r"; exit 6; }
  return 0
}

do_validate() { # task
  local task=$1 v
  task_setup "$task"
  for v in none none-with ref ref-with weak; do
    [ "$task" != r3 ] && [ "$v" = weak ] && continue
    OUT=$AB/validate-$task/$v; [ -e "$OUT" ] && { echo "exists $OUT"; continue; }; mkdir -p "$OUT"; WT=$WTROOT/ab-$ADR-v-$task-$v
    wt_add "$WT" "$BASE" || exit 5
    [ -n "$TESTS" ] && git -C "$WT" checkout "$TESTS" -- tests/ >> "$LOG" 2>&1
    (cd "$WT" && uv sync --locked) > "$OUT/uv-sync.txt" 2>&1; echo $? > "$OUT/uv-sync.rc"
    case "$v" in *-with) place_addition "$WT" task; check_copies "$WT" task > "$OUT/copies.txt";; esac
    # pre-check: the suite as the agent would find it
    (cd "$WT" && pyt -q -rf) > "$OUT/precheck-pytest.txt" 2>&1; echo $? > "$OUT/precheck-pytest.rc"
    grep -E '^(FAILED|ERROR)' "$OUT/precheck-pytest.txt" | sort > "$OUT/precheck-failed.txt"
    case "$v" in
      ref|ref-with)
        if [ "$task" = r3 ]; then git -C "$WT" checkout "$C39" -- tests/test_boundary.py
        elif [ "$task" = r1 ]; then git -C "$WT" checkout "$C5D" -- meridian .gitignore
        else git -C "$WT" checkout "$C39" -- meridian/boundary.py; fi;;
      weak) printf '\n\ndef test_validation_placeholder() -> None:\n    assert True\n' >> "$WT/tests/test_boundary.py";;
    esac
    NAME=v-$task-$v
    if [ "$task" = r3 ]; then grade_r3 "$WT" "$NAME"; else grade_r12 "$task" "$WT" "$NAME"; fi
    wt_rm "$WT"
    echo "$task $v: precheck=$(pytest_line "$OUT/precheck-pytest.txt") failed_ids_sha=$(sha256sum < "$OUT/precheck-failed.txt" | cut -c1-12) grade=$(jq -c . "$OUT/grade/grade.json")"
  done
}

case "${1:-}" in
  ok) do_ok "$2" "$3" "$4";;
  run) do_task "$2" "$3" "$4" "$5";;
  series)
    kind=$2; shift 2
    for spec in "$@"; do
      IFS=: read -r arm n with <<< "$spec"
      if [ "$kind" = ok ]; then ( do_ok "$arm" "$n" "$with" ); else ( do_task "$kind" "$arm" "$n" "$with" ); fi
      rc=$?
      [ $rc = 0 ] || { log "series stopped after $kind $arm-$n with rc=$rc"; exit $rc; }
    done;;
  validate) do_validate "$2";;
  *) sed -n '2,9p' "$0"; exit 2;;
esac
exit 0
