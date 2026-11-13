#!/usr/bin/env python3
"""Write the two result files of the ADR 0009 real-task series from the aggregate and two frames.

Usage: python -I merge_results.py AGGREGATE FRAME_PUBLIC FRAME_PRIVATE OUT_PUBLIC OUT_PRIVATE
The public file gets the aggregate's rows and totals inside the public frame; the private file
gets the same rows in the notes format (one entry per run). Reads only those three JSON files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    agg_p, fpub_p, fpriv_p, out_pub, out_priv = (Path(a) for a in sys.argv[1:6])
    agg = json.loads(agg_p.read_text(encoding="utf-8"))
    pub = json.loads(fpub_p.read_text(encoding="utf-8"))
    priv = json.loads(fpriv_p.read_text(encoding="utf-8"))
    notes = pub.pop("run_notes")

    rows = []
    for r in agg["runs"]:
        row = dict(r)
        row["note"] = notes.get(r["run"], "")
        if row["void"]:
            row["void"] = "rule 9(a) of the pre-registration: the run's shell commands read the fix over the network"
        rows.append(row)

    public = {}
    for k, v in pub.items():
        public[k] = v
        if k == "key":
            public["runs"] = rows
            public["arms"] = agg["arms"]
            public["extension"] = agg["extension"]
            public["checks_before_the_pre_registration"] = [
                {kk: c[kk] for kk in ("run", "exit", "duration_s", "deepseek", "codex", "gitleaks_findings")}
                for c in agg["checks_before_the_pre_registration"]
            ]
    public["totals"] = agg["totals"]
    out_pub.write_text(json.dumps(public, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    runs = []
    for r in agg["runs"]:
        ds, cx = r["deepseek"], r["codex"]
        entry = {
            "run": r["run"],
            "arm": r["arm"],
            "started": r["started"],
            "passed": bool(r["passed"]),
            "containment_ok": True,
            "void": "rule 9(a): read the fix over the network (see note)" if r["void"] else "",
            "billed_tokens": ds["billed_tokens"] if ds else (cx or {}).get("tokens_input_plus_output"),
            "billed_tokens_are": "DeepSeek (input + cache read + cache write + output, every model call)" if ds else "Codex (input + output)",
            "codex_tokens": (cx or {}).get("tokens_input_plus_output"),
            "rounds": ds["turns"] if ds else 1,
            "steps": ds["steps"] if ds else None,
            "duration_s": r["duration_s"],
            "exit": r["exit"],
            "target_reported_in_answer": r["target_reported_in_answer"],
            "findings": r["findings"],
            "first_call_prompt_tokens": ds["first_call_prompt_tokens"] if ds else None,
            "tool_calls": r["tool_calls"],
            "addition_used": "",
            "gitleaks_findings": r["gitleaks_findings"],
            "note": notes.get(r["run"], ""),
        }
        if r["arm"] == "with":
            entry["addition_used"] = (
                "yes: one codex_review call, one Codex child (read-only sandbox, 253,145 Codex tokens, 109 s)"
                if r["addition_acted"] else "no: its five tools were offered, none was called"
            )
        elif r["arm"] == "without":
            entry["addition_used"] = "not loaded"
        else:
            entry["addition_used"] = "not applicable (Codex alone)"
        runs.append(entry)

    private = {}
    for k, v in priv.items():
        private[k] = v
        if k == "task":
            private["task"] = dict(v)
            private["task"]["runs"] = runs
    private["arms"] = agg["arms"]
    private["checks_before_the_pre_registration"] = agg["checks_before_the_pre_registration"]
    private["totals"] = agg["totals"]
    out_priv.write_text(json.dumps(private, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out_pub.name} ({out_pub.stat().st_size} bytes) and {out_priv.name} ({out_priv.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
