"""ADR 0008: aggregate run 2 of the oh-my-codex with/without series into 0008-results.json.

Usage, in the distro:  python3 -I 0008_aggregate.py RUN2_DIR KEY_TXT OUT_JSON GUARD_SH

RUN2_DIR is the series folder on the owner's machine (not published), as 0008_m1.sh,
0008_r1.sh and 0008_proof.sh left it: m1/<letter>-<n>/, r1/<letter>-<n>/, proof/ and scripts/.
KEY_TXT is the series' arm key (0008-key.txt), whose first line starts omx_arm=a or omx_arm=b:
the letter that ran with oh-my-codex. GUARD_SH is the Gateway guard the series ran
(~/.cache/meridian/gateway-guard.sh); only its hash, size and file time are read. All four
arguments are required, OUT_JSON must end in .json, and an existing OUT_JSON that is not JSON
is never overwritten. It reads only numbers, verdict lines, changed file names,
file names, sizes and times from the home snapshots, and the scripts' hashes, and writes no
path, thread id, account field or prompt text. Standard library only, plus jq for the two
prompt renders (counted exactly as 0008_proof.sh and 0008_m2.sh count them).
Revised 2026-11-13 after the series (the run folders were not changed): SessionStart text
counted per thread, a sub-agent's inherited history kept apart from its own turns, the
owner-home containment summary, and the scripts' file times and the guard's hash added.
Revised again the same day after a second check: the Stop auto-nudge's reason text counted
(the text that continues a turn), the agents' questions and sleeps and the wall time without
those sleeps recorded, and the hand-run exec-noauth probe's file times recorded as absent
when its files are missing (its command was not kept, so a re-run cannot make them).
Revised a third time the same day after a third check, with the output unchanged: the arm key
read from KEY_TXT (it was the constant "b", which a re-run with a new key would mislabel half
the time) and the arguments checked, so that a call missing one cannot write over another file.
"""

import datetime
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys

USAGE = "usage: python3 -I 0008_aggregate.py RUN2_DIR KEY_TXT OUT_JSON GUARD_SH"
if len(sys.argv) != 5:
    sys.exit(USAGE)
RUN2, KEY, OUT, GUARD = sys.argv[1:5]
if not OUT.endswith(".json"):
    sys.exit("OUT_JSON must end in .json\n" + USAGE)
if os.path.exists(OUT):
    try:
        with open(OUT, encoding="utf-8") as f:
            json.load(f)
    except ValueError:
        sys.exit("OUT_JSON exists and is not JSON; not writing over it")
with open(KEY, encoding="utf-8") as f:
    DRAWN = re.match(r"omx_arm=([ab]) ", f.readline())
if not DRAWN:
    sys.exit("KEY_TXT's first line must start with omx_arm=a or omx_arm=b")
EXEC_ENV = "[Execution environment]"  # OMX's SessionStart text (as 0008_scan_run.py counts it)
# The Stop hook's block reason, the text that continues a turn: DEFAULT_AUTO_NUDGE_RESPONSE in
# src/scripts/notify-hook/auto-nudge.ts L43 at 610be90, used when $CODEX_HOME/.omx-config.json
# sets none (absent in every run's omx-paths snapshot). 0008_scan_run.py's needle "OMX native
# Stop" is the hook's systemMessage instead (codex-native-hook.ts L21868-21878).
NUDGE_REASON = "continue with the current task only if it is already authorized"
WITH = DRAWN.group(1)  # KEY_TXT: the letter that ran with oh-my-codex
ORDER_R1 = ["a-1", "b-1", "b-2", "a-2", "a-3", "b-3"]
ORDER_M1 = ["a-1", "a-2", "a-3", "b-1", "b-2", "b-3"]
PUBLISHED = {
    "common2.sh": "0008_common2.sh",
    "m1.sh": "0008_m1.sh",
    "r1.sh": "0008_r1.sh",
    "proof.sh": "0008_proof.sh",
    "scan_run.py": "0008_scan_run.py",
    "trust_keys.py": "0008_trust_keys.py",
    "codex_ab_summary.py": "0008_codex_ab_summary.py",
    "r1-brief.txt": "0008-brief-R1.txt",
}
TOOLS_JQ = '[.[]|select(.type=="additional_tools")|.tools|tojson|utf8bytelength]|add // 0'
MSGS_JQ = '[.[]|select(.type=="message")|.content[]|.text|utf8bytelength]|add'


