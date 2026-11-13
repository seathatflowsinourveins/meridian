#!/usr/bin/env bash
# Collect the resumed ADR 0004 task runs as JSON lines on stdout (aggregates only; no transcripts, no tool-call text).
set -uo pipefail
cd "$HOME/src/meridian-ab/0004" || exit 1
for d in a-r* b-r*; do
  [ -d "$d" ] || continue
  if [ ! -f "$d/summary.json" ]; then printf '{"run":"%s","incomplete":true}\n' "$d"; continue; fi
  jq -c --arg g "$(cat "$d/guard.log" 2>/dev/null)" --arg procs "$(paste -sd, "$d/procs-during.txt" 2>/dev/null)" \
        --arg inv "$(cat "$d/invalid.txt" 2>/dev/null)" --arg started "$(cat "$d/started_at.txt" 2>/dev/null)" \
        --arg wtfinal "$(wc -l < "$d/wt-status-final.txt" 2>/dev/null)" \
    'del(.skills) + {guard_log:$g, procs_during:$procs, invalid:$inv, started_at:$started, wt_status_final_lines:$wtfinal}' "$d/summary.json"
done
