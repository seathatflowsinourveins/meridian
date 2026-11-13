"""Split dsh's first captured Messages request into its parts and count o200k tokens.

Usage: python3 -I analyze_capture.py <count_tokens.py> <vocab_dir> <capture_dir> [<capture_dir> ...]
For each capture dir: picks the first POST to */v1/messages, writes parts/ (system.txt,
tools.json, msg-NN-<role>.txt, rest.json) beside it, and prints one JSON object per dir.
The prompt figure is system text + tools wire JSON (compact, key order as sent) + message
texts; the raw body figure counts the whole JSON body as sent (escapes included).
"""
import importlib.util
import json
import os
import sys

spec = importlib.util.spec_from_file_location("count_tokens", sys.argv[1])
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)
from pathlib import Path  # noqa: E402

ENC = ct.Encoder("o200k_base", Path(sys.argv[2]))


def tok(s):
    return len(ENC.encode(s))


def block_text(content):
    if isinstance(content, str):
        return content, ["text"]
    parts, kinds = [], []
    for b in content or []:
        kinds.append(b.get("type", "?"))
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif b.get("type") == "tool_result":
            t, _ = block_text(b.get("content"))
            parts.append(t)
        else:
            parts.append(json.dumps(b, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(parts), kinds


for cap in sys.argv[3:]:
    capd = Path(cap)
    pick = None
    for meta_f in sorted(capd.glob("req-*.json")):
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        if meta["method"] == "POST" and meta["path"].rstrip("/").endswith("/v1/messages"):
            pick = (meta, meta_f.with_suffix(".body"))
            break
    if pick is None:
        print(json.dumps({"capture": cap, "error": "no POST */v1/messages captured",
                          "requests": sorted(p.name for p in capd.glob("req-*.json"))}))
        continue
    meta, body_f = pick
    raw = body_f.read_bytes()
    body = json.loads(raw)
    out = capd / "parts"
    out.mkdir(exist_ok=True)
    system = body.get("system", "")
    sys_text, sys_kinds = block_text(system) if not isinstance(system, str) else (system, ["text"])
    (out / "system.txt").write_text(sys_text, encoding="utf-8")
    tools = body.get("tools", []) or []
    tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    (out / "tools.json").write_text(tools_json, encoding="utf-8")
    per_tool = []
    for t in tools:
        tj = json.dumps(t, ensure_ascii=False, separators=(",", ":"))
        per_tool.append({"name": t.get("name"), "chars": len(tj), "tokens": tok(tj)})
    msgs = []
    for i, m in enumerate(body.get("messages", []) or []):
        text, kinds = block_text(m.get("content"))
        (out / f"msg-{i:02d}-{m.get('role')}.txt").write_text(text, encoding="utf-8")
        msgs.append({"i": i, "role": m.get("role"), "kinds": kinds, "chars": len(text), "tokens": tok(text)})
    rest = {k: v for k, v in body.items() if k not in ("system", "tools", "messages")}
    (out / "rest.json").write_text(json.dumps(rest, indent=1, ensure_ascii=False), encoding="utf-8")
    sys_tok = tok(sys_text)
    tools_tok = tok(tools_json)
    msg_tok = sum(m["tokens"] for m in msgs)
    print(json.dumps({
        "capture": cap, "path": meta["path"], "body_bytes": len(raw),
        "raw_body_tokens_o200k": tok(raw.decode("utf-8")),
        "system_kinds": sys_kinds, "system_chars": len(sys_text), "system_tokens": sys_tok,
        "tool_count": len(tools), "tools_json_chars": len(tools_json), "tools_tokens": tools_tok,
        "messages": msgs, "messages_tokens": msg_tok,
        "prompt_tokens_o200k": sys_tok + tools_tok + msg_tok,
        "rest_keys": sorted(rest), "model": body.get("model"),
        "per_tool": per_tool,
    }, ensure_ascii=False))
