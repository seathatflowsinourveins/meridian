#!/usr/bin/env bash
# setup_profiles.sh TPLDIR -- the two temporary profiles ab-0009-a and ab-0009-b in the owner's
# dsh home, built from dsh's own headless template (made earlier in a scratch home, $EV/tplhome).
# TPLDIR holds one patch template per profile (<profile>.cordis.patch.yml.in). The templates
# show which profile has the addition, so they are kept outside the run folders.
# Writes only under ~/.dsh/profiles/ab-0009-{a,b} and $EV. Never opens ~/.dsh/.env.
set -euo pipefail
. "$(dirname "$0")/common.sh"
tpl=$1; T="$EV/tplhome/profiles/ab-tpl"
[ "$(dsh --version </dev/null)" = "$DSH_WANT" ] || { echo 'STOP: dsh changed'; exit 4; }
# the addition's one peer import, resolved to the copy the installed dsh itself uses
if [ ! -e "$EV/addition/node_modules/@deepseek-ai/schemastery" ]; then
  install -d "$EV/addition/node_modules/@deepseek-ai"
  ln -s "$HOME/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/schemastery" \
    "$EV/addition/node_modules/@deepseek-ai/schemastery"
fi
for p in ab-0009-a ab-0009-b; do
  d="$HOME/.dsh/profiles/$p"
  case "$d" in "$HOME"/.dsh/profiles/ab-*) ;; *) echo "setup: bad profile path"; exit 1 ;; esac
  [ ! -e "$d" ] || { echo "setup: $d exists"; exit 1; }
  [ -f "$tpl/$p.cordis.patch.yml.in" ] || { echo "setup: no template for $p"; exit 1; }
  install -d -m 0700 "$d"
  sed "s/dsh-profile-ab-tpl/dsh-profile-$p/" "$T/package.json" >"$d/package.json"
  cp "$T/pnpm-workspace.yaml" "$d/"
  "$S/write_patch.sh" "$tpl" "$p" "$EV/pre/r"
  ( cd "$d" && sha256sum package.json pnpm-workspace.yaml ) >"$EV/profile-$p.fixed.sha256"
  echo "made $d"
done
