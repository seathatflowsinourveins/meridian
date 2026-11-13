#!/usr/bin/env bash
# run_codex.sh TAG [BRIEF] -- one run of the reference arm: Codex alone on the same brief, in
# its read-only sandbox, under the owner's Codex sign-in. The checkout $EV/TAG/wt must exist.
# Runs in the same kind of mount namespace as a dsh run (ab-ns.sh), with the dsh home empty.
set -u
. "$(dirname "$0")/common.sh"
tag=$1 brief=${2:-$EV/brief-R4.txt}
D="$EV/$tag"; R="$D/r"; W="$D/wt"
[ -d "$W/.git" ] || { echo "run_codex: no checkout at $W"; exit 7; }
[ ! -e "$R" ] || { echo "run_codex: $R exists; a run is never overwritten"; exit 8; }
install -d -m 0700 "$R"
v=$(dsh --version </dev/null); echo "$v" >"$D/dsh-version.before"
cv=$(codex --version </dev/null); echo "$cv" >"$D/codex-version.before"
[ "$cv" = "$CODEX_WANT" ] || { echo "STOP: codex changed ($cv)"; exit 4; }
sha256sum "$brief" >"$D/brief.sha256"
git --no-optional-locks -C "$W" status --porcelain=v1 --ignored >"$D/status.before"
ls -A "$HOME" >"$D/home.before"
sha256sum "$HOME/.codex/config.toml" >"$D/codex-config.sha256.before"
find "$HOME/.dsh" -printf '%P\t%y\t%s\t%TY-%Tm-%Td %TH:%TM:%TS\n' | sort >"$D/dsh-listing.before"
date -Is >"$D/started"
guard "$R/guard.log" || exit 3
t0=$(date +%s.%N)
"$S/ab-ns.sh" "$R" "$W" timeout --signal=INT --kill-after="$KILL_AFTER" "$WALL" \
  codex exec --json --color never -m gpt-6-astra -c model_reasoning_effort=high -s read-only \
  --skip-git-repo-check --disable hooks -C "$W" -o "$R/answer.md" - \
  <"$brief" >"$R/events.jsonl" 2>"$R/stderr.txt"
rc=$?
t1=$(date +%s.%N)
echo "exit=$rc" >"$R/exit.txt"
date -Is >"$D/ended"
awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.1f\n", b - a }' >"$D/duration_s"
echo "run $tag exit=$rc duration=$(cat "$D/duration_s")s"
