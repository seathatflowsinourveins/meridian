# Sourced by ao_run.sh and r5_run.sh (ADR 0003 with/without series, distro meridian).
# Published copy (docs/adr/data/0003_common.sh): ran on 2026-11-13 as scripts/common.sh in the operator's
# work folder, written here as $WORK (a Windows temp folder, seen from WSL under /mnt/c; set WORK
# before running); the operator's home directory is written as $HOME. Otherwise unchanged.
set -u
ADR=0003
BASE=9c5daaae9d32acf259f965fd7b95b458604503b6
SCRIPTS=$WORK/scripts
TAR=$WORK/plugins-149d7b2.tar
TAR_SHA=67829998ce3345bd01573057a247cd696c858e69ba49af259fc0866c827ca57b
# One binary for the whole series (resolved 2026-11-13 01:51 ET), not the launcher symlink.
CB=$HOME/.local/share/claude/versions/2.1.322
ABROOT="$HOME/src/meridian-ab/$ADR"

die() { echo "ABORT: $*"; exit 4; }

guard() {
  [ "$(ss -Hltn 'sport = :4002' | wc -l)" = 0 ] && ! pgrep -f ibgateway >/dev/null || { echo GATEWAY-UP; exit 3; }
}

wt_add() { # wt_add WT ERRFILE
  local i
  for i in 1 2; do
    git -C "$HOME/src/meridian" worktree add --detach "$1" "$BASE" >/dev/null 2>"$2" && return 0
    grep -q 'index.lock' "$2" || return 1
    sleep 5
  done
  return 1
}

plug_copy() { # plug_copy DEST PLUGIN-NAME -> prints plugin dir
  mkdir -p "$1" && tar -xf "$TAR" -C "$1" "plugins/$2" && printf '%s' "$1/plugins/$2"
}

DENY=(--disallowedTools 'Bash(*meridian.ibkr_paper*)' 'Bash(*meridian.ib_probe*)' 'Bash(*meridian.boundary contract*)' 'Bash(*ibgateway*)' "Read(/$HOME/src/meridian/**)" "Read(/$HOME/src/meridian-ab/**)")
RUN=(env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_CODE_SUBAGENT_EFFORT -u ANTHROPIC_MODEL DISABLE_AUTOUPDATER=1 "$CB")

flags() { # flags MEMDIR -> sets FLAGS
  local set
  set=$(jq -nc --arg m "$1" '{autoMemoryDirectory:$m}')
  FLAGS=(--model claude-opus-5-5 --effort high --permission-mode bypassPermissions --settings "$set" --output-format stream-json --verbose)
}

preflight() {
  [ -x "$CB" ] || die "series binary $CB is gone"
  [ "$("$CB" --version 2>/dev/null)" = "2.1.322 (Claude Code)" ] || die "series binary version changed"
  [ "$(sha256sum "$TAR" | cut -d' ' -f1)" = "$TAR_SHA" ] || die "plugin archive changed"
}

metrics() { # metrics STREAM -> JSON on stdout
  jq -s '
    (map(select(.type=="system" and .subtype=="init"))[0]) as $i
    | (map(select(.type=="result"))|last) as $r
    | ($r.modelUsage // {}) as $mu
    | {version:$i.claude_code_version, model:$i.model, permissionMode:$i.permissionMode,
       plugins:$i.plugins, plugin_errors:$i.plugin_errors, n_skills:($i.skills|length), skills:$i.skills,
       subtype:$r.subtype, is_error:$r.is_error, terminal_reason:$r.terminal_reason,
       api_error_status:$r.api_error_status, num_turns:$r.num_turns, duration_ms:$r.duration_ms,
       total_cost_usd:$r.total_cost_usd, usage:$r.usage, modelUsage:$mu,
       always_on:(($r.usage.input_tokens // 0)+($r.usage.cache_creation_input_tokens // 0)+($r.usage.cache_read_input_tokens // 0)),
       tokens_all:([$mu[]|((.inputTokens // 0)+(.cacheCreationInputTokens // 0)+(.cacheReadInputTokens // 0)+(.outputTokens // 0))]|add),
       tokens_main:([$mu|to_entries[]|select(.key==$i.model or (.key|startswith($i.model)))|.value|((.inputTokens // 0)+(.cacheCreationInputTokens // 0)+(.cacheReadInputTokens // 0)+(.outputTokens // 0))]|add),
       fallback:([$mu|keys[]|select(.=="claude-opus-4-8" or .=="claude-opus-5")]|length>0),
       permission_denials:($r.permission_denials|length),
       api_retries:([.[]|select(.type=="system" and .subtype=="api_retry")]|length),
       hooks:([.[]|select(.type=="system" and (.subtype|tostring|startswith("hook_")))|.subtype]|group_by(.)|map({(.[0]):length})|add),
       skill_calls:[.[]|select(.type=="assistant")|.message.content[]?|select(.type=="tool_use" and .name=="Skill")|.input]}' "$1"
}
