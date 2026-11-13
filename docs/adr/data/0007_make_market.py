"""Build two marketplace manifests for codex-security from openai/plugins' marketplace.json.

usage: python3 -I make_market.py <src marketplace.json> <out pinned.json> <out curated.json>
pinned: renamed marketplace "ab-0007-pinned" holding only the codex-security entry.
curated: the reserved name "openai-curated" with only the codex-security entry.
Reads data only; writes the two output files.
"""

import json
import sys

src, out_pinned, out_curated = sys.argv[1:4]
with open(src, encoding="utf-8") as f:
    market = json.load(f)
entries = [p for p in market["plugins"] if p.get("name") == "codex-security"]
assert len(entries) == 1, entries
entry = entries[0]
assert entry["source"] == {"source": "local", "path": "./plugins/codex-security"}, entry

pinned = {"name": "ab-0007-pinned", "interface": {"displayName": "ab-0007-pinned"}, "plugins": [entry]}
curated = {"name": market["name"], "interface": market.get("interface", {}), "plugins": [entry]}
for path, obj in ((out_pinned, pinned), (out_curated, curated)):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
print("entry", json.dumps(entry, sort_keys=True))
print("curated name", curated["name"])