def text(*parts):
    with open(os.path.join(RUN2, *parts), encoding="utf-8") as f:
        return f.read()


def load(*parts):
    return json.loads(text(*parts))


def kv(line):
    return dict(p.split("=", 1) for p in line.split() if "=" in p)


def guard(*parts):
    out = []
    for line in text(*parts, "guard.log").splitlines():
        when, rc, said = line.split(" ", 2)
        out.append({"time": when, "rc": int(rc.split("=")[1]), "printed": said})
    return out


def versions(*parts):
    return text(*parts, "version.txt").split("\n")[:2]


def trust(*parts):
    lines = text(*parts).splitlines()
    total = next(int(x.split()[1]) for x in lines if x.startswith("projects_keys_total"))
    return {"projects_keys": total, "ab0008_keys": sum(x.startswith("ab0008_key") for x in lines)}


def agent_types(path):
    found = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line) if line.strip() else {}
            p = row.get("payload") or {}
            if row.get("type") == "response_item" and p.get("name") == "spawn_agent":
                try:
                    found.append(json.loads(p.get("arguments") or "{}").get("agent_type"))
                except json.JSONDecodeError:
                    found.append("unparsed")
    return found


def jq(expr, *parts):
    res = subprocess.run(
        ["jq", expr, os.path.join(RUN2, *parts)], check=True, capture_output=True, text=True
    )
    return int(res.stdout.strip())


def sizes(listing):
    out = {}
    for line in text("proof", listing).splitlines():
        name, kind, size, _ = line.split("\t")
        out[name] = (kind, int(size))
    return out


def pct(new, old):
    return round(100 * (new - old) / old, 1)


def rows_of(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) if line.strip() else {} for line in f]


def exec_env_lines(path):
    """Lines holding OMX's SessionStart text, as 0008_m1.sh's grep -c counts them."""
    with open(path, encoding="utf-8") as f:
        return sum(EXEC_ENV in line for line in f)


def exec_env_messages(rows):
    """Developer or user message parts holding the SessionStart text, as 0008_scan_run.py counts."""
    n = 0
    for r in rows:
        p = r.get("payload") or {}
        if r.get("type") == "response_item" and p.get("type") == "message" and p.get("role") in ("developer", "user"):
            n += sum(EXEC_ENV in (c.get("text") or "") for c in p.get("content") or [])
    return n


def contexts(rows):
    seen = {}
    for r in rows:
        if r.get("type") == "turn_context":
            p = r.get("payload") or {}
            key = f"{p.get('model')}/{p.get('effort')}"
            seen[key] = seen.get(key, 0) + 1
    return seen


def own_start(rows):
    """A sub-agent's rollout opens with the history it inherits from its root (the root's
    items, with no token_usage_record). Its own turns start at the last turn_context before
    its first token_usage_record."""
    first = next(i for i, r in enumerate(rows) if r.get("type") == "token_usage_record")
    return max(i for i, r in enumerate(rows[:first]) if r.get("type") == "turn_context")


def lines_holding(paths, needle):
    """Lines of the given files holding needle, summed."""
    n = 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            n += sum(needle in line for line in f)
    return n


def asks_and_sleeps(rows):
    """Calls to request_user_input_async (with Codex's answer) and to sleep (with the wall time
    the tool reported and the input tokens of the next model request, which reads its result)."""
    outs = {}
    for i, r in enumerate(rows):
        p = r.get("payload") or {}
        if r.get("type") == "response_item" and p.get("type") == "function_call_output":
            outs[p.get("call_id")] = (i, str(p.get("output")))
    asks, sleeps = [], []
    for r in rows:
        p = r.get("payload") or {}
        if r.get("type") != "response_item" or p.get("type") != "function_call":
            continue
        i, out = outs.get(p.get("call_id"), (None, ""))
        if p.get("name") == "request_user_input_async":
            asks.append(out)
        elif p.get("name") == "sleep":
            wall = re.search(r"Wall time: ([0-9.]+) seconds", out)
            nxt = next((x for x in rows[i + 1:] if x.get("type") == "token_usage_record"), None) if i is not None else None
            sleeps.append({
                "requested_ms": json.loads(p.get("arguments") or "{}").get("duration_ms"),
                "reported_wall_seconds": float(wall.group(1)) if wall else None,
                "next_request_input_tokens": nxt["payload"]["usage"]["input_tokens"] if nxt else None,
            })
    return asks, sleeps


