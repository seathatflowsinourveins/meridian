#!/usr/bin/env bash
# write_patch.sh TPLDIR PROFILE RUNDIR -- write the profile's own patch layer for one run from
# its template: @R@ becomes the run folder (the addition keeps its state there), @EVROOT@ the
# series folder, @HOME@ the account's home. Done the same way for both profiles before every run.
set -euo pipefail
. "$(dirname "$0")/common.sh"
tpl=$1 p=$2 r=$3
d="$HOME/.dsh/profiles/$p"
case "$d" in "$HOME"/.dsh/profiles/ab-0009-[ab]) ;; *) echo "write_patch: bad profile $p"; exit 1 ;; esac
[ -d "$d" ] || { echo "write_patch: no profile folder $d"; exit 1; }
sed -e "s|@R@|$r|g" -e "s|@EVROOT@|$EV|g" -e "s|@HOME@|$HOME|g" "$tpl/$p.cordis.patch.yml.in" >"$d/cordis.patch.yml"
