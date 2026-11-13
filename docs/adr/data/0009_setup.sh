#!/bin/bash
# ADR 0009 measurement setup in distro meridian. Writes only under ~/src/meridian-ab/0009.
set -u
EV=$HOME/src/meridian-ab/0009; S=$EV/scripts; H=$EV/dsh-home
GITC() { GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.https://github.com.helper= "$@"; }
[ "$(dsh --version </dev/null)" = 0.2.2-rc.1 ] || { echo 'STOP: dsh changed'; exit 4; }
install -d -m 0700 "$EV/sessions" "$EV/storages" "$EV/agents-home" "$EV/wt" "$H" "$EV/capture" "$EV/with" "$EV/peer-state"
date -Is > "$EV/start.stamp"
sha256sum "$HOME/.dsh/cordis.patch.yml" "$HOME"/.dsh/profiles/dsh-tui/{package.json,pnpm-lock.yaml,pnpm-workspace.yaml,cordis.patch.yml} > "$EV/owner-dsh.sha256"
ls -A "$HOME" > "$EV/home.before"; ls -A /tmp > "$EV/tmp.before"
ls -A "$HOME/.dsh" "$HOME/.dsh/profiles" > "$EV/owner-dsh.names.before"

printf '%s\n' 'Reply with exactly the word OK. Do not call any tool.' > "$EV/probe.txt"

cat > "$EV/ab-overlay.cordis.yml" <<YAML
- id: session-log-deepseek
  config: {enabled: false}
- id: plugin-package-inventory-deepseek
  config: {enabled: false}
- id: session-telemetry-otel
  config: {mode: DISABLED}
- id: session-title-llm
  disabled: true
- id: tool-web
  disabled: true
- id: agent-default-model
  config: {provider: deepseek-official, model: deepseek-flash}
- id: llm-deepseek
  config: {thinking: enabled, reasoningEffort: max}
- id: session-persistence-jsonl
  config: {root: $EV/sessions, compression: none}
- id: storage-json
  config: {root: $EV/storages}
YAML

cat > "$EV/with/with-only.cordis.yml" <<YAML
# with arm only: the plugin's own bundle row (cordis.patch.yml at f4882df) with a local module
# name resolved beside this file, plus the fact sheet's with-only stateDir
- insert:
    - id: codex-peer
      name: ./peer/index.js
      config:
        stateDir: $EV/peer-state
YAML

# the addition, as data, at its pin
mkdir "$EV/with/peer" && cd "$EV/with/peer" && GITC init -q . \
  && GITC fetch -q --depth 1 https://github.com/wuanthony397-hash/dsh-codex-peer.git f4882df301c063481a80014ab9e6f99845e4bc94 \
  && GITC -c advice.detachedHead=false checkout -q FETCH_HEAD
echo "peer HEAD $(git -C "$EV/with/peer" rev-parse HEAD) tree $(git -C "$EV/with/peer" rev-parse 'HEAD^{tree}')"
# its peer dependency, resolved to the copy the installed dsh itself uses
mkdir -p "$EV/with/node_modules/@deepseek-ai"
ln -s "$HOME/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/schemastery" "$EV/with/node_modules/@deepseek-ai/schemastery"

# scratch clone of the public repo holding only 96e82e6 (no 39cb68e in its object store)
mkdir "$EV/src" && cd "$EV/src" && GITC init -q . \
  && GITC fetch -q --depth 1 https://github.com/seathatflowsinourveins/meridian.git 96e82e6b521cdb9c7d172176898d20e2658ec50b \
  && git update-ref refs/heads/base FETCH_HEAD && GITC -c advice.detachedHead=false checkout -q --detach base
echo "src HEAD $(git -C "$EV/src" rev-parse HEAD); objects: $(git -C "$EV/src" rev-list --all | wc -l) commit(s); 39cb68e present: $(git -C "$EV/src" cat-file -e 39cb68ea3241caeececb6db0521a12ea2fa92fee 2>/dev/null && echo yes || echo no)"

# profiles in the scratch home, made with no network (own netns)
cd "$EV"
for a in without with; do
  unshare -rn env -u DSH_PERMISSION_MODE -u DEEPSEEK_API_KEY DSH_HOME="$H" DSH_AGENTS_HOME="$EV/agents-home" DSH_TELEMETRY_DISABLED=1 \
    dsh --profile "ab-$a" --from-default-profile headless --dump-config </dev/null >"$EV/create-$a.yml" 2>"$EV/create-$a.err"
  echo "create ab-$a exit=$?"
done
for a in without with; do
  extra=(); [ "$a" = with ] && extra=(--patch "$EV/with/with-only.cordis.yml")
  unshare -rn env -u DSH_PERMISSION_MODE -u DEEPSEEK_API_KEY DSH_HOME="$H" DSH_AGENTS_HOME="$EV/agents-home" DSH_TELEMETRY_DISABLED=1 \
    dsh --profile "ab-$a" --patch "$EV/ab-overlay.cordis.yml" "${extra[@]}" --dump-config </dev/null >"$EV/dump-$a.yml" 2>"$EV/dump-$a.err"
  echo "dump ab-$a exit=$?"
done
diff -u "$EV/dump-without.yml" "$EV/dump-with.yml" > "$EV/rows.diff"; echo "rows.diff lines: $(wc -l < "$EV/rows.diff")"
row() { awk -v id="- id: $2" '$0 == id { f = 1; next } /^- / { f = 0 } f' "$1"; }
for a in without with; do
  for r in session-log-deepseek plugin-package-inventory-deepseek; do row "$EV/dump-$a.yml" $r | grep -qx '    enabled: false' || echo "STOP $r $a"; done
  row "$EV/dump-$a.yml" session-telemetry-otel | grep -qx '    mode: DISABLED' || echo "STOP otel $a"
  row "$EV/dump-$a.yml" tool-plugin-manager | grep -qx '  disabled: true' || echo "STOP plugin tools $a"
done
ls -la "$H" "$H/profiles" 2>&1
echo "owner ~/.dsh names unchanged: $(ls -A "$HOME/.dsh" "$HOME/.dsh/profiles" | cmp -s - "$EV/owner-dsh.names.before" && echo yes || echo NO)"
sha256sum -c --quiet "$EV/owner-dsh.sha256" && echo "owner dsh hashes OK"
