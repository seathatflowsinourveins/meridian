"""Skills are shared by every agent: one copy in `.agents/skills/`, a link for Claude Code.

Codex, Antigravity and DeepSeek Harness read `.agents/skills/` themselves; Claude Code reads
`.claude/skills/`, so each skill has a relative link there (the layout `orca-ide skills install
--local` writes). A copy in `.claude/skills/` would drift from the shared one.
"""

import os

import pytest
from test_paper_only import REPO_ROOT
from test_upstream_unmodified import git_blob_id

SHARED = REPO_ROOT / ".agents" / "skills"
CLAUDE = REPO_ROOT / ".claude" / "skills"

# Copied unmodified from Orca 1.4.257 (git blob ids, as listed in UPSTREAM.md). A new Orca copy
# changes these on purpose, together with its UPSTREAM.md row and NOTICE.md.
UPSTREAM_SKILLS = {
    "orca-cli": "3b201f777ad807d104e8f87893f1e980f236c6c9",
    "orchestration": "8083c49535c17311585c7bffd177a8683464de46",
}
ORCA_TAG = "v1.4.257"
ORCA_COMMIT = "b0570d90fc9af8c9e7e3566c0fb841d0884e2462"


def test_the_notice_names_the_source_and_its_licence():
    notice = (SHARED / "NOTICE.md").read_text(encoding="utf-8")
    for text in (ORCA_TAG, ORCA_COMMIT, "MIT License", "Copyright (c) 2026 Lovecast Inc."):
        assert text in notice, f"NOTICE.md does not say {text!r}"


@pytest.mark.parametrize("name", sorted(UPSTREAM_SKILLS))
def test_upstream_skill_is_unmodified(name):
    files = sorted(p.name for p in (SHARED / name).iterdir())
    assert files == ["SKILL.md"]
    assert git_blob_id((SHARED / name / "SKILL.md").read_bytes()) == UPSTREAM_SKILLS[name]


def shared_skills() -> list[str]:
    return sorted(p.name for p in SHARED.iterdir() if (p / "SKILL.md").is_file())


def test_there_are_shared_skills():
    assert shared_skills(), "no skill found under .agents/skills"


@pytest.mark.parametrize("name", shared_skills())
def test_each_shared_skill_is_linked_for_claude_code(name):
    link = CLAUDE / name
    assert link.is_symlink(), f".claude/skills/{name} is not a link"
    assert os.readlink(link) == f"../../.agents/skills/{name}"


def test_claude_skills_holds_only_links_to_shared_skills():
    names = set(shared_skills())
    for entry in CLAUDE.iterdir():
        assert entry.is_symlink() and entry.name in names, f"unexpected .claude/skills/{entry.name}"


@pytest.mark.parametrize("name", shared_skills())
def test_each_skill_names_itself(name):
    head = (SHARED / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
    assert f"name: {name}" in head.splitlines()


# Skills written here (UPSTREAM.md, "own design"). A third-party skill is installed on the
# machine for the one runtime that uses it, never vendored into this public repository (ADR 0016).
OWN_DESIGN_SKILLS = {"lead"}


def test_the_shared_skills_are_orcas_two_and_named_own_designs():
    assert set(shared_skills()) == set(UPSTREAM_SKILLS) | OWN_DESIGN_SKILLS
    entries = {p.name for p in SHARED.iterdir()}
    assert entries == set(UPSTREAM_SKILLS) | OWN_DESIGN_SKILLS | {"NOTICE.md"}, (
        f"unexpected entries in .agents/skills: {sorted(entries)}"
    )
