"""Where does openai/plugins' codex-security copy come from? Compare SKILL.md blob ids only.

usage: python3 -I 0007_provenance.py <blob-less clone of openai/plugins> <blob-less clone of
openai/codex-security> [<plugins commit, default d420d13051bffe4543ed39e30fa46b87148e47dd>]

Reads tree entries with `git ls-tree` (blob ids are hashes of the file bytes, so no file
content is downloaded or read). Prints how many of the copy's SKILL.md files match each
upstream npm-v* tag, and which commits on upstream main's first-parent line match all of
them (and whether they are consecutive). Writes nothing.
"""

import subprocess
import sys

PLUGINS, UPSTREAM = sys.argv[1], sys.argv[2]
PIN = sys.argv[3] if len(sys.argv) > 3 else "d420d13051bffe4543ed39e30fa46b87148e47dd"
PREFIX = "plugins/codex-security/skills/"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                          text=True).stdout


def skills(repo, rev):
    out = {}
    for line in git(repo, "ls-tree", "-r", rev, "--", PREFIX).splitlines():
        meta, path = line.split("\t", 1)
        if path.endswith("/SKILL.md"):
            out[path[len(PREFIX):]] = meta.split()[2]
    return out


copy = skills(PLUGINS, PIN)
print(f"copy at {PIN[:9]}: {len(copy)} SKILL.md")


def score(rev):
    up = skills(UPSTREAM, rev)
    return sum(1 for k, v in copy.items() if up.get(k) == v)


tags = [t for t in git(UPSTREAM, "tag", "--list", "npm-v*").split() if t]
best = []
for t in tags:
    n = score(t)
    best.append((n, t))
    if t in ("npm-v0.1.31", "npm-v0.1.32", "npm-v0.2.0", "npm-v0.2.1", "npm-v0.10.0"):
        date = git(UPSTREAM, "log", "-1", "--format=%h %cI %s", t).strip()
        print(f"tag {t}: {n}/{len(copy)}  ({date})")
best.sort(reverse=True)
print("npm-v* tags:", len(tags), "best:", best[:3])

rows = git(UPSTREAM, "rev-list", "--first-parent", "--format=%h %cI", "HEAD").splitlines()
line = [r.split() for r in rows if not r.startswith("commit ")]
line.reverse()  # oldest first
full = [(i, h, d) for i, (h, d) in enumerate(line) if score(h) == len(copy)]
print("first-parent commits on main:", len(line), "matching all:", len(full))
if full:
    idx = [i for i, _, _ in full]
    print("consecutive:", idx == list(range(idx[0], idx[-1] + 1)))
    print("first:", full[0][1], full[0][2], " last:", full[-1][1], full[-1][2])
    before = line[idx[0] - 1] if idx[0] > 0 else None
    after = line[idx[-1] + 1] if idx[-1] + 1 < len(line) else None
    print("just before:", before, score(before[0]) if before else "-")
    print("just after:", after, score(after[0]) if after else "-")
