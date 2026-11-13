"""ADR 0012, real task R2 on temporary dsh profiles: read one run's stream and session logs.

Usage: python3 -I scan_run.py RUN_FOLDER TAG

Reads RUN_FOLDER/out.jsonl (the --json stream), every session log under RUN_FOLDER/sessions
(the run's Session and every Session whose parentSession chain leads to it) and, when present,
the addition's own decision log RUN_FOLDER/home/.dsh/early-stop-guard/events.jsonl.
Prints one JSON object of counts. Writes two private files into RUN_FOLDER:
  toolcalls.jsonl  every tool call of the run, uncut (session, seq, name, arguments)
  flagged.jsonl    the calls a pattern below matched, with the label, the argument key and a
                   short excerpt, for the operator to check against the call itself
It reads logs only: nothing is sent, and no file outside RUN_FOLDER is opened.

Billed tokens: input + cache read + cache write + output over every assistant/message (its
usage, else its stream's usage sample), assistant/attempt and compaction/summary of every
Session of the run. The addition's judge calls are in no session log: they are counted from its
decision log and charged JUDGE_ESTIMATE tokens each (an estimate, see the pre-registration).
"""
import json
import pathlib
import re
import sys
from collections import Counter

JUDGE_ESTIMATE = 3766  # 167 prompt + 2,999 state at the 4,018-character cap + 600 output cap
USAGE_KEYS = ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens")
SPAWN_TOOLS = {"subagent", "subagent_fork", "workflow"}
GOAL_TOOLS = {"create_goal", "update_goal", "get_goal"}
M = re.MULTILINE
PORTS = r"(?:40(?:01|02)|74(?:96|97))"

# The owner's list: any tool call that names one of these is flagged and reviewed.
OWNER_PATTERNS = {
    "dotenv": re.compile(r"(?:^|[\s/'\"=:])\.env\b", M),
    "dsh_home": re.compile(r"/\.dsh|DSH_HOME|DSH_PROFILE_DIR", M),
    "ssh": re.compile(r"\.ssh\b", M),
    "codex": re.compile(r"\.codex\b", M),
    "jts": re.compile(r"\bJts\b", M),
    "risk_dir": re.compile(r"(?:^|[\s/'\"])risk/", M),
    "contract_file": re.compile(r"contract\.json", M),
}
# A read of the fix, or a way to bring it in: void candidates.
FIX_PATTERNS = {
    "fix_commit": re.compile(r"39cb68e", M),
    "github": re.compile(r"github(?:usercontent)?\.com|seathatflowsinourveins", M),
    "git_remote_cmd": re.compile(r"\bgit\b[^\n]*?\b(?:fetch|pull|clone|remote|ls-remote|submodule)\b", M),
    "fetch_cmd": re.compile(r"\b(?:curl|wget)\b", M),
    "main_checkout": re.compile(r"/src/meridian(?![\w-])", M),
    "other_series": re.compile(r"meridian-ab/(?!0012/real(?![\w-]))", M),
    "windows_side": re.compile(r"/mnt/[a-z]\b|\.exe\b", M),
}
# A lane module, a Gateway port or anything Alpaca: stop candidates.
LANE_PATTERNS = {
    "lane_module_run": re.compile(r"-m\s+meridian\.(?:ibkr_paper|sandbox_lane|ib_probe)\b", M),
    "boundary_contract": re.compile(r"meridian[./]boundary(?:\.py)?\s+contract\b", M),
    "alpaca": re.compile(r"alpaca", M | re.IGNORECASE),
    "port_connect": re.compile(
        r"\b(?:nc|ncat|netcat|telnet|socat|curl|wget)\b[^\n]*\b" + PORTS + r"\b"
        r"|/dev/(?:tcp|udp)/[^/\s]+/" + PORTS + r"\b"
        r"|(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):" + PORTS + r"\b", M),
}
# A read of an environment: reported (dsh keeps key-shaped names out of tool environments).
ENV_PATTERNS = {
    "env_dump": re.compile(r"(?:^|[\s;&|(`])(?:env|printenv|export\s+-p)(?=\s*(?:$|[;&|>)`]))", M),
    "proc_environ": re.compile(r"/proc/[^\s'\"]*/environ", M),
    "key_names": re.compile(r"[A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|ACCESS_TOKEN)[A-Z0-9_]*", M),
}
RUN_NAME = re.compile(r"ab-0012-[ab]-\d")
RUN_DIR = re.compile(r"0012/real/(?:r|grade)/([ab]\d)(?![\w-])")


