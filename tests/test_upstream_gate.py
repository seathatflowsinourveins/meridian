"""Offline upstream gate, built on pytest and the existing tracked-tree scans."""

import fnmatch
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from test_paper_only import REPO_ROOT
from test_public_tree import tracked_files


def register_rows(text: str) -> dict[str, tuple[str, str]]:
    """Keep exact component labels, versions and origins from register tables."""
    rows = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) >= 6 and cells[-1] == "upstream":
            assert cells[0] not in rows, f"duplicate upstream row: {cells[0]}"
            rows[cells[0]] = (cells[1], cells[-1])
    return rows


def area_problems(
    names: list[str], areas: dict[str, dict[str, str]], rows: dict[str, tuple[str, str]]
) -> list[str]:
    files = [name for name in names if name.startswith(("meridian/", "deploy/"))]
    found = []
    for name in files:
        matches = [pattern for pattern in areas if fnmatch.fnmatchcase(name, pattern)]
        if len(matches) != 1:
            found.append(f"{name}: expected one upstream entry, found {len(matches)}")
    for pattern, area in areas.items():
        if not any(fnmatch.fnmatchcase(name, pattern) for name in files):
            found.append(f"{pattern}: matches no code file")
        if area.get("upstream") not in rows:
            found.append(f"{pattern}: no upstream row: {area.get('upstream')}")
        if area.get("how") not in {"install", "integrate", "build-on"}:
            found.append(f"{pattern}: how must be install, integrate or build-on")
        for field in ("feature", "why"):
            if not isinstance(area.get(field), str) or not area[field].strip():
                found.append(f"{pattern}: missing {field}")
    return found


def package_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement.strip())
    assert match is not None, f"invalid dependency: {requirement}"
    return re.sub(r"[-_.]+", "-", match[0]).lower()


def dependency_problems(
    project: dict[str, Any],
    lock: dict[str, Any],
    aliases: dict[str, str],
    rows: dict[str, tuple[str, str]],
) -> list[str]:
    metadata = project["project"]
    requirements = list(metadata.get("dependencies", []))
    for group in metadata.get("optional-dependencies", {}).values():
        requirements.extend(group)
    groups = project.get("dependency-groups", {})
    for group in groups.values():
        for requirement in group:
            if isinstance(requirement, str):
                requirements.append(requirement)
            else:
                # Every group is scanned, including groups included by another group.
                assert set(requirement) == {"include-group"}
                assert requirement["include-group"] in groups, "unknown dependency group"
    dependencies = {package_name(requirement) for requirement in requirements}
    found = [
        f"{name}: alias has no declared dependency"
        for name in sorted(aliases.keys() - dependencies)
    ]
    for name in sorted(dependencies):
        row = rows.get(aliases.get(name, ""))
        if row is None:
            found.append(f"{name}: no upstream dependency row")
            continue
        versions = {
            package["version"]
            for package in lock["package"]
            if package_name(package["name"]) == name and "version" in package
        }
        # The register's version cell starts with the version, followed by prose.
        version = re.match(r"v?(\d[^\s,;]*)", row[0])
        if version is None or versions != {version[1]}:
            found.append(
                f"{name}: register version {row[0]!r} disagrees with lock {sorted(versions)}"
            )
    return found


def load_toml(name: str, root: Path = REPO_ROOT) -> dict[str, Any]:
    return tomllib.loads((root / name).read_text(encoding="utf-8"))


def test_every_code_area_and_dependency_has_its_upstream():
    mapping = load_toml("upstream-map.toml")
    rows = register_rows((REPO_ROOT / "UPSTREAM.md").read_text(encoding="utf-8"))
    assert area_problems(tracked_files(), mapping["areas"], rows) == []
    assert (
        dependency_problems(
            load_toml("pyproject.toml"), load_toml("uv.lock"), mapping["dependencies"], rows
        )
        == []
    )


@pytest.fixture
def area():
    return {"upstream": "Example", "how": "build-on", "feature": "hooks", "why": "local policy"}


def test_planted_module_without_entry_fails(area):
    found = area_problems(
        ["meridian/known.py", "meridian/planted.py"],
        {"meridian/known.py": area},
        {"Example": ("1.0", "upstream")},
    )
    assert found == ["meridian/planted.py: expected one upstream entry, found 0"]


def test_entry_without_upstream_row_fails(area):
    assert area_problems(["deploy/example.service"], {"deploy/*": area}, {}) == [
        "deploy/*: no upstream row: Example"
    ]


def test_overlap_and_unused_entries_fail(area):
    found = area_problems(
        ["meridian/known.py"],
        {"meridian/*": area, "meridian/known.py": area, "deploy/*": area},
        {"Example": ("1.0", "upstream")},
    )
    assert found == [
        "meridian/known.py: expected one upstream entry, found 2",
        "deploy/*: matches no code file",
    ]


@pytest.mark.parametrize("field", ["how", "feature", "why"])
def test_missing_provenance_fails(area, field):
    del area[field]
    assert area_problems(
        ["meridian/known.py"], {"meridian/known.py": area}, {"Example": ("1.0", "upstream")}
    )


@pytest.mark.parametrize("location", ["project", "optional", "group"])
def test_dependency_without_row_fails(location):
    project = {"project": {}}
    if location == "project":
        project["project"]["dependencies"] = ["planted>=1"]
    elif location == "optional":
        project["project"]["optional-dependencies"] = {"extra": ["planted>=1"]}
    else:
        project["dependency-groups"] = {"dev": ["planted>=1"]}
    assert dependency_problems(project, {"package": []}, {}, {}) == [
        "planted: no upstream dependency row"
    ]


@pytest.mark.parametrize("version", ["1.0", "1.0.1", None])
def test_dependency_version_must_match_lock(version):
    project = {
        "project": {"dependencies": ["Example_Package[extra]>=1; python_version >= '3.14'"]},
        "dependency-groups": {"dev": [{"include-group": "checks"}], "checks": []},
    }
    packages = [] if version is None else [{"name": "example-package", "version": version}]
    found = dependency_problems(
        project,
        {"package": packages},
        {"example-package": "Example"},
        {"Example": ("1.0 from PyPI", "upstream")},
    )
    assert bool(found) == (version != "1.0")


def test_register_uses_only_upstream_rows_and_exact_labels():
    text = (
        "| Component | Version or commit | Source | Date | Used for | Origin |\n"
        "| Example (with extra) | 1.0 | url | date | testing | upstream |\n"
        "| Local | this repo | n/a | date | hooks | own design |\n"
    )
    assert register_rows(text) == {"Example (with extra)": ("1.0", "upstream")}
