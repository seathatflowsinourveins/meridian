"""Reconstruct the Claude Code skill-listing lines a plugin adds, from SKILL.md frontmatter.

Usage: py -3 -I reconstruct_listing.py SKILLS_DIR PLUGIN_NAME OUT_DIR PREFIX
Reads <SKILLS_DIR>/<dir>/SKILL.md (data only; executes nothing), parses the YAML frontmatter
keys name / description / when_to_use / disable-model-invocation / user-invocable with a small
parser for the scalar forms used (plain, double-quoted, single-quoted), and writes UTF-8 / LF:
  <PREFIX>-skill-listing.txt          "- <plugin>:<name>: <description>" per model-visible skill
  <PREFIX>-skill-listing-escaped.txt  same, with < and > shown as &lt; and &gt;
  <PREFIX>-manual-skill-names.txt     "- <plugin>:<name>" per disable-model-invocation skill
  <PREFIX>-skills-table.tsv           one row per skill
"""

import json
import os
import sys

CAP = 1536  # skillListingMaxDescChars default (code.claude.com/docs/en/settings-reference)


def parse_scalar(raw, path, key):
    raw = raw.strip()
    if raw.startswith('"'):
        if not raw.endswith('"') or len(raw) < 2:
            raise ValueError(f"{path}: unterminated double-quoted {key}")
        return json.loads(raw)  # YAML double-quoted escapes used here are a JSON subset
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise ValueError(f"{path}: unterminated single-quoted {key}")
        return raw[1:-1].replace("''", "'")
    if raw in ("|", ">", "|-", ">-"):
        raise ValueError(f"{path}: block scalar for {key} not handled")
    if ": " in raw or " #" in raw:
        raise ValueError(f"{path}: plain scalar for {key} contains ': ' or ' #'")
    return raw


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if lines[0].strip() != "---":
        raise ValueError(f"{path}: no frontmatter")
    out = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            break
        if not line or line[0] in " \t-":
            continue  # list items / continuation lines (allowed-tools lists only here)
        key, sep, rest = line.partition(":")
        if not sep:
            raise ValueError(f"{path}: line without key: {line!r}")
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if rest.strip() == "" and nxt.startswith(("  ", "\t")) and not nxt.lstrip().startswith("-"):
            raise ValueError(f"{path}: multi-line value for {key}")
        out[key.strip()] = parse_scalar(rest, path, key.strip()) if rest.strip() else ""
    else:
        raise ValueError(f"{path}: frontmatter not closed")
    return out


def truthy(v):
    return str(v).strip().lower() == "true"


def main(skills_dir, plugin, out_dir, prefix):
    rows, visible, manual = [], [], []
    for d in sorted(os.listdir(skills_dir)):
        p = os.path.join(skills_dir, d, "SKILL.md")
        if not os.path.isfile(p):
            continue
        fm = frontmatter(p)
        name = fm.get("name") or d
        desc = fm.get("description", "")
        wtu = fm.get("when_to_use", "")
        text = desc + ((" " + wtu) if wtu else "")
        dmi = truthy(fm.get("disable-model-invocation", "false"))
        rows.append((name, d, dmi, fm.get("user-invocable", ""), len(text), len(text) > CAP))
        if dmi:
            manual.append(f"- {plugin}:{name}")
        else:
            visible.append(f"- {plugin}:{name}: {text[:CAP]}")
    def write(fname, lines):
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    write(f"{prefix}-skill-listing.txt", visible)
    write(f"{prefix}-skill-listing-escaped.txt",
          [s.replace("<", "&lt;").replace(">", "&gt;") for s in visible])
    write(f"{prefix}-manual-skill-names.txt", manual)
    write(f"{prefix}-skills-table.tsv",
          ["name\tdir\tdisable_model_invocation\tuser_invocable\tdesc_chars\tover_cap"]
          + ["\t".join(str(x) for x in r) for r in rows])
    print(f"skills={len(rows)} model_visible={len(visible)} manual_only={len(manual)}")
    print("max desc chars:", max(r[4] for r in rows), "over cap:", sum(1 for r in rows if r[5]))
    for r in rows:
        print("\t".join(str(x) for x in r))


if __name__ == "__main__":
    main(*sys.argv[1:5])
