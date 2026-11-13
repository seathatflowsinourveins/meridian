"""Independent reconstruction of the per-call Codex stdin texts and output schemas of dsh-codex-peer @f4882df.

Published copy: it differs from the file as it ran in one respect only. It ran beside its helper
as extract_tools.py; this copy loads the helper under its published name, 0009_extract_tools.py.

Parses string-array literals and object literals out of lib/argv.js, lib/review.js and lib/plan.js
as TEXT (no execution) and re-assembles them the way buildPrompt / buildReviewPrompt / buildPlanPrompt
and JSON.stringify(schema, null, 2) + '\n' (runner.js writeFileAtomic) do.

usage: py -3 -I build_percall.py <plugin src dir> <out dir>
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('xt', str(Path(__file__).resolve().parent / '0009_extract_tools.py'))
xt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xt)


def array_after(text, marker, consts=None):
    i = text.index(marker) + len(marker)
    p = xt.P(text, consts or {}, {})
    p.i = i
    return p.arr()


def obj_after(text, marker):
    i = text.index(marker) + len(marker)
    p = xt.P(text, {}, {})
    p.i = i
    return p.obj()


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    argv_js = (src / 'lib/argv.js').read_text(encoding='utf-8')
    review_js = (src / 'lib/review.js').read_text(encoding='utf-8')
    plan_js = (src / 'lib/plan.js').read_text(encoding='utf-8')
    preamble = '\n'.join(array_after(argv_js, 'export const DEFAULT_PREAMBLE = '))
    # modeInstruction: three `return [ ... ].join(' ')` arrays in order plan, implement, ask
    body = argv_js[argv_js.index('export function modeInstruction'):argv_js.index('export function buildPreamble')]
    arrays = []
    pos = 0
    while True:
        k = body.find('return [', pos)
        if k < 0:
            break
        p = xt.P(body, {}, {})
        p.i = k + len('return ')
        arrays.append(' '.join(p.arr()))
        pos = p.i
    modes = {'plan': arrays[0], 'implement': arrays[1], 'ask': arrays[2]}

    def build_prompt(mode, cwd, prompt):
        sections = [preamble, modes[mode], f'Working directory for this thread: {cwd}', '--- request ---', prompt.strip()]
        return '\n\n'.join(sections) + '\n'

    w = lambda name, text: (out / name).write_text(text, encoding='utf-8', newline='\n')
    for m in ('ask', 'plan', 'implement'):
        w(f'0009-v3-percall-codex-stdin-{m}-skeleton.txt', build_prompt(m, '<cwd>', '<request>'))

    # review prompt (buildReviewPrompt) for an R4-style literal target
    rv = review_js[review_js.index('export function buildReviewPrompt'):]
    p = xt.P(rv, {}, {})
    k = rv.index('const lines = [')
    # the second element is a template literal using ${described}; parse manually
    raw = rv[k + len('const lines = '):rv.index(']', k) + 1]
    target, focus, cwd = 'meridian/boundary.py', 'ways a non-paper login could pass the checks', '<cwd>'
    targets = obj_after(review_js, 'export const REVIEW_TARGETS = Object.freeze(')
    described = targets.get(target, f'the following, read directly from the working tree: {target}')
    lines = []
    for lit in re.findall(r"'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`", raw):
        s = lit[0] if lit[0] else lit[1]
        lines.append(s.replace('${described}', described))
    lines.append(f'Reviewer focus from the Harness agent (weight it heavily, but still report anything severe you find outside it): {focus}')
    lines.append(f'Working directory: {cwd}')
    review_prompt = '\n'.join(lines) + '\n'
    w('0009-v3-percall-codex-review-stdin-R4.txt', build_prompt('ask', cwd, review_prompt))

    review_schema = obj_after(review_js, 'export const REVIEW_SCHEMA = Object.freeze(')
    w('0009-v3-percall-codex-review-output-schema.json', json.dumps(review_schema, indent=2, ensure_ascii=False) + '\n')
    plan_schema = obj_after(plan_js, 'export const PLAN_SCHEMA = Object.freeze(')
    w('0009-v3-percall-codex-plan-output-schema.json', json.dumps(plan_schema, indent=2, ensure_ascii=False) + '\n')

    # plan critique for a one-task self-organizing draft routed to the default owner
    pb = plan_js[plan_js.index('export function buildPlanPrompt'):plan_js.index('export function renderTaskLine')]
    fixed = re.findall(r"^\s{4}'((?:[^'\\]|\\.)*)',\s*$", pb, re.M)
    notes = obj_after(plan_js, 'export const MODE_NOTES = Object.freeze(')
    goal = '<goal>'
    why = 'no routing rule matched, so it stays with the default owner (dsh)'
    head = fixed[:2]
    assert fixed[2:5] == ['', 'Draft split:', ''], fixed[:6]
    tail = fixed[5:]
    plines = [head[0], head[1], f'Goal: {goal}', f"How the split was decided so far: {notes['self-organizing']}.", '',
              'Draft split:', f'- 1. {goal} | owner: dsh | why: {why}', ''] + tail + [f'Working directory: {cwd}']
    plan_prompt = '\n'.join(plines) + '\n'
    w('0009-v3-percall-codex-plan-critique-stdin.txt', build_prompt('ask', cwd, plan_prompt))
    print('modes', {k: len(v) for k, v in modes.items()}, 'fixed plan lines', len(fixed))


if __name__ == '__main__':
    main()
