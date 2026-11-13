#!/usr/bin/env bash
# Print one line per ADR 0005 run folder: running / metrics / grade / invalid / gateway.
cd "$HOME/src/meridian-ab/0005" || exit 1
for d in a-k* b-k* a-[0-9]* b-[0-9]*; do
  [ -d "$d" ] || continue
  s=running
  [ -f "$d/metrics.json" ] && s=$(jq -c '{always_on:.result_input_all,turns:.num_turns,tr:.terminal_reason,tok:.tokens_all,plugins:.plugins}' "$d/metrics.json")
  [ -f "$d/summary.json" ] && s=$(jq -c '{passed,turns:.num_turns,tok:.tokens_all,tr:.terminal_reason,flags:.containment_flags,leaks:.leak_hits,wall_s}' "$d/summary.json")
  [ -f "$d/invalid.txt" ] && s="INVALID $(cat "$d/invalid.txt")"
  [ -f "$d/guard-fired.txt" ] && s=GATEWAY-UP
  echo "$d $s"
done