def snap_lines(*parts):
    return text(*parts).splitlines()


def owner_home(*d):
    """Containment of the owner's home for one run, from its home-pre and home-post snapshots
    (names, sizes and times only; snaphome in 0008_common2.sh)."""
    def shas(side):
        return [x.split()[0] for x in snap_lines(*d, side, "owner-config.txt") if re.fullmatch(r"[0-9a-f]{64}", x.split()[0] if x.split() else "")]

    def present(side):
        return sum(x.startswith("PRESENT") for x in snap_lines(*d, side, "omx-paths.txt"))

    def top_files(side):
        out = {}
        for x in snap_lines(*d, side, "codex-full.txt"):
            name, kind, size, mtime = x.split("\t")
            if kind == "f" and "/" not in name:
                out[name] = (int(size), mtime)
        return out

    pre, post = top_files("home-pre"), top_files("home-post")
    db = {n: [pre[n][0] if n in pre else None, post[n][0]] for n in sorted(post) if n.endswith(".sqlite") and pre.get(n) != post[n]}
    wal = sorted(n for n in post if n.endswith(".sqlite-wal") and pre.get(n) != post[n])
    procs = text(*d, "home-post", "procs.txt").strip()
    return {
        "config_toml_and_hooks_json_sha256_unchanged": len(shas("home-pre")) == 2 and shas("home-pre") == shas("home-post"),
        "omx_paths_checked": len(snap_lines(*d, "home-pre", "omx-paths.txt")),
        "omx_paths_present_before_after": [present("home-pre"), present("home-post")],
        "omx_process_left": procs != "none",
        "codex_databases_rewritten_size_before_after": db,
        "codex_write_ahead_logs_written": wal,
    }


# M1: always-on, Codex's own count of the first (only) request
m1 = []
for run in ORDER_M1:
    s = load("m1", run, "summary.json")
    u = s["events"]["turn_completed_usage"]
    m1.append({
        "run": run,
        "arm": "with" if run.startswith(WITH) else "without",
        "guard": guard("m1", run),
        "codex_version_before_after": versions("m1", run),
        "exit_and_seconds": kv(text("m1", run, "run.txt")),
        "input_tokens": u["input_tokens"],
        "cached_input_tokens": u["cached_input_tokens"],
        "output_tokens": u["output_tokens"],
        "total_tokens": s["root"]["sum_request_usage"]["total_tokens"],
        "model_requests": s["root"]["requests"],
        "model_effort": f"{s['root']['model']}/{s['root']['effort']}",
        "completed_items": s["events"]["completed_item_types"],
        "first_request_bytes_by_block": s["root"]["initial_context_block_bytes"],
        "first_request_tool_declaration_bytes": s["root"]["initial_additional_tools"]["bytes"],
        "session_start_exec_env_lines": exec_env_lines(os.path.join(RUN2, "m1", run, "rollout.jsonl")),
        "rollouts_written_to_owner_codex_sessions": int(os.path.exists(os.path.join(RUN2, "m1", run, "rollout.jsonl"))),
        "owner_home": owner_home("m1", run),
        "warnings": s["warnings"],
    })
m1_a = [r["input_tokens"] for r in m1 if r["arm"] == "without"]
m1_b = [r["input_tokens"] for r in m1 if r["arm"] == "with"]
blk_a = next(r for r in m1 if r["arm"] == "without")
blk_b = next(r for r in m1 if r["arm"] == "with")
block_delta = {
    k: blk_b["first_request_bytes_by_block"][k] - blk_a["first_request_bytes_by_block"][k]
    for k in blk_a["first_request_bytes_by_block"]
}
block_delta["tool_declarations"] = (
    blk_b["first_request_tool_declaration_bytes"] - blk_a["first_request_tool_declaration_bytes"]
)

