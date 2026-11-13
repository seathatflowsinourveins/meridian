#!/usr/bin/env bash
# Export a compact JSON of every ADR 0002 R1 run folder (aggregates only; no transcripts, no secrets) to stdout.
# Usage: collect-r2.sh <run folder>...   (folders under ~/src/meridian-ab/0002)
set -uo pipefail
cd "$HOME/src/meridian-ab/0002" || exit 1
all='{}'
for d in "$@"; do
  [ -f "$d/summary.json" ] || { all=$(jq --arg k "$d" '. + {($k):{missing_summary:true}}' <<<"$all"); continue; }
  dbg=$d/r1.debug.txt
  loaded=$(grep -cF 'Loaded 1 LSP server(s) from plugin: pyright-lsp' "$dbg")
  started=$(grep -cF 'Starting LSP server instance: plugin:pyright-lsp:pyright' "$dbg")
  first_start=$(grep -F 'Starting LSP server instance: plugin:pyright-lsp:pyright' "$dbg" | head -n 1 | cut -c1-24)
  delivering=$(grep -cF 'LSP Diagnostics: Delivering' "$dbg")
  delivered_diags=$(grep -oE 'LSP Diagnostics: Delivering [0-9]+ file\(s\) with [0-9]+ diagnostic' "$dbg" | grep -oE 'with [0-9]+' | awk '{s+=$2} END{print s+0}')
  received=$(grep -cE 'Received diagnostics from plugin:pyright-lsp:pyright: [0-9]+ diagnostic' "$dbg")
  received_nonzero=$(grep -oE 'Received diagnostics from plugin:pyright-lsp:pyright: [0-9]+ diagnostic' "$dbg" | grep -vcE ': 0 diagnostic')
  lsp_tool=$(jq -r 'select(.name=="LSP")|.name' "$d/tool_calls.jsonl" | wc -l)
  toolsearch=$(jq -r 'select(.name=="ToolSearch")|.input|tostring' "$d/tool_calls.jsonl" | paste -sd'|' -)
  tool_names=$(jq -r '.name' "$d/tool_calls.jsonl" | sort | uniq -c | awk '{print $2"x"$1}' | paste -sd, -)
  # the diagnostics text Claude Code injected (from the transcript), first 300 chars of each block
  diag_blocks=$(grep -o '<new-diagnostics>[^<]*' "$d/r1.transcript.jsonl" 2>/dev/null | sort -u | cut -c1-300 | jq -R . | jq -s -c .)
  [ -n "$diag_blocks" ] || diag_blocks='[]'
  codex_any=$(grep -ci codex "$d/tool_calls.jsonl")
  stop_gate=$(grep -F 'stop-review-gate-hook.mjs' "$dbg" | grep -o 'finished with status [0-9]* ([0-9]*ms)' | paste -sd, -)
  codex=$(cat "$d/codex.json" 2>/dev/null || echo null)
  guard=$(cat "$d/guard.log" 2>/dev/null | jq -R . | jq -s -c .)
  flags=$(paste -sd, "$d/containment-flags.txt" 2>/dev/null)
  tmpnew=$(diff "$d/snap-pre/tmp.txt" "$d/snap-post/tmp.txt" 2>/dev/null | sed -n 's/^> //p' | grep -vE '^uv-[0-9a-f]+\.lock$' | paste -sd, -)
  homenew=$(diff "$d/snap-pre/home.txt" "$d/snap-post/home.txt" 2>/dev/null | sed -n 's/^> //p' | paste -sd, -)
  cachenew=$(diff "$d/snap-pre/cache.txt" "$d/snap-post/cache.txt" 2>/dev/null | sed -n 's/^> //p' | paste -sd, -)
  pdatanew=$(diff "$d/snap-pre/plugin-data.txt" "$d/snap-post/plugin-data.txt" 2>/dev/null | sed -n 's/^> //p' | paste -sd, -)
  wtnew=$(diff "$d/snap-pre/worktrees.txt" "$d/snap-post/worktrees.txt" 2>/dev/null | sed -n 's/^> //p' | paste -sd, -)
  cjnew=$(diff <(sort "$d/snap-pre/claude-json-keys.txt") <(sort "$d/snap-post/claude-json-keys.txt") 2>/dev/null | sed -n 's/^[<>] //p' | paste -sd, -)
  recs=$(diff -q "$d/snap-pre/plugin-records.sha256" "$d/snap-post/plugin-records.sha256" >/dev/null 2>&1 && echo same || echo changed)
  wtprocs=$(cat "$d/snap-post/wt-procs.txt" 2>/dev/null | paste -sd, -)
  lsprocs=$(comm -13 "$d/snap-pre/langserver-procs.txt" "$d/snap-post/langserver-procs.txt" 2>/dev/null | cut -c1-80 | paste -sd'|' -)
  wtstatus=$(diff "$d/snap-pre/wt-status-ignored.txt" "$d/snap-post/wt-status-ignored.txt" 2>/dev/null | sed -n 's/^> //p' | paste -sd, -)
  leaks=$(cut -c1-160 "$d/leak-hits.txt" | jq -R . | jq -s -c .)
  denials=$(jq -R 'fromjson? // empty' "$d/r1.stream.jsonl" | jq -c 'select(.type=="result")|[.permission_denials[]?|{tool_name, input:(.tool_input|tostring|.[0:160])}]')
  void=$(cat "$d/void.txt" 2>/dev/null || true); inv=$(cat "$d/invalid.txt" 2>/dev/null || true); vm=$(cat "$d/version-mismatch.txt" 2>/dev/null || true)
  started_at=$(cat "$d/started_at.txt" 2>/dev/null)
  launcher=$(cat "$d/launcher-target.txt" 2>/dev/null)
  rec=$(jq -n --slurpfile s "$d/summary.json" --slurpfile m "$d/metrics.json" \
    --argjson diag "$diag_blocks" --argjson codex "$codex" --argjson guard "${guard:-[]}" --argjson leaks "$leaks" --argjson denials "${denials:-[]}" \
    --arg loaded "$loaded" --arg started "$started" --arg first_start "$first_start" --arg delivering "$delivering" --arg delivered_diags "$delivered_diags" \
    --arg received "$received" --arg received_nonzero "$received_nonzero" --arg lsp_tool "$lsp_tool" --arg toolsearch "$toolsearch" --arg tool_names "$tool_names" \
    --arg codex_any "$codex_any" --arg stop_gate "$stop_gate" --arg flags "$flags" --arg tmpnew "$tmpnew" --arg homenew "$homenew" --arg cachenew "$cachenew" \
    --arg pdatanew "$pdatanew" --arg wtnew "$wtnew" --arg cjnew "$cjnew" --arg recs "$recs" --arg wtprocs "$wtprocs" --arg lsprocs "$lsprocs" --arg wtstatus "$wtstatus" \
    --arg void "$void" --arg inv "$inv" --arg vm "$vm" --arg started_at "$started_at" --arg launcher "$launcher" \
    '{summary:($s[0]|del(.grade.pytest_tail)|. + {pytest_tail:$s[0].grade.pytest_tail}), modelUsage:$m[0].modelUsage, usage:$m[0].usage, init_model:$m[0].model,
      started_at:$started_at, launcher_target:$launcher,
      lsp:{loaded_1:($loaded|tonumber), started:($started|tonumber), first_start:$first_start, delivering:($delivering|tonumber), delivered_diagnostics:($delivered_diags|tonumber),
           received:($received|tonumber), received_nonzero:($received_nonzero|tonumber), lsp_tool_calls:($lsp_tool|tonumber), toolsearch_inputs:$toolsearch, injected_blocks:$diag},
      tool_names:$tool_names,
      codex:{tool_calls_mentioning_codex:($codex_any|tonumber), stop_review_gate_hook:$stop_gate, observer:$codex},
      guard_log:$guard,
      containment:{flags:$flags, tmp_new_non_uv_lock:$tmpnew, home_new:$homenew, cache_new:$cachenew, plugin_data_new:$pdatanew, worktrees_new:$wtnew,
                   claude_json_key_changes:$cjnew, plugin_records:$recs, procs_left_in_wt:$wtprocs, langserver_left:$lsprocs, wt_status_new:$wtstatus},
      leak_hits:$leaks, permission_denials:$denials,
      void:(if $void=="" then null else $void end), invalid:(if $inv=="" then null else $inv end), version_mismatch:(if $vm=="" then null else $vm end)}')
  all=$(jq --arg k "$d" --argjson v "$rec" '. + {($k):$v}' <<<"$all")
done
jq . <<<"$all"
