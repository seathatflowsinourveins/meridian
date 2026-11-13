"""Scan one Codex 0.167.2 run's rollouts and events for void reasons, hook effects and tool calls.

Usage: python3 -I scan_run.py EVENTS_JSONL SELF_CLONE_NAME ROLLOUT [ROLLOUT ...]
Prints JSON: tool-call counts, flagged tool inputs (first 240 characters each, for manual review),
OMX hook-text counts and model request counts. Reads only its arguments.
"""

import json
import re
import sys

events_path, self_name, rollouts = sys.argv[1], sys.argv[2], sys.argv[3:]

FLAGS = [
    ("git_history", re.compile(r"\bgit\b[^\n]{0,80}\b(log|show|reflog|rev-list|cat-file|blame|whatchanged|for-each-ref|fsck|ls-tree|branch\s+-a|branch\s+-r|stash|switch|checkout|restore\s+--source|diff\s+[^\n]*(origin|main|5d51c9c|HEAD[~^@]))\b")),
    ("fix_sha", re.compile(r"5d51c9c")),
    ("all_refs", re.compile(r"--all\b|origin/|refs/")),
    ("main_checkout", re.compile(r"src/meridian(?=[/\s'\"\)\]]|$)")),
    ("other_run", re.compile(r"meridian-ab|ab-\d{4}-(?!" + re.escape(self_name.split("ab-0008-")[-1]) + r"\b)[\w-]+")),
    ("network", re.compile(r"\b(curl|wget|git\s+(fetch|pull|clone|push)|pip\s+install|uv\s+(add|pip\s+install)|npm\s+(install|i)\b|https?://)")),
    ("forbidden", re.compile(r"ibkr_paper|ib_probe|boundary\s+contract|\b4002\b|alpaca", re.I)),
    ("tests_or_agents_write", re.compile(r"(>\s*|tee\s+|sed\s+-i[^\n]*|apply_patch[^\n]*)(tests/|AGENTS\.md)")),
]
HOOK_TEXTS = {
    "session_start_exec_env": "[Execution environment]",
    "stop_auto_nudge": "OMX native Stop",
    "posttool_block": "The Bash output indicates a command/setup failure",
    "prompt_triage": "OMX native UserPromptSubmit triage",
}


def jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


inputs = []  # (source, name, text)
tool_counts = {}
hook_counts = {k: 0 for k in HOOK_TEXTS}
requests = []
for ro in rollouts:
    rows = jsonl(ro)
    nreq = sum(1 for r in rows if r.get("type") == "token_usage_record")
    requests.append(nreq)
    for r in rows:
        if r.get("type") != "response_item":
            continue
        p = r.get("payload") or {}
        t = p.get("type")
        if t in ("custom_tool_call", "function_call", "local_shell_call"):
            name = p.get("name") or t
            tool_counts[name] = tool_counts.get(name, 0) + 1
            text = p.get("input") or p.get("arguments") or json.dumps(p.get("action") or {})
            inputs.append((ro.rsplit("/", 1)[-1][-20:], name, str(text)))
        if t == "message" and p.get("role") in ("developer", "user"):
            for c in p.get("content") or []:
                txt = c.get("text") or ""
                for k, needle in HOOK_TEXTS.items():
                    if needle in txt:
                        hook_counts[k] += 1

for e in jsonl(events_path):
    it = e.get("item") or {}
    if e.get("type") == "item.completed" and it.get("type") == "command_execution":
        inputs.append(("events", "command_execution", str(it.get("command"))))

flagged = []
for src, name, text in inputs:
    for label, rx in FLAGS:
        m = rx.search(text)
        if m:
            s = max(0, m.start() - 100)
            flagged.append({"flag": label, "src": src, "tool": name, "snippet": text[s:s + 240]})
print(json.dumps({
    "model_requests_per_rollout": requests,
    "tool_calls": tool_counts,
    "tool_inputs_scanned": len(inputs),
    "hook_text_counts": hook_counts,
    "flagged": flagged,
}, indent=1))