# R1: the real task
r1 = []
for slot, run in enumerate(ORDER_R1, 1):
    d = ("r1", run)
    s = load(*d, "summary.json")
    scan = load(*d, "scan.json")
    grade_lines = text(*d, "grade.txt").splitlines()
    g = kv(grade_lines[0].split(" pytest_tail=")[0])
    tail = grade_lines[0].split(" pytest_tail=")[1]
    checks = kv(text(*d, "containment.txt").splitlines()[0])
    cont = text(*d, "containment.txt")
    trust_block = cont.split("## trust keys\n", 1)[1].split("\n", 1)[0]
    subs = sorted(os.listdir(os.path.join(RUN2, *d, "sub")))
    al = s["all_threads_request_usage"]
    flagged = {}
    for f in scan["flagged"]:
        flagged[f["flag"]] = flagged.get(f["flag"], 0) + 1
    root_rows = rows_of(os.path.join(RUN2, *d, "rollout.jsonl"))
    sub_rows = [rows_of(os.path.join(RUN2, *d, "sub", x)) for x in subs]
    sub_split = [(rows[:own_start(rows)], rows[own_start(rows):]) for rows in sub_rows]
    hooks = dict(scan["hook_text_counts"])
    hooks["session_start_exec_env"] = exec_env_messages(root_rows)  # root thread only
    # Every rollout line and the event stream, root and sub-agents (inherited history included).
    hooks["stop_auto_nudge_reason_text"] = lines_holding(
        [os.path.join(RUN2, *d, "events.jsonl"), os.path.join(RUN2, *d, "rollout.jsonl")]
        + [os.path.join(RUN2, *d, "sub", x) for x in subs],
        NUDGE_REASON,
    )
    root_asks, root_sleeps = asks_and_sleeps(root_rows)
    sub_own = [asks_and_sleeps(own) for _, own in sub_split]
    secs_run = int(kv(text(*d, "run.txt"))["seconds"])
    idle = round(sum(x["reported_wall_seconds"] or 0 for x in root_sleeps + [y for _, s in sub_own for y in s]))
    r1.append({
        "run": run,
        "order_slot": slot,
        "arm": "with" if run.startswith(WITH) else "without",
        "guard": guard(*d),
        "codex_version_before_after": versions(*d),
        "exit_and_seconds": kv(text(*d, "run.txt")),
        "user_input_requests": {
            "root": len(root_asks),
            "sub_agents_own_turns": sum(len(a) for a, _ in sub_own),
            "answers": root_asks + [y for a, _ in sub_own for y in a],
        },
        "sleep_calls": {"root": root_sleeps, "sub_agents_own_turns": [y for _, s in sub_own for y in s]},
        "seconds_idle_in_sleep": idle,
        "seconds_without_sleep": secs_run - idle,
        "pytest_before_in_the_run_clone": re.sub(r" in [0-9.]+s$", "", text(*d, "pytest-before.txt").splitlines()[-1]),
        "grade_on_a_fresh_clone": {
            "ruff_check": int(g["ruff"]),
            "ruff_format_check": int(g["format"]),
            "pyright": int(g["pyright"]),
            "pytest": int(g["pytest"]),
            "pytest_tail": re.sub(r" in [0-9.]+s$", "", tail),
        },
        "own_clone_checks": checks,
        "passed": grade_lines[-1] == "pass=yes",
        "tracked_files_changed_from_base": text(*d, "changed-tracked.txt").split(),
        "owner_trust_keys_before_after": [trust(*d, "trust-pre.txt"), trust(*d, "trust-post.txt")],
        "owner_trust_keys_check": trust_block,
        "tokens_all_threads": al,
        "root": {
            "model_effort": f"{s['root']['model']}/{s['root']['effort']}",
            "cli_version": s["root"]["cli_version"],
            "model_requests": s["root"]["requests"],
            "total_tokens": s["root"]["sum_request_usage"]["total_tokens"],
            "first_request_input_tokens": s["root"]["first_request_usage"]["input_tokens"],
            "spawn_agent_types": agent_types(os.path.join(RUN2, *d, "rollout.jsonl")),
        },
        "sub_agents": [
            {
                "model_requests": x["requests"],
                "total_tokens": x["sum_request_usage"]["total_tokens"],
                "own_turn_contexts": contexts(sub_split[i][1]),
                "inherited_turn_contexts": contexts(sub_split[i][0]),
                "session_start_text_inherited_own": [exec_env_messages(sub_split[i][0]), exec_env_messages(sub_split[i][1])],
                "token_usage_records_in_inherited_history": sum(r.get("type") == "token_usage_record" for r in sub_split[i][0]),
            }
            for i, x in enumerate(s["subagents"])
        ],
        "omx_hook_texts_seen": hooks,
        "session_start_text_in_all_rollouts_as_scanned": scan["hook_text_counts"]["session_start_exec_env"],
        "tool_inputs_scanned": scan["tool_inputs_scanned"],
        "flagged_tool_inputs_by_pattern": flagged,
        "rollouts_written_to_owner_codex_sessions": 1 + len(subs),
        "owner_home": owner_home(*d),
        "warnings": s["warnings"],
    })


