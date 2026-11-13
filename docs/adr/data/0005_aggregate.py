"""Aggregate ADR 0005 runs. Usage: py -3 -I aggregate.py <collected.json> <with-letter>
collected.json: {"ok": {name: metrics}, "r1": {name: summary}} as exported from the distro."""
import json
import statistics
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
with_letter = sys.argv[2]


def arm_of(name):
    return "with" if name.startswith(with_letter + "-") else "without"


ok = {"with": [], "without": []}
for name, m in sorted(data["ok"].items()):
    valid = m["num_turns"] == 1 and not m["is_error"] and m["terminal_reason"] == "completed"
    ok[arm_of(name)].append((name, m["result_input_all"], valid))
print("always-on:", ok)
mw = statistics.median(v for _, v, ok_ in ok["with"] if ok_)
mo = statistics.median(v for _, v, ok_ in ok["without"] if ok_)
print(f"median with {mw}, without {mo}, delta {mw - mo} ({(mw - mo) / mo * 100:.2f}% of without)")

r1 = {"with": [], "without": []}
for name, s in sorted(data["r1"].items()):
    r1[arm_of(name)].append((name, s))
for arm in ("without", "with"):
    rows = r1[arm]
    print(f"\n{arm}: {len(rows)} runs")
    for name, s in rows:
        print(f"  {name}: passed={s['passed']} turns={s['num_turns']} tokens_all={s['tokens_all']} dur_s={s['duration_ms']/1000:.0f} "
              f"tr={s['terminal_reason']} flags={s['containment_flags']!r} leaks={s['leak_hits']} cost={s['total_cost_usd']}")
    if rows:
        print("  passes:", sum(1 for _, s in rows if s["passed"]),
              "median turns:", statistics.median(s["num_turns"] for _, s in rows),
              "median tokens:", statistics.median(s["tokens_all"] for _, s in rows),
              "median dur_s:", statistics.median(s["duration_ms"] / 1000 for _, s in rows),
              "sum tokens:", sum(s["tokens_all"] for _, s in rows),
              "sum cost:", round(sum(s["total_cost_usd"] or 0 for _, s in rows), 4))
