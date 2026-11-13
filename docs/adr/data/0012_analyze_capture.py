"""Split dsh's first captured Messages request into its parts and count o200k tokens.

Adapted for ADR 0012 (second round) from ~/src/meridian-ab/0011/scripts/analyze_capture.py.
Change: also reports figures with the run's worktree path replaced by a fixed placeholder
('<RUN>'), so arms whose cwd differs by one letter compare byte for byte, and a sha256 per part.

Usage: python3 -I analyze_capture.py <count_tokens.py> <vocab_dir> <capture_dir> <cwd>
Picks the first POST to */v1/messages, writes parts/ (system.txt, tools.json,
msg-NN-<role>.txt, rest.json) beside it, and prints one JSON object. Never prints prompt text.
The prompt figure is system text + tools wire JSON (compact, key order as sent) + message
texts; the raw body figure counts the whole JSON body as sent (escapes included).
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("count_tokens", sys.argv[1])
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)

ENC = ct.Encoder("o200k_base", Path(sys.argv[2]))
CAP = Path(sys.argv[3])
CWD = sys.argv[4]
PH = "<RUN>"


def tok(s):
    return len(ENC.encode(s))


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def norm(s):
    return s.replace(CWD, PH)


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


reqs = []
pick = None
for meta_f in sorted(CAP.glob("req-*.json")):
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    reqs.append({"n": meta.get("n"), "method": meta.get("method"), "path": meta.get("path"),
                 "body_bytes": meta.get("body_bytes")})
    if pick is None and meta["method"] == "POST" and meta["path"].rstrip("/").endswith("/v1/messages"):
        pick = (meta, meta_f.with_suffix(".body"))
if pick is None:
    print(json.dumps({"capture": str(CAP), "error": "no POST */v1/messages captured", "requests": reqs}))
    sys.exit(0)
meta, body_f = pick
raw = body_f.read_bytes()
body = json.loads(raw)
out = CAP / "parts"
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
    per_tool.append({"name": t.get("name"), "chars": len(tj), "tokens": tok(tj), "sha256": sha(tj)})
msgs = []
for i, m in enumerate(body.get("messages", []) or []):
    text, kinds = block_text(m.get("content"))
    (out / f"msg-{i:02d}-{m.get('role')}.txt").write_text(text, encoding="utf-8")
    msgs.append({"i": i, "role": m.get("role"), "kinds": kinds, "chars": len(text), "bytes": len(text.encode("utf-8")),
                 "tokens": tok(text), "cwd_occurrences": text.count(CWD),
                 "norm_tokens": tok(norm(text)), "norm_sha256": sha(norm(text))})
rest = {k: v for k, v in body.items() if k not in ("system", "tools", "messages")}
(out / "rest.json").write_text(json.dumps(rest, indent=1, ensure_ascii=False), encoding="utf-8")
sys_tok = tok(sys_text)
tools_tok = tok(tools_json)
msg_tok = sum(m["tokens"] for m in msgs)
norm_total = tok(norm(sys_text)) + tok(norm(tools_json)) + sum(m["norm_tokens"] for m in msgs)
raw_text = raw.decode("utf-8")
print(json.dumps({
    "capture": str(CAP), "path": meta["path"], "requests": reqs, "body_bytes": len(raw),
    "raw_body_tokens_o200k": tok(raw_text),
    "raw_body_norm_tokens_o200k": tok(norm(raw_text)),
    "raw_body_norm_sha256": sha(norm(raw_text)),
    "cwd": CWD, "cwd_occurrences_body": raw_text.count(CWD),
    "system_kinds": sys_kinds, "system_chars": len(sys_text), "system_bytes": len(sys_text.encode("utf-8")),
    "system_tokens": sys_tok, "system_norm_sha256": sha(norm(sys_text)),
    "tool_count": len(tools), "tool_names": [t.get("name") for t in tools],
    "tools_json_chars": len(tools_json), "tools_json_bytes": len(tools_json.encode("utf-8")),
    "tools_tokens": tools_tok, "tools_norm_sha256": sha(norm(tools_json)),
    "messages": msgs, "messages_tokens": msg_tok,
    "prompt_tokens_o200k": sys_tok + tools_tok + msg_tok,
    "prompt_norm_tokens_o200k": norm_total,
    "rest_keys": sorted(rest), "rest_norm_sha256": sha(norm(json.dumps(rest, sort_keys=True))),
    "model": body.get("model"), "max_tokens": body.get("max_tokens"),
    "thinking": body.get("thinking"), "output_config": body.get("output_config"),
    "per_tool": per_tool,
}, ensure_ascii=False))
