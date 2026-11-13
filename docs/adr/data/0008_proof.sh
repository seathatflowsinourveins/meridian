# Proof that the project-scope route touches no owner file (ADR 0008, run 2).
# usage: bash proof.sh install|setup|trust|cleanup
set -u
. "$HOME/src/meridian-ab/0008/run2/scripts/common2.sh"
PR=$R2/proof; mkdir -p "$PR"
WT=$WTD/ab-0008-proof
E=(env -u GH_TOKEN -u GITHUB_TOKEN HOME="$T/home" npm_config_userconfig=/dev/null npm_config_cache="$T/npm-cache"
   npm_config_update_notifier=false XDG_CONFIG_HOME="$T/home/.config" XDG_CACHE_HOME="$T/home/.cache")

case "$1" in
install)
  snaphome "$PR/before"
  mkdir -p "$T/home" "$T/npmcwd" "$T/pack"
  cd "$T/npmcwd" || exit 1
  got=$("${E[@]}" npm view oh-my-codex@0.22.6 dist.integrity 2>/dev/null)
  echo "registry integrity: $got"
  [ "$got" = "$INTEGRITY" ] || { echo "INTEGRITY MISMATCH"; exit 1; }
  "${E[@]}" npm install --global --prefix "$T/npm" --ignore-scripts --no-audit --no-fund oh-my-codex@0.22.6 > "$PR/npm-install.log" 2>&1
  echo "install rc=$?"; tail -3 "$PR/npm-install.log"
  "${E[@]}" npm pack oh-my-codex@0.22.6 --pack-destination "$T/pack" > "$PR/npm-pack.log" 2>&1
  tgz=$(ls "$T/pack"/oh-my-codex-0.22.6.tgz)
  echo "tarball bytes $(stat -c %s "$tgz") sha512-$(openssl dgst -sha512 -binary "$tgz" | base64 -w0)"
  mkdir -p "$T/pack/x" && tar -xzf "$tgz" -C "$T/pack/x"
  if diff -rq "$T/pack/x/package" "$PKG" > "$PR/installed-vs-tarball.txt" 2>&1; then echo "installed package == tarball (all files)"; else echo "installed differs:"; head -20 "$PR/installed-vs-tarball.txt"; fi
  "${E[@]}" npm ls --global --prefix "$T/npm" --all > "$R2/npm-ls-all.txt" 2>&1
  echo "npm ls lines: $(wc -l < "$R2/npm-ls-all.txt"); vs run 1: $(diff <(sed 1d "$R/npm-ls-all.txt") <(sed 1d "$R2/npm-ls-all.txt") > /dev/null && echo identical-tree || echo DIFFERENT-tree)"
  "$OMX" --version 2>&1 | head -2
  ;;
setup)
  mkclone "$WT" "$MAIN" || exit 1
  snapdir "$WT" | grep -v -E '^\.git/' > "$PR/clone-before.txt"
  snaphome "$PR/pre-setup"
  omx_project_setup "$WT" proof > "$PR/setup-project.log" 2>&1; echo "setup rc=$?"
  snaphome "$PR/after"
  snapdir "$WT" | grep -v -E '^\.git/' > "$PR/clone-after.txt"
  echo "## home diff (install window: before -> pre-setup)"; diffhome "$PR/before" "$PR/pre-setup"
  echo "## home diff (setup window: pre-setup -> after)"; diffhome "$PR/pre-setup" "$PR/after"
  echo "## clone: entries before $(wc -l < "$PR/clone-before.txt"), after $(wc -l < "$PR/clone-after.txt")"
  echo "## clone changes (git status, ignored included)"; git -C "$WT" status --porcelain --ignored | tee "$PR/clone-status.txt" | head -30
  echo "## written paths by top folder"; diff <(cut -f1 "$PR/clone-before.txt") <(cut -f1 "$PR/clone-after.txt") | grep '^>' | cut -c3- | awk -F/ '{print $1"/"$2}' | sort | uniq -c | head -40
  echo "## sizes"; stat -c '%n %s' "$WT/AGENTS.md" "$WT/.gitignore" "$WT/.codex/config.toml" "$WT/.codex/hooks.json" 2>&1 | sed "s|$WT/||"
  echo "## setup home writes"; find "$T/home-proof" "$T/codex-setup-proof" -printf '%P\t%s\n' 2>/dev/null | head -20
  ;;
