"""Offline consistency of the manifest's recorded placement table and counts."""

import re
from collections import Counter

import pytest
from test_paper_only import REPO_ROOT

MANIFEST = "docs/adr/data/ecosystem-manifest.md"
PLACEMENT = "## Placement of the starred repositories\n"
HEADER = "| repository | group | in architecture | starred |"
COUNTS = (
    "Starred repositories returned by the command",
    "Rows with `starred` = yes",
    "Rows with `starred` = no",
)


def manifest_problems(text: str) -> list[str]:
    sections = text.split(PLACEMENT)
    if len(sections) != 2:
        return ["expected one placement section"]
    section = sections[1].split("\n## ", 1)[0]
    tables = section.split(HEADER + "\n")
    if len(tables) != 2:
        return ["expected one placement table"]
    found = []
    repositories: Counter[str] = Counter()
    starred: Counter[str] = Counter()
    lines = tables[1].splitlines()
    if not lines or not re.fullmatch(r"\|(?:\s*:?-+:?\s*\|){4}", lines[0]):
        return ["invalid placement table separator"]
    for line in lines[1:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if (
            len(cells) != 4
            or not re.fullmatch(r"`[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+`", cells[0])
            or not cells[1]
            or cells[2] not in {"yes", "no"}
            or cells[3] not in {"yes", "no"}
        ):
            found.append(f"invalid placement row: {line}")
            continue
        repositories[cells[0].strip("`").lower()] += 1
        starred[cells[3]] += 1
    found.extend(
        f"duplicate repository: {name}" for name, count in repositories.items() if count != 1
    )
    if not repositories:
        found.append("placement table is empty")
    for label, actual in zip(COUNTS, (starred["yes"], starred["yes"], starred["no"]), strict=True):
        stated = re.findall(rf"^- {re.escape(label)}: (\d+)\s*$", tables[0], re.MULTILINE)
        if len(stated) != 1:
            found.append(f"expected one count: {label}")
        elif int(stated[0]) != actual:
            found.append(f"{label}: stated {stated[0]}, counted {actual}")
    return found


def test_ecosystem_placement_and_counts():
    assert manifest_problems((REPO_ROOT / MANIFEST).read_text(encoding="utf-8")) == []


@pytest.fixture
def manifest():
    return (
        "# Ecosystem manifest\n\n"
        "| unrelated/example | ignored outside placement |\n\n"
        + PLACEMENT
        + "\n- Starred repositories returned by the command: 1\n"
        "- Rows with `starred` = yes: 1\n"
        "- Rows with `starred` = no: 1\n\n" + HEADER + "\n|---|---|---|---|\n"
        "| `owner/example` | Layer 1 | yes | yes |\n"
        "| `owner/other` | Outside the ecosystem | no | no |\n"
    )


def test_small_placement_is_consistent(manifest):
    assert manifest_problems(manifest) == []


@pytest.mark.parametrize("duplicate", ["owner/example", "OWNER/EXAMPLE", "owner/other"])
def test_planted_duplicate_fails_even_with_unchanged_counts(manifest, duplicate):
    old = "owner/other" if duplicate.lower() == "owner/example" else "owner/example"
    found = manifest_problems(manifest.replace(old, duplicate))
    assert found == [f"duplicate repository: {duplicate.lower()}"]


@pytest.mark.parametrize("label", COUNTS)
def test_each_stated_count_is_checked(manifest, label):
    found = manifest_problems(manifest.replace(f"{label}: 1", f"{label}: 2"))
    assert found == [f"{label}: stated 2, counted 1"]


def test_missing_row_fails(manifest):
    found = manifest_problems(manifest.replace("| `owner/example` | Layer 1 | yes | yes |\n", ""))
    assert found == [f"{label}: stated 1, counted 0" for label in COUNTS[:2]]


@pytest.mark.parametrize("removed", [PLACEMENT, HEADER, f"- {COUNTS[0]}: 1"])
def test_missing_structure_fails(manifest, removed):
    assert manifest_problems(manifest.replace(removed, ""))


def test_invalid_starred_flag_fails(manifest):
    assert any(
        problem.startswith("invalid placement row:")
        for problem in manifest_problems(manifest.replace("| yes | yes |", "| yes | maybe |"))
    )
