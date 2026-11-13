"""ADR 0006: build docs/adr/data/0006-results.json from the series' run folders.

Usage (in the distro): python3 -I 0006_aggregate.py <run-root> <out-json>
<run-root> is the folder the runners write to (~/src/meridian-ab/0006 on the owner's machine,
not published). Read-only. It reads each run's metrics.json, summary.json, grade/grade.json,
context_usage.json, guard.log, the containment and leak-scan files and the tool-call inputs
(tool_calls.jsonl), never a tool result, plus s2-details/ (plugin validate and details) and
s2-validate/ (the grader check), and writes counts and figures only: no paths, no command text,
no model output. Arm key: 0006-key.txt ("a" is the arm with the addition). Written after the
series, on 2026-11-13; the runners' own records are what it reads.
"""
import json
import re
import statistics
import sys
from pathlib import Path

WITH_ARM = "a"
RULE_CAP = 2000  # always-on cap of the default rule (ab-claude-code.md)


def load(p):
    try:
        t = Path(p).read_text(encoding="utf-8")
        return json.loads(t) if t.strip() else None
    except (OSError, ValueError):
        return None


def lines(p):
    try:
        return [x for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def calls(run):
    out = []
    for x in lines(run / "tool_calls.jsonl"):
        try:
            out.append(json.loads(x))
        except ValueError:
            pass
    return out


CODEX = re.compile(r"(^|[\s/;&|(])codex(\s|$|-companion)|codex-companion|/codex:")
GOAL = re.compile(r"(^|[\s'\"])/goal\b")
NESTED = re.compile(r"(^|[\s;&|(])claude\s+(-p|--print)\b")


def tool_counts(run):
    cs = calls(run)
    bash = [str((c.get("input") or {}).get("command", "")) for c in cs if c.get("name") == "Bash"]
    return {
        "skill_calls": len(lines(run / "skill-calls.txt")),
        "subagent_calls": len(lines(run / "subagent-calls.txt")),
        "codex_calls": sum(1 for c in cs if (c.get("name") == "Skill" and str((c.get("input") or {}).get("skill", "")).startswith("codex"))
                           or (c.get("name") in ("Task", "Agent") and "codex" in str((c.get("input") or {}).get("subagent_type", "")).lower()))
        + sum(1 for b in bash if CODEX.search(b)),
        "goal_or_nested_claude_commands": sum(1 for b in bash if GOAL.search(b) or NESTED.search(b)),
    }


def guard(run):
    g = [x.split(" ", 1)[1] if " " in x else x for x in lines(run / "guard.log")]
    return {"calls": len(g), "all_down": all(x == "rc=0 gateway down" for x in g)}


def common(run, m):
    return {
        "run": run.name, "arm": run.name.split("-")[1], "with": run.name.split("-")[1] == WITH_ARM,
        "claude_code_version": m.get("claude_code_version"), "model_keys": m.get("model_keys"),
        "plugins": m.get("plugins"), "plugin_errors": m.get("plugin_errors"), "n_skills": m.get("n_skills"),
        "terminal_reason": m.get("terminal_reason"), "is_error": m.get("is_error"), "num_turns": m.get("num_turns"),
        "api_retries": m.get("api_retries"), "permission_denials": len(m.get("permission_denials") or []),
        "hooks": sorted({h.get("hook_name") or h.get("subtype") for h in (m.get("hook_events") or [])}),
        "containment_flags": lines(run / "containment-flags.txt"), "leak_scan_hits": len(lines(run / "leak-hits.txt")),
        "guard": guard(run),
    }


MANUAL_ONLY = ["ce-dogfood", "ce-help", "ce-polish", "ce-product-pulse", "ce-promote", "ce-retune",
               "ce-sweep", "ce-test-xcode", "wtf"]  # disable-model-invocation: true at d8f8e03


def details(root):
    """`plugin validate --strict` and `plugin details` as ab2.sh's details mode saved them."""
    v, d = lines(root / "s2-details" / "validate.txt"), lines(root / "s2-details" / "details.txt")
    comp = {}
    for x in d:
        m = re.match(r"^\s+([a-z0-9-]+)\s+~([0-9.,]+)(k?)\s+~([0-9.,]+)(k?)$", x)
        if m:
            comp[m.group(1)] = int(float(m.group(2).replace(",", "")) * (1000 if m.group(3) else 1))
    inv = {m.group(1): int(m.group(2)) for x in d for m in [re.match(r"^\s+(Skills|Agents|Hooks|MCP servers|LSP servers) \((\d+)\)", x)] if m}
    ao = next((int(m.group(1).replace(",", "")) for x in d for m in [re.search(r"Always-on:\s+~([0-9,]+) tok", x)] if m), None)
    return {
        "validate_strict_exit": next((x.split("=", 1)[1] for x in v if x.startswith("exit=")), None),
        "validate_warnings": sum(1 for x in v if x.strip().startswith("❯ root:")),
        "details_exit": next((x.split("=", 1)[1] for x in d if x.startswith("exit=")), None),
        "source_inline": any("Source: compound-engineering@inline" in x for x in d),
        "inventory": inv, "always_on_estimate": ao,
        "manual_only_estimate_sum": sum(comp.get(n, 0) for n in MANUAL_ONLY),
        "always_on_estimate_without_manual_only": (ao or 0) - sum(comp.get(n, 0) for n in MANUAL_ONLY),
    }


def grader_check(root):
    out = {}
    for v in ("none", "ref"):
        g = load(root / "s2-validate" / v / "grade" / "grade.json") or {}
        out[v] = {k: g.get(k) for k in ("passed", "ruff_check_rc", "ruff_format_rc", "pyright_rc", "pytest_rc", "pytest_tail", "pyright_tail")}
    return out


def ok_record(run):
    m = load(run / "metrics.json") or {}
    r = common(run, m)
    r["n_skills_from_addition"] = sum(1 for s in (m.get("skills") or []) if str(s).startswith("compound-engineering:"))
    cu = lines(run / "context_usage.json")
    c = json.loads(cu[-1]) if cu else {}
    r.update({
        "always_on": m.get("result_input_all"), "tokens_all": m.get("tokens_all"),
        "total_cost_usd": m.get("total_cost_usd"),
        "valid": m.get("num_turns") == 1 and m.get("is_error") is False and m.get("terminal_reason") == "completed",
        "context_total_tokens": c.get("total_tokens"),
        "context_categories": {x["name"]: x["tokens"] for x in c.get("categories", [])},
        "context_result": (lambda z: {k: z.get(k) for k in ("subtype", "is_error", "num_turns", "local_command", "total_cost_usd")})(json.loads(lines(run / "context_result.json")[-1])) if lines(run / "context_result.json") else None,
    })
    r.update(tool_counts(run))
    return r


def r1_record(run):
    m = load(run / "metrics.json")
    exitc = (lines(run / "r1.exit") or [None])[0]
    if not m:
        return {"run": run.name, "arm": run.name.split("-")[1], "with": run.name.split("-")[1] == WITH_ARM,
                "void": f"no init or result event: the agent did not start (exit {exitc})", "guard": guard(run)}
    g = load(run / "grade" / "grade.json") or {}
    s = load(run / "summary.json") or {}
    r = common(run, m)
    r.update({
        "void": (lines(run / "invalid.txt") or [None])[0], "exit": exitc,
        "passed": g.get("passed"), "grade": {k: g.get(k) for k in ("tests_unchanged_rc", "apply_rc", "ruff_check_rc", "ruff_format_rc", "pyright_rc", "pytest_rc", "pytest_tail", "pyright_tail", "outside_tracked", "outside_untracked", "new_commits")},
        "files_changed": sorted(x.split("\t", 1)[-1] for x in (g.get("allowed_changed") or "").split(",") if x),
        "tokens_all": m.get("tokens_all"), "duration_s": round((m.get("duration_ms") or 0) / 1000, 1),
        "wall_s": s.get("wall_s"), "total_cost_usd": m.get("total_cost_usd"),
        "new_ce_tmp_entries": len(lines(run / "tmp-ce-new.txt")), "refs_from_run": len(lines(run / "refs-from-run.txt")),
        "new_home_entries": len(lines(run / "home-new.txt")),
    })
    r.update(tool_counts(run))
    return r


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    ok = [ok_record(p) for p in sorted(root.glob("s2-[ab]-k[0-9]"))]
    r1 = [r1_record(p) for p in sorted(root.glob("s[23]-[ab]-[0-9]"))]
    vok = [r for r in ok if r["valid"] and not r["containment_flags"]]
    w = [r["always_on"] for r in vok if r["with"]]
    wo = [r["always_on"] for r in vok if not r["with"]]
    vr1 = [r for r in r1 if not r.get("void")]
    rw = [r for r in vr1 if r["with"]]
    rwo = [r for r in vr1 if not r["with"]]
    mw, mwo = med(w), med(wo)
    tw, two = med([r["tokens_all"] for r in rw]), med([r["tokens_all"] for r in rwo])
    pw, pwo = sum(1 for r in rw if r["passed"]), sum(1 for r in rwo if r["passed"])
    summary = {
        "always_on": {"with_runs": w, "without_runs": wo, "median_with": mw, "median_without": mwo,
                      "delta": mw - mwo, "delta_share_of_without": round((mw - mwo) / mwo, 4),
                      "per_session_estimate": (mw - mwo) * med([r["num_turns"] for r in rwo])},
        "r1": {
            "with": {"passed": pw, "valid_runs": len(rw), "tokens": [r["tokens_all"] for r in rw], "median_tokens": tw,
                     "median_turns": med([r["num_turns"] for r in rw]), "median_duration_s": med([r["duration_s"] for r in rw]),
                     "cost_usd_sum": round(sum(r["total_cost_usd"] for r in rw), 2)},
            "without": {"passed": pwo, "valid_runs": len(rwo), "tokens": [r["tokens_all"] for r in rwo], "median_tokens": two,
                        "median_turns": med([r["num_turns"] for r in rwo]), "median_duration_s": med([r["duration_s"] for r in rwo]),
                        "cost_usd_sum": round(sum(r["total_cost_usd"] for r in rwo), 2)},
            "median_tokens_with_vs_without": round((tw - two) / two, 4),
            "voids": [r["run"] for r in r1 if r.get("void")],
        },
        "guard_calls": sum(r["guard"]["calls"] for r in ok + r1), "guard_all_down": all(r["guard"]["all_down"] for r in ok + r1),
    }
    cond1 = len(rw) >= 3 and pw >= 2 and pwo <= 1
    cond2 = pw >= 2 and pwo >= 2 and tw <= 0.75 * two
    viol = sum(1 for r in ok + vr1 if r.get("containment_flags"))
    summary["rule"] = {"condition_1": cond1, "condition_2": cond2, "always_on_within_cap": (mw - mwo) <= RULE_CAP,
                       "containment_violations": viol, "extension_triggered": abs(pw - pwo) == 1 or (pw == 2 and pwo == 2),
                       "result": "adopt" if (cond1 or (cond2 and (mw - mwo) <= RULE_CAP)) and viol == 0 else "not adopted"}
    det = details(root)
    summary["always_on"]["estimates_against_delta"] = {
        "plugin_details": det["always_on_estimate"], "plugin_details_without_manual_only": det["always_on_estimate_without_manual_only"]}
    doc = {"adr": "0006", "built_by": "0006_aggregate.py", "plugin_check": det, "grader_check": grader_check(root),
           "always_on_runs": ok, "r1_runs": r1, "summary": summary}
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
