#!/usr/bin/env python3
"""Summarise one `codex exec --json` run of Codex CLI 0.167.2 for an evidence ADR.

Stdlib only. Run inside the distro as:  python3 -I codex_ab_summary.py EVENTS_JSONL CODEX_HOME
Prints one JSON object (numbers and sizes only: no prompt text, no account fields).

Formats read (openai/codex tag rust-v0.167.2):
- EVENTS_JSONL: stdout of `codex exec --json` (codex-rs/exec/src/exec_events.rs):
  thread.started{thread_id}, turn.completed{usage{input_tokens, cached_input_tokens,
  cache_write_input_tokens, output_tokens, reasoning_output_tokens}}, turn.failed, item.*.
  turn.completed.usage is the thread total (event_processor_with_jsonl_output.rs).
- Rollout: $CODEX_HOME/sessions/YYYY/MM/DD/rollout-<local time>-<thread_id>.jsonl
  (codex-rs/rollout/src/recorder.rs). Lines {"timestamp","ordinal"?,"type","payload"} with
  type session_meta | turn_context | response_item | token_usage_record | event_msg | ...
  (codex-rs/history/src/rollout_payload.rs). token_usage_record = one completed Responses
  API response (core/src/session/mod.rs record_response_token_usage).
"""

import glob
import json
import os
import sys

MARKERS = [
    ("agents_md", "# AGENTS.md instructions"),
    ("skills_catalog", "<skills_instructions>"),
    ("plugins_instructions", "<plugins_instructions>"),
    ("recommended_plugins", "<recommended_plugins>"),
    ("apps_instructions", "<apps_instructions>"),
    ("environment_context", "<environment_context>"),
    ("permissions_instructions", "<permissions instructions>"),
    ("collaboration_mode", "<collaboration_mode>"),
    ("multi_agent_mode", "<multi_agent_mode>"),
    ("user_instructions", "<user_instructions>"),
]
USAGE_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"type": "_unparsed", "line": n})
    return out


def usage_sum(records):
    total = {k: 0 for k in USAGE_KEYS}
    for u in records:
        for k in USAGE_KEYS:
            total[k] += int(u.get(k) or 0)
    return total


def rollout_paths(codex_home):
    return sorted(glob.glob(os.path.join(codex_home, "sessions", "*", "*", "*", "rollout-*.jsonl")))


