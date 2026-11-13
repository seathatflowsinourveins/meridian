"""Compare the captured first requests of the ADR 0012 second-round always-on probes.

Usage: python3 -I compare_runs.py <ao-capture dir> <with-letter> <tag> [<tag> ...]
Reads <dir>/<tag>/analysis.json, usage.json, run.exit, containment; prints one JSON object with
per-run figures, part hashes (cwd replaced by '<RUN>') and the with-minus-without medians.
Never prints prompt text.
"""
import json
import statistics
import sys
from pathlib import Path

EV = Path(sys.argv[1])
WITHL = sys.argv[2]
tags = sys.argv[3:]
runs = []
for tag in tags:
    r = EV / tag
    a = json.loads((r / "analysis.json").read_text(encoding="utf-8"))
    u = json.loads((r / "usage.json").read_text(encoding="utf-8"))
    ex = dict(line.split("=", 1) for line in (r / "run.exit").read_text().split() if "=" in line)
    cont = dict(line.split("=", 1) for line in (r / "containment").read_text().splitlines() if "=" in line)
    letter = tag.split("-")[1]
    runs.append({
        "tag": tag, "arm": "with" if letter == WITHL else "without",
        "exit": ex.get("exit"), "duration_ms": int(ex["duration_ms"]) if ex.get("duration_ms", "").isdigit() else None,
        "final_reason_kind": u.get("final_reason_kind"), "steps": u.get("steps"), "tool_calls": u.get("tool_calls"),
        "billed_tokens": u.get("tokens", {}).get("billed_total"),
        "requests": [q["path"] for q in a.get("requests", [])],
        "body_bytes": a.get("body_bytes"), "tool_count": a.get("tool_count"),
        "system_tokens": a.get("system_tokens"), "tools_tokens": a.get("tools_tokens"),
        "messages_tokens": a.get("messages_tokens"), "prompt_tokens_o200k": a.get("prompt_tokens_o200k"),
        "prompt_norm_tokens_o200k": a.get("prompt_norm_tokens_o200k"),
        "raw_body_tokens_o200k": a.get("raw_body_tokens_o200k"),
        "messages": [{k: m[k] for k in ("i", "role", "chars", "bytes", "tokens", "norm_tokens", "norm_sha256")} for m in a.get("messages", [])],
        "hash": {"system": a.get("system_norm_sha256"), "tools": a.get("tools_norm_sha256"),
                 "messages": [m["norm_sha256"] for m in a.get("messages", [])],
                 "rest": a.get("rest_norm_sha256"), "raw_body": a.get("raw_body_norm_sha256")},
        "containment": cont,
    })


def med(arm, key):
    vals = [x[key] for x in runs if x["arm"] == arm and isinstance(x[key], int)]
    return statistics.median(vals) if vals else None


out = {"runs": runs}
for key in ("prompt_tokens_o200k", "prompt_norm_tokens_o200k", "raw_body_tokens_o200k", "body_bytes", "tool_count"):
    w, wo = med("with", key), med("without", key)
    out[f"median_{key}"] = {"with": w, "without": wo, "delta": (w - wo) if w is not None and wo is not None else None}
for part in ("system", "tools", "rest", "raw_body"):
    out[f"distinct_{part}_hashes"] = sorted({x["hash"][part] for x in runs})
out["distinct_message_hash_lists"] = sorted({json.dumps(x["hash"]["messages"]) for x in runs})
print(json.dumps(out, indent=1))
