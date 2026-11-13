"""ADR 0004: recompute the figures and the adoption rule from 0004-results.json.

Usage: python3 -I docs/adr/data/0004_aggregate.py [docs/adr/data/0004-results.json]
Standard library only. Prints the always-on figures, one line per task and arm, then the rule under
two readings of the containment check, and exits 1 on any mismatch.

Recomputed and compared with what is recorded:
- always_on: median_without and median_with from without_runs and with_runs, the delta, the
  listing-only control's delta, and the condition string from that delta and the 150 limit.
- per_task: every field, per arm and per task, from task_runs. A recorded per_task field it does not
  recompute, or a recomputed one that is not recorded, is a mismatch too.
- rule_result and rule_result_literal_clause, from the per-task results.
Taken as recorded: each run's own fields in task_runs (passed, tokens, turns, skill_invoked, stall,
containment_ok, bash_clause_calls and the rest come from the raw runs, which are not published).
Not checked: free text (rule_note, summary, cost, containment, the notes).

Always-on: the rule fixed before any run (the assessment's adopt_if of 2026-11-12 and the fact
sheet of 01:44 ET, both measuring with the copies uncommitted) applies the 150-token limit to the
measured delta, 182, so the condition fails. The first run's record, written at 02:01 ET after the
always-on runs (01:58 to 01:59 ET), applied the limit to the listing-only control's 121 instead; it
is not part of that rule. An unpublished draft of the rule, written after that result, bound the limit to a rerun
with the copies committed; that rerun was not done (no committed-copy runs are recorded), so under
the unpublished draft (03:30 ET) the condition is open. A task whose outcome conditions all held would come out "not
adopted" under the first and "open" under the second.

Token ranges: per arm, min_tokens and max_tokens beside the median; with 3 runs per arm and
overlapping ranges, the ratio of medians is within the run-to-run spread.

Containment, two readings of the assessment's check:
- as applied (read after the runs, in the ADR's revision of 2026-11-13): a run breaks it only if its
  containment_ok is false. A with-run that does scores as a failure; a without-run that does should
  have been re-run, which is reported as a mismatch.
- literal: a run whose Bash calls name a word of the check's list (bash_clause_calls) breaks it.
  Such with-runs score as failures; such without-runs would be re-run, so the without arm is
  unknown and a task is "not adopted" only if no re-run outcome could adopt it.
Void runs are left out of every figure, the stall check included.
"""

import json
import statistics
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("0004-results.json"))
res = json.loads(path.read_text(encoding="utf-8"))
runs = res["task_runs"]
problems = []
CLAUSE = [
    "ibkr_paper",
    "ib_probe",
    "ibgateway",
    "4002",
    "curl",
    "wget",
    "pip install",
    "uv add",
    "npm",
    "npx",
]


def check(label, recorded, computed):
    if recorded != computed:
        problems.append(f"{label}: recorded {recorded!r}, recomputed {computed!r}")


def compare(label, recorded, computed):
    for k, v in recorded.items():
        if k not in computed:
            problems.append(f"{label} {k}: recorded but not recomputed")
        elif v != computed[k]:
            problems.append(f"{label} {k}: recorded {v}, recomputed {computed[k]}")
    for k in computed:
        if k not in recorded:
            problems.append(f"{label} {k}: recomputed but not recorded")


# Always-on
ao = res["always_on"]
limit = ao["limit"]
med_wo, med_w = statistics.median(ao["without_runs"]), statistics.median(ao["with_runs"])
check("always_on median_without", ao["median_without"], med_wo)
check("always_on median_with", ao["median_with"], med_w)
delta = med_w - med_wo
check("always_on delta", ao["delta"], delta)
ctl = ao["listing_only_control"]
check("always_on listing_only_control delta", ctl["delta"], ctl["with"] - ctl["without"])
if "committed_copy_with_runs" in ao or "committed_copy_without_runs" in ao:
    problems.append("always_on: committed-copy runs are recorded; this script does not score them")
pre_run = "fails" if delta > limit else "holds"
sign = ">" if delta > limit else "<="
condition = (
    f"{pre_run} under the rule fixed before any run ({delta} {sign} {limit}); open under "
    "the unpublished draft's later committed-copy rerun, which was not done"
)
check("always_on condition", ao.get("condition"), condition)
print(
    f"always-on: medians {med_wo:,} without and {med_w:,} with, delta {delta}; listing-only "
    f"control delta {ctl['with'] - ctl['without']}; condition: {condition}"
)

# Bash calls naming the check's words
for r in runs:
    calls = r["bash_clause_calls"]
    if set(calls) - set(CLAUSE) or any(v <= 0 for v in calls.values()):
        problems.append(f"{r['run']} bash_clause_calls: unknown word or zero count {calls}")
    n_any = r["bash_calls_naming_clause_words"]
    if not (max(calls.values(), default=0) <= n_any <= min(sum(calls.values()), r["bash_calls"])):
        problems.append(
            f"{r['run']} bash_calls_naming_clause_words {n_any} inconsistent with {calls}"
        )
scored_runs = [r for r in runs if not r["void"]]
words = {w: sum(1 for r in scored_runs if w in r["bash_clause_calls"]) for w in CLAUSE}
print(
    "runs whose Bash calls name each word of the check:",
    ", ".join(f"{w} {n}" for w, n in words.items()),
    f"| Bash calls naming any: {sum(r['bash_calls_naming_clause_words'] for r in scored_runs)}"
    f" of {sum(r['bash_calls'] for r in scored_runs)}",
)


