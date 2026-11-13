"""
The size budget (plan 9.5): the build fails if the agent instructions, the handbook or an ADR
grow past their line limits, or if the tracked prose, config, workflows or skills grow past
theirs. The limits and what counts as prose or config are in ``size-budget.toml``; raising one
takes a pull request that says why. Every tracked file has to be of a kind the limits file
names, so a new kind of file cannot slip past the totals unseen.

Like the other scans this is a tripwire, not a lock: an agent can edit the limits file too
(see its header). It counts what git sees, new files included, as the paper-only scan does.
"""

import fnmatch
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from test_paper_only import REPO_ROOT
from test_public_tree import tracked_files

LIMITS_FILE = "size-budget.toml"
ADR_DIR = "docs/adr"
ADR_NAME = re.compile(r"^docs/adr/(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
# An index row lists the ADR its first cell links: | [NNNN](NNNN-short-title.md) | ...
INDEX_ROW = re.compile(r"\|\s*\[(\d{4})\]\((\1-[^)\s]+)\)\s*\|")
MARKDOWN = (".md", ".markdown")
INSTRUCTION_FILES = {"agents.md", "claude.md"}
KINDS = ("adr_data", "prose", "not_counted", "config")  # the order in which a file is matched


def load_limits(root: Path = REPO_ROOT) -> dict[str, Any]:
    return tomllib.loads((root / LIMITS_FILE).read_text(encoding="utf-8"))


def lines(name: str, root: Path = REPO_ROOT) -> int:
    return len((root / name).read_text(encoding="utf-8").splitlines())


def matches(name: str, patterns: list[str]) -> bool:
    path, base = name.lower(), PurePosixPath(name).name.lower()
    return any(
        fnmatch.fnmatchcase(path, p.lower()) or fnmatch.fnmatchcase(base, p.lower())
        for p in patterns
    )


def kind_of(name: str, kinds: dict[str, list[str]]) -> str | None:
    return next((kind for kind in KINDS if matches(name, kinds[kind])), None)


def adr_files(names: list[str]) -> list[str]:
    """ADRs: every Markdown file under docs/adr/ but the README and the data/ folder, so one
    put in a subfolder or given another extension is still held to the ADR rules (and fails
    the naming check)."""
    return sorted(
        n
        for n in names
        if n.startswith(f"{ADR_DIR}/") and n.lower().endswith(MARKDOWN)
        if n != f"{ADR_DIR}/README.md" and not n.startswith(f"{ADR_DIR}/data/")
    )


def regular_files(names: list[str], root: Path) -> list[str]:
    return [n for n in names if (root / n).is_file() and not (root / n).is_symlink()]


def measure(names: list[str], limits: dict[str, Any], root: Path = REPO_ROOT) -> dict[str, int]:
    files = regular_files(names, root)
    kinds = {n: kind_of(n, limits["kinds"]) for n in files}
    return {
        "agent_instruction_lines": sum(
            lines(n, root) for n in files if PurePosixPath(n).name.lower() in INSTRUCTION_FILES
        ),
        "prose_lines": sum(lines(n, root) for n in files if kinds[n] == "prose"),
        "config_lines": sum(lines(n, root) for n in files if kinds[n] == "config"),
        "workflows": sum(
            1 for n in files if n.startswith(".github/workflows/") and n.endswith((".yml", ".yaml"))
        ),
        "skills": sum(1 for n in files if PurePosixPath(n).name == "SKILL.md"),
    }


def unclassified(names: list[str], limits: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    return [n for n in regular_files(names, root) if kind_of(n, limits["kinds"]) is None]


def over_budget(names: list[str], limits: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    """One line per limit that is exceeded; empty when the tree is within its budget."""
    found = []
    for name, limit in limits["lines"].items():
        if name not in names:
            found.append(f"{name}: missing; the budget names it")
        elif (n := lines(name, root)) > limit:
            found.append(f"{name}: {n} lines, limit {limit}")
    adrs = adr_files(names)
    adr = limits["adr"]
    if len(adrs) > adr["max_count"]:
        found.append(f"{ADR_DIR}: {len(adrs)} ADRs, limit {adr['max_count']}")
    for name in adrs:
        if (n := lines(name, root)) > adr["max_lines_each"]:
            found.append(f"{name}: {n} lines, an ADR is at most {adr['max_lines_each']}")
    for key, value in measure(names, limits, root).items():
        if value > limits["totals"][key]:
            found.append(f"{key}: {value}, limit {limits['totals'][key]}")
    for name in unclassified(names, limits, root):
        found.append(
            f"{name}: not a kind {LIMITS_FILE} names;"
            " add it to prose, config, adr_data or not_counted"
        )
    return found


def index_links(readme: str) -> set[str]:
    """The files listed by the README's index table: one per row under "## Index", the file
    its first cell links. A link in a later cell (a status such as "superseded by
    [0002](...)") or anywhere else in the README does not list an ADR."""
    _, _, index = readme.partition("\n## Index\n")
    return {m.group(2) for row in index.splitlines() if (m := INDEX_ROW.match(row))}


def adr_index_problems(names: list[str], root: Path = REPO_ROOT) -> list[str]:
    """Every ADR is named NNNN-title.md, has its own number, and has a row in the index."""
    found = []
    index = index_links((root / ADR_DIR / "README.md").read_text(encoding="utf-8"))
    numbers: dict[str, str] = {}
    for name in adr_files(names):
        m = ADR_NAME.match(name)
        if m is None:
            found.append(f"{name}: not named docs/adr/NNNN-short-title.md")
            continue
        if m.group(1) in numbers:
            found.append(f"{name}: number {m.group(1)} is also {numbers[m.group(1)]}")
        numbers[m.group(1)] = name
        if PurePosixPath(name).name not in index:
            found.append(f"{name}: no row in the index of {ADR_DIR}/README.md")
    return found


# --- the tree as it is ------------------------------------------------------------------------


def test_the_tree_is_within_its_size_budget():
    names = tracked_files()
    assert LIMITS_FILE in names, "the limits file must be tracked"
    assert over_budget(names, load_limits()) == []


def test_every_adr_is_numbered_and_in_the_index():
    assert adr_index_problems(tracked_files()) == []


def test_the_measure_sees_the_files_it_should():
    measured = measure(tracked_files(), load_limits())
    assert measured["prose_lines"] >= lines("AGENTS.md") + lines("docs/HANDBOOK.md")
    assert measured["config_lines"] >= lines("pyproject.toml") + lines(LIMITS_FILE)
    assert measured["agent_instruction_lines"] >= lines("AGENTS.md") + lines("CLAUDE.md")
    assert measured["workflows"] >= 1


# --- the checks catch what they should ---------------------------------------------------------


def planted(tmp_path: Path, files: dict[str, int]) -> list[str]:
    for name, count in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n" * count, encoding="utf-8")
    return sorted(files)


SMALL = {
    "lines": {"AGENTS.md": 10, "CLAUDE.md": 1, "docs/HANDBOOK.md": 20},
    "adr": {"max_lines_each": 5, "max_count": 2},
    "totals": {
        "agent_instruction_lines": 11,
        "prose_lines": 100,
        "config_lines": 10,
        "workflows": 1,
        "skills": 1,
    },
    "kinds": load_limits()["kinds"],
}
WITHIN = {
    "AGENTS.md": 10,
    "CLAUDE.md": 1,
    "docs/HANDBOOK.md": 20,
    "docs/adr/README.md": 3,
    "docs/adr/0001-a.md": 5,
    "docs/adr/data/0001-big.json": 500,  # ADR data is neither an ADR nor config
    "evidence/M2-x.json": 500,  # run records are not config
    "meridian/x.py": 500,  # code is not counted
    "pyproject.toml": 6,
    ".github/workflows/ci.yml": 4,
    ".agents/skills/one/SKILL.md": 2,
}


def test_a_tree_within_the_budget_passes(tmp_path):
    assert over_budget(planted(tmp_path, WITHIN), SMALL, tmp_path) == []


def test_markdown_under_adr_data_adds_nothing_to_prose(tmp_path):
    before = measure(planted(tmp_path, WITHIN), SMALL, tmp_path)["prose_lines"]
    data = {"docs/adr/data/ab-sheet.md": 500, "docs/adr/data/0001-notes.MARKDOWN": 500}
    names = planted(tmp_path, WITHIN | data)
    assert measure(names, SMALL, tmp_path)["prose_lines"] == before
    assert over_budget(names, SMALL, tmp_path) == []


@pytest.mark.parametrize(
    "name",
    ["notes.md", "evidence/M2-x.md", "upstream/x/NOTICE.md", "docs/adr/data.md", "docs/data/x.md"],
)
def test_markdown_elsewhere_is_still_prose(tmp_path, name):
    before = measure(planted(tmp_path, WITHIN), SMALL, tmp_path)["prose_lines"]
    names = planted(tmp_path, WITHIN | {name: 7})
    assert measure(names, SMALL, tmp_path)["prose_lines"] == before + 7


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"AGENTS.md": 11}, "AGENTS.md: 11 lines, limit 10"),
        ({"CLAUDE.md": 2}, "CLAUDE.md: 2 lines, limit 1"),
        ({"docs/HANDBOOK.md": 21}, "docs/HANDBOOK.md: 21 lines, limit 20"),
        ({"docs/adr/0001-a.md": 6}, "docs/adr/0001-a.md: 6 lines, an ADR is at most 5"),
        ({"docs/adr/0002-b.md": 1, "docs/adr/0003-c.md": 1}, "docs/adr: 3 ADRs, limit 2"),
        ({"docs/adr/0002-b.MARKDOWN": 6}, "docs/adr/0002-b.MARKDOWN: 6 lines, an ADR is at most 5"),
        ({"notes.md": 60}, "prose_lines: 101, limit 100"),
        ({"NOTES.MD": 60}, "prose_lines: 101, limit 100"),
        ({"deploy/AGENTS.md": 1}, "agent_instruction_lines: 12, limit 11"),
        ({".mcp.json": 1}, "config_lines: 11, limit 10"),
        ({"deploy/x.user-data": 1}, "config_lines: 11, limit 10"),
        ({"deploy/systemd/x.service": 1}, "config_lines: 11, limit 10"),
        ({".github/workflows/more.yml": 0}, "workflows: 2, limit 1"),
        ({".claude/skills/two/SKILL.md": 1}, "skills: 2, limit 1"),
        ({"deploy/x.env.sample": 1}, "deploy/x.env.sample: not a kind size-budget.toml names"),
    ],
)
def test_each_limit_catches_a_tree_over_it(tmp_path, change, expected):
    names = planted(tmp_path, WITHIN | change)
    assert any(f.startswith(expected) for f in over_budget(names, SMALL, tmp_path)), expected


