# ADR 0008, run 2 helpers (sourced; distro meridian only).
# Writes only under $R2, $T and the run clones in ~/src/meridian-worktrees/ab-0008-*.
# Never writes ~/src/meridian, ~/.codex/config.toml, ~/.codex/hooks.json or any owner file.
R=$HOME/src/meridian-ab/0008
R2=$R/run2
T=$R2/t
SEED=$R2/seed.git
PKG=$T/npm/lib/node_modules/oh-my-codex
OMX=$T/npm/bin/omx
WTD=$HOME/src/meridian-worktrees
GH_URL=https://github.com/seathatflowsinourveins/meridian
MAIN=9c5daaae9d32acf259f965fd7b95b458604503b6
R1_BASE=27aa964df79d646027d0060eb4d3a14bd49dae8f
R1_TESTS=5d51c9c163c34b689b5066bd931bb45412d69340
INTEGRITY='sha512-ZpMHipwnaiHV/T8rp/czmF5U+ugqVdUOb28obL5U61q9WQwvfKAmzP4k1V82EnUXYMvsBgZIzFl0I3HADBbFEQ=='
P_CTX='Reply with exactly the word OK. Do not run any command or call any tool.'

GITC() { GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.https://github.com.helper= "$@"; }

# Both arms: OMX's own env switches off, .omx/ ignored through core.excludesFile (no owner file touched).
export OMX_AUTO_UPDATE=0 OMX_NATIVE_AUTO_FETCH=0
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.excludesFile GIT_CONFIG_VALUE_0="$T/omx-ignore"

# Gateway guard: output and time appended to <run folder>/guard.log; nonzero = stop the series.
guard() {
  local dir=$1 out rc
  mkdir -p "$dir"
  out=$(bash "$HOME/.cache/meridian/gateway-guard.sh" 2>&1); rc=$?
  echo "$(date -Is) rc=$rc $out" >> "$dir/guard.log"
  echo "guard rc=$rc $out"
  return $rc
}

# Fresh standalone clone (never a worktree of ~/src/meridian), detached at $2.
mkclone() {
  local wt=$1 rev=$2
  rm -rf "$wt"
  git clone -q --no-checkout "$SEED" "$wt" || return 1
  git -C "$wt" remote set-url origin "$GH_URL"
  git -C "$wt" -c advice.detachedHead=false checkout -q --detach "$rev"
}

# Orca's 9 user hooks in ~/.codex/hooks.json switched off for one invocation (session-flag layer).
orca_off() {
  local h=$HOME/.codex/hooks.json s="" e
  for e in session_start user_prompt_submit pre_tool_use permission_request post_tool_use subagent_start subagent_stop stop interrupt; do
    s="$s${s:+, }\"$h:$e:0:0\"={enabled=false}"
  done
  printf 'hooks.state={%s}' "$s"
}

# Identical flags in both arms; only the clone's contents differ.
codex_flags() {
  local wt=$1
  FLAGS=(--json --color never -m gpt-6-astra -c model_reasoning_effort=high
    --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust
    -C "$wt" -c "projects={\"$wt\"={trust_level=\"trusted\"}}" -c "$(orca_off)")
}

# OMX project-scope setup into clone $1; HOME, CODEX_HOME and XDG dirs are throwaway under $T; no GitHub token.
omx_project_setup() {
  local wt=$1 tag=$2 h
  h=$T/home-$tag
  mkdir -p "$h" "$T/codex-setup-$tag"
  ( cd "$wt" && env -u GH_TOKEN -u GITHUB_TOKEN -u GH_ENTERPRISE_TOKEN \
      HOME="$h" CODEX_HOME="$T/codex-setup-$tag" XDG_CONFIG_HOME="$h/.config" XDG_CACHE_HOME="$h/.cache" \
      XDG_STATE_HOME="$h/.local/state" XDG_DATA_HOME="$h/.local/share" GH_CONFIG_DIR="$h/gh" \
      npm_config_userconfig=/dev/null npm_config_cache="$T/npm-cache" \
      "$OMX" setup --scope project --install-mode legacy --mcp none --merge-agents --verbose ) < /dev/null
}

# Names, types, sizes and mtimes only (never contents).
snapdir() {
  if [ -e "$1" ]; then find "$1" -printf '%P\t%y\t%s\t%T@\n' 2>/dev/null | LC_ALL=C sort; else echo "ABSENT $1"; fi
}

# Home-level containment snapshot into dir $1 (one file per area).
snaphome() {
  local d=$1; mkdir -p "$d"
  snapdir "$HOME/.codex" > "$d/codex-full.txt"
  grep -v -E '^(sessions/|shell_snapshots/|thread-writer-locks/|log/|tmp/|\.tmp/)' "$d/codex-full.txt" > "$d/codex.txt"
  snapdir "$HOME/.omx" > "$d/omx.txt"
  snapdir "$HOME/.npm" > "$d/npm.txt"
  snapdir "$HOME/.config" > "$d/config.txt"
  { for x in .omx .omx-runs .cache/oh-my-codex .local/state/oh-my-codex .agents .hermes .codex/.omx .codex/.omx-config.json .codex/AGENTS.md .codex/agents .codex/prompts; do
      [ -e "$HOME/$x" ] && echo "PRESENT ~/$x" || echo "absent ~/$x"; done; } > "$d/omx-paths.txt"
  ls -1A "$HOME" > "$d/home-top.txt"
  ls -1A "$HOME/.cache" > "$d/cache-top.txt"
  ls -1A "$HOME/.local/state" > "$d/state-top.txt" 2>&1
  ls -1A /tmp > "$d/tmp-top.txt"
  { stat -c '%n %s %Y' "$HOME/.codex/config.toml" "$HOME/.codex/hooks.json"; sha256sum "$HOME/.codex/config.toml" "$HOME/.codex/hooks.json"; } \
    2>&1 | sed "s|$HOME|~|g" > "$d/owner-config.txt"
  { git -C "$HOME/src/meridian" rev-parse HEAD; git -C "$HOME/src/meridian" status --porcelain | wc -l; \
    sha256sum "$HOME/src/meridian/.git/info/exclude" | cut -c1-64; git -C "$HOME/src/meridian" worktree list; } > "$d/main-checkout.txt" 2>&1
  { pgrep -af 'oh-my-codex|codex-native-hook|omx-runtime|notify-hook|/omx ' | grep -v -e pgrep -e 'bash -l -s' || echo none; } > "$d/procs.txt"
  { tmux ls 2>&1 | head -3; } > "$d/tmux.txt"
}

# Diff two snaphome dirs: print only areas that changed (names only).
diffhome() {
  local a=$1 b=$2 f
  for f in codex.txt omx.txt npm.txt config.txt omx-paths.txt home-top.txt cache-top.txt state-top.txt tmp-top.txt owner-config.txt main-checkout.txt procs.txt tmux.txt; do
    if ! cmp -s "$a/$f" "$b/$f"; then echo "### $f changed"; diff "$a/$f" "$b/$f" | head -40; fi
  done
}
