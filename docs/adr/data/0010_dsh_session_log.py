"""Read DeepSeek Harness 0.2.2-rc.1 JSONL session logs and report the first request's
always-on context and the provider-reported token usage.

Usage: python3 -I dsh_session_log.py PATH [--root-session ID] [--dump-dir DIR]

PATH is one log file, one Session directory, a project directory
(`<root>/--<project-key>--/`) or a whole Session root. With --root-session, only that Session
and the Sessions whose `parentSession` chain leads to it (its subagents) are read, wherever
they are under PATH; use it with the run's id from the `session` event of the --json file. Files: `session.vN.jsonl.zstd` (the default: concatenated Zstandard
frames) or `session.vN.jsonl` (`compression: none`); the highest N in a directory is the
live generation (packages/session/session-persistence-jsonl/README.md at dsh-v0.2.2-rc.1).
Needs Python 3.14+ for `compression.zstd`.

Row 1 is the physical header ({"type": "session", "id", "delegationDepth", "cwd",
"parentSession", ...}); each later row is {"type", "seq", "time", "data", ...}. The
always-on context of the first request is the `system/message`, the `request/header`
tools, and the `user/message`/`developer/message` events that precede the first
`assistant/message` or `assistant/attempt` (packages/core/session/src/types.ts).

Prints JSON with sizes, SHA-256 digests, source kinds and token counts only. Message text
is written only with --dump-dir (for `diff -ru` between arms); review it before sharing.
"""
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter

try:
    from compression import zstd
except ImportError:  # Python < 3.14
    zstd = None

LOG_NAME = re.compile(r"^session(?:\.v(\d+))?\.jsonl(\.zstd)?$")
USAGE_KEYS = ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens", "reasoningTokens")


def decompress_frames(data):
    """Decode concatenated frames; keep complete records of a torn final frame, as dsh does."""
    if zstd is None:
        raise SystemExit("compression.zstd is unavailable: run with Python 3.14 or newer")
    parts = []
    while data:
        decoder = zstd.ZstdDecompressor()
        try:
            parts.append(decoder.decompress(data))
        except zstd.ZstdError:
            break
        if not decoder.eof:
            break
        data = decoder.unused_data
    return b"".join(parts)


def read_rows(path):
    data = path.read_bytes()
    if path.name.endswith(".zstd"):
        data = decompress_frames(data)
    rows, bad = [], 0
    for line in data.decode("utf-8", errors="replace").split("\n"):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            bad += 1
    return rows, bad


def live_logs(root):
    """Map each Session directory under root to its highest-generation log file."""
    candidates = [root] if root.is_file() else [p for p in root.rglob("session*.jsonl*") if p.is_file()]
    best = {}
    for path in candidates:
        match = LOG_NAME.match(path.name)
        if not match:
            continue
        version = int(match.group(1) or 0)
        current = best.get(path.parent)
        if current is None or version > current[0]:
            best[path.parent] = (version, path)
    return [path for _, path in sorted(best.values(), key=lambda item: str(item[1]))]


