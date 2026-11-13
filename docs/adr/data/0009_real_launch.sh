#!/usr/bin/env bash
# launch.sh NAME CMD [ARGS...] -- start CMD detached from the calling shell (its own session, no
# terminal), with its output in $EV/NAME.driver.log and its pid in $EV/NAME.driver.pid.
# wait.sh NAME SECONDS then waits for it. One run at a time: refuses while another is alive.
set -u
. "$(dirname "$0")/common.sh"
name=$1; shift
for f in "$EV"/*.driver.pid; do
  [ -f "$f" ] || continue
  if kill -0 "$(cat "$f")" 2>/dev/null; then echo "launch: $(basename "$f" .driver.pid) is still running"; exit 9; fi
done
[ ! -e "$EV/$name.driver.log" ] || { echo "launch: $name was started before"; exit 8; }
setsid nohup "$@" >"$EV/$name.driver.log" 2>&1 </dev/null &
echo $! >"$EV/$name.driver.pid"
echo "started $name pid $! at $(date -Is)"