def summarise_rollout(path):
    lines = read_jsonl(path)
    meta = next((x.get("payload", {}) for x in lines if x.get("type") == "session_meta"), {})
    turn_ctx = next((x.get("payload", {}) for x in lines if x.get("type") == "turn_context"), {})
    records = [x.get("payload", {}) for x in lines if x.get("type") == "token_usage_record"]
    counts = [
        x.get("payload", {})
        for x in lines
        if x.get("type") == "event_msg" and x.get("payload", {}).get("type") == "token_count"
    ]
    last_info = next((c.get("info") for c in reversed(counts) if c.get("info")), None) or {}
    # Initial input = every developer/user message and additional_tools item before the
    # model's first output item. The task prompt lands in user_unmarked_text; hook
    # additionalContext has role developer and no marker, so it lands in developer_unmarked_text.
    blocks = {name: 0 for name, _ in MARKERS}
    blocks["developer_unmarked_text"] = 0
    blocks["user_unmarked_text"] = 0
    initial_tools = {"items": 0, "tools": 0, "bytes": 0}
    later_tools = {"items": 0, "tools": 0, "bytes": 0}
    item_types = {}
    initial = True
    for x in lines:
        if x.get("type") != "response_item":
            continue
        p = x.get("payload", {})
        t = p.get("type", "?")
        item_types[t] = item_types.get(t, 0) + 1
        if t == "additional_tools":
            tools = p.get("tools") or []
            bucket = initial_tools if initial else later_tools
            bucket["items"] += 1
            bucket["tools"] += len(tools)
            bucket["bytes"] += len(json.dumps(tools, ensure_ascii=False).encode("utf-8"))
            continue
        if not (t == "message" and p.get("role") in ("developer", "user")):
            initial = False
            continue
        if not initial:
            continue
        for c in p.get("content") or []:
            if c.get("type") != "input_text":
                continue
            text = c.get("text") or ""
            size = len(text.encode("utf-8"))
            hit = next((name for name, m in MARKERS if m in text), None)
            if hit:
                blocks[hit] += size
            else:
                blocks[f"{p.get('role')}_unmarked_text"] += size
    base = (meta.get("base_instructions") or {}).get("text") or ""
    return {
        "path": path,
        "thread_id": meta.get("id"),
        "session_id": meta.get("session_id"),
        "parent_thread_id": meta.get("parent_thread_id"),
        "cli_version": meta.get("cli_version"),
        "originator": meta.get("originator"),
        "model": turn_ctx.get("model"),
        "effort": turn_ctx.get("effort"),
        "approval_policy": turn_ctx.get("approval_policy"),
        "requests": len(records),
        "first_request_usage": (records[0].get("usage") if records else None),
        "sum_request_usage": usage_sum([r.get("usage") or {} for r in records]),
        "last_token_count_total": last_info.get("total_token_usage"),
        "model_context_window": last_info.get("model_context_window"),
        "base_instructions_bytes": len(base.encode("utf-8")),
        "initial_context_block_bytes": blocks,
        "initial_additional_tools": initial_tools,
        "later_additional_tools": later_tools,
        "response_item_types": item_types,
    }


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: codex_ab_summary.py EVENTS_JSONL CODEX_HOME")
    events_path, codex_home = sys.argv[1], sys.argv[2]
    events = read_jsonl(events_path)
    thread_id = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
    completed = [e.get("usage") for e in events if e.get("type") == "turn.completed"]
    failed = [e.get("error", {}).get("message") for e in events if e.get("type") == "turn.failed"]
    item_types = {}
    for e in events:
        if e.get("type") == "item.completed":
            t = (e.get("item") or {}).get("type", "?")
            item_types[t] = item_types.get(t, 0) + 1
    result = {
        "events": {
            "thread_id": thread_id,
            "turn_completed_usage": completed[-1] if completed else None,
            "turn_failed": bool(failed),
            "completed_item_types": item_types,
        },
        "root": None,
        "subagents": [],
        "all_threads_request_usage": None,
        "warnings": [],
    }
    if not thread_id:
        result["warnings"].append("no thread.started event")
        print(json.dumps(result, indent=2))
        return
    paths = rollout_paths(codex_home)
    if glob.glob(os.path.join(codex_home, "sessions", "*", "*", "*", f"rollout-*{thread_id}*.jsonl.zst")):
        result["warnings"].append("a compressed .jsonl.zst rollout exists; decompress it first")
    root_path = next((p for p in paths if p.endswith(f"-{thread_id}.jsonl")), None)
    if not root_path:
        result["warnings"].append("root rollout not found under CODEX_HOME/sessions")
        print(json.dumps(result, indent=2))
        return
    root = summarise_rollout(root_path)
    result["root"] = root
    totals = [root["sum_request_usage"]]
    for p in paths:
        if p == root_path:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                first = json.loads(f.readline() or "{}")
        except (OSError, json.JSONDecodeError):
            continue
        pl = first.get("payload", {}) if first.get("type") == "session_meta" else {}
        if pl.get("session_id") == root.get("session_id") and pl.get("id") != thread_id:
            sub = summarise_rollout(p)
            result["subagents"].append(
                {k: sub[k] for k in ("path", "thread_id", "requests", "sum_request_usage")}
            )
            totals.append(sub["sum_request_usage"])
    result["all_threads_request_usage"] = usage_sum(totals)
    tc = result["events"]["turn_completed_usage"] or {}
    if root["requests"] == 1 and root["first_request_usage"] and tc:
        if int(tc.get("input_tokens", -1)) != int(root["first_request_usage"].get("input_tokens", -2)):
            result["warnings"].append("one request, but turn.completed input_tokens differs from it")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
