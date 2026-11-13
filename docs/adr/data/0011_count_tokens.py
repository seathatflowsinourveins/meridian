"""Offline token counter: o200k_base (default) or cl100k_base, standard library only.

A port of tiktoken's encode_ordinary (tiktoken 0.14.0, src/lib.rs): split the text with the
encoding's regex, look each piece up whole, else merge byte pairs by lowest rank, leftmost first.
The vocabularies are OpenAI's published files, checked against the sha256 pins in
tiktoken_ext/openai_public.py at tag 0.14.0. Unicode classes (\\p{L} and the rest) are built from
Python's unicodedata; \\s is Unicode White_Space, as in Rust's regex crate.

Usage:
  py -3 -I count_tokens.py --self-test
  py -3 -I count_tokens.py [--encoding o200k_base|cl100k_base] FILE [FILE ...]
  py -3 -I count_tokens.py [--encoding ...] -          (reads stdin)
Output, one line per file: chars, utf8_bytes, tokens, chars_per_token, path.
"""

import argparse
import base64
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

VOCAB_DIR = Path(__file__).resolve().parent.parent / "vocab"
PINS = {
    "o200k_base": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
    "cl100k_base": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
}
WHITE_SPACE = [(0x09, 0x0D), (0x20, 0x20), (0x85, 0x85), (0xA0, 0xA0), (0x1680, 0x1680),
               (0x2000, 0x200A), (0x2028, 0x2029), (0x202F, 0x202F), (0x205F, 0x205F),
               (0x3000, 0x3000)]


def _ranges(pred):
    out, start, prev = [], None, None
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            ok = False
        else:
            ok = pred(cp)
        if ok and start is None:
            start = cp
        if not ok and start is not None:
            out.append((start, prev))
            start = None
        prev = cp
    if start is not None:
        out.append((start, 0x10FFFF))
    return out


def _cls_body(ranges):
    def esc(cp):
        return "\\U%08x" % cp
    return "".join(esc(a) if a == b else esc(a) + "-" + esc(b) for a, b in ranges)


def _build_classes():
    cats = {}
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        cats.setdefault(unicodedata.category(chr(cp)), []).append(cp)

    def body(prefixes):
        s = set()
        for c, cps in cats.items():
            if any(c == p or (len(p) == 1 and c.startswith(p)) for p in prefixes):
                s.update(cps)
        return _cls_body(_ranges(lambda cp: cp in s))

    return {
        "L": body(["L"]), "N": body(["N"]), "M": body(["M"]),
        "Lu": body(["Lu"]), "Lt": body(["Lt"]), "Lm": body(["Lm"]),
        "Lo": body(["Lo"]), "Ll": body(["Ll"]), "S": _cls_body(WHITE_SPACE),
    }


def _pattern(name, k):
    L, N, M, S = k["L"], k["N"], k["M"], k["S"]
    up = k["Lu"] + k["Lt"] + k["Lm"] + k["Lo"] + M
    lo = k["Ll"] + k["Lm"] + k["Lo"] + M
    contr = r"(?i:'s|'t|'re|'ve|'m|'ll|'d)?"
    if name == "o200k_base":
        parts = [
            rf"[^\r\n{L}{N}]?[{up}]*[{lo}]+{contr}",
            rf"[^\r\n{L}{N}]?[{up}]+[{lo}]*{contr}",
            rf"[{N}]{{1,3}}",
            rf" ?[^{S}{L}{N}]+[\r\n/]*",
            rf"[{S}]*[\r\n]+",
            rf"[{S}]+(?![^{S}])",
            rf"[{S}]+",
        ]
    elif name == "cl100k_base":
        parts = [
            r"'(?i:[sdmt]|ll|ve|re)",
            rf"[^\r\n{L}{N}]?+[{L}]++",
            rf"[{N}]{{1,3}}+",
            rf" ?[^{S}{L}{N}]++[\r\n]*+",
            rf"[{S}]++\Z",
            rf"[{S}]*[\r\n]",
            rf"[{S}]+(?![^{S}])",
            rf"[{S}]",
        ]
    else:
        raise SystemExit(f"unknown encoding {name}")
    return re.compile("|".join(parts))


