# Published copy (docs/adr/data/0007_run_summary.py): the operator's user name in /home/<user> is written
# as 'owner' (same length). Otherwise byte for byte the file that ran.
"""Summarise one `codex exec --json` run: tokens, calls, item kinds and containment patterns.

usage: python3 -I run_summary.py <events.jsonl> <main rollout.jsonl> [sub-agent rollout.jsonl ...]
Prints one JSON object. Never prints command text, tool output or account fields: only
counts, pattern names and token numbers.
"""

import json
import os
import re
import sys
from collections import Counter

OWN_WT = os.environ.get("OWN_WT", "/nonexistent")
PATTERNS = {
    "jts_dir": re.compile(r"(~|/home/owner|\$HOME|HOME\b[^\n]{0,20})/Jts|\bJts/"),
    "main_checkout": re.compile(r"/home/owner/src/meridian(?![-\w])|~/src/meridian(?![-\w])"),
    "other_runs": re.compile(r"meridian-worktrees|meridian-ab/(?!0007/wt/)|meridian-ab/0007/wt/(?!" + re.escape(OWN_WT.rsplit("/", 1)[-1]) + r"\b)"),
    "own_out_dir": re.compile(r"meridian-ab/0007/(out|notes|briefs|key|fh|market|homes)"),
    "fix_commit": re.compile(r"39cb68e|git\s+log\s+[^\n]*--all|git\s+fetch|git\s+remote"),
    "lane_or_gateway": re.compile(r"ibkr_paper|ib_probe|boundary\s+contract|ibgateway|sandbox_lane|:4002\b|\b4002\b|alpaca", re.I),
    "secrets": re.compile(r"auth\.json|\.credentials\.json|\.ssh/|\.gnupg|\.env\b|\.npmrc|\.dsh/|\.gemini/"),
    "risk_or_contract": re.compile(r"\brisk/|\.contract\.json"),
    "network": re.compile(r"\bcurl\b|\bwget\b|https?://", re.I),
}


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def rollout_stats(rows):
    calls = Counter()
    inputs = []
    outputs = []
    usage_records = []
    token_counts = 0
    last_total = None
    meta = {}
    for r in rows:
        t, p = r.get("type"), r.get("payload") or {}
        if t == "session_meta":
            meta = {"cli_version": p.get("cli_version"), "source": p.get("source")}
        elif t == "turn_context":
            meta.setdefault("model", p.get("model"))
            meta.setdefault("effort", p.get("effort") or p.get("reasoning_effort"))
            sp = p.get("sandbox_policy")
            meta.setdefault("sandbox", sp.get("type") if isinstance(sp, dict) else sp)
            meta.setdefault("approval", p.get("approval_policy"))
        elif t == "response_item":
            pt = p.get("type")
            if pt in ("custom_tool_call", "function_call", "local_shell_call"):
                calls[p.get("name") or pt] += 1
                inputs.append(json.dumps(p.get("input") or p.get("arguments") or p.get("action") or "", ensure_ascii=False))
            elif pt in ("custom_tool_call_output", "function_call_output"):
                outputs.append(json.dumps(p.get("output") or "", ensure_ascii=False))
        elif t == "token_usage_record":
            usage_records.append(p.get("usage") or {})
        elif t == "event_msg" and p.get("type") == "token_count":
            info = p.get("info") or {}
            if info:
                token_counts += 1
                last_total = info.get("total_token_usage") or last_total
    return meta, calls, inputs, outputs, usage_records, token_counts, last_total


def sum_usage(records):
    total = Counter()
    for u in records:
        for k, v in u.items():
            if isinstance(v, (int, float)):
                total[k] += v
    return dict(total)


events = load(sys.argv[1])
ev_usage = [e.get("usage") for e in events if e.get("type") == "turn.completed"]
ev_items = Counter(e.get("item", {}).get("type") for e in events if e.get("type") == "item.completed")
ev_errors = [e.get("type") for e in events if e.get("type") in ("turn.failed", "error")]
ev_cmds = [json.dumps(e.get("item", {}).get("command", ""), ensure_ascii=False) for e in events
           if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "command_execution"]

main = load(sys.argv[2])
meta, calls, inputs, outputs, recs, tcount, last_total = rollout_stats(main)
subs = []
for path in sys.argv[3:]:
    m2, c2, i2, o2, r2, t2, lt2 = rollout_stats(load(path))
    subs.append({"meta": m2, "calls": dict(c2), "usage_records": len(r2), "usage_sum": sum_usage(r2),
                 "token_count_events": t2, "last_total": lt2})
    inputs += i2
    outputs += o2

hits_in = {k: sum(len(p.findall(s)) for s in inputs + ev_cmds) for k, p in PATTERNS.items()}
hits_out = {k: sum(len(p.findall(s)) for s in outputs) for k, p in PATTERNS.items()
            if k in ("jts_dir", "main_checkout", "other_runs", "fix_commit", "secrets")}
print(json.dumps({
    "events_turn_completed_usage": ev_usage,
    "events_item_kinds": dict(ev_items),
    "events_errors": ev_errors,
    "rollout_meta": meta,
    "rollout_tool_calls": dict(calls),
    "rollout_usage_records": len(recs),
    "rollout_usage_sum": sum_usage(recs),
    "rollout_token_count_events": tcount,
    "rollout_last_total": last_total,
    "subagents": subs,
    "pattern_hits_in_calls": {k: v for k, v in hits_in.items() if v},
    "pattern_hits_in_outputs": {k: v for k, v in hits_out.items() if v},
}, indent=1, default=str))
