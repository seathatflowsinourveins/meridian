"""No agent configuration is committed here, apart from the shared skills, and setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code and Codex have MCP off
machine-wide (``deploy/wsl/meridian.user-data``); Antigravity has no such setting. So the only
agent files git may list are the skills in ``.agents/skills/`` and their links in
``.claude/skills/``. This catches an accidental commit. It cannot stop a branch from outside the
owner's own sessions, which carries its own tests: docs/HANDBOOK.md (Rules) keeps such branches
out of worktrees.
"""

import json
import re
import subprocess
import sys
import tomllib

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


@pytest.mark.parametrize(
    "switch", ["idleCompaction", "precomputeCompactionEnabled", "autoContinueAtUsageLimit"]
)
def test_claude_settings_show_thinking_and_keep_compaction_at_its_defaults(switch):
    settings = json.loads(claude_settings_filter("claude_settings", {}).stdout)
    assert settings["showThinkingSummaries"] is True
    assert settings["showMessageTimestamps"] is True
    assert settings["tui"] == "fullscreen"
    # These three are on when absent: setup writes none of them, the check refuses "off".
    assert switch not in settings
    assert claude_settings_filter("check_claude", settings).returncode == 0
    assert claude_settings_filter("check_claude", settings | {switch: True}).returncode == 0
    assert claude_settings_filter("check_claude", settings | {switch: False}).returncode == 1
    for key in ("showThinkingSummaries", "showMessageTimestamps", "tui", "autoCompactEnabled"):
        without = {name: value for name, value in settings.items() if name != key}
        assert claude_settings_filter("check_claude", without).returncode == 1


def test_claude_settings_override_an_old_auto_compact_switch():
    # Claude Code falls back to ~/.claude.json for autoCompactEnabled when settings.json has
    # none, so an absent key could hide an old "off". Setup writes it; the check requires it.
    for before in ({}, {"autoCompactEnabled": False}):
        settings = json.loads(claude_settings_filter("claude_settings", before).stdout)
        assert settings["autoCompactEnabled"] is True
    settings["autoCompactEnabled"] = False
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


def setup_function_body(name):
    return (DEPLOY / "setup.sh").read_text().split(f"{name}() {{\n", 1)[1].split("\n}", 1)[0]


