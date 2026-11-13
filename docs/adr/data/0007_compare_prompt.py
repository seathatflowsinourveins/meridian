"""Compare two `codex debug prompt-input` renders section by section (texts only).

usage: python3 -I compare_prompt.py <before.json> <after.json>
Prints, per item: type/role, a short label, UTF-8 byte length in each render and whether
the texts are byte-identical. Item ids and create_time are ignored. Prints no item text.
"""

import json
import sys


def items(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for it in data:
        kind = it.get("type")
        if kind == "message":
            text = "".join(c.get("text", "") for c in it.get("content", []) if isinstance(c, dict))
            label = text.lstrip()[:28].split("\n")[0]
            out.append((f"message/{it.get('role')}", label, text))
        elif kind == "additional_tools":
            text = json.dumps(it.get("tools"), sort_keys=True, ensure_ascii=False)
            out.append(("additional_tools", f"{len(it.get('tools') or [])} tools", text))
        else:
            clean = {k: v for k, v in it.items() if k not in ("id", "create_time")}
            out.append((str(kind), "", json.dumps(clean, sort_keys=True, ensure_ascii=False)))
    return out


a, b = items(sys.argv[1]), items(sys.argv[2])
print(f"items: before {len(a)} after {len(b)}")
tot_a = tot_b = 0
for i in range(max(len(a), len(b))):
    ka, la, ta = a[i] if i < len(a) else ("-", "", "")
    kb, lb, tb = b[i] if i < len(b) else ("-", "", "")
    ba, bb = len(ta.encode("utf-8")), len(tb.encode("utf-8"))
    tot_a += ba
    tot_b += bb
    same = "identical" if (ka == kb and ta == tb) else "DIFFERENT"
    print(f"{i}\t{ka}\t{la!r}\t{ba}\t{bb}\t{same}")
print(f"total_bytes\t{tot_a}\t{tot_b}\tdelta {tot_b - tot_a}")
for needle in ("codex-security", "codex_security", "ab-0007-pinned", "openai-curated"):
    print(f"mentions {needle!r}: before {sum(t.count(needle) for _, _, t in a)} after {sum(t.count(needle) for _, _, t in b)}")
