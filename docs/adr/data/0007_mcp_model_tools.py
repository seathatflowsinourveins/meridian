"""List the MCP tools codex-security's main stdio server registers, and which the model sees.

Reads the decompressed bundle as text only (never executes it). The main server is
createCodexSecurityServer(); the bundle uses it unless --artifact-writer is passed. Tools come
from three kinds of site, followed from that function through every `registerXxx(server, ...)`
helper it calls, recursively:
- `server.registerTool("<name>", {... _meta ...})`: visible to the model when `_meta` is or
  spreads `modelActionMeta` or `modelOnlyMeta` ({ui: {visibility: ["model"]}}), app-only when it
  is `appMeta`;
- `registerCompactTool(server, {name: "<name>", ...})`: the helper always passes
  `_meta: modelOnlyMeta`, so these are visible to the model (checked below);
- the description is a double-quoted literal, possibly joined with +.
The first version of this script (ADR 0007's first draft) counted only literal-name
`server.registerTool` sites with `modelActionMeta`, anywhere in the bundle: 39 sites, 12 visible.
Usage: py -3 -I 0007_mcp_model_tools.py BUNDLE OUT_TXT OUT_TSV
"""
import json
import re
import sys
from pathlib import Path

FUNC = re.compile(r"^(?:async )?function (\w+)\(", re.M)
DIRECT = re.compile(r'server\.registerTool\(\s*"([^"]+)",\s*\{')
COMPACT = re.compile(r'registerCompactTool\(server,\s*\{\s*name:\s*"([^"]+)"')
CALL = re.compile(r"\b(register\w+)\(server\b")
DESC = re.compile(r'\bdescription:\s*((?:"(?:[^"\\]|\\.)*"\s*\+?\s*)+)')
MODEL_META = ("modelActionMeta", "modelOnlyMeta")


def functions(text):
    """Top-level function name -> its text (to the next top-level function)."""
    marks = [(m.group(1), m.start()) for m in FUNC.finditer(text)]
    out = {}
    for i, (name, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out.setdefault(name, text[start:end])
    return out


def description(window):
    d = DESC.search(window)
    if not d:
        return ""
    return "".join(json.loads(p) for p in re.findall(r'"(?:[^"\\]|\\.)*"', d.group(1)))


def collect(funcs, name, seen, rows):
    if name in seen or name == "registerCompactTool":
        return
    seen.add(name)
    body = funcs[name]
    sites = []
    for m in DIRECT.finditer(body):
        window = body[m.end(): m.end() + 6000]
        meta_at = window.find("_meta")
        meta = window[meta_at: meta_at + 200]
        model = any(k in meta for k in MODEL_META)
        app = "appMeta" in meta and not model
        sites.append((m.start(), m.group(1), model, app, description(window[:meta_at]), name, "registerTool"))
    for m in COMPACT.finditer(body):
        window = body[m.end(): m.end() + 6000]
        sites.append((m.start(), m.group(1), True, False, description(window[: window.find("inputSchema")]),
                      name, "registerCompactTool"))
    calls = [(m.start(), m.group(1)) for m in CALL.finditer(body) if m.group(1) in funcs]
    for pos, kind in sorted([(s[0], ("site", s)) for s in sites] + [(c[0], ("call", c[1])) for c in calls]):
        if kind[0] == "site":
            rows.append(kind[1][1:])
        else:
            collect(funcs, kind[1], seen, rows)


def main():
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    funcs = functions(text)
    helper = funcs["registerCompactTool"]
    assert "_meta: modelOnlyMeta" in helper, "registerCompactTool no longer passes modelOnlyMeta"
    assert re.search(r'modelOnlyMeta = \{\s*ui: \{ visibility: \["model"\] \}', text), "modelOnlyMeta changed"
    assert 'const modelActionMeta = { ui: { visibility: ["model"] } }' in funcs["createCodexSecurityServer"]
    assert 'artifactWriter ? await createCodexSecurityArtifactWriterServer() : createCodexSecurityServer()' in text
    rows = []
    collect(funcs, "createCodexSecurityServer", set(), rows)
    names = [r[0] for r in rows]
    assert len(names) == len(set(names)), "a tool name registered twice"
    assert all(r[3] for r in rows), "a tool without a description literal"
    Path(sys.argv[3]).write_text(
        "name\tmodel\tapp_only\tdesc_chars\tfunction\tsite\n"
        + "".join(f"{r[0]}\t{r[1]}\t{r[2]}\t{len(r[3])}\t{r[4]}\t{r[5]}\n" for r in rows),
        encoding="utf-8", newline="\n")
    vis = [r for r in rows if r[1]]
    Path(sys.argv[2]).write_bytes(("\n".join(f"- {r[0]}: {r[3]}" for r in vis) + "\n").encode("utf-8"))
    sites_anywhere = len(re.findall(r'server\.registerTool\(\s*"', text))
    print(f"tools={len(rows)} model_visible={len(vis)} app_only={sum(1 for r in rows if r[2])} "
          f"direct={sum(1 for r in rows if r[5] == 'registerTool')} "
          f"compact={sum(1 for r in rows if r[5] == 'registerCompactTool')} "
          f"literal_registerTool_sites_in_bundle={sites_anywhere}")
    for r in vis:
        print(r[0], len(r[3]), r[4], r[5])


if __name__ == "__main__":
    main()
