#!/usr/bin/env bash
# IB Gateway guard for the plan 8.6 with/without runs (not part of the repo).
# Up = a listener on 4002, a process whose executable is under ~/Jts, or a
# process named exactly java or ibgateway. Matches process names and
# executables, never command lines, so another agent's argv cannot trip it.
up=""
[ -n "$(ss -Hltn 'sport = :4002')" ] && up="listener on 4002"
for d in /proc/[0-9]*; do
  case "$(readlink "$d/exe" 2>/dev/null)" in "$HOME"/Jts/*) up="${up:+$up; }pid ${d#/proc/} runs from ~/Jts";; esac
done
pgrep -x java >/dev/null && up="${up:+$up; }a java process"
pgrep -x ibgateway >/dev/null && up="${up:+$up; }a process named ibgateway"
if [ -n "$up" ]; then echo "GATEWAY-UP ($up)"; exit 3; fi
echo "gateway down"
