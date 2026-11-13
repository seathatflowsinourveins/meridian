#!/usr/bin/env bash
# ab-ns.sh RUNDIR WORKDIR CMD [ARGS...] -- run CMD in a mount namespace like the one ab-dsh.sh
# gives a dsh run, for the Codex-only reference runs and for checks that call no model:
#   every existing path in $HIDE is empty; the dsh home is empty too (AB_NS_DSH=hide, the
#   default) or read-only (AB_NS_DSH=ro, as a dsh run sees it); the addition's clone and the
#   owner's Codex config file are read-only; RUNDIR and WORKDIR stay writable.
# CMD gets HOME=RUNDIR/home, TMPDIR=RUNDIR/tmp and CODEX_HOME=<the account's ~/.codex>, which is
# what a Codex child started by the addition gets in the with arm.
# Nothing here opens ~/.dsh/.env or any credential file.
set -euo pipefail
. "$(dirname "$0")/common.sh"
ev=$1 wd=$2; shift 2
install -d -m 0700 "$ev/home" "$ev/tmp"
pre=()
IFS=: read -r -a hs <<<"$HIDE"
for h in "${hs[@]}"; do
  [ -n "$h" ] || continue
  if [ -d "$h" ]; then pre+=(--tmpfs "$h"); elif [ -e "$h" ]; then pre+=(--ro-bind /dev/null "$h"); fi
done
if [ "${AB_NS_DSH:-hide}" = ro ]; then pre+=(--ro-bind "$HOME/.dsh" "$HOME/.dsh"); else pre+=(--tmpfs "$HOME/.dsh"); fi
post=()
IFS=: read -r -a ss <<<"$SHOW"
for s in "${ss[@]}"; do if [ -n "$s" ] && [ -e "$s" ]; then post+=(--ro-bind "$s" "$s"); fi; done
cd "$wd"
exec bwrap --dev-bind / / "${pre[@]}" "${post[@]}" --bind "$ev" "$ev" --bind "$wd" "$wd" --die-with-parent -- \
  env -u DEEPSEEK_API_KEY HOME="$ev/home" TMPDIR="$ev/tmp" CODEX_HOME="$HOME/.codex" "$@"