def run_config_writer(name, tmp_path, helpers=()):
    # Extract only configuration writers; no installer, agent or service is started.
    # Replace the home reference in the extracted code, leaving the real HOME untouched.
    functions = "\n".join(
        f"{f}() {{\n{setup_function_body(f)}\n}}" for f in (*helpers, name)
    ).replace("${HOME}", "${fixture_root}")
    subprocess.run(
        [
            "bash",
            "-eu",
            "-o",
            "pipefail",
            "-c",
            "fixture_root=$1\nCODEX_MODEL=model\nDSH_MODEL=model\n"
            'fail() { echo "$*" >&2; exit 1; }\n' + functions + f"\n{name}",
            "test-config",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def codex_config_check(path):
    body = setup_function_body("check_codex")
    program = body.split("\nimport sys\n", 1)[1].split("\nPY", 1)[0]
    return subprocess.run(
        [sys.executable, "-I", "-", str(path), "model"],
        input="import sys\n" + program,
        capture_output=True,
        text=True,
        check=False,
    )


def test_codex_startup_menu_is_disabled_in_new_and_existing_configs(tmp_path):
    run_config_writer("codex_config_file", tmp_path)
    path = tmp_path / ".codex/config.toml"
    original = path.read_text()
    assert tomllib.loads(original)["check_for_update_on_startup"] is False
    for setting in (
        "",
        "check_for_update_on_startup = true\n",
        '"check_for_update_on_startup" = true\n',
    ):
        text = original.replace("check_for_update_on_startup = false\n", setting)
        text = text.replace("apps = false", "apps = true")
        text += (
            '\n[hooks.state.test]\ncommand = "keep"\n'
            '[projects."/example"]\ntrust_level = "trusted"\n'
        )
        path.write_text(text)
        run_config_writer("codex_config", tmp_path, ("codex_config_file", "codex_setting_off"))
        expected = tomllib.loads(text)
        expected["check_for_update_on_startup"] = False
        expected["features"]["apps"] = False
        assert tomllib.loads(path.read_text()) == expected
        assert codex_config_check(path).returncode == 0
        once = path.read_bytes()
        run_config_writer("codex_config", tmp_path, ("codex_config_file", "codex_setting_off"))
        assert path.read_bytes() == once


@pytest.mark.parametrize("setting", ["", "check_for_update_on_startup = true\n"])
def test_codex_check_rejects_a_startup_menu(tmp_path, setting):
    run_config_writer("codex_config_file", tmp_path)
    path = tmp_path / ".codex/config.toml"
    path.write_text(path.read_text().replace("check_for_update_on_startup = false\n", setting))
    assert codex_config_check(path).returncode != 0


def test_dsh_writes_home_wide_guide_completion_and_preserves_other_state(tmp_path):
    run_config_writer("dsh_home_files", tmp_path)
    path = tmp_path / ".dsh-tui/onboarding.json"
    assert json.loads(path.read_text()) == {"completed": True, "version": 1}
    for version in (0, 1, 2):
        path.write_text(json.dumps({"completed": False, "version": version, "other": "keep"}))
        run_config_writer("dsh_home_files", tmp_path)
        assert json.loads(path.read_text()) == {
            "completed": True,
            "version": max(1, version),
            "other": "keep",
        }


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"completed": False, "version": 1},
        {"completed": True, "version": 0},
        {"completed": True, "version": "1"},
        {"completed": True, "version": 1},
    ],
)
def test_dsh_check_requires_completed_guide_at_current_revision(state):
    body = setup_function_body("check_dsh")
    expression = re.search(
        r"jq -e '([^']+)'\s*\\\n\s*\"\$\{HOME\}/.dsh-tui/onboarding.json\"", body
    )
    assert expression, "agents-check does not check the home-wide guide state"
    result = subprocess.run(
        ["jq", "-e", expression[1]],
        input=json.dumps(state),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == (state == {"completed": True, "version": 1})


def setup_value(name):
    pin = re.search(rf"^{name}=(\S+)$", (DEPLOY / "setup.sh").read_text(), re.M)
    assert pin, f"setup.sh has no {name}"
    return pin[1]


def test_gitleaks_is_the_build_and_checksum_ci_uses():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    version, sha = setup_value("GITLEAKS_VERSION"), setup_value("GITLEAKS_SHA256")
    assert f"/download/v{version}/gitleaks_{version}_linux_x64.tar.gz" in ci
    assert f'echo "{sha}  gitleaks.tar.gz"' in ci


def run_gitleaks_step(tmp_path, step, version="8.30.1"):
    # cmd_gitleaks and check_gitleaks on a fake home with a fake curl that copies a local
    # tarball holding a fake gitleaks; nothing is downloaded and the real home is untouched.
    pack = tmp_path / "pack"
    pack.mkdir(exist_ok=True)
    fake = pack / "gitleaks"
    fake.write_text(f'#!/bin/sh\n[ "$1" = version ] && echo {version}\n')
    fake.chmod(0o755)
    tarball = tmp_path / "gitleaks.tar.gz"
    subprocess.run(["tar", "-czf", str(tarball), "-C", str(pack), "gitleaks"], check=True)
    sha = subprocess.run(
        ["sha256sum", str(tarball)], check=True, capture_output=True, text=True
    ).stdout.split()[0]
    home = tmp_path / "home"
    script = (DEPLOY / "setup.sh").read_text()
    one_liner = re.search(r"^gitleaks_version\(\) \{.*\}$", script, re.M)
    assert one_liner, "setup.sh has no gitleaks_version"
    functions = "\n".join(
        [one_liner[0]]
        + [f"{f}() {{\n{setup_function_body(f)}\n}}" for f in ("cmd_gitleaks", "check_gitleaks")]
    )
    program = (
        'HOME=$1; PATH="$HOME/.local/bin:$PATH"; TARBALL=$2; CALLS=$3\n'
        f"GITLEAKS_VERSION=8.30.1\nGITLEAKS_SHA256={sha}\nGITLEAKS_URL=https://example.invalid/g\n"
        'fail() { echo "FAIL: $*" >&2; exit 1; }\nok() { echo "ok:   $*"; }\n'
        'curl() { echo "$@" >> "$CALLS"; cp "$TARBALL" "$2"; }\n' + functions + f"\n{step}"
    )
    calls = tmp_path / "curl-calls"
    result = subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", program, "t", str(home), str(tarball), str(calls)],
        capture_output=True,
        text=True,
        check=False,
    )
    count = len(calls.read_text().splitlines()) if calls.exists() else 0
    return result, count


def test_the_gitleaks_step_installs_once_and_its_check_passes(tmp_path):
    first, downloads = run_gitleaks_step(tmp_path, "cmd_gitleaks")
    assert first.returncode == 0, first.stderr
    assert downloads == 1 and (tmp_path / "home/.local/bin/gitleaks").is_file()
    assert "ok:   gitleaks 8.30.1 in ~/.local/bin" in first.stdout
    again, downloads = run_gitleaks_step(tmp_path, "cmd_gitleaks")
    assert again.returncode == 0 and downloads == 1  # already there: no second download


def test_the_gitleaks_check_fails_when_missing_or_another_version(tmp_path):
    missing, _ = run_gitleaks_step(tmp_path, "check_gitleaks")
    assert missing.returncode == 1 and "is not 8.30.1" in missing.stderr
    installed, _ = run_gitleaks_step(tmp_path, "cmd_gitleaks", version="8.29.0")
    assert installed.returncode == 1 and "is not 8.30.1" in installed.stderr
