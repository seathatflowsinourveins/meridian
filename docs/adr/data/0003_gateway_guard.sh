#!/usr/bin/env bash
# IB Gateway guard for the plan 8.6 with/without runs, run right before every agent start.
# The one published copy for the series; some series ran copies that checked port 4002 only.
# Up = a listener on the paper Gateway's port 4002 or TWS's paper port 7497, a process whose
# executable is under ~/Jts, or a process named exactly java or ibgateway. Matches process
# names and executables, never command lines, so another agent's argv cannot trip it, and it
# connects to nothing. It sees only the distro, not a Gateway or TWS on the Windows side.
# Prints "gateway down" and exits 0, or prints GATEWAY-UP and exits 3.
up=""
for port in 4002 7497; do
  [ -n "$(ss -Hltn "sport = :$port")" ] && up="${up:+$up; }listener on $port"
done
for d in /proc/[0-9]*; do
  case "$(readlink "$d/exe" 2>/dev/null)" in "$HOME"/Jts/*) up="${up:+$up; }pid ${d#/proc/} runs from ~/Jts";; esac
done
pgrep -x java >/dev/null && up="${up:+$up; }a java process"
pgrep -x ibgateway >/dev/null && up="${up:+$up; }a process named ibgateway"
if [ -n "$up" ]; then echo "GATEWAY-UP ($up)"; exit 3; fi
echo "gateway down"