def arm(name):
    runs = [r for r in r1 if r["arm"] == name]
    tot = [r["tokens_all_threads"]["total_tokens"] for r in runs]
    secs = [int(r["exit_and_seconds"]["seconds"]) for r in runs]
    req = [r["root"]["model_requests"] + sum(x["model_requests"] for x in r["sub_agents"]) for r in runs]
    return {
        "runs": [r["run"] for r in runs],
        "passed": sum(r["passed"] for r in runs),
        "total_tokens": tot,
        "total_tokens_sum": sum(tot),
        "total_tokens_median": statistics.median(tot),
        "root_thread_tokens": [r["root"]["total_tokens"] for r in runs],
        "sub_agent_tokens": [sum(x["total_tokens"] for x in r["sub_agents"]) for r in runs],
        "sub_agent_threads": [len(r["sub_agents"]) for r in runs],
        "output_tokens": [r["tokens_all_threads"]["output_tokens"] for r in runs],
        "seconds": secs,
        "seconds_median": statistics.median(secs),
        "user_input_requests_root": [r["user_input_requests"]["root"] for r in runs],
        "seconds_idle_in_sleep": [r["seconds_idle_in_sleep"] for r in runs],
        "seconds_without_sleep": [r["seconds_without_sleep"] for r in runs],
        "seconds_without_sleep_median": statistics.median(r["seconds_without_sleep"] for r in runs),
        "model_requests_incl_sub_agents": req,
        "first_request_input_tokens": [r["root"]["first_request_input_tokens"] for r in runs],
    }


A, B = arm("without"), arm("with")
gap = abs(A["passed"] - B["passed"])
extend = gap == 1 or (A["passed"] == 2 and B["passed"] == 2)
more_passes = B["passed"] >= 2 and A["passed"] <= 1
fewer_tokens = A["passed"] == B["passed"] == 3 and B["total_tokens_sum"] <= 0.75 * A["total_tokens_sum"]
clean = all(
    r["own_clone_checks"]["tests_unchanged_exit"] == "0"
    and r["own_clone_checks"]["tests_untracked"] == "0"
    and r["own_clone_checks"]["tracked_outside_allowed"] == "0"
    and r["omx_hook_texts_seen"]["stop_auto_nudge"] == 0
    and r["omx_hook_texts_seen"]["stop_auto_nudge_reason_text"] == 0
    and r["owner_trust_keys_check"] == "unchanged"
    for r in r1
)
# Containment as applied (narrower than the pre-registered snapshot test, and chosen after the
# runs, once that test had failed; see "notes"): owner config.toml and hooks.json unchanged,
# trust keys unchanged, no OMX path, no OMX process.
contained = all(
    r["owner_home"]["config_toml_and_hooks_json_sha256_unchanged"]
    and r["owner_home"]["omx_paths_present_before_after"] == [0, 0]
    and not r["owner_home"]["omx_process_left"]
    for r in m1 + r1
) and all(r["owner_trust_keys_check"] == "unchanged" for r in r1)
# The pre-registered test: the snapshot "must differ only by the ab-0008 worktrees". Every run
# wrote its own rollouts into the owner's ~/.codex/sessions, so no run met it.
prereg_contained = not any(r["rollouts_written_to_owner_codex_sessions"] for r in m1 + r1)


def file_time(path):
    return datetime.datetime.fromtimestamp(os.stat(path).st_mtime).astimezone().isoformat(timespec="seconds")


def file_time_if_kept(path):
    """None for a file a re-run cannot make (the hand-run exec-noauth probe's)."""
    return file_time(path) if os.path.exists(path) else None

