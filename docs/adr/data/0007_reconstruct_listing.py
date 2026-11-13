"""Reconstruct the Codex 0.167.2 skill-listing lines a plugin adds (host catalog, CORE_COMPATIBLE).

Follows codex-rs at ce21072: skills/src/parser.rs (frontmatter, split_whitespace join),
ext/skills/src/render.rs (line format, 1,024-char description cap, sort by name),
ext/skills/src/aliases.rs (root line "- `rN` = `<root>`"), loader/namespace.rs ("{plugin}:{name}").

Usage: py -3 -I reconstruct_listing.py PLUGIN_DIR NAMESPACE ROOT ALIAS OUT_ALIASED OUT_UNALIASED
Writes UTF-8 with LF. Prints per-skill notes to stdout.
"""
import sys
from pathlib import Path

import yaml

MAX_DESC = 1024


def sanitize(raw):
    return " ".join(str(raw).split())


def frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    body = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(body)
        body.append(line)
    return None


def repair(fm):
    # Line-oriented quoting of 'key: value: more' scalars, as parser.rs does on a YAML error.
    out, changed = [], False
    for line in fm.split("\n"):
        if ":" not in line:
            out.append(line)
            continue
        key, value = line.split(":", 1)
        if not key.strip() or (value and not value[0].isspace()):
            out.append(line)
            continue
        scalar = value.strip()
        if not scalar or scalar[0] in "|>'\"":
            out.append(line)
            continue
        if ": " in scalar:
            out.append(f"{key}: '" + scalar.replace("'", "''") + "'")
            changed = True
        else:
            out.append(line)
    return "\n".join(out) if changed else None


def parse(path):
    text = path.read_text(encoding="utf-8")
    fm = frontmatter(text)
    if fm is None:
        raise ValueError(f"no frontmatter: {path}")
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError:
        fixed = repair(fm)
        if fixed is None:
            raise
        data = yaml.safe_load(fixed)
    name = sanitize(data.get("name") or "") or path.parent.name
    desc = sanitize(data.get("description") or "")
    if len(desc) > MAX_DESC:
        desc = desc[: MAX_DESC - 3] + "..."
    return name, desc


def main():
    plugin_dir, ns, root, alias, out_a, out_u = sys.argv[1:7]
    skills_dir = Path(plugin_dir) / "skills"
    rows = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        name, desc = parse(skill_md)
        rel = skill_md.relative_to(Path(plugin_dir)).as_posix()
        rows.append((f"{ns}:{name}", desc, rel))
        print(f"{ns}:{name}\tdesc_chars={len(desc)}\t{rel}")
    rows.sort(key=lambda r: r[0])
    aliased = [f"- `{alias}` = `{root}`"]
    unaliased = []
    for full, desc, rel in rows:
        aliased.append(f"- {full}: {desc} (file: {alias}/{rel})")
        unaliased.append(f"- {full}: {desc} (file: {root}/{rel})")
    Path(out_a).write_bytes(("\n".join(aliased) + "\n").encode("utf-8"))
    Path(out_u).write_bytes(("\n".join(unaliased) + "\n").encode("utf-8"))
    print(f"skills={len(rows)}")


if __name__ == "__main__":
    main()
