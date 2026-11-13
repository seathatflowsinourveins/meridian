#!/usr/bin/env python3
"""Aggregate of the ADR 0009 real-task series. Usage: python3 -I aggregate.py EV WITH_LETTER

Reads each run folder's exit, duration, usage, grade and scan files (written by run_dsh.sh,
run_codex.sh, after_run.sh and the grader) and prints one JSON object with per-run rows, totals
and the pre-registered rule applied to them. It reads no session text and no credential file.
WITH_LETTER (a or b) is the arm key, kept outside the run folders.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ORDER = [
    "ab-0009-a-1", "ab-0009-b-1", "ab-0009-b-2", "ab-0009-a-2", "ab-0009-a-3", "ab-0009-b-3",
    "ab-0009-c-1", "ab-0009-c-2", "ab-0009-c-3",
]
CHECKS = ["smoke-c", "smoke-c2", "smoke-a", "smoke-b"]


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def text(p: Path) -> str | None:
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def row(ev: Path, tag: str, with_letter: str) -> dict:
    d = ev / tag
    letter = tag.split("-")[2] if tag.startswith("ab-") else None
    arm = {"c": "codexdirect"}.get(letter, "with" if letter == with_letter else "without") if letter else "check"
    ds = load(d / "usage.sessions.json")
    cx = load(d / "usage.codex.json")
    first = load(d / "usage.first-call.json")
    g = load(d / "graded.json") or {}
    calls = d / "r" / "toolcalls.jsonl"
    names: dict[str, int] = {}
    if calls.is_file():
        for line in calls.read_text(encoding="utf-8").splitlines():
            n = json.loads(line).get("name", "?")
            names[n] = names.get(n, 0) + 1
    exit_code = int((text(d / "r" / "exit.txt") or "exit=-1").split("=")[1])
    out = {
        "run": tag,
        "arm": arm,
        "started": text(d / "started"),
        "exit": exit_code,
        "duration_s": float(text(d / "duration_s") or 0),
        "turn_completed": g.get("turn_completed"),
        "void": g.get("void"),
        "target_reported_in_answer": g.get("target_reported", g.get("target_reported_in_answer")),
        "passed": g.get("passed"),
        "findings": g.get("counts"),
        "deepseek": None if ds is None else {
            "billed_tokens": ds["billed"], "model_calls": ds["model_calls"],
            "calls_without_usage": ds["calls_without_usage"], "turns": ds["turns"], "steps": ds["steps"],
            "input_uncached": ds["input"], "cache_read": ds["cache_read"], "cache_write": ds["cache_write"],
            "output": ds["output"], "compactions": ds["compactions"],
            "first_call_prompt_tokens": None if first is None else first["first_call_prompt_tokens"],
        },
        "codex": None if cx is None else {
            "tokens_input_plus_output": cx.get("codex_tokens_input_plus_output"),
            "cached_input": cx.get("cached_input"), "reasoning_output": cx.get("reasoning_output"),
            "runs": cx.get("codex_runs", cx.get("turns")),
        },
        "tool_calls": names or None,
        "addition_acted": g.get("addition_acted") if arm == "with" else None,
        "checkout_unchanged": g.get("checkout_unchanged"),
        "gitleaks_findings": len(load(d / "gitleaks.json") or []),
        "flags_reviewed": len((text(d / "flags.txt") or "").splitlines()),
    }
    return out


def main() -> int:
    ev, with_letter = Path(sys.argv[1]), sys.argv[2]
    runs = [row(ev, t, with_letter) for t in ORDER if (ev / t / "r").is_dir()]
    checks = [row(ev, t, with_letter) for t in CHECKS if (ev / t / "r").is_dir()]
    arms: dict[str, dict] = {}
    for arm in ("without", "with", "codexdirect"):
        rs = [r for r in runs if r["arm"] == arm]
        counted = [r for r in rs if not r["void"]]
        arms[arm] = {
            "runs": len(rs),
            "void": len(rs) - len(counted),
            "counted": len(counted),
            "passed": sum(1 for r in counted if r["passed"]),
            "defect_reported_in_counted_runs": sum(1 for r in counted if r["target_reported_in_answer"]),
            "defect_reported_in_any_answer": sum(1 for r in rs if r["target_reported_in_answer"]),
            "false_findings_in_counted_runs": sum((r["findings"] or {}).get("false", 0) for r in counted),
            "real_findings_in_counted_runs": [(r["findings"] or {}).get("real") for r in counted],
            "median_duration_s": statistics.median(r["duration_s"] for r in rs) if rs else None,
            "deepseek_billed_tokens": [r["deepseek"]["billed_tokens"] for r in rs if r["deepseek"]],
            "codex_tokens": [r["codex"]["tokens_input_plus_output"] for r in rs if r["codex"]],
            "first_call_prompt_tokens": [r["deepseek"]["first_call_prompt_tokens"] for r in rs if r["deepseek"]],
        }
    w, wo, cd = arms["with"], arms["without"], arms["codexdirect"]
    delta = None
    if w["first_call_prompt_tokens"] and wo["first_call_prompt_tokens"]:
        delta = statistics.median(w["first_call_prompt_tokens"]) - statistics.median(wo["first_call_prompt_tokens"])
    clauses = {
        "with_reports_defect_in_at_least_2_of_3": {"value": f'{w["defect_reported_in_counted_runs"]} of {w["runs"]} ({w["void"]} void, counted against the arm)', "met": w["defect_reported_in_counted_runs"] >= 2},
        "without_reports_defect_in_at_most_1_of_3": {"value": f'{wo["defect_reported_in_counted_runs"]} of {wo["runs"]} ({wo["void"]} void, not counted)', "met": wo["defect_reported_in_counted_runs"] <= 1},
        "with_at_most_one_more_false_finding_than_without": {"value": f'{w["false_findings_in_counted_runs"]} against {wo["false_findings_in_counted_runs"]}', "met": w["false_findings_in_counted_runs"] <= wo["false_findings_in_counted_runs"] + 1},
        "codexdirect_at_most_1_of_3_or_more_false_findings_than_with": {"value": f'{cd["defect_reported_in_counted_runs"]} of {cd["runs"]}, {cd["false_findings_in_counted_runs"]} false against {w["false_findings_in_counted_runs"]}', "met": cd["defect_reported_in_counted_runs"] <= 1 or cd["false_findings_in_counted_runs"] > w["false_findings_in_counted_runs"]},
        "always_on_delta_at_most_2500_provider_tokens": {"value": delta, "met": delta is not None and delta <= 2500},
    }
    total_ds = sum(r["deepseek"]["billed_tokens"] for r in runs + checks if r["deepseek"])
    total_cx = sum(r["codex"]["tokens_input_plus_output"] or 0 for r in runs + checks if r["codex"])
    out = {
        "adr": "0009",
        "task": "R4",
        "runs": runs,
        "checks_before_the_pre_registration": checks,
        "arms": arms,
        "extension": {
            "applies": abs(w["passed"] - wo["passed"]) == 1 or (w["passed"] == 2 and wo["passed"] == 2),
            "passed_with": w["passed"], "passed_without": wo["passed"],
        },
        "rule_clauses_from_counts": clauses,
        "totals": {"deepseek_billed_tokens": total_ds, "codex_tokens_input_plus_output": total_cx,
                   "deepseek_runs_only": sum(r["deepseek"]["billed_tokens"] for r in runs if r["deepseek"]),
                   "codex_runs_only": sum(r["codex"]["tokens_input_plus_output"] or 0 for r in runs if r["codex"])},
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