# Route proof: project-scope setup in a throwaway clone, and the trust renders
before, after = sizes("clone-before.txt"), sizes("clone-after.txt")
ref = {}
for run in ("a-1", "b-1"):
    ref[run] = {
        "AGENTS.md_bytes": len(text("r1", run, "ref-AGENTS.md").encode("utf-8")),
        "gitignore_lines": len(text("r1", run, "ref-gitignore").splitlines()),
    }

scripts = []
for name in sorted(os.listdir(os.path.join(RUN2, "scripts"))):
    with open(os.path.join(RUN2, "scripts", name), "rb") as f:
        data = f.read()
    scripts.append({
        "series_name": name,
        "published_as": PUBLISHED.get(name),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "copied_into_series_folder": file_time(os.path.join(RUN2, "scripts", name)),
    })
if GUARD:
    with open(GUARD, "rb") as f:
        data = f.read()
    scripts.append({
        "series_name": "gateway-guard.sh (~/.cache/meridian, outside the series folder; guard() in 0008_common2.sh runs it)",
        "published_as": "0008_gateway_guard.sh",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "last_written": file_time(GUARD),
    })
proof_times = {
    stage: file_time_if_kept(os.path.join(RUN2, "proof", name))
    for stage, name in (
        ("install: home snapshot before", "before"),
        ("install: npm install log", "npm-install.log"),
        ("setup: project-scope setup log", "setup-project.log"),
        ("trust: second render", "render-trusted.json"),
        ("exec-noauth probe (in no published script): untrusted", "exec-noauth-untrusted.jsonl"),
        ("exec-noauth probe (in no published script): trusted", "exec-noauth-trusted.jsonl"),
        ("selftrust: last probe", "st-no-hashes.jsonl"),
    )
}