def test_a_file_the_budget_names_cannot_simply_disappear(tmp_path):
    names = planted(tmp_path, {k: v for k, v in WITHIN.items() if k != "docs/HANDBOOK.md"})
    assert "docs/HANDBOOK.md: missing; the budget names it" in over_budget(names, SMALL, tmp_path)


def test_the_index_check_catches_an_unlisted_or_misnamed_adr(tmp_path):
    (tmp_path / ADR_DIR).mkdir(parents=True)
    readme = (
        "Like [0002](0002-b.md) in the prose: a link outside the index table lists nothing.\n"
        "| [0002](0002-b.md) | a row above the index lists nothing | adopted |\n"
        "\n## Index\n\n| ADR | Title | Status |\n|---|---|---|\n"
        "| [0001](0001-a.md) | a | superseded by [0002](0002-b.md) |\n"
    )
    (tmp_path / ADR_DIR / "README.md").write_text(readme, encoding="utf-8")
    (tmp_path / ADR_DIR / "old").mkdir()
    (tmp_path / ADR_DIR / "data").mkdir()
    planted = ("0001-a.md", "0002-b.md", "0001-dup.md", "notes.md", "old/0003-c.md", "data/x.md")
    for name in planted:
        (tmp_path / ADR_DIR / name).write_text("x\n", encoding="utf-8")
    names = [f"{ADR_DIR}/{n}" for n in planted]
    found = adr_index_problems(names, tmp_path)
    assert "docs/adr/old/0003-c.md: not named docs/adr/NNNN-short-title.md" in found
    assert not any(f.startswith("docs/adr/data/") for f in found)  # data is not an ADR
    assert "docs/adr/0002-b.md: no row in the index of docs/adr/README.md" in found
    assert any("number 0001 is also" in f for f in found)
    assert "docs/adr/notes.md: not named docs/adr/NNNN-short-title.md" in found
    assert not any(f.startswith("docs/adr/0001-a.md") for f in found)


@pytest.mark.parametrize(
    ("row", "listed"),
    [
        ("| [0003](0003-c.md) | c | adopted |", {"0003-c.md"}),
        ("| 0003 | [c](0003-c.md) | adopted |", set()),  # the link is not the first cell
        ("| [0004](0003-c.md) | c | adopted |", set()),  # the number is not the file's own
        ("see | [0003](0003-c.md) | above", set()),  # not a table row
    ],
)
def test_an_index_row_lists_only_the_adr_its_first_cell_links(row, listed):
    assert index_links(f"\n## Index\n\n{row}\n") == listed