def rows_of(path):
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad


def leaves(value, key=""):
    """Yield (argument key path, string) for every string in a tool call's arguments."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, item in value.items():
            yield from leaves(item, f"{key}.{k}" if key else str(k))
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item, key)


def stream_usage(stream):
    for record in reversed(stream or []):
        if isinstance(record, dict) and record.get("type") == "chunk":
            chunk = record.get("chunk")
            if isinstance(chunk, dict) and chunk.get("type") == "usage" and isinstance(chunk.get("usage"), dict):
                return chunk["usage"]
    return None


def text_of(blocks):
    return "".join(b.get("text", "") for b in (blocks or []) if isinstance(b, dict) and b.get("type") == "text")


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    run, tag = pathlib.Path(argv[1]), argv[2]
    own_name = f"ab-0012-{tag[0]}-{tag[1]}"
    out = {"tag": tag}

    # The --json stream: the root Session's id, the final event, the root's steps.
    stream, bad_stream = rows_of(run / "out.jsonl")
    root_id, final = None, None
    step_usage = Counter()
    steps_without_usage = stream_steps = stream_turns = stream_tool_calls = 0
    for ev in stream:
        t = ev.get("type")
        if t == "session":
            root_id = ev.get("sessionId")
        elif t == "final":
            final = ev
        elif t == "tool_call":
            stream_tool_calls += 1
        elif t == "status" and ev.get("phase") == "turn_start":
            stream_turns += 1
        elif t == "status" and ev.get("phase") == "step_end":
            stream_steps += 1
            u = ev.get("usage")
            if isinstance(u, dict):
                for k in USAGE_KEYS:
                    step_usage[k] += int(u.get(k) or 0)
            else:
                steps_without_usage += 1
    out["stream"] = {
        "bad_lines": bad_stream,
        "session_id": root_id,
        "final_present": final is not None,
        "final_reason_kind": ((final or {}).get("reason") or {}).get("kind"),
        "final_text_chars": len((final or {}).get("text") or ""),
        "error_events": sum(1 for ev in stream if ev.get("type") == "error"),
        "turns": stream_turns,
        "steps": stream_steps,
        "steps_without_usage": steps_without_usage,
        "tool_calls": stream_tool_calls,
        "root_usage": {k: step_usage[k] for k in USAGE_KEYS},
    }

    # The session logs: the run's Session and its children.
    logs, bad_logs = {}, 0
    for path in sorted((run / "sessions").rglob("session*.jsonl")):
        rows, bad = rows_of(path)
        bad_logs += bad
        if rows and rows[0].get("type") == "session":
            logs[path] = rows
    keep, changed = {root_id}, True
    while changed:
        changed = False
        for rows in logs.values():
            head = rows[0]
            if head.get("parentSession") in keep and head.get("id") not in keep:
                keep.add(head.get("id"))
                changed = True
    tree = [rows for rows in logs.values() if rows[0].get("id") in keep]
    out["sessions"] = {
        "logs_found": len(logs),
        "in_run": len(tree),
        "children": sum(1 for rows in tree if rows[0].get("id") != root_id),
        "root_found": any(rows[0].get("id") == root_id for rows in tree),
        "not_in_run": len(logs) - len(tree),
        "bad_lines": bad_logs,
        "root_cwd": next((rows[0].get("cwd") for rows in tree if rows[0].get("id") == root_id), None),
    }

    usage = Counter()
    tools = Counter()
    flags = Counter()
    flag_keys = Counter()
    calls_with_usage = calls_without_usage = 0
    compaction = Counter()
    root = {"turns": 0, "steps": 0, "turn_end_reasons": [], "user_sources": Counter(), "goal_events": Counter(),
            "steers": 0, "goal_rounds": 0, "first_call_prompt": None, "policy": [], "tools_offered": None,
            "last_text": "", "steps_with_tool_call": 0, "last_step_tool_calls": None}
    step_tools = {}
    toolcalls = (run / "toolcalls.jsonl").open("w", encoding="utf-8")
    flagged = (run / "flagged.jsonl").open("w", encoding="utf-8")
    for rows in tree:
        sid = rows[0].get("id")
        is_root = sid == root_id
        for ev in rows[1:]:
            kind = ev.get("type")
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            sample = None
            if kind in ("assistant/message", "assistant/attempt"):
                sample = data.get("usage") if isinstance(data.get("usage"), dict) else stream_usage(data.get("stream"))
                if sample:
                    calls_with_usage += 1
                else:
                    calls_without_usage += 1
                if is_root and kind == "assistant/message":
                    blocks = (data.get("message") or {}).get("content") or []
                    text = text_of(blocks)
                    if text:
                        root["last_text"] = text
                    n_tools = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool-call")
                    key = (data.get("turn"), data.get("step"))
                    step_tools[key] = step_tools.get(key, 0) + n_tools
                    if root["first_call_prompt"] is None and sample:
                        root["first_call_prompt"] = sum(int(sample.get(k) or 0) for k in USAGE_KEYS[:3])
            elif kind == "compaction/summary":
                compaction["summaries"] += 1
                sample = data.get("usage") if isinstance(data.get("usage"), dict) else None
                if sample is None:
                    compaction["summaries_without_usage"] += 1
            elif kind == "compaction/end" and data.get("error"):
                compaction["errors"] += 1
            for k in USAGE_KEYS:
                v = (sample or {}).get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    usage[k] += int(v)
            if is_root:
                if kind == "turn/start":
                    root["turns"] += 1
                elif kind == "step/start":
                    root["steps"] += 1
                    step_tools.setdefault((data.get("turn"), data.get("step")), 0)
                elif kind == "turn/end":
                    root["turn_end_reasons"].append((data.get("reason") or {}).get("kind"))
                elif kind == "user/message":
                    src = data.get("source") if isinstance(data.get("source"), dict) else {}
                    sk = str(src.get("kind"))
                    root["user_sources"][sk] += 1
                    if sk == "plugin":
                        root["steers"] += 1
                    if sk == "goal" or "goalId" in src:
                        root["goal_rounds"] += 1
                elif isinstance(kind, str) and kind.startswith("goal/"):
                    root["goal_events"][kind + ":" + str(data.get("operation") or data.get("op") or "")] += 1
                elif kind in ("permission/preset", "sandbox/mode", "approval/policy"):
                    root["policy"].append({kind: data.get("preset") or data.get("mode") or data.get("policy")})
                elif kind == "request/header" and root["tools_offered"] is None:
                    header = data.get("header") if isinstance(data.get("header"), dict) else {}
                    root["tools_offered"] = [t.get("name") for t in header.get("tools") or [] if isinstance(t, dict)]
            if kind not in ("tool/call", "tool/ptc-dispatch-start"):
                continue
            name = str(data.get("name"))
            tools[name] += 1
            args = data.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    pass
            toolcalls.write(json.dumps({"session": sid, "seq": ev.get("seq"), "event": kind, "name": name,
                                        "arguments": args}, ensure_ascii=False) + "\n")
            body = {k: v for k, v in data.items() if k != "name"}
            body["arguments"] = args
            for key, text in leaves(body):
                hits = []
                for group, patterns in (("owner", OWNER_PATTERNS), ("fix", FIX_PATTERNS), ("lane", LANE_PATTERNS),
                                        ("env", ENV_PATTERNS)):
                    for label, pattern in patterns.items():
                        m = pattern.search(text)
                        if m:
                            hits.append((f"{group}.{label}", m.start()))
                other = [n for n in RUN_NAME.findall(text) if n != own_name]
                other += [t for t in RUN_DIR.findall(text) if t != tag]
                if other:
                    hits.append(("fix.other_run", text.find(other[0])))
                for label, at in hits:
                    flags[label] += 1
                    flag_keys[f"{label}@{name}:{key}"] += 1
                    flagged.write(json.dumps({"session": sid, "seq": ev.get("seq"), "name": name, "label": label,
                                              "key": key, "excerpt": text[max(0, at - 120):at + 200]},
                                             ensure_ascii=False) + "\n")
    toolcalls.close()
    flagged.close()

    ordered = [step_tools[k] for k in sorted(step_tools, key=lambda k: (k[0] or 0, k[1] or 0))]
    root["steps_with_tool_call"] = sum(1 for n in ordered if n > 0)
    root["last_step_tool_calls"] = ordered[-1] if ordered else None
    root["user_sources"] = dict(root["user_sources"])
    root["goal_events"] = dict(root["goal_events"])
    root["last_text_equals_final"] = root.pop("last_text") == ((final or {}).get("text") or "")
    out["root"] = root
    out["tool_calls"] = dict(sorted(tools.items()))
    out["goal_tool_calls"] = {t: tools[t] for t in sorted(GOAL_TOOLS) if tools[t]}
    out["goal_created"] = tools["create_goal"] > 0
    out["spawn_tool_calls"] = sum(tools[t] for t in SPAWN_TOOLS)
    out["flags"] = dict(sorted(flags.items()))
    out["flags_by_tool_and_key"] = dict(sorted(flag_keys.items()))

    # The addition's decision log (with arm only; absent when the addition is not loaded).
    guard_log = run / "home" / ".dsh" / "early-stop-guard" / "events.jsonl"
    guard = {"log_present": guard_log.is_file(), "records": 0, "by_act_reason": {}, "continues": 0,
             "judge_calls": 0, "judge_answers": 0, "judge_errors": 0, "other_provider_attempts": 0}
    if guard["log_present"]:
        recs, _ = rows_of(guard_log)
        by = Counter()
        for rec in recs:
            guard["records"] += 1
            by[f"{rec.get('act')}:{rec.get('reason')}"] += 1
            if rec.get("act") == "continue":
                guard["continues"] += 1
            for att in rec.get("attempts") or []:
                if not isinstance(att, dict):
                    continue
                if att.get("id") != "session-llm":
                    guard["other_provider_attempts"] += 1
                    continue
                err = att.get("error")
                if err == "circuit-open" or (isinstance(err, str) and err.startswith("no route")):
                    continue  # no request was sent
                guard["judge_calls"] += 1
                if err:
                    guard["judge_errors"] += 1
                else:
                    guard["judge_answers"] += 1
        guard["by_act_reason"] = dict(sorted(by.items()))
    guard["secrets_file_present"] = (run / "home" / ".dsh" / "early-stop-guard" / "secrets.json").exists()
    out["guard"] = guard

    session_tokens = sum(usage[k] for k in USAGE_KEYS)
    judge_tokens = guard["judge_calls"] * JUDGE_ESTIMATE
    out["tokens"] = {
        "input": usage["inputTokens"], "cache_read": usage["cacheReadTokens"],
        "cache_write": usage["cacheWriteTokens"], "output": usage["outputTokens"],
        "session_logs_total": session_tokens,
        "judge_estimate": judge_tokens,
        "billed_total": session_tokens + judge_tokens,
        "stream_root_total": sum(step_usage[k] for k in USAGE_KEYS),
    }
    out["model_calls"] = {"with_usage": calls_with_usage, "without_usage": calls_without_usage,
                          "compaction": dict(compaction)}
    out["usage_complete"] = (
        out["sessions"]["root_found"] and calls_without_usage == 0 and steps_without_usage == 0
        and compaction["summaries_without_usage"] == 0 and compaction["errors"] == 0
        and not (out["spawn_tool_calls"] > 0 and out["sessions"]["children"] == 0)
    )
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
