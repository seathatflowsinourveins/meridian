#!/usr/bin/env bash
# Export a compact JSON of all ADR 0002 runs (aggregates only; no transcripts) to stdout.
set -uo pipefail
cd "$HOME/src/meridian-ab/0002" || exit 1
ok='{}'; r1='{}'
for d in a-k* b-k*; do
  [ -f "$d/metrics.json" ] || continue
  rec=$(jq -n --slurpfile m "$d/metrics.json" --slurpfile l "$d/lsp-markers.json" \
    --slurpfile cu <(cat "$d/context_usage.json" 2>/dev/null || echo null) \
    --slurpfile cr <(cat "$d/context_result.json" 2>/dev/null || echo null) \
    --arg flags "$(paste -sd, "$d/containment-flags.txt")" --arg leaks "$(wc -l < "$d/leak-hits.txt")" \
    '{metrics:($m[0]|del(.modelUsage)), lsp:$l[0], context_usage:$cu[0], context_result:$cr[0], flags:$flags, leak_hits:($leaks|tonumber)}')
  ok=$(jq --arg k "$d" --argjson v "$rec" '. + {($k):$v}' <<<"$ok")
done
for d in a-[0-9]* b-[0-9]*; do
  [ -f "$d/summary.json" ] || continue
  void=$(cat "$d/void.txt" 2>/dev/null || true)
  inv=$(cat "$d/invalid.txt" 2>/dev/null || true)
  rec=$(jq --arg void "$void" --arg inv "$inv" --slurpfile m "$d/metrics.json" \
    '. + {void:(if $void=="" then null else $void end), invalid:(if $inv=="" then null else $inv end), modelUsage:$m[0].modelUsage, usage:$m[0].usage}' "$d/summary.json")
  r1=$(jq --arg k "$d" --argjson v "$rec" '. + {($k):$v}' <<<"$r1")
done
jq -n --argjson ok "$ok" --argjson r1 "$r1" '{ok:$ok, r1:$r1}'
