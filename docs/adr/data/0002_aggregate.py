"""Recompute the figures of ADR 0002 from docs/adr/data/0002-results.json.

Usage: python3 -I 0002_aggregate.py 0002-results.json
Prints the always-on medians, the R1 figures per arm, both readings of the rule and the cost,
then compares them with the file's "figures" block and exits 1 on any difference.
"""

import json
import statistics
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
ok, r1 = data["ok"], data["r1"]


def valid_ok(run):
    return run["num_turns"] == 1 and not run["is_error"] and run["terminal_reason"] == "completed"


def arm_ok(arm):
    return [r for r in ok.values() if r["arm"] == arm and valid_ok(r)]


aw, ao = arm_ok("with"), arm_ok("without")
mw = statistics.median(r["result_input_all"] for r in aw)
mo = statistics.median(r["result_input_all"] for r in ao)


def arm_r1(arm):
    names = sorted((n for n, r in r1.items() if r["arm"] == arm), key=lambda n: n[2])
    rs = [r1[n] for n in names]
    return names, rs


def summary(names, rs):
    return {
        "runs": names,
        "passed": sum(r["passed"] for r in rs),
        "tokens": [r["tokens_all"] for r in rs],
        "median_tokens": statistics.median(r["tokens_all"] for r in rs),
        "mean_tokens": round(statistics.mean(r["tokens_all"] for r in rs), 1),
        "turns": [r["num_turns"] for r in rs],
        "median_turns": statistics.median(r["num_turns"] for r in rs),
        "duration_s": [round(r["duration_ms"] / 1000, 1) for r in rs],
        "median_duration_s": round(statistics.median(r["duration_ms"] for r in rs) / 1000, 1),
        "server_started_runs": sum(1 for r in rs if r["lsp"]["started"] > 0),
        "diagnostics_delivered": sum(r["lsp"]["delivered_diagnostics"] for r in rs),
        "lsp_tool_calls": sum(r["lsp"]["lsp_tool_calls"] for r in rs),
        "runs_with_edit_tool": sum(1 for r in rs if r["distinct_tool_calls"].get("Edit", 0) > 0),
    }


for r in r1.values():
    assert r["tokens_all"] == sum(r["modelUsage"][k] for k in ("input", "cache_creation", "cache_read", "output"))
    assert r["claude_code_version"] == "2.1.322" and r["model_keys"] == ["claude-opus-5-5"]
for r in ok.values():
    assert r["claude_code_version"] == "2.1.322"
    assert r["result_input_all"] == sum(r["usage"][k] for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))

nw, rw = arm_r1("with")
no, ro = arm_r1("without")
sw, so = summary(nw, rw), summary(no, ro)
need = so["median_tokens"] * 0.75
delta = mw - mo
okw_tok = statistics.median(r["tokens_all"] for r in aw)
oko_tok = statistics.median(r["tokens_all"] for r in ao)
fig = {
    "always_on": {
        "median_with": mw, "median_without": mo, "delta": delta,
        "delta_pct_of_without": round(delta / mo * 100, 2),
        "n_tools_with": aw[0]["n_tools"], "n_tools_without": ao[0]["n_tools"],
        "context_deferred_tools_with": aw[0]["context_categories"]["System tools (deferred)"],
        "context_deferred_tools_without": ao[0]["context_categories"]["System tools (deferred)"],
        "context_total_with": aw[0]["context_total_tokens"], "context_total_without": ao[0]["context_total_tokens"],
        "per_session_at_median_r1_turns_without": delta * so["median_turns"],
    },
    "r1": {
        "with": sw, "without": so,
        "median_token_change_pct": round((sw["median_tokens"] / so["median_tokens"] - 1) * 100, 1),
        "condition_2_needs_with_median_at_most": int(need),
    },
    "cost": {
        "with": {"tokens": 3 * okw_tok + sum(sw["tokens"]),
                 "usd_estimate": round(sum(r["total_cost_usd"] for r in aw) + sum(r["total_cost_usd"] for r in rw), 2)},
        "without": {"tokens": 3 * oko_tok + sum(so["tokens"]),
                    "usd_estimate": round(sum(r["total_cost_usd"] for r in ao) + sum(r["total_cost_usd"] for r in ro), 2)},
    },
}
fig["cost"]["total"] = {"tokens": fig["cost"]["with"]["tokens"] + fig["cost"]["without"]["tokens"],
                        "usd_estimate": round(sum(r["total_cost_usd"] for r in ok.values())
                                              + sum(r["total_cost_usd"] for r in r1.values()), 2)}

# The rule, read two ways (0002-prereg.txt).
cond1_itt = sw["passed"] >= 2 and so["passed"] <= 1
cond2_itt = sw["passed"] >= 2 and sw["passed"] == so["passed"] and sw["median_tokens"] <= need
tie = abs(sw["passed"] - so["passed"]) == 1 or (sw["passed"] == so["passed"] == 2)
valid_with = [r for r in rw if r["valid_under_fact_sheet_marker_rule"]]
print(f"always-on: with {mw}, without {mo}, delta {delta} ({fig['always_on']['delta_pct_of_without']}% of without)")
for arm, s in (("without", so), ("with", sw)):
    print(f"R1 {arm}: {s['runs']} passed {s['passed']} of 3, tokens {s['tokens']} median {s['median_tokens']}, "
          f"turns {s['turns']} median {s['median_turns']}, seconds {s['duration_s']} median {s['median_duration_s']}, "
          f"server started in {s['server_started_runs']}, diagnostics delivered {s['diagnostics_delivered']}")
print(f"median tokens with vs without: {fig['r1']['median_token_change_pct']:+}%; condition 2 needs at most {int(need)}")
print(f"intent to treat: condition 1 {cond1_itt}, condition 2 {cond2_itt}, tie rule {tie}")
print(f"validity rule: valid with-arm runs {[n for n, r in zip(nw, rw) if r['valid_under_fact_sheet_marker_rule']]}; "
      f"condition 1 {len([r for r in valid_with if r['passed']]) >= 2 and so['passed'] <= 1} whatever replacements do; "
      f"condition 2 would need two replacements each <= {int(need)} (lowest run in the series: "
      f"{min(r['tokens_all'] for r in r1.values())})")
print(f"cost: {fig['cost']}")

stored = data["figures"]
if json.loads(json.dumps(fig)) != stored:
    for part in fig:
        if json.loads(json.dumps(fig[part])) != stored.get(part):
            print(f"MISMATCH in figures.{part}:\n recomputed {fig[part]}\n stored     {stored.get(part)}")
    sys.exit(1)
print("figures block matches")
