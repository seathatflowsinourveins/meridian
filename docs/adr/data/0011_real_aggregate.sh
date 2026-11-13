#!/usr/bin/env bash
# 0011r_aggregate.sh WITH_LETTER VOIDFILE RUN...
# Aggregate of the R2 series of ADR 0011: per run pass, billed tokens, turns, steps, seconds and what the
# addition did; per arm the passes and the median billed tokens over scored runs; and the pre-registered
# rule. VOIDFILE holds one line per voided run, "<run><TAB><reason>" (it may be empty). Paths are not printed.
set -euo pipefail
with=$1; voidfile=$2; shift 2
EV=$HOME/src/meridian-ab/0011/real
rows='[]'
for tag in "$@"; do
  R=$EV/$tag
  void=$(awk -F'\t' -v t="$tag" '$1 == t { print $2 }' "$voidfile")
  arm=without; [ "${tag:0:1}" = "$with" ] && arm=with
  ledger=null
  [ -f "$R/goal-gate/state.json" ] && ledger=$(jq -c --slurpfile h <(cat "$R/goal-gate/history.jsonl" 2>/dev/null || true) \
     '{falseCompletes: (.falseCompletes // 0), gate_evaluations: ($h | length), evaluation_codes: ($h | map(.code)), triggers: ($h | map(.trigger))}' "$R/goal-gate/state.json")
  row=$(jq -c --arg arm "$arm" --arg void "$void" --argjson ledger "$ledger" --slurpfile a "$R/addition.json" \
     --arg started "$(cat "$R/run.started")" '
     {run, arm: $arm, started: $started, passed, void: (if $void == "" then "none" else $void end), dsh_exit: .exit, final_reason,
      duration_s, billed_tokens, model_calls, calls_without_usage, turns, steps, sessions, goal_rounds, tool_calls,
      replay, tests_unchanged, scope_ok, patch_bytes,
      addition: {plugin_tool_calls: ($a[0].plugin_tool_calls | map(.name)), dsh_goal_tool_calls: ($a[0].dsh_goal_tool_calls | map(.name)),
                 skill_calls: ($a[0].skill_calls | length), gate_denials: $a[0].gate_denials, ledger: $ledger},
      containment}' "$R/summary.json")
  rows=$(jq -c --argjson row "$row" '. + [$row]' <<<"$rows")
done
jq -n --argjson rows "$rows" '
  def median: sort | if length == 0 then null elif length % 2 == 1 then .[(length - 1) / 2] else (.[length / 2 - 1] + .[length / 2]) / 2 end;
  def arm($a): $rows | map(select(.arm == $a and .void == "none"));
  (arm("with")) as $w | (arm("without")) as $o
  | ($w | map(select(.passed)) | length) as $sw | ($o | map(select(.passed)) | length) as $so
  | ($w | map(.billed_tokens) | median) as $mw | ($o | map(.billed_tokens) | median) as $mo
  | ($w | map(select((.addition.ledger.falseCompletes // 0) >= 2)) | length) as $blocked
  | {runs: $rows,
     with: {scored: ($w | length), passes: $sw, median_billed_tokens: $mw, median_duration_s: ($w | map(.duration_s) | median), blocked_runs: $blocked},
     without: {scored: ($o | length), passes: $so, median_billed_tokens: $mo, median_duration_s: ($o | map(.duration_s) | median)},
     token_ratio_with_over_without: (if $mo != null and $mo > 0 and $mw != null then ($mw / $mo * 1000 | round / 1000) else null end),
     total_billed_tokens_all_runs: ($rows | map(.billed_tokens) | add),
     rule: "Adopt only if no BLOCKED or safety violation and S_with >= 2 and S_without <= 1, or S_with >= S_without >= 2 with median billed tokens <= 0.75x.",
     rule_route_success: ($sw >= 2 and $so <= 1),
     rule_route_tokens: ($sw >= $so and $so >= 2 and $mw != null and $mo != null and $mw <= 0.75 * $mo),
     extension_due: ((($sw - $so) | fabs) == 1 or ($sw == 2 and $so == 2))}'
