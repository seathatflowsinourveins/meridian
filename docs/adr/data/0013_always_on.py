"""ADR 0013: rebuild the always-on texts agy loads from this repository, and count them.

agy puts the whole AGENTS.md in its system prompt on every turn, and the name and description
of each .agents/skills/<name>/SKILL.md. agy's own framing of the skill list is not published;
it is written here as "- <name>: <description>" per line, a folded (>-) description joined
with single spaces. Standard library only; run it from a clone of the public repository:

  python3 -I docs/adr/data/0013_always_on.py --repo . --out OUT \
      --counter docs/adr/data/0013_count_tokens.py --vocab-dir VOCAB [--builtin DIR]

VOCAB holds OpenAI's o200k_base.tiktoken (the counter checks its sha256). --builtin names the
installed agy's built-in skills folder (~/.gemini/antigravity-cli/builtin/skills); that text
is Google's, so it is counted and hashed here but never committed. The JSON on stdout holds
every text figure of 0013-results.json's "always_on" block (each text's chars, bytes, sha256
and o200k tokens, and the AGENTS.md blob ids), not the block itself: its layout, notes and the
counter and vocabulary digests were written by hand.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

MAIN = "9c5daaae9d32acf259f965fd7b95b458604503b6"  # main with PR #1 and #2, 2026-11-13
READ = "f65d835ee39ca716ee0348db33e173d896ba3b47"  # main at the reading, 2026-11-12
R1_START = "27aa964df79d646027d0060eb4d3a14bd49dae8f"  # R1's start commit (ab-tasks.md)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout


def frontmatter(text):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out, key, block = {}, None, []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if key and (line.startswith((" ", "\t")) or not line.strip()):
            block.append(line.strip())
            continue
        if key:
            out[key] = " ".join(x for x in block if x)
            key, block = None, []
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            v = v.strip()
            if v in (">", ">-", "|", "|-"):
                key = k.strip()
            else:
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1].replace("''", "'") if v[0] == "'" else v[1:-1]
                out[k.strip()] = v
    if key:
        out[key] = " ".join(x for x in block if x)
    return out


def listing(skills):
    """skills: [(folder, SKILL.md text)], sorted by folder."""
    rows = []
    for folder, text in sorted(skills):
        fm = frontmatter(text)
        rows.append(f"- {fm.get('name') or folder}: {fm.get('description', '')}\n")
    return "".join(rows)


def repo_skills(repo, commit):
    names = git(repo, "ls-tree", "-r", "--name-only", commit, "--", ".agents/skills")
    out = []
    for path in names.decode().splitlines():
        parts = path.split("/")
        if len(parts) == 4 and parts[3] == "SKILL.md":
            out.append((parts[2], git(repo, "show", f"{commit}:{path}").decode("utf-8")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--counter", required=True)
    ap.add_argument("--vocab-dir", required=True)
    ap.add_argument("--builtin", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)

    agents = {c: git(a.repo, "show", f"{c}:AGENTS.md").decode("utf-8")
              for c in (MAIN, READ, R1_START)}
    lst = listing(repo_skills(a.repo, MAIN))
    texts = {
        "agents-main": (agents[MAIN], f"AGENTS.md at {MAIN}"),
        "skills-listing-main": (lst, f".agents/skills/*/SKILL.md at {MAIN}, as listed"),
        "total-main": (agents[MAIN] + lst, "AGENTS.md + listing at main: what agy loads now"),
        "agents-reading": (agents[READ], f"AGENTS.md at {READ} (the reading)"),
        "agents-r1-start": (agents[R1_START], f"AGENTS.md at {R1_START} (R1 'with' arm)"),
        "total-r1-with": (agents[R1_START] + lst, "R1 'with' arm: start AGENTS.md + listing"),
    }
    if a.builtin:
        root = Path(a.builtin).expanduser()
        skills = [(p.parent.name, p.read_text(encoding="utf-8"))
                  for p in sorted(root.glob("*/SKILL.md"))]
        texts["agy-builtin-listing"] = (listing(skills),
                                        f"{len(skills)} built-in SKILL.md files, as listed")

    result = {}
    for name, (text, what) in texts.items():
        f = out / f"{name}.txt"
        f.write_bytes(text.encode("utf-8"))
        result[name] = {"what": what, "chars": len(text), "bytes": len(text.encode("utf-8")),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        cnt = subprocess.run([sys.executable, "-I", a.counter, "--vocab-dir", a.vocab_dir,
                              str(f)], check=True, capture_output=True, text=True).stdout
        result[name]["tokens_o200k"] = int(cnt.split("\t")[2])
    for c in (MAIN, READ, R1_START):
        result.setdefault("blobs", {})[c] = git(a.repo, "rev-parse", f"{c}:AGENTS.md").decode().strip()
    json.dump(result, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
