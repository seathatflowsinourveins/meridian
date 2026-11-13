#!/usr/bin/env bash
# Collect ADR 0004 run results into one JSON on stdout (aggregates only; no transcripts).
set -uo pipefail
cd "$HOME/src/meridian-ab/0004" || exit 1
{
  echo '{"ok":{'
  first=1
  for d in a-k* b-k*; do
    [ -f "$d/metrics.json" ] || continue
    [ $first = 1 ] || echo ','; first=0
    ctx=$(head -n 1 "$d/context_usage.json" 2>/dev/null); [ -n "$ctx" ] || ctx=null
    printf '"%s":{"metrics":%s,"context":%s,"flags":%s}' "$d" "$(jq -c 'del(.modelUsage)' "$d/metrics.json")" "$ctx" "$(jq -Rs . < "$d/containment-flags.txt")"
  done
  echo '},"tasks":{'
  first=1
  for d in a-r* b-r*; do
    [ -f "$d/summary.json" ] || continue
    [ $first = 1 ] || echo ','; first=0
    printf '"%s":%s' "$d" "$(jq -c 'del(.skills)' "$d/summary.json")"
  done
  echo '}}'
} | jq .