trust)
  # Renders without a model call in empty scratch homes: untrusted vs session-flag trusted.
  for v in untrusted trusted; do
    H=$T/h-$v; rm -rf "$H"; mkdir -p "$H"
    fl=(); [ "$v" = trusted ] && fl=(-c "projects={\"$WT\"={trust_level=\"trusted\"}}")
    CODEX_HOME="$H" codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -C "$WT" -m gpt-6-astra \
      -c model_reasoning_effort=high "${fl[@]}" debug prompt-input "$P_CTX" < /dev/null > "$PR/render-$v.json" 2> "$PR/render-$v.stderr"
    echo "$v rc=$? msg_bytes=$(jq '[.[]|select(.type=="message")|.content[]|.text|utf8bytelength]|add' "$PR/render-$v.json") tool_bytes=$(jq '[.[]|select(.type=="additional_tools")|.tools|tojson|utf8bytelength]|add // 0' "$PR/render-$v.json") omx_devinstr=$(grep -c 'oh-my-codex\|OMX' "$PR/render-$v.json") agents_block=$(jq '[.[]|select(.type=="message")|.content[]|.text|select(contains("# AGENTS.md instructions"))|utf8bytelength]|add // 0' "$PR/render-$v.json") home_files=$(find "$H" -type f | wc -l)"
    find "$H" -maxdepth 1 -printf '  %P %s\n'
  done
  ;;
selftrust)
  # Does OMX's self-written trusted_hash equal Codex 0.167.2's hook hash? Scratch home, no sign-in
  # (the turn fails at the model request with 401, after SessionStart), NO --dangerously-bypass-hook-trust.
  hs=$(python3 -I -c 'import sys,tomllib
d=tomllib.load(open(sys.argv[1],"rb"))
print(", ".join("\"%s\"={trusted_hash=\"%s\"}" % (k, v["trusted_hash"]) for k, v in d["hooks"]["state"].items()))' "$WT/.codex/config.toml")
  snaphome "$PR/st-before"
  for v in omx-hashes no-hashes; do
    H=$T/x-st-$v; rm -rf "$H"; mkdir -p "$H"
    fl=(-c "projects={\"$WT\"={trust_level=\"trusted\"}}")
    [ "$v" = omx-hashes ] && fl+=(-c "hooks.state={$hs}")
    rm -rf "$WT/.omx/state/sessions" 2>/dev/null
    CODEX_HOME="$H" timeout 90 codex exec --json --color never -m gpt-6-astra -c model_reasoning_effort=high \
      --dangerously-bypass-approvals-and-sandbox -C "$WT" "${fl[@]}" "$P_CTX" < /dev/null > "$PR/st-$v.jsonl" 2> "$PR/st-$v.stderr"
    ro=$(find "$H/sessions" -name 'rollout-*.jsonl' | head -1)
    echo "$v rc=$? rollout=$([ -n "$ro" ] && echo yes || echo no) exec_env=$([ -n "$ro" ] && grep -c 'Execution environment' "$ro") hook_events=$([ -n "$ro" ] && grep -o '"type":"hook_[a-z]*"' "$ro" | sort | uniq -c | tr -s ' \n' ' ')"
    grep -i -E 'hook|trust' "$PR/st-$v.stderr" | sed "s|$HOME|~|g" | head -5
  done
  pgrep -af 'codex-native-hook' | grep -v pgrep || echo "no hook process left"
  snaphome "$PR/st-after"; echo "## home diff around selftrust probe"; diffhome "$PR/st-before" "$PR/st-after"
  ;;
cleanup)
  rm -rf "$WT" "$T/h-untrusted" "$T/h-trusted" "$T/home-proof" "$T/codex-setup-proof"
  echo "proof clone removed: $([ -e "$WT" ] && echo NO || echo yes)"
  ;;
esac
