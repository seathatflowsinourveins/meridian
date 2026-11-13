#!/usr/bin/env bash
# run_dsh.sh TAG PROFILE TPLDIR [BRIEF] -- one DeepSeek Harness run of the task under a temporary
# "ab-" profile of the owner's dsh home. The checkout $EV/TAG/wt must exist (mkclone.sh).
# The same command for both profiles; what differs is the profile's own patch layer.
# dsh loads its own key itself; this script never opens, copies or exports ~/.dsh/.env.
set -u
. "$(dirname "$0")/common.sh"
tag=$1 p=$2 tpl=$3 brief=${4:-$EV/brief-R4.txt}
D="$EV/$tag"; R="$D/r"; W="$D/wt"
[ -d "$W/.git" ] || { echo "run_dsh: no checkout at $W"; exit 7; }
[ ! -e "$R" ] || { echo "run_dsh: $R exists; a run is never overwritten"; exit 8; }
install -d -m 0700 "$R"
v=$(dsh --version </dev/null); echo "$v" >"$D/dsh-version.before"
[ "$v" = "$DSH_WANT" ] || { echo "STOP: dsh changed ($v)"; exit 4; }
cv=$(codex --version </dev/null); echo "$cv" >"$D/codex-version.before"
[ "$cv" = "$CODEX_WANT" ] || { echo "STOP: codex changed ($cv)"; exit 4; }
sha256sum "$brief" >"$D/brief.sha256"
# the profile: its fixed files unchanged, its own patch layer written for this run
( cd "$HOME/.dsh/profiles/$p" && sha256sum package.json pnpm-workspace.yaml ) | cmp -s - "$EV/profile-$p.fixed.sha256" \
  || { echo "STOP: profile $p changed"; exit 10; }
"$S/write_patch.sh" "$tpl" "$p" "$R" || exit 10
sha256sum "$HOME/.dsh/profiles/$p/cordis.patch.yml" | cut -d' ' -f1 >"$D/profile-patch.sha256"
sed -e "s|@EV@|$R|g" -e "s|@ROUNDS@|$ROUNDS|g" "$S/ab-overlay.cordis.yml.in" >"$R/ab-overlay.cordis.yml"
# state before, for the containment check: names, sizes, times and hashes only
git --no-optional-locks -C "$W" status --porcelain=v1 --ignored >"$D/status.before"
ls -A "$HOME" >"$D/home.before"
sha256sum "$HOME/.codex/config.toml" >"$D/codex-config.sha256.before"
find "$HOME/.dsh" -printf '%P\t%y\t%s\t%TY-%Tm-%Td %TH:%TM:%TS\n' | sort >"$D/dsh-listing.before"
date -Is >"$D/started"
guard "$R/guard.log" || exit 3
t0=$(date +%s.%N)
AB_HIDE="$HIDE" AB_SHOW="$SHOW" AB_TIMEOUT="$WALL" AB_KILL_AFTER="$KILL_AFTER" \
  "$S/ab-dsh.sh" "$p" "$R" "$W" --patch "$R/ab-overlay.cordis.yml" --json \
  --permission-mode read-only --approval-policy never - <"$brief" >"$R/out.jsonl" 2>"$R/stderr.txt"
rc=$?
t1=$(date +%s.%N)
echo "exit=$rc" >"$R/exit.txt"
date -Is >"$D/ended"
awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.1f\n", b - a }' >"$D/duration_s"
echo "run $tag exit=$rc duration=$(cat "$D/duration_s")s"
