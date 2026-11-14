"""No agent configuration is committed here, apart from the shared skills, and setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code and Codex have MCP off
machine-wide (``deploy/wsl/meridian.user-data``); Antigravity has no such setting. So the only
agent files git may list are the skills in ``.agents/skills/`` and their links in
``.claude/skills/``. This catches an accidental commit. It cannot stop a branch from outside the
owner's own sessions, which carries its own tests: AGENTS.md keeps such branches out of worktrees.
"""

import json
import re
import subprocess

import pytest
from test_paper_only import REPO_ROOT, git_files

DEPLOY = REPO_ROOT / "deploy" / "wsl"
# The newest first-patched version among GitHub's published advisories for the GitHub CLI
# (UPSTREAM.md, GitHub CLI row). The pin may not fall below it.
GH_NEWEST_FIX = (2, 97, 0)

# Folders the four agents (or Gemini CLI, whose layout Antigravity shares) read in a project.
AGENT_FOLDERS = (".agents/", ".claude/", ".codex/", ".gemini/", ".dsh/")
ALLOWED = (".agents/skills/", ".claude/skills/")
# Files an agent reads wherever they are: Claude Code's project MCP servers.
AGENT_FILES = {".mcp.json"}


def agent_config(names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if (name.startswith(AGENT_FOLDERS) and not name.startswith(ALLOWED))
        or name.rsplit("/", 1)[-1] in AGENT_FILES
    ]


def test_no_agent_configuration_is_committed():
    names = git_files("--cached", "--others", "--exclude-standard")
    assert names, "git reported no files; the check would pass without looking"
    assert agent_config(names) == []


@pytest.mark.parametrize(
    "name",
    [
        ".mcp.json",
        "sub/.mcp.json",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/agents/reviewer.md",
        ".codex/config.toml",
        ".agents/mcp_config.json",
        ".agents/hooks.json",
        ".agents/plugins/x/plugin.json",
        ".gemini/settings.json",
        ".dsh/cordis.patch.yml",
    ],
)
def test_the_check_catches_agent_configuration(name):
    assert agent_config([name]) == [name]


@pytest.mark.parametrize(
    "name",
    [
        ".agents/skills/orca-cli/SKILL.md",
        ".agents/skills/NOTICE.md",
        ".claude/skills/orca-cli",
        "a.json",
    ],
)
def test_the_check_leaves_the_skills_alone(name):
    assert agent_config([name]) == []


def test_gh_comes_from_githubs_release_at_a_patched_version():
    # Ubuntu's gh 2.46.0 is inside two high advisories, so the definition does not install it and
    # setup.sh pins GitHub's own build.
    definition = (DEPLOY / "meridian.user-data").read_text(encoding="utf-8")
    assert not re.search(r"^\s*-\s*gh\s*$", definition, re.MULTILINE), "the definition installs gh"
    pin = re.search(r"^GH_VERSION=(\d+)\.(\d+)\.(\d+)$", (DEPLOY / "setup.sh").read_text(), re.M)
    assert pin, "setup.sh has no GH_VERSION pin"
    assert tuple(int(part) for part in pin.groups()) >= GH_NEWEST_FIX


def test_the_setup_script_is_executable_in_git():
    # Editing it from Windows through \\wsl.localhost resets the mode; the documented commands
    # run it directly (deploy/wsl/setup.sh agents-check).
    entry = subprocess.run(
        ["git", "ls-files", "-s", "--", "deploy/wsl/setup.sh"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert entry.startswith("100755 "), f"deploy/wsl/setup.sh is not executable in git: {entry!r}"


def claude_settings_filter(function, settings):
    # Exercise the actual jq expressions on fakes without sourcing or running setup.sh.
    script = (DEPLOY / "setup.sh").read_text()
    body = script.split(f"{function}() {{\n", 1)[1].split("\n}", 1)[0]
    expression = re.search(r"jq [^\n]* '\n(.*?)\n  '", body, re.S)
    assert expression, f"no jq settings expression in {function}"
    return subprocess.run(
        ["jq", "-e", "--arg", "model", "model", "--arg", "floor", "floor", expression[1]],
        input=json.dumps(settings),
        capture_output=True,
        text=True,
        check=False,
    )


def test_claude_settings_enable_the_two_plugins_and_preserve_unrelated_settings():
    original = {"hooks": {}, "enabledPlugins": {"unreviewed@example": True}}
    result = claude_settings_filter("claude_settings", original)
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings["enabledPlugins"] == {
        "codex@openai-codex": True,
        "cc-plugin-you-should-know@builtin": True,
        "unreviewed@example": True,
    }
    assert settings["hooks"] == original["hooks"]
    assert claude_settings_filter("check_claude", settings).returncode == 1


def test_claude_check_allows_only_the_two_plugin_names():
    settings = json.loads(claude_settings_filter("claude_settings", {}).stdout)
    settings["enabledPlugins"] = {
        "codex@openai-codex": True,
        "cc-plugin-you-should-know@builtin": True,
    }
    assert claude_settings_filter("check_claude", settings).returncode == 0
    settings["enabledPlugins"]["unreviewed@example"] = True
    assert claude_settings_filter("check_claude", settings).returncode == 1
    settings["enabledPlugins"]["unreviewed@example"] = False
    assert claude_settings_filter("check_claude", settings).returncode == 0
    settings["enabledPlugins"]["cc-plugin-you-should-know@builtin"] = False
    assert claude_settings_filter("check_claude", settings).returncode == 0
    settings["disableClaudeAiConnectors"] = False
    assert claude_settings_filter("check_claude", settings).returncode == 1
