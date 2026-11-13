"""Read-only recount of ADR 0009's six captured first requests on ADR 0011's prompt-text basis.

usage: python3 -I prompt_basis.py COUNT_TOKENS_PY VOCAB_DIR CAPTURE_ROOT
Same split as docs/adr/data/0011_analyze_capture.py (system text + tools wire JSON + message
texts, each text block counted on its own), but writes nothing and prints numbers only.
"""
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("count_tokens", sys.argv[1])
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)
ENC = ct.Encoder("o200k_base", Path(sys.argv[2]))
ROOT = Path(sys.argv[3])


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


out = {}
for tag in ["A1", "B1", "B2", "A2", "A3", "B3"]:
    raw = (ROOT / f"probe-{tag}" / "req-01.body").read_bytes()
    body = json.loads(raw)
    system = body.get("system", "")
    sys_text, sys_kinds = block_text(system) if not isinstance(system, str) else (system, ["text"])
    tools = body.get("tools", []) or []
    tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    msgs = []
    for i, m in enumerate(body.get("messages", []) or []):
        text, kinds = block_text(m.get("content"))
        blocks = []
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if b.get("type") == "text":
                    blocks.append({"chars": len(b.get("text", "")), "tokens": tok(b.get("text", ""))})
        msgs.append({"i": i, "role": m.get("role"), "kinds": kinds, "chars": len(text),
                     "tokens": tok(text), "text_blocks": blocks})
    s_tok, t_tok = tok(sys_text), tok(tools_json)
    m_tok = sum(m["tokens"] for m in msgs)
    out[tag] = {
        "body_bytes": len(raw), "raw_body_tokens": tok(raw.decode("utf-8")),
        "system_chars": len(sys_text), "system_tokens": s_tok,
        "tool_count": len(tools), "tools_chars": len(tools_json), "tools_tokens": t_tok,
        "messages": msgs, "messages_tokens": m_tok,
        "prompt_chars": len(sys_text) + len(tools_json) + sum(m["chars"] for m in msgs),
        "prompt_tokens": s_tok + t_tok + m_tok,
    }
print(json.dumps(out, indent=1))