def block_bytes(blocks):
    total = 0
    for block in blocks or []:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            total += len(block["text"].encode("utf-8"))
        else:
            total += len(json.dumps(block, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return total


def block_text(blocks):
    parts = []
    for block in blocks or []:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        else:
            parts.append(json.dumps(block, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stream_usage(stream):
    for record in reversed(stream or []):
        if isinstance(record, dict) and record.get("type") == "chunk":
            chunk = record.get("chunk")
            if isinstance(chunk, dict) and chunk.get("type") == "usage" and isinstance(chunk.get("usage"), dict):
                return chunk["usage"]
    return None


def prompt_tokens(usage):
    return sum(int(usage.get(k) or 0) for k in ("inputTokens", "cacheReadTokens", "cacheWriteTokens"))


def summarize(path, dump_dir=None):
    rows, bad = read_rows(path)
    header = rows[0] if rows and rows[0].get("type") == "session" else {}
    events = rows[1:] if header else rows
    counts = Counter(str(e.get("type")) for e in events)
    usage = Counter()
    calls_with_usage = calls_without_usage = 0
    tools = Counter()
    routes = Counter()
    first = {"system": None, "header": None, "messages": [], "assistant_usage": None}
    first_done = False
    for event in events:
        kind = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if kind in ("assistant/message", "assistant/attempt"):
            sample = data.get("usage") if isinstance(data.get("usage"), dict) else stream_usage(data.get("stream"))
            if sample is None:
                calls_without_usage += 1
            else:
                calls_with_usage += 1
                for key in USAGE_KEYS:
                    value = sample.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        usage[key] += int(value)
            if not first_done:
                first["assistant_usage"] = sample
                first_done = True
            continue
        if kind == "tool/call":
            tools[str(data.get("name"))] += 1
        if kind == "request/header" and isinstance(data.get("header"), dict):
            config = data["header"].get("config") or {}
            routes[f"{config.get('provider')}/{config.get('model')}/{config.get('reasoningEffort')}"] += 1
        if first_done:
            continue
        if kind == "system/message":
            message = data.get("message") or {}
            first["system"] = block_text(message.get("content"))
        elif kind == "request/header":
            first["header"] = data.get("header") or {}
        elif kind in ("user/message", "developer/message"):
            message = data if kind == "user/message" else (data.get("message") or {})
            source = message.get("source") if isinstance(message.get("source"), dict) else {}
            text = block_text(message.get("content"))
            first["messages"].append({
                "event": kind,
                "source_kind": source.get("kind"),
                "source_form": source.get("form"),
                "bytes": block_bytes(message.get("content")),
                "sha256": digest(text),
                "_text": text,
            })
    tool_schemas = (first["header"] or {}).get("tools") or []
    tools_json = json.dumps(tool_schemas, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    config = (first["header"] or {}).get("config") or {}
    injected = [m for m in first["messages"] if m["source_kind"] != "user"]
    task = [m for m in first["messages"] if m["source_kind"] == "user"]
    system_text = first["system"] or ""
    result = {
        "file": str(path),
        "header": {k: header.get(k) for k in ("id", "version", "delegationDepth", "origin", "parentSession", "cwd", "agentPreset")},
        "bad_lines": bad,
        "event_counts": dict(sorted(counts.items())),
        "steps": counts.get("step/start", 0),
        "model_calls_with_usage": calls_with_usage,
        "model_calls_without_usage": calls_without_usage,
        "usage": dict(usage),
        "prompt_total": sum(usage[k] for k in ("inputTokens", "cacheReadTokens", "cacheWriteTokens")),
        "billed_total": sum(usage[k] for k in ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens")),
        "routes": dict(routes),
        "tool_calls": dict(sorted(tools.items())),
        "first_request": {
            "route": {"provider": config.get("provider"), "model": config.get("model"), "reasoningEffort": config.get("reasoningEffort")},
            "system_prompt_bytes": len(system_text.encode("utf-8")),
            "system_prompt_sha256": digest(system_text),
            "tool_count": len(tool_schemas),
            "tool_names": sorted(str(t.get("name")) for t in tool_schemas if isinstance(t, dict)),
            "tools_json_bytes": len(tools_json.encode("utf-8")),
            "tools_sha256": digest(tools_json),
            "injected_messages": [{k: v for k, v in m.items() if k != "_text"} for m in injected],
            "injected_bytes": sum(m["bytes"] for m in injected),
            "task_bytes": sum(m["bytes"] for m in task),
            "always_on_bytes": len(system_text.encode("utf-8")) + len(tools_json.encode("utf-8")) + sum(m["bytes"] for m in injected),
            "provider_prompt_tokens": prompt_tokens(first["assistant_usage"]) if first["assistant_usage"] else None,
            "provider_usage": first["assistant_usage"],
        },
    }
    if dump_dir is not None:
        # The parent Session dumps to `root` so two arms can be compared with `diff -ru A/root B/root`.
        depth = header.get("delegationDepth") or 0
        name = "root" if depth == 0 else f"depth{depth}-{header.get('id') or path.parent.name}"
        out = pathlib.Path(dump_dir) / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "system.txt").write_text(system_text, encoding="utf-8")
        ordered = sorted(tool_schemas, key=lambda t: str(t.get("name")) if isinstance(t, dict) else "")
        (out / "tools.json").write_text(json.dumps(ordered, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        for index, message in enumerate(first["messages"]):
            name = f"{index:02d}-{message['event'].replace('/', '_')}-{message['source_kind']}.txt"
            (out / name).write_text(message["_text"], encoding="utf-8")
    return result


def select_tree(logs, root_id):
    """Keep the Session `root_id` and every Session whose parentSession chain leads to it."""
    headers = {}
    for path in logs:
        rows, _ = read_rows(path)
        if rows and rows[0].get("type") == "session":
            headers[path] = rows[0]
    keep, changed = {root_id}, True
    while changed:
        changed = False
        for header in headers.values():
            if header.get("parentSession") in keep and header.get("id") not in keep:
                keep.add(header.get("id"))
                changed = True
    return [path for path in logs if headers.get(path, {}).get("id") in keep]


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = pathlib.Path(argv[1]).expanduser()
    dump_dir = None
    if "--dump-dir" in argv:
        dump_dir = argv[argv.index("--dump-dir") + 1]
    logs = live_logs(root)
    if "--root-session" in argv:
        logs = select_tree(logs, argv[argv.index("--root-session") + 1])
    if not logs:
        print(json.dumps({"path": str(root), "error": "no session log found"}))
        return 1
    sessions = [summarize(path, dump_dir) for path in logs]
    total = Counter()
    for session in sessions:
        total.update(session["usage"])
    report = {
        "path": str(root),
        "sessions": len(sessions),
        "subagent_sessions": sum(1 for s in sessions if (s["header"].get("delegationDepth") or 0) > 0),
        "usage_all_sessions": dict(total),
        "prompt_total_all_sessions": sum(total[k] for k in ("inputTokens", "cacheReadTokens", "cacheWriteTokens")),
        "billed_total_all_sessions": sum(total[k] for k in ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens")),
        "model_calls_without_usage": sum(s["model_calls_without_usage"] for s in sessions),
        "per_session": sessions,
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
