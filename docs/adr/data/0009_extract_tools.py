"""Independent reconstruction of the five dsh-codex-peer tool schemas as dsh 0.2.2-rc.1 sends them.

Reads the plugin source as TEXT (never executes it), parses the JS object literals of each
tool's name/description/parameters with a small literal parser, resolves the few constants
and spreads used, and writes the DeepSeek wire form {name, description, input_schema}
serialized like JSON.stringify (compact, non-ASCII kept).

usage: py -3 -I extract_tools.py <plugin src dir> <out dir>
"""
import json
import re
import sys
from pathlib import Path


class P:
    def __init__(self, text, consts, funcs):
        self.t = text
        self.i = 0
        self.consts = consts
        self.funcs = funcs

    def ws(self):
        t = self.t
        while self.i < len(t):
            c = t[self.i]
            if c in ' \t\r\n':
                self.i += 1
            elif t.startswith('//', self.i):
                self.i = t.index('\n', self.i)
            elif t.startswith('/*', self.i):
                self.i = t.index('*/', self.i) + 2
            else:
                break

    def peek(self):
        self.ws()
        return self.t[self.i]

    def expect(self, s):
        self.ws()
        if not self.t.startswith(s, self.i):
            raise SyntaxError(f'expected {s!r} at {self.i}: {self.t[self.i:self.i+60]!r}')
        self.i += len(s)

    def ident(self):
        self.ws()
        m = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*').match(self.t, self.i)
        if not m:
            raise SyntaxError(f'ident expected at {self.i}: {self.t[self.i:self.i+60]!r}')
        self.i = m.end()
        return m.group(0)

    def string(self):
        q = self.t[self.i]
        self.i += 1
        out = []
        while True:
            c = self.t[self.i]
            if c == '\\':
                n = self.t[self.i + 1]
                if n == 'u':
                    out.append(chr(int(self.t[self.i + 2:self.i + 6], 16)))
                    self.i += 6
                    continue
                out.append({'n': '\n', 't': '\t', '\\': '\\', "'": "'", '"': '"', '`': '`'}[n])
                self.i += 2
                continue
            if c == q:
                self.i += 1
                return ''.join(out)
            if q == '`' and self.t.startswith('${', self.i):
                end = self.t.index('}', self.i)
                expr = self.t[self.i + 2:end]
                out.append(self.eval_expr(expr))
                self.i = end + 1
                continue
            out.append(c)
            self.i += 1

    def eval_expr(self, expr):
        m = re.fullmatch(r"\s*([A-Z_]+)\.join\('([^']*)'\)\s*", expr)
        if not m:
            raise SyntaxError(f'unsupported template expression {expr!r}')
        return m.group(2).join(self.consts[m.group(1)])

    def value(self):
        c = self.peek()
        if c == '{':
            return self.obj()
        if c == '[':
            return self.arr()
        if c in '\'"`':
            return self.string()
        m = re.compile(r'-?\d+(\.\d+)?').match(self.t, self.i)
        if m:
            self.i = m.end()
            return float(m.group(0)) if '.' in m.group(0) else int(m.group(0))
        name = self.ident()
        if name in ('true', 'false', 'null'):
            return {'true': True, 'false': False, 'null': None}[name]
        if name in self.consts:
            return list(self.consts[name])
        raise SyntaxError(f'unknown identifier {name} at {self.i}')

    def arr(self):
        self.expect('[')
        out = []
        while self.peek() != ']':
            out.append(self.value())
            if self.peek() == ',':
                self.expect(',')
        self.expect(']')
        return out

    def obj(self):
        self.expect('{')
        out = {}
        while self.peek() != '}':
            if self.t.startswith('...', self.i):
                self.i += 3
                fname = self.ident()
                self.expect('(')
                self.expect(')')
                for k, v in self.funcs[fname].items():
                    out[k] = v
            else:
                c = self.peek()
                key = self.string() if c in '\'"' else self.ident()
                self.expect(':')
                out[key] = self.value()
            if self.peek() == ',':
                self.expect(',')
        self.expect('}')
        return out


def body_of_function(text, fname):
    """Return the text after 'function fname(...) {' up to the matching 'return {' object start."""
    m = re.search(r'function ' + re.escape(fname) + r'\([^)]*\)\s*\{\s*return\s*', text)
    if not m:
        raise SystemExit(f'function {fname} not found')
    return m.end()


def field_after(text, start, key):
    """Find 'key:' at object top level after start (first occurrence)."""
    m = re.compile(r'\n\s{4}' + re.escape(key) + r':').search(text, start)
    if not m:
        raise SystemExit(f'key {key} not found after {start}')
    return m.end()


def const_list(text, name):
    m = re.search(r'export const ' + name + r' = (\[[^\]]*\])', text)
    return [s for s in re.findall(r"'([^']*)'", m.group(1))]


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rd = lambda p: (src / p).read_text(encoding='utf-8')
    config_js, plan_js, tasks_js = rd('lib/config.js'), rd('lib/plan.js'), rd('lib/tasks.js')
    tools_js, ptools_js = rd('lib/tools.js'), rd('lib/planning-tools.js')
    consts = {
        'MODES': const_list(config_js, 'MODES'),
        'SANDBOXES': const_list(config_js, 'SANDBOXES'),
        'PLAN_MODES': const_list(plan_js, 'PLAN_MODES'),
        'TASK_STATUSES': const_list(tasks_js, 'TASK_STATUSES'),
        'EVIDENCE_KINDS': const_list(tasks_js, 'EVIDENCE_KINDS'),
    }
    funcs = {}
    for text, fname in ((tools_js, 'commonProperties'), (ptools_js, 'runProperties')):
        p = P(text, consts, funcs)
        p.i = body_of_function(text, fname)
        funcs[fname] = p.obj()
    tools = []
    for text, fname in ((tools_js, 'codexAskTool'), (tools_js, 'codexReviewTool'), (tools_js, 'codexStatusTool'),
                        (ptools_js, 'codexPlanTool'), (ptools_js, 'codexTaskTool')):
        start = body_of_function(text, fname)
        rec = {}
        for key in ('name', 'description', 'parameters'):
            p = P(text, consts, funcs)
            p.i = field_after(text, start, key)
            rec[key] = p.value()
        tools.append(rec)
    wire = [{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters']} for t in tools]
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(',', ':'))
    (out / '0009-v3-always-on-tools.wire.json').write_text(dump(wire), encoding='utf-8', newline='\n')
    for w in wire:
        (out / f"0009-v3-tool-{w['name']}.wire.json").write_text(dump(w), encoding='utf-8', newline='\n')
    listing = '\n'.join(f"- {t['name']}: {t['description']}" for t in tools) + '\n'
    (out / '0009-v3-always-on-tools.listing.txt').write_text(listing, encoding='utf-8', newline='\n')
    print('consts', consts)
    for w in wire:
        print(w['name'], len(dump(w)), 'chars; top-level params:', list(w['input_schema'].get('properties', {}).keys()))
    print('array chars', len(dump(wire)), 'sum of elements', sum(len(dump(w)) for w in wire))


if __name__ == '__main__':
    main()
