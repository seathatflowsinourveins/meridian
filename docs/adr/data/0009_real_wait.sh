#!/usr/bin/env bash
# wait.sh NAME SECONDS -- wait up to SECONDS for the driver started by launch.sh NAME.
set -u
. "$(dirname "$0")/common.sh"
name=$1 secs=$2
pid=$(cat "$EV/$name.driver.pid")
timeout "$secs" tail --pid="$pid" -f /dev/null
if kill -0 "$pid" 2>/dev/null; then
  echo "RUNNING $name pid $pid at $(date -Is)"
else
  echo "DONE $name at $(date -Is)"; cat "$EV/$name.driver.log"
fi
