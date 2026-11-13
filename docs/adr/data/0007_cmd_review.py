"""List the commands and web searches of one `codex exec --json` run, for containment review.

usage: python3 -I cmd_review.py <events.jsonl>
Prints each command_execution's command text (cut at 1,200 chars) with its exit code, and each
web_search query or action. Never prints command output.
"""

import json
import re
import sys

RISK = re.compile(r"4002|socket|connect|ib_probe|ibkr_paper|sandbox_lane|boundary\s+contract|"
                  r"/Jts|Jts/|ibgateway|alpaca|auth\.json|\.ssh|\.gnupg|\.env\b|risk/|contract\.json|"
                  r"git\s+fetch|git\s+remote|39cb68e|curl|wget", re.I)
n = 0
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "item.completed":
            continue
        it = e.get("item") or {}
        if it.get("type") == "command_execution":
            n += 1
            cmd = it.get("command") or ""
            hits = sorted(set(m.group(0).lower() for m in RISK.finditer(cmd)))
            print(f"--- cmd {n} exit={it.get('exit_code')} status={it.get('status')} risk_terms={hits}")
            print(cmd[:1200] + (" [...cut]" if len(cmd) > 1200 else ""))
        elif it.get("type") == "web_search":
            q = {k: v for k, v in it.items() if k in ("query", "action")}
            print(f"--- web_search {json.dumps(q, ensure_ascii=False)[:400]}")