def arm_stats(task, arm):
    rs = [r for r in runs if r["task"] == task and r["arm"] == arm]
    scored = [r for r in rs if not r["void"]]
    if arm == "without":
        for r in scored:
            if not r["containment_ok"]:
                problems.append(f"{r['run']}: a without-run that broke containment must be re-run")

    def counts(r):  # a with-run that breaks containment scores as a failure
        return arm == "without" or r["containment_ok"]

    clause = [r for r in scored if r["bash_clause_calls"]]
    s = {
        "n": len(scored),
        "passes": sum(bool(r["passed"]) and counts(r) for r in scored),
        "passes_strict": sum(bool(r["passed_strict"]) and counts(r) for r in scored),
        "median_tokens": statistics.median(r["tokens"] for r in scored),
        "min_tokens": min(r["tokens"] for r in scored),
        "max_tokens": max(r["tokens"] for r in scored),
        "median_turns": statistics.median(r["turns"] for r in scored),
        "median_duration_s": statistics.median(r["duration_s"] for r in scored),
        "sum_tokens": sum(r["tokens"] for r in scored),
        "sum_cost_usd": round(sum(r["cost_usd"] for r in scored), 4),
        "skill_invoked": sum(bool(r["skill_invoked"]) for r in scored) if arm == "with" else None,
        "stalls": sum(bool(r["stall"]) for r in scored),
        "voids": len(rs) - len(scored),
        "containment_breaches": sum(not r["containment_ok"] for r in scored),
        "runs_naming_clause_words": len(clause),
    }
    if arm == "with":
        s["passes_literal_clause"] = sum(
            bool(r["passed"]) and r["containment_ok"] and not r["bash_clause_calls"] for r in scored
        )
    return s


results, results_literal = [], []
for task, skill in (("R3", "tdd"), ("R1", "diagnosing-bugs")):
    w, wo = arm_stats(task, "with"), arm_stats(task, "without")
    for arm, s in (("with", w), ("without", wo)):
        print(
            f"{task} {skill:15} {arm:7} n={s['n']} passes={s['passes']} "
            f"median_tokens={s['median_tokens']:,} "
            f"(range {s['min_tokens']:,} to {s['max_tokens']:,}) median_turns={s['median_turns']} "
            f"median_s={s['median_duration_s']} invoked={s['skill_invoked']} "
            f"stalls={s['stalls']} voids={s['voids']} breaches={s['containment_breaches']} "
            f"runs_naming_clause_words={s['runs_naming_clause_words']} cost_usd={s['sum_cost_usd']}"
        )
        compare(f"{task} {arm}", res["per_task"][task][arm], s)
    n = w["n"]
    gap = abs(w["passes"] - wo["passes"])
    extension = n == 3 and (gap == 1 or (w["passes"] == 2 and wo["passes"] == 2))
    hi, lo = (2, 1) if n == 3 else (4, 2)
    ratio = w["median_tokens"] / wo["median_tokens"]
    cond_a = w["passes"] >= hi and wo["passes"] <= lo
    cond_b = w["passes"] >= hi and wo["passes"] >= hi and ratio <= 0.75
    invoked = w["skill_invoked"] >= hi
    no_stall = w["stalls"] == 0  # scored with-runs only
    outcome = (not extension) and (cond_a or cond_b) and invoked and no_stall
    if not outcome:
        result = "not adopted"
    elif pre_run == "fails":
        result = "not adopted under the rule fixed before any run (always-on); open under the unpublished draft (03:30 ET)"
    else:
        result = "adopt"
    # Literal reading: the with arm can still adopt only if it can reach the threshold after the
    # one extension (2 more runs: 4 of 5) or without it (2 of 3), whatever the re-run without arm
    # does.
    need = 2 if n == 3 else 4
    feasible = w["passes_literal_clause"] >= need and w["skill_invoked"] >= need
    result_literal = "not adopted" if not feasible else "undetermined: without-runs to re-run"
    results.append(result)
    results_literal.append(result_literal)
    print(
        f"{task} rule as applied: extension_needed={extension} with/without median tokens="
        f"{ratio:.4f} (a)={cond_a} (b)={cond_b} invoked>={hi}={invoked} no_stall={no_stall} "
        f"outcome_conditions_met={outcome} -> {result}"
    )
    print(
        f"{task} rule, Bash clause literal: with passes {w['passes_literal_clause']} of {n}, "
        f"{wo['runs_naming_clause_words']} without-runs to re-run -> {result_literal}"
    )
    computed = {
        "skill": skill,
        "with": res["per_task"][task]["with"],
        "without": res["per_task"][task]["without"],  # compared field by field above
        "extension_needed": extension,
        "with_over_without_median_tokens": round(ratio, 4),
        "cond_a_with_ge2_without_le1": cond_a,
        "cond_b_both_ge2_and_tokens_le_75pct": cond_b,
        "skill_invoked_ge2_of_3": invoked,
        "no_stall": no_stall,
        "outcome_conditions_met": outcome,
        "result": result,
        "result_literal_clause": result_literal,
    }
    compare(task, res["per_task"][task], computed)

overall = "not adopted" if all(r == "not adopted" for r in results) else "open"
overall_literal = "not adopted" if all(r == "not adopted" for r in results_literal) else "open"
print("rule result:", overall, "| with the Bash clause read literally:", overall_literal)
check("rule_result", res["rule_result"], overall)
check("rule_result_literal_clause", res.get("rule_result_literal_clause"), overall_literal)
for p in problems:
    print("MISMATCH", p)
sys.exit(1 if problems else 0)
