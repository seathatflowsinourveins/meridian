"""Print only the count of [projects] trust keys in a Codex config.toml and those naming ab-0008 paths.

No values are printed (paths of ab-0008 run clones only). Usage: python3 -I trust_keys.py CONFIG_TOML
"""
import sys
import tomllib

with open(sys.argv[1], "rb") as f:
    d = tomllib.load(f)
p = d.get("projects") or {}
print("projects_keys_total", len(p))
for k in sorted(p):
    if "ab-0008" in k:
        print("ab0008_key", k)
