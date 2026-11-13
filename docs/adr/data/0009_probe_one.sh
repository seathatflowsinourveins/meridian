#!/bin/bash
# One always-on probe. args: LETTER(A|B) N. Key (outside the run folders): A=without, B=with.
set -u
EV=$HOME/src/meridian-ab/0009; S=$EV/scripts
L=$1 n=$2
case $L in A) arm=without ;; B) arm=with ;; *) exit 2 ;; esac
tag=probe-$L$n d=$EV/wt/$L$n
[ "$(dsh --version </dev/null)" = 0.2.2-rc.1 ] || { echo 'STOP: dsh changed'; exit 4; }
# IB GATEWAY GUARD (required before every run that starts an agent under test)
[ "$(ss -Hltn 'sport = :4002' | wc -l)" = 0 ] && ! pgrep -f ibgateway >/dev/null || { echo GATEWAY-UP; exit 3; }
git --no-optional-locks -C "$HOME/src/meridian" status --porcelain=v1 | sha256sum > "$EV/$tag.main.before"
git -C "$EV/src" worktree add -q --detach "$d" base || exit 7
date -Is > "$EV/$tag.started"
unshare -rn bash "$S/probe_inner.sh" "$arm" "$tag" "$d"
cat "$EV/$tag.exit"
bash "$S/check_after.sh" "$tag" "$d"