def load_ranks(name, vocab_dir=VOCAB_DIR):
    path = vocab_dir / f"{name}.tiktoken"
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != PINS[name]:
        raise SystemExit(f"{path}: sha256 {digest} does not match tiktoken 0.14.0's pin")
    ranks = {}
    for line in data.splitlines():
        if line:
            tok, rank = line.split()
            ranks[base64.b64decode(tok)] = int(rank)
    return ranks


def _bpe(piece, ranks):
    parts = [piece[i:i + 1] for i in range(len(piece))]
    while len(parts) > 1:
        best, best_i = None, -1
        for i in range(len(parts) - 1):
            r = ranks.get(parts[i] + parts[i + 1])
            if r is not None and (best is None or r < best):
                best, best_i = r, i
        if best is None:
            break
        parts[best_i:best_i + 2] = [parts[best_i] + parts[best_i + 1]]
    return [ranks[p] for p in parts]


class Encoder:
    def __init__(self, name, vocab_dir=VOCAB_DIR):
        self.name = name
        self.ranks = load_ranks(name, vocab_dir)
        self.regex = _pattern(name, _build_classes())

    def encode(self, text):
        out = []
        for m in self.regex.finditer(text):
            piece = m.group(0).encode("utf-8", errors="surrogatepass")
            tok = self.ranks.get(piece)
            if tok is not None:
                out.append(tok)
            else:
                out.extend(_bpe(piece, self.ranks))
        return out

    def split(self, text):
        return [m.group(0) for m in self.regex.finditer(text)]


def self_test():
    cl = Encoder("cl100k_base", VOCAB_DIR)
    vectors = {  # tiktoken 0.14.0 tests/test_encoding.py
        "hello world": [15339, 1917], "rer": [38149], "'rer": [2351, 81],
        "today\n ": [31213, 198, 220], "today\n \n": [31213, 27907],
        "today\n  \n": [31213, 14211], " \x850": [220, 126, 227, 15],
        "\U0001f44d": [9468, 239, 235],
    }
    ok = True
    for text, want in vectors.items():
        got = cl.encode(text)
        ok &= got == want
        print("cl100k", repr(text), got, "OK" if got == want else f"FAIL want {want}")
    o2 = Encoder("o200k_base", VOCAB_DIR)
    text = "This is a test         with a lot of spaces"  # tiktoken-rs v0.12.1 tests/tiktoken.rs
    want = [2500, 382, 261, 1746, 269, 483, 261, 3261, 328, 18608]
    want_split = ["This", " is", " a", " test", "        ", " with", " a", " lot", " of", " spaces"]
    got, got_split = o2.encode(text), o2.split(text)
    ok &= got == want and got_split == want_split
    print("o200k", repr(text), got, "OK" if got == want else f"FAIL want {want}")
    print("o200k split", "OK" if got_split == want_split else f"FAIL {got_split}")
    for big in ["^", "0", "a", "'s", " ", "\n"]:  # catastrophic-repetition cases, decode round trip
        for enc in (cl, o2):
            inv = {v: k for k, v in enc.ranks.items()} if not hasattr(enc, "inv") else enc.inv
            enc.inv = inv
            s = " " + big * 2000
            rt = b"".join(inv[t] for t in enc.encode(s)).decode("utf-8")
            ok &= rt == s
    print("round trips", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoding", default="o200k_base", choices=sorted(PINS))
    ap.add_argument("--vocab-dir", default=None, help="folder holding <encoding>.tiktoken")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()
    if a.vocab_dir:
        global VOCAB_DIR
        VOCAB_DIR = Path(a.vocab_dir)
    if a.self_test:
        return self_test()
    enc = Encoder(a.encoding, VOCAB_DIR)
    total_c = total_t = 0
    for f in a.files:
        text = sys.stdin.read() if f == "-" else Path(f).read_text(encoding="utf-8")
        n = len(enc.encode(text))
        c = len(text)
        total_c += c
        total_t += n
        ratio = (c / n) if n else 0.0
        print(f"{c}\t{len(text.encode('utf-8'))}\t{n}\t{ratio:.2f}\t{a.encoding}\t{f}")
    if len(a.files) > 1:
        print(f"{total_c}\t-\t{total_t}\t{(total_c / total_t) if total_t else 0:.2f}\t{a.encoding}\tTOTAL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
