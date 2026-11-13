"""Split one captured Anthropic-format request body into its always-on parts.

Usage: python3 -I split_request.py BODY_FILE OUT_DIR

Writes OUT_DIR/system.txt, OUT_DIR/tools.json (the tools array, compact, as JSON on the wire)
and OUT_DIR/msg-<i>-<label>.txt for each text block of the first request's messages, then prints
a JSON summary: byte and character sizes and sha256 of each part, the tool names, the model
settings, and the always-on total (system + tools + every message block except the task).
"""
import hashlib
import json
import pathlib
import sys

body_path = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
raw = body_path.read_bytes()
req = json.loads(raw)


def part(name, text):
    (out / name).write_text(text, encoding="utf-8", newline="")
    data = text.encode("utf-8")
    return {"file": name, "chars": len(text), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def label(text):
    if text.startswith("<system-reminder>\nThe following workspace instructions"):
        return "agent-instructions"
    if text.startswith("Current runtime context."):
        return "runtime-context"
    if "skill" in text[:200].lower():
        return "skill-catalog"
    return "other"


system = req.get("system")
if isinstance(system, list):
    system_text = "\n".join(b.get("text", "") for b in system if isinstance(b, dict))
else:
    system_text = system or ""
tools = req.get("tools") or []
tools_text = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
summary = {
    "body_bytes": len(raw),
    "model": req.get("model"),
    "max_tokens": req.get("max_tokens"),
    "thinking": req.get("thinking"),
    "output_config": req.get("output_config"),
    "system": part("system.txt", system_text),
    "tools": dict(part("tools.json", tools_text), count=len(tools), names=sorted(t.get("name") for t in tools)),
    "messages": [],
}
for i, message in enumerate(req.get("messages") or []):
    content = message.get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
    for j, block in enumerate(blocks):
        text = block.get("text", "") if isinstance(block, dict) else ""
        kind = "task" if (i == 0 and j == 0) else label(text)
        info = part(f"msg-{i}-{j}-{kind}.txt", text)
        info.update(role=message.get("role"), kind=kind)
        summary["messages"].append(info)
always = summary["system"]["bytes"] + summary["tools"]["bytes"] + sum(m["bytes"] for m in summary["messages"] if m["kind"] != "task")
summary["always_on_bytes"] = always
summary["always_on_chars"] = summary["system"]["chars"] + summary["tools"]["chars"] + sum(m["chars"] for m in summary["messages"] if m["kind"] != "task")
json.dump(summary, sys.stdout, indent=1)
sys.stdout.write("\n")
