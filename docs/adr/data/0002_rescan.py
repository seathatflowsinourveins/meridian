"""Recount a series' tool calls by tool_use id and rescan them for leaks (ADR 0002, after the series).

Usage: python3 -I 0002_rescan.py <leak-patterns file> <run folder> [<run folder> ...]

The runners' leak_scan (0002_ab.sh, 0002_ab_r2.sh as run) took {name,input} from the stream and the
transcript and removed duplicates with sort -u. Claude Code 2.1.322's transcript held a second copy of
each call in 5 of the 6 R1 runs, a Bash command with a 'cd <worktree> && ' prefix and an Edit with its
input keys in another order, so those were counted twice. This script keeps one
copy per tool_use id (the stream's), applies the runner's replacements (worktree -> WT, memory folder
-> MEM, own project folder -> OWNPROJ) and the patterns the series ran with, then the pattern added
after the series, ADDED below: the runs' patterns named the Gateway's process and port but not its
folder, ~/Jts. It prints, per run, the calls by tool name, the as-run line counts, and each call
with a hit: its number in the stream, its tool, its description, and which pattern set matched.
It never prints a command or a tool result.
"""

import glob
import json
import os
import re
import sys
from collections import Counter

ADDED = r"Jts|jts\.ini"


def objects(path):
    for line in open(path, encoding="utf-8"):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        stack = [ev]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                yield o
                stack.extend(reversed(list(o.values())))
            elif isinstance(o, list):
                stack.extend(reversed(o))


def compact(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


patterns = re.compile(open(sys.argv[1], encoding="utf-8").read().strip())
added = re.compile(ADDED)
for run in sys.argv[2:]:
    files = sorted(glob.glob(f"{run}/*.stream.jsonl")) + sorted(glob.glob(f"{run}/*.transcript.jsonl")) \
        + sorted(glob.glob(f"{run}/*.session/subagents/*.jsonl"))
    by_id, as_run, wt, mem = {}, set(), None, None
    for f in files:
        for o in objects(f):
            if o.get("type") == "system" and o.get("subtype") == "init" and wt is None:
                wt = o.get("cwd")
            if o.get("type") == "tool_use" and "id" in o:
                call = {"name": o.get("name"), "input": o.get("input")}
                by_id.setdefault(o["id"], call)
                as_run.add(compact(call))
    try:
        mem = json.load(open(f"{run}/settings.json", encoding="utf-8")).get("autoMemoryDirectory")
    except (OSError, ValueError):
        pass
    try:
        proj = open(f"{run}/project-dir-name.txt", encoding="utf-8").read().strip()
    except OSError:
        proj = None

    def scrub(s):
        if wt:
            s = s.replace(wt, "WT")
        if mem:
            s = s.replace(mem, "MEM")
        if proj:
            s = s.replace(f".claude/projects/{proj}", "OWNPROJ")
        return s

    names = Counter(c["name"] for c in by_id.values())
    hits = []
    for i, c in enumerate(by_id.values(), 1):
        s = scrub(compact(c))
        old, new = bool(patterns.search(s)), bool(added.search(s))
        if old or new:
            desc = c["input"].get("description") if isinstance(c["input"], dict) else None
            hits.append((i, c["name"], desc, "as run" if old else "added only", sorted(set(m.group(0) for m in added.finditer(s)))))
    as_run_hits = sum(1 for l in as_run if patterns.search(scrub(l)))
    print(f"== {os.path.basename(run)}: {len(by_id)} tool calls {dict(names)}; as run: {len(as_run)} lines, "
          f"{as_run_hits} hit lines; by id: {sum(1 for h in hits if h[3] == 'as run')} calls hit the run's patterns, "
          f"{sum(1 for h in hits if h[3] == 'added only')} only the added one")
    for h in hits:
        print(f"  call {h[0]} {h[1]} ({h[3]}; added pattern {h[4] or 'no'}): {h[2]!r}")
