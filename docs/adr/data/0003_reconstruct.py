r"""Rebuild the texts a Claude Code plugin skill injects, from a SKILL.md at a pinned commit.

Usage: py -3 -I reconstruct.py PLUGIN_NAME SKILL_MD OUT_DIR PREFIX
Writes (UTF-8, LF):
  PREFIX-listing-item.txt  "- <plugin>:<name>: <description>\n" (assumed listing form)
  PREFIX-skill-body.md     SKILL.md after the frontmatter, leading blank lines dropped, one trailing LF
Prints the parsed frontmatter keys and the description length.
Minimal YAML: only `key: value` scalar lines; double-quoted values get YAML double-quote escapes
(\\ \" \n \t \/ \uXXXX); anything else (block scalars, single quotes with '' escapes, lists) is refused.
"""
import re
import sys
from pathlib import Path


def unquote(v: str) -> str:
    v = v.strip()
    if v.startswith('"'):
        if not v.endswith('"') or len(v) < 2:
            raise SystemExit(f"unterminated double-quoted scalar: {v[:60]}")
        inner = v[1:-1]
        out, i = [], 0
        esc = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "/": "/"}
        while i < len(inner):
            c = inner[i]
            if c == "\\":
                n = inner[i + 1]
                if n in esc:
                    out.append(esc[n]); i += 2; continue
                if n == "u":
                    out.append(chr(int(inner[i + 2:i + 6], 16))); i += 6; continue
                raise SystemExit(f"unsupported escape \\{n}")
            if c == '"':
                raise SystemExit("bare quote inside double-quoted scalar")
            out.append(c); i += 1
        return "".join(out)
    if v.startswith("'") or v.startswith("|") or v.startswith(">") or v.startswith("["):
        raise SystemExit(f"unsupported scalar form: {v[:20]}")
    return v


def main():
    plugin, skill_md, out_dir, prefix = sys.argv[1:5]
    raw = Path(skill_md).read_bytes().decode("utf-8")
    if "\r" in raw:
        raise SystemExit("CR found; refusing")
    lines = raw.split("\n")
    if lines[0] != "---":
        raise SystemExit("no frontmatter")
    end = lines.index("---", 1)
    fm = {}
    for ln in lines[1:end]:
        m = re.match(r"^([A-Za-z0-9_-]+):\s?(.*)$", ln)
        if not m:
            raise SystemExit(f"unparsed frontmatter line: {ln[:60]}")
        fm[m.group(1)] = unquote(m.group(2))
    body_lines = lines[end + 1:]
    while body_lines and body_lines[0].strip() == "":
        body_lines.pop(0)
    body = "\n".join(body_lines).rstrip("\n") + "\n"
    desc = fm["description"]
    listing = f"- {plugin}:{fm['name']}: {desc}\n"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{prefix}-listing-item.txt").write_bytes(listing.encode("utf-8"))
    (out / f"{prefix}-skill-body.md").write_bytes(body.encode("utf-8"))
    print("frontmatter keys:", list(fm))
    print({k: v for k, v in fm.items() if k != "description"})
    print("description chars:", len(desc), "has <>:", "<" in desc or ">" in desc)
    print("body first line:", body_lines[0] if body_lines else "")
    print("frontmatter end line index (1-based closing ---):", end + 1)


if __name__ == "__main__":
    main()
