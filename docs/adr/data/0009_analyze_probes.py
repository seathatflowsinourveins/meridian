"""ADR 0009 always-on analysis of the loopback-captured first requests (no model call was made).

usage: python3 -I analyze_probes.py EV COUNT_TOKENS_PY VOCAB_DIR STATIC_WIRE_DIR
Prints JSON aggregates only (sizes, token counts, hashes, names); never prints prompt text.
"""
import hashlib
import importlib.util
import json
import pathlib
import statistics
import sys

EV = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("count_tokens", sys.argv[2])
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)
ENC = ct.Encoder("o200k_base", pathlib.Path(sys.argv[3]))
STATIC = pathlib.Path(sys.argv[4])
KEY = {"A": "without", "B": "with"}
PEER = ["codex_ask", "codex_plan", "codex_review", "codex_status", "codex_task"]


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def tok(text):
    return len(ENC.encode(text))


runs = {}
for tag in ["A1", "B1", "B2", "A2", "A3", "B3"]:
    cap = EV / "capture" / f"probe-{tag}"
    reqs = sorted(cap.glob("req-*.body"))
    raw = reqs[0].read_bytes()
    body = json.loads(raw)
    text = raw.decode("utf-8")
    faithful = dump(body).encode("utf-8") == raw
    cwd = str(EV / "wt" / tag)
    normalized = text.replace(cwd, "<RUN>")
    tools = body.get("tools") or []
    names = [t.get("name") for t in tools]
    tools_json = dump(tools)
    peer = [t for t in tools if t.get("name") in PEER]
    peer_json = dump(peer)
    system = body.get("system")
    system_json = dump(system)
    msgs = body.get("messages") or []
    msgs_json = dump(msgs)
    other = {k: v for k, v in body.items() if k not in ("tools", "system", "messages")}
    static_match = None
    if peer:
        static_match = {}
        for t in peer:
            f = STATIC / f"0009-v3-tool-{t['name']}.wire.json"
            static_match[t["name"]] = f.exists() and f.read_text(encoding="utf-8").rstrip("\n") == dump({"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]})
    runs[tag] = {
        "arm": KEY[tag[0]],
        "requests_captured": len(reqs),
        "path": json.loads((cap / "req-01.json").read_text())["path"],
        "body_bytes": len(raw),
        "reserialization_faithful": faithful,
        "body_tokens_o200k": tok(text),
        "body_sha256_cwd_normalized": hashlib.sha256(normalized.encode()).hexdigest(),
        "tool_count": len(tools),
        "tool_names": names,
        "tools_json_bytes": len(tools_json.encode()),
        "tools_tokens_o200k": tok(tools_json),
        "peer_tools_in_request": [t["name"] for t in peer],
        "peer_tools_json_chars": len(peer_json),
        "peer_tools_json_bytes": len(peer_json.encode()),
        "peer_tools_tokens_o200k": tok(peer_json) if peer else 0,
        "peer_tools_equal_static_fact_sheet_files": static_match,
        "system_json_bytes": len(system_json.encode()),
        "system_tokens_o200k": tok(system_json),
        "messages_json_bytes": len(msgs_json.encode()),
        "messages_tokens_o200k": tok(msgs_json),
        "other_fields": sorted(other.keys()),
        "other_fields_sha256": hashlib.sha256(dump(other).encode()).hexdigest(),
        "system_sha256": hashlib.sha256(system_json.encode()).hexdigest(),
        "messages_sha256_cwd_normalized": hashlib.sha256(msgs_json.replace(cwd, "<RUN>").encode()).hexdigest(),
        "non_peer_tools_sha256": hashlib.sha256(dump([t for t in tools if t.get("name") not in PEER]).encode()).hexdigest(),
    }

summary = {}
for arm in ("without", "with"):
    rs = [r for r in runs.values() if r["arm"] == arm]
    summary[arm] = {
        k: {"runs": [r[k] for r in rs], "median": statistics.median(r[k] for r in rs)}
        for k in ("body_bytes", "body_tokens_o200k", "tools_json_bytes", "tools_tokens_o200k", "tool_count")
    }
    summary[arm]["identical_cwd_normalized_bodies"] = len({r["body_sha256_cwd_normalized"] for r in rs}) == 1
delta = {k: summary["with"][k]["median"] - summary["without"][k]["median"] for k in ("body_bytes", "body_tokens_o200k", "tools_json_bytes", "tools_tokens_o200k", "tool_count")}
same_other = len({r["other_fields_sha256"] for r in runs.values()}) == 1
same_system = len({r["system_sha256"] for r in runs.values()}) == 1
same_msgs = len({r["messages_sha256_cwd_normalized"] for r in runs.values()}) == 1
same_nonpeer_tools = len({r["non_peer_tools_sha256"] for r in runs.values()}) == 1
print(json.dumps({"runs": runs, "summary": summary, "delta_with_minus_without_medians": delta,
                  "all_six_share": {"system": same_system, "messages_cwd_normalized": same_msgs,
                                    "non_peer_tools": same_nonpeer_tools, "other_request_fields": same_other}}, indent=1))