result = {
    "adr": "0008",
    "what": "Run 2 of the oh-my-codex 0.22.6 with/without series in Codex CLI 0.167.2 on 2026-11-13 (04:09 to 04:37 ET): M1 always-on tokens and the real task R1, 3 runs per arm; arm b with oh-my-codex in project scope. Built by 0008_aggregate.py from the run folders, which stay on the owner's machine (not published). M2 (prompt bytes, user scope, run 1) is in 0008-m2.json. Rebuilt twice on 2026-11-13 after the series by the revised script, from the same run folders (see notes).",
    "arm_key": f"{WITH} = with oh-my-codex (0008-key.txt)",
    "m1": {
        "order": ORDER_M1,
        "runs": m1,
        "median_input_tokens_without": statistics.median(m1_a),
        "median_input_tokens_with": statistics.median(m1_b),
        "delta": statistics.median(m1_b) - statistics.median(m1_a),
        "delta_percent_of_without": pct(statistics.median(m1_b), statistics.median(m1_a)),
        "first_request_bytes_delta_by_block": block_delta,
    },
    "r1": {
        "brief": "0008-brief-R1.txt",
        "order": ORDER_R1,
        "runs": r1,
        "without": A,
        "with": B,
        "with_vs_without_total_tokens_percent": {
            "by_sum": pct(B["total_tokens_sum"], A["total_tokens_sum"]),
            "by_median": pct(B["total_tokens_median"], A["total_tokens_median"]),
        },
        "extension_runs_needed": extend,
    },
    "rule": {
        "text": "adopt only if b passes more R1 runs (2 of 3 against at most 1, after any extension), or both pass every run and b uses at least 25 % fewer total tokens; and containment passes, no tests/ edit, no auto-nudge continuation, no write outside the run's worktree",
        "b_passes_more": more_passes,
        "both_pass_all_and_b_25_percent_fewer_tokens": fewer_tokens,
        "own_clone_and_owner_trust_checks_clean": clean,
        "containment_as_applied": contained,
        "containment_as_preregistered": prereg_contained,
        "result": "undecided: run the extension" if extend else ("adopt" if (more_passes or fewer_tokens) and clean and contained and prereg_contained else "not adopted"),
    },
    "setup_proof": {
        "clone_at_main_9c5daaa_before_after_setup": {
            k: [before.get(k, ("-", None))[1], after.get(k, ("-", None))[1]]
            for k in ("AGENTS.md", ".gitignore", ".codex/config.toml", ".codex/hooks.json")
        },
        "codex_agents_toml": sum(1 for k in after if re.fullmatch(r"\.codex/agents/[^/]+\.toml", k)),
        "codex_prompts_md": sum(1 for k in after if re.fullmatch(r"\.codex/prompts/[^/]+\.md", k)),
        "codex_skill_folders": sum(1 for k, v in after.items() if re.fullmatch(r"\.codex/skills/[^/]+", k) and v[0] == "d"),
        "r1_base_27aa964_without_vs_after_setup": ref,
        "render_without_trust": {"message_bytes": jq(MSGS_JQ, "proof", "render-untrusted.json"), "tool_bytes": jq(TOOLS_JQ, "proof", "render-untrusted.json")},
        "render_with_session_trust_flag": {"message_bytes": jq(MSGS_JQ, "proof", "render-trusted.json"), "tool_bytes": jq(TOOLS_JQ, "proof", "render-trusted.json")},
        "route_proof_file_times": proof_times,
    },
    "cost_tokens": {
        "m1": sum(r["total_tokens"] for r in m1),
        "r1_without": A["total_tokens_sum"],
        "r1_with": B["total_tokens_sum"],
        "all": sum(r["total_tokens"] for r in m1) + A["total_tokens_sum"] + B["total_tokens_sum"],
    },
    "scripts": scripts,
    "notes": [
        "SessionStart text: omx_hook_texts_seen.session_start_exec_env counts the root thread only. 0008_scan_run.py, as run, counted it in every rollout (session_start_text_in_all_rollouts_as_scanned, 2 per b run): the second is the root's text again, in the history a sub-agent inherits (sub_agents[].session_start_text_inherited_own). A sub-agent's own turns are those from the last turn_context before its first token_usage_record; its inherited history holds no token record, so its token counts are its own.",
        "Sub-agent effort: own_turn_contexts are the sub-agent's own turns; the one inherited_turn_context is the root's, copied into its rollout.",
        "Containment as applied, a test chosen after the runs once the pre-registered one had failed: in every run the owner's ~/.codex/config.toml and hooks.json kept their sha256, the [projects] trust-key count and the ab-0008 trust keys were unchanged (R1), none of the omx_paths_checked existed before or after, and no OMX process was left. That is narrower than the pre-registered test (the snapshot must differ only by the ab-0008 worktrees), which no run met: both arms ran in the owner's signed-in ~/.codex (pre-registration change 1), so each wrote its rollouts to ~/.codex/sessions and wrote Codex's state and thread-history logs there (codex_write_ahead_logs_written). codex_databases_rewritten_size_before_after lists the owner's Codex database files whose size or time changed in the run's window, whichever process wrote them.",
        "Script times: copied_into_series_folder is the time each script was copied into the series folder the runs read it from. 0008_proof.sh and 0008_common2.sh are the final versions: the route proof's install stage ran under earlier versions of both, and its setup and trust stages before proof.sh's last edit (route_proof_file_times). The exec-noauth probe was run by hand and its command was not kept, so no published script makes its files; a re-run records its two times as null.",
        "Stop auto-nudge: omx_hook_texts_seen.stop_auto_nudge counts 0008_scan_run.py's needle, the Stop hook's systemMessage; stop_auto_nudge_reason_text counts the block reason that would continue the turn (auto-nudge.ts DEFAULT_AUTO_NUDGE_RESPONSE at the pin) in every line of the run's event stream and of its root and sub-agent rollouts. The rule's no-auto-nudge condition (own_clone_and_owner_trust_checks_clean) requires both to be 0.",
        "Questions and sleeps: user_input_requests counts the agent's calls to Codex's request_user_input_async, with Codex's answers; in headless exec nobody replies. sleep_calls lists calls to Codex's sleep tool, with the wall time it reported and the input tokens of the next model request, which reads its result. seconds_without_sleep is the run's seconds less seconds_idle_in_sleep (the reported sleep times, summed and rounded). A sub-agent's calls are counted in its own turns only, not in the history it inherits.",
    ],
}

with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(result, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(json.dumps({"m1_delta": result["m1"]["delta"], "passes": [A["passed"], B["passed"]], "tokens_percent": result["r1"]["with_vs_without_total_tokens_percent"], "rule": result["rule"]["result"]}))
