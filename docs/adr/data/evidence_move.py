"""Move the historical evidence mechanically; run with --apply, then --check.

From the repository root: ``uv run python docs/adr/data/evidence_move.py --check``.
The default --base is origin/main (before this move); --base also accepts its
commit ID for reproducing the proof after the move has landed on main.
Only link destinations change in records; short ADRs retain the original text
with links relative to their original directory. No evidence commands are run.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
STUDY = "docs/m3-alpaca.md"
DATA = "docs/adr/data/"
LINK = re.compile(r"(?<=\]\()([^\s)]+)")
FORMAT = (
    "An ADR decided by the earlier with-and-without method keeps its status, candidate and "
    "decision in its own file and its full text in `data/NNNN-record.md`.\n"
)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def original(base: str, name: str) -> str:
    return git("show", f"{base}:{name}").decode("utf-8")


def moves(base: str) -> dict[str, str]:
    names = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    adrs = [n for n in names if re.fullmatch(r"docs/adr/00(?:0[1-9]|1[0-3])-[^/]+\.md", n)]
    assert len(adrs) == 13, "base must contain the 13 original ADRs"
    return {STUDY: DATA + "m3-alpaca.md"} | {
        n: DATA + Path(n).name[:4] + "-record.md" for n in sorted(adrs)
    }


def section(text: str, title: str) -> str:
    match = re.search(rf"^## {title}\n.*?(?=^## |\Z)", text, re.M | re.S)
    assert match, f"missing {title}"
    return match[0].rstrip("\n")


def short_adr(text: str, record: str) -> str:
    title = text.splitlines()[0]
    status = next(line for line in text.splitlines() if line.startswith("**Status:"))
    candidate = section(text, "Candidate").split("\n\n")[:2]
    decision = section(text, "Decision")
    return (
        "\n\n".join(
            [
                title,
                status,
                "\n\n".join(candidate),
                decision,
                f"Full record: [data/{Path(record).name}](data/{Path(record).name})",
            ]
        )
        + "\n"
    )


def relative_target(name: str, target: str) -> str | None:
    url = urlsplit(target)
    if url.scheme or url.netloc or target.startswith("/"):
        return None
    return os.path.normpath(str(Path(name).parent / unquote(url.path))) if url.path else name


def heading_ids(text: str) -> set[str]:
    return {
        re.sub(r"[^\w\- ]", "", line.lstrip("# ").lower()).replace(" ", "-")
        for line in text.splitlines()
        if line.startswith("#")
    }


def rewrite_links(
    text: str, old: str, new: str, mapping: dict[str, str], shorts: dict[str, str]
) -> str:
    def replace(match: re.Match[str]) -> str:
        target = match[0]
        path = relative_target(old, target)
        if path is None:
            return target
        url = urlsplit(target)
        destination = mapping[STUDY] if path == STUDY else path
        # Line references are unstable after extraction; missing headings live in records.
        if (
            path in shorts
            and url.fragment
            and (
                re.fullmatch(r"L?\d+(?:-L?\d+)?", url.fragment)
                or unquote(url.fragment) not in heading_ids(shorts[path])
            )
        ):
            destination = mapping[path]
        if old == new and destination == path:
            return target
        relative = os.path.relpath(destination, Path(new).parent)
        if not url.path and destination == new:
            relative = ""
        return (
            relative
            + ("?" + url.query if url.query else "")
            + ("#" + url.fragment if url.fragment else "")
        )

    return LINK.sub(replace, text)


def reference_files(mapping: dict[str, str]) -> list[str]:
    # Names only: do not open unrelated data or any protected/credential file.
    pattern = "|".join(re.escape(Path(n).name) for n in mapping)
    result = subprocess.run(
        [
            "git",
            "grep",
            "-Ilz",
            "-E",
            pattern,
            "--",
            ":!risk",
            ":!upstream",
            ":!local",
            ":!*.contract.json",
            ":!*key*",
            ":!*.env*",
            ":!meridian/order_budget/pacer.py",
            ":!meridian/order_budget/controls.py",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr.decode()
    return [n for n in result.stdout.decode().split("\0") if n]


def references(text: str, name: str, mapping: dict[str, str], shorts: dict[str, str]) -> str:
    text = rewrite_links(text, name, name, mapping, shorts)
    text = text.replace(STUDY, mapping[STUDY])
    for old, new in mapping.items():
        if old == STUDY:
            continue
        # Repository-root citations with a line suffix, outside Markdown links.
        text = re.sub(re.escape(old) + r"(?=:L?\d)", new, text)
    return text


def apply(base: str, mapping: dict[str, str], shorts: dict[str, str]) -> None:
    for old, new in mapping.items():
        before = original(base, old)
        after = rewrite_links(before, old, new, mapping, shorts)
        destination = ROOT / new
        if not destination.exists():
            assert (ROOT / old).read_bytes() == before.encode(), f"local edits in {old}"
            git("mv", old, new)
        else:
            assert destination.read_bytes() == after.encode(), f"local edits in {new}"
        destination.write_bytes(after.encode())
        if old in shorts:
            (ROOT / old).write_bytes(shorts[old].encode())
    for name in reference_files(mapping):
        if (
            name in mapping
            or name in mapping.values()
            or name == str(Path(__file__).relative_to(ROOT))
        ):
            continue
        path = ROOT / name
        before = path.read_text()
        after = references(before, name, mapping, shorts)
        if after != before:
            path.write_text(after)
    readme = ROOT / "docs/adr/README.md"
    text = readme.read_text()
    if FORMAT not in text:
        readme.write_text(text.replace("## Format\n", "## Format\n\n" + FORMAT))


def check(base: str, mapping: dict[str, str], shorts: dict[str, str]) -> None:
    print(f"Base: {git('rev-parse', base).decode().strip()}")
    for old, new in mapping.items():
        before = original(base, old)
        after = (ROOT / new).read_bytes()
        assert after == rewrite_links(before, old, new, mapping, shorts).encode(), new
        old_lines, new_lines = (
            before.encode().splitlines(keepends=True),
            after.splitlines(keepends=True),
        )
        assert len(old_lines) == len(new_lines), new
        changed = 0
        for left, right in zip(old_lines, new_lines, strict=True):
            if left != right:
                # Remove only link destinations: even other bytes on link lines must match.
                assert LINK.search(left.decode()), new
                assert LINK.sub("", left.decode()) == LINK.sub("", right.decode()), new
                changed += 1
        print(
            f"{new}: {changed} link lines differ; "
            f"all other {len(old_lines) - changed} lines byte-identical"
        )
    assert not (ROOT / STUDY).exists(), "old study remains"
    for name, text in shorts.items():
        assert (ROOT / name).read_bytes() == text.encode(), f"short extraction: {name}"
    print("13 short ADRs: title, status, first Candidate paragraph and whole Decision verified")
    readme = (ROOT / "docs/adr/README.md").read_text()
    before_readme = original(base, "docs/adr/README.md")
    assert readme == before_readme.replace("## Format\n", "## Format\n\n" + FORMAT)
    print("ADR README: only the Format sentence added; index unchanged")
    files = set(mapping.values()) | set(shorts) | {"docs/adr/README.md"}
    for name in reference_files(mapping):
        if (
            name in mapping
            or name in mapping.values()
            or name == str(Path(__file__).relative_to(ROOT))
        ):
            continue
        text = (ROOT / name).read_text()
        assert references(text, name, mapping, shorts) == text, f"stale reference: {name}"
        if text != original(base, name) and Path(name).suffix == ".md":
            files.add(name)
    links = 0
    for name in sorted(files):
        # A link shown as inline code (the README's naming example) is not a link.
        markdown = re.sub(r"(`+).*?\1", "", (ROOT / name).read_text())
        for match in LINK.finditer(markdown):
            target = relative_target(name, match[0])
            if target is not None:
                assert (ROOT / target).is_file(), f"broken link in {name}: {match[0]}"
                links += 1
    print(
        f"Relative links: {links} in {len(files)} moved/rewritten files; "
        "all resolve to existing files"
    )
    # Use the actual size test, materializing only the prose it counts from the base.
    sys.path.insert(0, str(ROOT / "tests"))
    from test_size_budget import kind_of, load_limits, measure, tracked_files

    limits = tomllib.loads(original(base, "size-budget.toml"))
    names = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    with tempfile.TemporaryDirectory(prefix="evidence-move-") as folder:
        root = Path(folder)
        for name in names:
            if kind_of(name, limits["kinds"]) == "prose":
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(git("show", f"{base}:{name}"))
        before = measure(names, limits, root)["prose_lines"]
    after = measure(tracked_files(), load_limits(), ROOT)["prose_lines"]
    print(
        f"Markdown total (tests/test_size_budget.py measure): {before} before; "
        f"{after} after; {before - after} freed"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mapping = moves(args.base)
    shorts = {
        old: short_adr(original(args.base, old), new)
        for old, new in mapping.items()
        if old != STUDY
    }
    if args.apply:
        apply(args.base, mapping, shorts)
    else:
        check(args.base, mapping, shorts)


if __name__ == "__main__":
    main()
