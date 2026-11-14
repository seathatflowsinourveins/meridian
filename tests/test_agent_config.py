"""Only admitted agent configuration is committed; setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code and Codex have MCP off
machine-wide (``deploy/wsl/meridian.user-data``); Antigravity has no such setting. So the only
agent files git may list are shared skills and their Claude links, plus ADR 0019's exact
OMC stage schedule (checked below). Runtime state remains forbidden. This catches accidental
commits; branches outside the owner's sessions stay out under docs/HANDBOOK.md (Rules).
"""

import hashlib
import importlib.util
import json
import os
import re
import runpy
import signal
import subprocess
import sys
import tarfile
import time
import tomllib
from pathlib import Path

import pytest
from test_paper_only import REPO_ROOT, git_files

DEPLOY = REPO_ROOT / "deploy" / "wsl"
# The newest first-patched version among GitHub's published advisories for the GitHub CLI
# (UPSTREAM.md, GitHub CLI row). The pin may not fall below it.
GH_NEWEST_FIX = (2, 97, 0)

# Folders the four agents (or Gemini CLI, whose layout Antigravity shares) read in a project.
# Also the project folders of serena (the MCP server dsh runs, ADR 0016) and beads.
AGENT_FOLDERS = (
    ".agents/",
    ".claude/",
    ".codex/",
    ".gemini/",
    ".dsh/",
    ".serena/",
    ".beads/",
    ".omc/",
)
ALLOWED = (".agents/skills/", ".claude/skills/")
# Files an agent reads wherever they are: Claude Code's project MCP servers.
AGENT_FILES = {".mcp.json"}


def agent_config(names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if (
            name.startswith(AGENT_FOLDERS)
            and not name.startswith(ALLOWED)
            and name != ".claude/omc.jsonc"
        )
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
        ".serena/project.yml",
        ".beads/issues.db",
        ".omc/state/run.json",
        ".claude/omc.jsonc.backup",
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
        ".claude/omc.jsonc",
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


WRAPPER = "/home/owner/.local/bin/meridian-claude-hud"


def claude_settings_filter(function, settings):
    # Exercise the actual jq expressions on fakes without sourcing or running setup.sh.
    script = (DEPLOY / "setup.sh").read_text()
    body = script.split(f"{function}() {{\n", 1)[1].split("\n}", 1)[0]
    expression = re.search(r"jq [^\n]* '\n(.*?)\n  '", body, re.S)
    assert expression, f"no jq settings expression in {function}"
    return subprocess.run(
        ["jq", "-e", "--arg", "model", "model", "--arg", "floor", "floor"]
        + ["--arg", "wrapper", WRAPPER, expression[1]],
        input=json.dumps(settings),
        capture_output=True,
        text=True,
        check=False,
    )


def test_claude_settings_enable_the_three_plugins_and_preserve_unrelated_settings():
    original = {"hooks": {}, "enabledPlugins": {"unreviewed@example": True}}
    result = claude_settings_filter("claude_settings", original)
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings["enabledPlugins"] == {
        "codex@openai-codex": True,
        "cc-plugin-you-should-know@builtin": True,
        "claude-hud@claude-hud": True,
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


def test_claude_check_allows_only_the_three_plugin_names():
    settings = json.loads(claude_settings_filter("claude_settings", {}).stdout)
    settings["enabledPlugins"] = {
        "codex@openai-codex": True,
        "cc-plugin-you-should-know@builtin": True,
        "claude-hud@claude-hud": True,
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


ORCA_STATUS_LINE = '[ -n "${HOME-}" ] && /bin/sh "${HOME-}/.orca/agent-hooks/claude-statusline.sh"'
HUD_STATUS_LINE = "'/usr/local/bin/node' '/home/owner/.claude/plugins/claude-hud/statusline.mjs'"


@pytest.mark.parametrize("before", [None, ORCA_STATUS_LINE, HUD_STATUS_LINE, WRAPPER])
def test_the_status_line_becomes_the_wrapper_and_keeps_the_rest(before):
    original: dict = {"hooks": {"Stop": []}, "model": "m"}
    if before is not None:
        original["statusLine"] = {"type": "command", "command": before, "padding": 1}
    result = claude_settings_filter("claude_statusline", original)
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings["statusLine"] == {"type": "command", "command": WRAPPER}
    assert {k: v for k, v in settings.items() if k != "statusLine"} == {
        k: v for k, v in original.items() if k != "statusLine"
    }
    again = claude_settings_filter("claude_statusline", settings)
    assert json.loads(again.stdout) == settings


def test_another_status_line_command_is_not_overwritten():
    original = {"statusLine": {"type": "command", "command": "~/bin/my-status-line"}}
    result = claude_settings_filter("claude_statusline", original)
    assert result.returncode != 0
    assert "statusLine runs another command" in result.stderr


def test_the_wrapper_name_suits_both_orca_and_claude_hud():
    body = (DEPLOY / "setup.sh").read_text()
    name = re.search(r'^CLAUDE_HUD_WRAPPER="\$\{HOME\}/(\S+)"$', body, re.M)
    assert name, "no CLAUDE_HUD_WRAPPER in setup.sh"
    # claude-hud's doctor looks for its name; Orca rewrites a command that names its reporter.
    assert "claude-hud" in name[1]
    assert "agent-hooks/claude-statusline" not in name[1]
    assert WRAPPER.endswith(name[1])


def run_wrapper(home, payload, launcher=None, reporter=None, limit="300"):
    # The wrapper under a fake home: no real Orca, claude-hud or settings file is touched.
    # claude-hud's time limit is far above anything a loaded CI runner needs to start node, so
    # no test here depends on speed; the limit itself has its own test with a launcher that
    # never returns.
    if launcher is not None:
        path = home / ".claude" / "plugins" / "claude-hud" / "statusline.mjs"
        path.parent.mkdir(parents=True)
        path.write_text(launcher)
    if reporter is not None:
        path = home / ".orca" / "agent-hooks" / "claude-statusline.sh"
        path.parent.mkdir(parents=True)
        path.write_text(reporter)
        path.chmod(0o755)
    environment = {"HOME": str(home), "PATH": os.environ["PATH"], "MERIDIAN_HUD_TIMEOUT": limit}
    return subprocess.run(
        [str(DEPLOY / "meridian-claude-hud.sh")],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=600,
    )


PAYLOAD = json.dumps(
    {
        "model": {"display_name": "Model"},
        "effort": {"level": "high"},
        "context_window": {"used_percentage": 12.7},
        "rate_limits": {"five_hour": {"used_percentage": 3}},
    }
)
PLAIN_LINE = "[Model] high | ctx 12% | 5h 3% | 7d -%\n"


def test_the_wrapper_prints_a_plain_line_without_claude_hud(tmp_path):
    result = run_wrapper(tmp_path, PAYLOAD)
    assert (result.returncode, result.stdout, result.stderr) == (0, PLAIN_LINE, "")


def test_the_wrapper_prints_what_claude_hud_prints(tmp_path):
    result = run_wrapper(tmp_path, PAYLOAD, launcher='console.log("one\\ntwo")\n')
    assert (result.returncode, result.stdout, result.stderr) == (0, "one\ntwo\n", "")


@pytest.mark.parametrize("launcher", ["process.exit(3)\n", 'console.error("broken")\n'])
def test_the_wrapper_falls_back_when_claude_hud_fails_or_is_silent(tmp_path, launcher):
    result = run_wrapper(tmp_path, PAYLOAD, launcher=launcher)
    assert (result.returncode, result.stdout, result.stderr) == (0, PLAIN_LINE, "")


def test_the_wrapper_feeds_orcas_reporter_without_waiting_for_it(tmp_path):
    # The reporter stays alive until this test releases it, so "the wrapper returned first"
    # does not depend on how fast the runner is; then it is let go, leaving no process behind.
    received, release, finished = (tmp_path / name for name in ("received", "release", "done"))
    reporter = (
        f'#!/bin/sh\ncat > "{received}"\ni=0\n'
        f'while [ ! -e "{release}" ] && [ "$i" -lt 3000 ]; do sleep 0.1; i=$((i + 1)); done\n'
        f'touch "{finished}"\necho noise\necho noise >&2\n'
    )
    result = run_wrapper(tmp_path, PAYLOAD, reporter=reporter)
    assert (result.returncode, result.stdout, result.stderr) == (0, PLAIN_LINE, "")
    assert not finished.exists(), "the wrapper waited for Orca's reporter"

    def wait_for(path):
        for _ in range(3000):
            if path.exists():
                return
            time.sleep(0.1)
        raise AssertionError(f"{path.name} never appeared")

    wait_for(received)
    release.touch()
    wait_for(finished)
    assert received.read_text() == PAYLOAD


def test_the_wrapper_gives_claude_hud_a_time_limit(tmp_path):
    # A launcher that never returns: after the limit (one second here) the plain line is used.
    result = run_wrapper(tmp_path, PAYLOAD, launcher="setInterval(() => {}, 1000)\n", limit="1")
    assert (result.returncode, result.stdout, result.stderr) == (0, PLAIN_LINE, "")
    wrapper = (DEPLOY / "meridian-claude-hud.sh").read_text()
    assert 'timeout "${MERIDIAN_HUD_TIMEOUT:-5}" node' in wrapper


def test_the_wrapper_survives_an_empty_payload(tmp_path):
    result = run_wrapper(tmp_path, "", reporter="#!/bin/sh\nexit 1\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, "\n", "")


def test_the_wrapper_is_executable_in_git():
    entry = subprocess.run(
        ["git", "ls-files", "-s", "deploy/wsl/meridian-claude-hud.sh"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert entry.startswith("100755 "), f"the wrapper is not executable in git: {entry!r}"


def test_claude_hud_config_is_written_once_with_the_account_labels_off(tmp_path):
    file = tmp_path / ".claude" / "plugins" / "claude-hud" / "config.json"
    run_config_writer("claude_hud_config", tmp_path)
    config = json.loads(file.read_text())
    display = config["display"]
    # The two options that read the account block of ~/.claude.json, and the usage file paths.
    assert display["showAuth"] is False and display["showAuthUser"] is False
    assert not any(key.startswith("externalUsage") for key in display)
    switched_on = {key for key, value in display.items() if value is True}
    for key in (
        "showTools",
        "showSkills",
        "showMcp",
        "showAgents",
        "showTodos",
        "showEffortLevel",
        "showAgentEffort",
        "showSpeed",
        "showPromptCache",
        "showCacheHitRate",
        "showSessionTokens",
    ):
        assert key in switched_on, key
    assert display["sevenDayThreshold"] == 0 and display["contextValue"] == "both"
    assert config["gitStatus"] == {"showAheadBehind": True, "showFileStats": True}
    file.write_text('{"display": {"showTools": false}}')
    run_config_writer("claude_hud_config", tmp_path)
    assert json.loads(file.read_text()) == {"display": {"showTools": False}}


def setup_function_body(name):
    return (DEPLOY / "setup.sh").read_text().split(f"{name}() {{\n", 1)[1].split("\n}", 1)[0]


def run_config_writer(name, tmp_path, helpers=(), model="model"):
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
            f"fixture_root=$1\nCODEX_MODEL=model\nDSH_MODEL={model}\n"
            'fail() { echo "$*" >&2; exit 1; }\n' + functions + f"\n{name}",
            "test-config",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def drift_report(lines):
    # The table and exit code of `setup.sh drift`, on made-up versions: nothing is installed
    # or read. sort -V stands in for the script's own version comparison.
    program = (
        'version_ge() { [ "$(printf \'%s\\n\' "$1" "$2" | sort -V | head -n 1)" = "$2" ]; }\n'
        f"drift_report() {{\n{setup_function_body('drift_report')}\n}}\ndrift_report"
    )
    return subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", program],
        input=lines,
        capture_output=True,
        text=True,
        check=False,
    )


def test_drift_is_quiet_when_every_runtime_is_at_its_pin():
    result = drift_report("claude-code 2.1.325 2.1.325 2.1.325\norca 1.4.257 1.4.257 -\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count("at the pin") == 2


@pytest.mark.parametrize(
    ("line", "state"),
    [
        ("claude-code 2.1.330 2.1.325 2.1.330", "ahead of the pin; upstream has 2.1.330"),
        ("orca 1.4.255 1.4.257 -", "behind the pin"),
        ("claude-hud - 0.15.0 0.15.0", "behind the pin"),
        ("orca 1.4.257 1.4.257 1.4.258", "at the pin; upstream has 1.4.258"),
    ],
)
def test_drift_reports_a_runtime_that_is_off_its_pin(line, state):
    result = drift_report(f"gh 2.104.0 2.104.0 2.104.0\n{line}\ncodex 0.167.2 0.167.2 0.167.0\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[1].endswith(state)
    # An older or unread upstream version, and one equal to the pin, are not drift.
    assert result.stdout.splitlines()[0].endswith("at the pin")
    assert result.stdout.splitlines()[2].endswith("at the pin")


def test_the_upkeep_prompt_lands_through_the_gate_and_names_what_a_run_must_never_do():
    script = (DEPLOY / "setup.sh").read_text()
    prompt = script.split("UPKEEP_PROMPT='", 1)[1].split("\n\nupkeep_automation() {", 1)[0]
    steps, never = prompt.split("Never:", 1)
    # The run finishes its own change: another family's review, the gate under the shared
    # lock, then the pins applied and checked.
    for phrase in (
        "codex review --base origin/main",
        "flock ~/.cache/meridian/landing.lock",
        "`trial`, `open` and `land`",
        "never go around it",
        "git -C ~/src/meridian pull --ff-only",
        "~/src/meridian/deploy/wsl/setup.sh upkeep",
        "~/src/meridian/deploy/wsl/setup.sh agents-check",
    ):
        assert phrase in steps, phrase
    for phrase in (
        "any pull request but your own upkeep changes",
        "start a lane",
        "key or credential",
        "risk/",
        "plugin, skill or MCP server",
        "change a model id",
        "stop a process you did not start",
    ):
        assert phrase in never, phrase
    upkeep = setup_function_body("cmd_upkeep")
    for installer in ("cmd_gh", "cmd_ocr", "cmd_claude", "cmd_codex", "cmd_agy", "cmd_dsh"):
        assert f"  {installer}\n" in upkeep, installer
    # Orca's server is installed last, and only when it is behind its pin.
    assert upkeep.rstrip().endswith('version_ge "$(orca_version)" "${ORCA_VERSION}" || cmd_orca')


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


# The worker stack of DeepSeek Harness (docs/adr/0016-dsh-worker-stack.md).
SETUP = (DEPLOY / "setup.sh").read_text(encoding="utf-8")
GATE = DEPLOY / "dsh-check-gate.sh"
ORCA_BLOCK = (
    "# >>> orca-managed-dsh-hooks (managed by Orca; do not edit) >>>\n"
    "- insert:\n"
    "    - id: orca-agent-hooks\n"
    "      name: '@deepseek-ai/dsh-hooks-claude-code'\n"
    "      config:\n"
    "        configPath: '/example/.orca/agent-hooks/dsh-hooks.json'\n"
    "# <<< orca-managed-dsh-hooks <<<\n"
)


def setup_pin(name):
    match = re.search(rf"^{name}=(\S+)$", SETUP, re.M)
    assert match, f"setup.sh has no {name} pin"
    return match[1].strip('"')


def dsh_skill_pins():
    block = re.search(r"^DSH_SKILLS=\(\n(.*?)\n\)$", SETUP, re.M | re.S)
    assert block, "setup.sh has no DSH_SKILLS list"
    return [line.strip().strip('"').split() for line in block[1].splitlines()]


def test_the_stack_is_pinned_to_exact_commits_versions_and_checksums():
    upstream = (REPO_ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
    pins = dsh_skill_pins()
    assert [repo for repo, *_ in pins] == [
        "addyosmani/agent-skills",
        "obra/superpowers",
        "mattpocock/skills",
    ]
    names = []
    for repo, commit, *paths in pins:
        assert re.fullmatch(r"[0-9a-f]{40}", commit), f"{repo} is not pinned to a full commit"
        assert commit in upstream, f"{repo} at {commit} has no UPSTREAM.md row"
        assert paths and all(re.fullmatch(r"skills/[a-z0-9/-]+", path) for path in paths)
        names += [path.rsplit("/", 1)[-1] for path in paths]
    assert len(names) == len(set(names)) == 8, "two skills would share a folder in ~/.dsh/skills"
    for name in ("AST_GREP_SHA256", "AGENTSVIEW_SHA256"):
        assert re.fullmatch(r"[0-9a-f]{64}", setup_pin(name)), f"{name} is not a SHA-256"
        assert setup_pin(name) in upstream, f"{name} has no UPSTREAM.md row"
    for name in ("AST_GREP_VERSION", "AGENTSVIEW_VERSION"):
        assert re.fullmatch(r"\d+\.\d+\.\d+", setup_pin(name)), f"{name} is not an exact version"
    for name in ("DSH_LSP_INTEGRITY", "DSH_LSP_STDIO_INTEGRITY", "DSH_TOOL_LSP_INTEGRITY"):
        assert re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", setup_pin(name)), f"{name} is not sha512"
        assert setup_pin(name) in upstream, f"{name} has no UPSTREAM.md row"


def test_code_navigation_is_the_read_only_lsp_tool_on_the_worktrees_own_pyright(tmp_path):
    run_config_writer("dsh_home_files", tmp_path)
    block = (tmp_path / ".dsh/cordis.patch.yml").read_text(encoding="utf-8")
    for package in ("dsh-lsp", "dsh-lsp-stdio", "dsh-tool-lsp"):
        assert f"      name: '@deepseek-ai/{package}'\n" in block
    assert "dsh-mcp-client" not in block, "the stack adds no MCP server"


FAKE_SERVER = """#!/usr/bin/env python3
import json, os, sys
header = b""
while not header.endswith(b"\\r\\n\\r\\n"):
    header += sys.stdin.buffer.read(1)
length = int(header.split(b":")[1])
params = json.loads(sys.stdin.buffer.read(length))["params"]
rest = sys.stdin.buffer.read()
print(json.dumps({"rootUri": params["rootUri"], "folders": params["workspaceFolders"],
                  "args": sys.argv[1:], "rest": rest.decode()}))
"""


def frame(message: dict) -> bytes:
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def test_the_lsp_server_runs_at_the_worktree_root_from_a_subdirectory(tmp_path):
    # The provider starts the server in the session's directory and sends it as the workspace.
    # From a subdirectory, the row's command must still find the worktree's own server and give
    # it the worktree root, or pyright resolves none of the repository's imports.
    run_config_writer("dsh_home_files", tmp_path)
    block = (tmp_path / ".dsh/cordis.patch.yml").read_text(encoding="utf-8")
    command = re.search(r"^            args: \['-c', '(.*)'\]$", block, re.M)
    assert command, "no server command in the LSP provider row"
    shim = tmp_path / ".dsh/lsp/dsh-lsp-root.py"
    shim.parent.mkdir(parents=True)
    shim.write_bytes((DEPLOY / "dsh-lsp-root.py").read_bytes())
    repo = tmp_path / "worktree"
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / "meridian").mkdir()
    server = repo / ".venv/bin/pyright-langserver"
    server.write_text(FAKE_SERVER)
    server.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subdirectory = (repo / "meridian").resolve()
    initialize = frame(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"rootUri": subdirectory.as_uri(), "workspaceFolders": []},
        }
    )
    later = frame({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    result = subprocess.run(
        ["sh", "-c", command[1]],
        cwd=subdirectory,
        input=initialize + later,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    seen = json.loads(result.stdout)
    root = repo.resolve().as_uri()
    assert seen["rootUri"] == root and seen["folders"] == [{"uri": root, "name": "worktree"}]
    assert seen["args"] == ["--stdio"]
    assert seen["rest"] == later.decode(), "a message after initialize was changed"


def test_the_root_shim_leaves_every_other_message_alone():
    spec = importlib.util.spec_from_file_location("dsh_lsp_root", DEPLOY / "dsh-lsp-root.py")
    assert spec and spec.loader
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    for body in (b'{"jsonrpc":"2.0","method":"initialized","params":{}}', b"not json", b"[1]"):
        assert shim.with_root(body, Path("/repo")) is body


def write_patch(tmp_path, text):
    path = tmp_path / ".dsh/cordis.patch.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_meridian_block_sits_above_orcas_block_and_leaves_it_alone(tmp_path):
    rows = "- id: session-log-deepseek\n  config:\n    enabled: false\n"
    old_model = (
        "- id: agent-default-model\n  config:\n    model: old\n    provider: deepseek-official\n"
    )
    path = write_patch(tmp_path, rows + old_model + ORCA_BLOCK)
    run_config_writer("dsh_home_files", tmp_path)
    text = path.read_text(encoding="utf-8")
    split = r"(?=# >>> meridian-managed)|(?<=# <<< meridian-managed <<<\n)"
    before, ours, after = re.split(split, text)
    assert before == rows, "the rows above the block changed, or the old model row stayed"
    assert after == ORCA_BLOCK, "Orca's block is not byte-identical at the end of the file"
    assert "    model: model\n" in ours and "model: old" not in text
    assert "    - id: meridian-tool-lsp\n      name: '@deepseek-ai/dsh-tool-lsp'\n" in ours
    gate = "    - id: meridian-check-gate\n      name: '@deepseek-ai/dsh-hooks-claude-code'\n"
    assert gate in ours
    once = path.read_bytes()
    run_config_writer("dsh_home_files", tmp_path)
    assert path.read_bytes() == once, "a second run changed the file"
    run_config_writer("dsh_home_files", tmp_path, model="next")
    text = path.read_text(encoding="utf-8")
    assert "    model: next\n" in text and text.count("# >>> meridian-managed") == 1
    assert text.endswith(ORCA_BLOCK)


def test_the_meridian_block_is_written_into_a_new_patch_file(tmp_path):
    run_config_writer("dsh_home_files", tmp_path)
    text = (tmp_path / ".dsh/cordis.patch.yml").read_text(encoding="utf-8")
    assert text.count("- id: agent-default-model\n") == 1
    assert text.rstrip().endswith("# <<< meridian-managed <<<")


def test_the_writer_refuses_an_unclosed_meridian_block(tmp_path):
    path = write_patch(tmp_path, "# >>> meridian-managed >>>\n- id: x\n" + ORCA_BLOCK)
    with pytest.raises(subprocess.CalledProcessError):
        run_config_writer("dsh_home_files", tmp_path)
    assert path.read_text(encoding="utf-8").endswith(ORCA_BLOCK)


def gate_repo(tmp_path, meridian=True):
    repo = tmp_path / "repo"
    (repo / "meridian").mkdir(parents=True)
    if meridian:
        (repo / "meridian/boundary.py").write_text("")
        (repo / "size-budget.toml").write_text("")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "README").write_text("x\n")
    commit(repo, "base")
    # A stand-in for uv: the gate's check line passes or fails as the test says, and each call
    # is logged, so a test can tell a skipped check from one that ran.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(
        '#!/bin/sh\necho "uv $*" | tee -a "$GATE_LOG"\n[ ! -e "$GATE_FAIL" ] || exit 1\n'
    )
    (bin_dir / "uv").chmod(0o755)
    return repo, bin_dir


def commit(repo, message):
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", message], check=True)


def mark_origin_main(repo):
    # The repository's origin/main is its current commit, as after a fetch.
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"], check=True
    )


def checks_run(repo) -> int:
    log = repo.parent / "uv.log"
    return log.read_text().count("uv sync") if log.exists() else 0


def run_gate(repo, bin_dir, session="session-1", fail=None) -> dict | None:
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(repo.parent),
        "GATE_FAIL": str(fail or repo.parent / "never"),
        "GATE_LOG": str(repo.parent / "uv.log"),
    }
    result = subprocess.run(
        ["bash", str(GATE)],
        input=json.dumps({"session_id": session, "cwd": str(repo), "hook_event_name": "Stop"}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def blocked(decision: dict | None) -> dict:
    assert decision is not None and decision["decision"] == "block", decision
    return decision


def test_the_gate_lets_a_clean_tree_or_another_repository_stop(tmp_path):
    repo, bin_dir = gate_repo(tmp_path)
    flag = tmp_path / "fail"
    flag.write_text("")
    assert run_gate(repo, bin_dir, fail=flag) is None, "a clean tree was blocked"
    other, _ = gate_repo(tmp_path / "other", meridian=False)
    (other / "README").write_text("changed\n")
    assert run_gate(other, bin_dir, fail=flag) is None, "another repository was blocked"


def test_the_gate_blocks_a_failing_change_at_most_twice_per_session(tmp_path):
    repo, bin_dir = gate_repo(tmp_path)
    (repo / "README").write_text("changed\n")
    flag = tmp_path / "fail"
    flag.write_text("")
    first = blocked(run_gate(repo, bin_dir, fail=flag))
    assert "block 1 of 2" in first["reason"]
    assert "uv run pytest" in first["reason"], "the failing output is not in the reason"
    assert "block 2 of 2" in blocked(run_gate(repo, bin_dir, fail=flag))["reason"]
    assert run_gate(repo, bin_dir, fail=flag) is None, "the gate blocked a third time"
    blocked(run_gate(repo, bin_dir, session="session-2", fail=flag))


def test_a_pass_lets_the_turn_end_and_resets_the_count(tmp_path):
    repo, bin_dir = gate_repo(tmp_path)
    (repo / "README").write_text("changed\n")
    flag = tmp_path / "fail"
    flag.write_text("")
    blocked(run_gate(repo, bin_dir, fail=flag))
    assert run_gate(repo, bin_dir) is None, "a passing check line was blocked"
    (repo / "README").write_text("changed again\n")
    assert "block 1 of 2" in blocked(run_gate(repo, bin_dir, fail=flag))["reason"]


def test_the_gate_checks_committed_work_ahead_of_origin_main(tmp_path):
    repo, bin_dir = gate_repo(tmp_path)
    mark_origin_main(repo)
    flag = tmp_path / "fail"
    flag.write_text("")
    assert run_gate(repo, bin_dir, fail=flag) is None, "work equal to origin/main was blocked"
    assert checks_run(repo) == 0
    (repo / "README").write_text("delivered\n")
    commit(repo, "the work")
    # A clean tree with a commit ahead of origin/main: the gate runs and blocks the failure.
    assert "block 1 of 2" in blocked(run_gate(repo, bin_dir, fail=flag))["reason"]
    flag.unlink()
    assert run_gate(repo, bin_dir) is None and checks_run(repo) == 2
    # The same state after a pass is not checked again, even with the check line now failing.
    flag.write_text("")
    assert run_gate(repo, bin_dir, fail=flag) is None, "a state that passed was blocked"
    assert checks_run(repo) == 2, "a state that passed was checked again"
    # A new commit after the pass is a new state: the gate runs again.
    (repo / "README").write_text("delivered, then fixed\n")
    commit(repo, "a follow-up")
    blocked(run_gate(repo, bin_dir, fail=flag))
    assert checks_run(repo) == 3


def test_without_origin_main_only_a_dirty_tree_counts(tmp_path):
    repo, bin_dir = gate_repo(tmp_path)
    (repo / "README").write_text("delivered\n")
    commit(repo, "the work")
    flag = tmp_path / "fail"
    flag.write_text("")
    assert run_gate(repo, bin_dir, fail=flag) is None and checks_run(repo) == 0
    (repo / "README").write_text("uncommitted\n")
    blocked(run_gate(repo, bin_dir, fail=flag))


def test_the_gate_script_is_executable_in_git():
    entry = subprocess.run(
        ["git", "ls-files", "-s", "--", "deploy/wsl/dsh-check-gate.sh"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert entry.startswith("100755 "), f"the gate script is not executable in git: {entry!r}"


def run_release_binaries(tmp_path):
    # dsh_release_binaries on a fixture home: curl is a stand-in that serves a fake agentsview
    # release whose checksum the run is given; ast-grep is already at its pin.
    version = setup_pin("AGENTSVIEW_VERSION")
    fake = tmp_path / "release" / "agentsview"
    fake.parent.mkdir(exist_ok=True)
    fake.write_text(f'#!/bin/sh\necho "agentsview v{version} (fake)"\n')
    fake.chmod(0o755)
    tarball = tmp_path / "release" / "agentsview.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(fake, arcname="agentsview")
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "curl").write_text(
        f'#!/bin/sh\necho "$@" >> "{tmp_path}/curl.log"\ncp "{tarball}" "$2"\n'
    )
    (bin_dir / "curl").chmod(0o755)
    ast_grep = tmp_path / ".local/bin/ast-grep"
    ast_grep.parent.mkdir(parents=True, exist_ok=True)
    ast_grep.write_text(f'#!/bin/sh\necho "ast-grep {setup_pin("AST_GREP_VERSION")}"\n')
    ast_grep.chmod(0o755)
    one_liner = re.search(r"^ast_grep_version\(\) \{.*\}$", SETUP, re.M)
    assert one_liner, "setup.sh has no ast_grep_version"
    functions = "\n".join(
        [one_liner[0]]
        + [
            f"{f}() {{\n{setup_function_body(f)}\n}}"
            for f in ("agentsview_version", "dsh_release_binaries")
        ]
    ).replace("${HOME}", "${fixture_root}")
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    subprocess.run(
        [
            "bash",
            "-eu",
            "-o",
            "pipefail",
            "-c",
            f"fixture_root=$1\nAST_GREP_VERSION={setup_pin('AST_GREP_VERSION')}\n"
            f"AGENTSVIEW_VERSION={version}\nAGENTSVIEW_SHA256={digest}\nAGENTSVIEW_URL=fake\n"
            'fail() { echo "$*" >&2; exit 1; }\n' + functions + "\ndsh_release_binaries",
            "test-release",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TMPDIR": str(tmp_path)},
    )
    launcher = tmp_path / ".local/bin/agentsview"
    return launcher, subprocess.run([str(launcher), "--version"], capture_output=True, text=True)


def test_a_standalone_agentsview_at_the_pin_does_not_skip_the_private_install(tmp_path):
    # A standalone agentsview at ~/.local/bin, at the pinned version, is not the private binary.
    standalone = tmp_path / ".local/bin/agentsview"
    standalone.parent.mkdir(parents=True)
    standalone.write_text(f'#!/bin/sh\necho "agentsview v{setup_pin("AGENTSVIEW_VERSION")}"\n')
    standalone.chmod(0o755)
    launcher, result = run_release_binaries(tmp_path)
    assert (tmp_path / ".local/libexec/meridian/agentsview").is_file(), "the install was skipped"
    assert result.returncode == 0 and "(fake)" in result.stdout, result.stderr
    assert "AGENTSVIEW_TELEMETRY_ENABLED=0" in launcher.read_text()


def test_an_installed_private_agentsview_at_the_pin_is_not_downloaded_again(tmp_path):
    run_release_binaries(tmp_path)
    (tmp_path / "curl.log").unlink()
    _, result = run_release_binaries(tmp_path)
    assert result.returncode == 0
    assert not (tmp_path / "curl.log").exists(), "the pinned private binary was downloaded again"


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


OMC_ADAPTER = DEPLOY / "meridian-omc.py"


def omc_api():
    return runpy.run_path(str(OMC_ADAPTER))


def test_omc_project_profile_is_only_the_admitted_stage_schedule():
    profile = json.loads((REPO_ROOT / ".claude/omc.jsonc").read_text())
    assert profile == {
        "autopilot": {
            "workflows": {
                "meridian-full": {
                    "version": 1,
                    "stages": ["ralplan", "execution", "ralph", "qa"],
                }
            }
        }
    }


def fake_omc_home(tmp_path):
    api = omc_api()
    home = tmp_path / ".claude"
    user = tmp_path / ".config/claude-omc/config.jsonc"
    settings = {"statusLine": {"type": "command", "command": WRAPPER}, "model": "keep", "hooks": {}}
    for event in api["HOOKS"]:
        settings["hooks"][event] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "sh ~/.orca/agent-hooks/claude-hook.sh",
                    }
                ]
            }
        ]
    api["write"](home / "settings.json", settings)
    staging = tmp_path / "staging"
    api["stage"](home, staging)
    staged_settings = api["read"](staging / "settings.json")
    for event, names in api["HOOKS"].items():
        for name in names:
            path = staging / "hooks" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('console.log(JSON.stringify({decision:"block",reason:"upstream"}));\n')
            staged_settings["hooks"][event].append(
                {"hooks": [{"type": "command", "command": f'node "{path}"'}]}
            )
    api["write"](staging / "settings.json", staged_settings)
    api["write"](staging / ".omc-version.json", {"version": api["VERSION"]})
    (staging / "CLAUDE.md").write_text("<!-- OMC:START -->\nupstream\n<!-- OMC:END -->\n")
    for name in api["SKILLS"] | {"code-review", "tdd"}:
        path = staging / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("synthetic " + name)
        (path.parent / ".omc-managed").write_text("omc-managed\n")
    for name in api["AGENTS"] | {"scientist"}:
        path = staging / "agents" / f"{name}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text("synthetic " + name)
    adapter = tmp_path / "adapter"
    adapter.write_bytes(OMC_ADAPTER.read_bytes())
    api["install"](home, user, adapter, staging)
    return api, home, user


def test_omc_configuration_is_idempotent_and_preserves_orca_and_hud(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    api["check"](home, user, tmp_path / "adapter")
    once = (home / "settings.json").read_bytes(), (home / "CLAUDE.md").read_bytes()
    api["prepare"](home, user)
    api["configure"](home, tmp_path / "adapter")
    api["check"](home, user, tmp_path / "adapter")
    assert once == ((home / "settings.json").read_bytes(), (home / "CLAUDE.md").read_bytes())
    assert api["read"](home / "settings.json")["model"] == "keep"


@pytest.mark.parametrize("damage", ["statusLine", "orca", "omc", "mcp", "hud", "triggers"])
def test_omc_check_rejects_drift(tmp_path, damage):
    api, home, user = fake_omc_home(tmp_path)
    path = home / "settings.json"
    settings = api["read"](path)
    if damage == "statusLine":
        settings["statusLine"]["command"] = "another-hud"
    elif damage in ("orca", "omc"):
        settings["hooks"]["Stop"].pop(0 if damage == "orca" else -1)
    elif damage == "mcp":
        settings["mcpServers"] = {"unexpected": {"command": "false"}}
    elif damage == "hud":
        api["write"](home / ".omc-config.json", {"hudEnabled": True})
    else:
        api["write"](user, {"keywordDetector": {"disabled": []}})
    api["write"](path, settings)
    with pytest.raises(AssertionError):
        api["check"](home, user, tmp_path / "adapter")


def run_omc_hook(home, event, data):
    name = {
        "Stop": "persistent-mode.mjs",
        "PostToolUse": "post-tool-use.mjs",
        "UserPromptSubmit": "keyword-detector.mjs",
    }[event]
    return subprocess.run(
        [sys.executable, str(OMC_ADAPTER), "hook", event, str(home / "hooks" / name)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        check=True,
        env=dict(os.environ, CLAUDE_CONFIG_DIR=str(home)),
    ).stdout


@pytest.mark.parametrize(
    "message",
    [
        "May I change that boundary?",
        "Waiting for the owner.",
        "[MERIDIAN_WAIT]",
        "Blocked on approval.",
        "",
        None,
    ],
)
def test_omc_stop_releases_owner_questions(tmp_path, message):
    _, home, _ = fake_omc_home(tmp_path)
    assert (
        run_omc_hook(home, "Stop", {"session_id": "one", "last_assistant_message": message}) == ""
    )


@pytest.mark.parametrize(
    "command",
    [
        "orca orchestration ask --question 'Need an owner decision'",
        "orca orchestration send --type worker_done --body 'Done'",
    ],
)
def test_omc_orca_handoff_latches_only_its_session_until_next_prompt(tmp_path, command):
    _, home, _ = fake_omc_home(tmp_path)
    stop = {"session_id": "one", "last_assistant_message": "Continue implementation."}
    assert json.loads(run_omc_hook(home, "Stop", stop))["decision"] == "block"
    run_omc_hook(home, "PostToolUse", {"session_id": "one", "tool_input": {"command": command}})
    assert run_omc_hook(home, "Stop", stop) == ""
    assert (
        json.loads(run_omc_hook(home, "Stop", stop | {"session_id": "two"}))["decision"] == "block"
    )
    run_omc_hook(home, "UserPromptSubmit", {"session_id": "one", "prompt": "Authorized reply"})
    assert json.loads(run_omc_hook(home, "Stop", stop))["decision"] == "block"


def test_omc_dispatch_probe_runs_detector_in_disposable_state(tmp_path):
    _, home, user = fake_omc_home(tmp_path)
    (home / "hooks/keyword-detector.mjs").write_text(
        'import fs from "node:fs";\n'
        'const input=JSON.parse(fs.readFileSync(0,"utf8"));\n'
        'if(!fs.existsSync(".claude/omc.jsonc")) process.exit(2);\n'
        'fs.writeFileSync("probe-wrote-here", "scratch");\n'
        "console.log(JSON.stringify({prompt:input.prompt,cwd:process.cwd()}));\n"
    )
    result = subprocess.run(
        [sys.executable, str(OMC_ADAPTER), "probe", str(home), str(user)],
        input="build me a tool",
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["prompt"] == "build me a tool"
    assert not os.path.exists(output["cwd"])


def test_omc_does_not_spawn_factory_work_when_a_session_ends(tmp_path, capsys):
    api, home, _ = fake_omc_home(tmp_path)
    assert api["hook"]("SessionEnd", home / "hooks/session-end.mjs", "{}") == 0
    assert capsys.readouterr().out == ""


def test_omc_bootstrap_before_orca_and_final_check_have_distinct_requirements(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    settings = api["read"](home / "settings.json")
    for groups in settings["hooks"].values():
        groups.pop(0)
    api["write"](home / "settings.json", settings)
    # A removed existing Orca hook fails even during bootstrap.
    with pytest.raises(AssertionError):
        api["check"](home, user, tmp_path / "adapter", require_orca=False)
    before = api["read"](home / ".meridian-omc-before.json")
    before["hooks"] = {}
    api["write"](home / ".meridian-omc-before.json", before)
    api["check"](home, user, tmp_path / "adapter", require_orca=False)
    with pytest.raises(AssertionError):
        api["check"](home, user, tmp_path / "adapter")


def test_omc_setup_ignores_state_once_without_replacing_existing_exclusions(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    exclude = tmp_path / ".git/info/exclude"
    exclude.write_text("keep-this\n")
    program = f"omc_ignore_state() {{\n{setup_function_body('omc_ignore_state')}\n}}"
    program += '\nomc_ignore_state "$1"\nomc_ignore_state "$1"\n'
    subprocess.run(["bash", "-euc", program, "fixture", str(tmp_path)], check=True)
    assert exclude.read_text() == "keep-this\n/.omc/\n"
    program = f"omc_unignore_state() {{\n{setup_function_body('omc_unignore_state')}\n}}"
    program += '\nomc_unignore_state "$1"\n'
    subprocess.run(["bash", "-euc", program, "fixture", str(tmp_path)], check=True)
    assert exclude.read_text() == "keep-this\n"


def test_omc_install_remove_round_trip_preserves_all_other_assets_and_settings(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    adapter = tmp_path / "adapter"
    api["remove"](home, user, adapter)
    settings = api["read"](home / "settings.json")
    settings.update(
        env={"OTHER_SWITCH": "keep", "OMC_NOTIFY": "original"},
        skillOverrides={"autopilot": "off", "user-skill": "name-only"},
    )
    api["write"](home / "settings.json", settings)
    api["write"](user, {"keywordDetector": {"disabled": ["ralph"], "other": "keep"}})
    api["write"](home / ".omc-config.json", {"hudEnabled": True, "other": "keep"})
    (home / "CLAUDE.md").write_text("Owner instructions without trailing newline")
    other = home / "skills/code-review/SKILL.md"
    other.parent.mkdir(parents=True)
    other.write_text("Other review skill, no OMC marker")
    before = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    before_user = user.read_bytes()
    adapter.write_bytes(OMC_ADAPTER.read_bytes())
    api["install"](home, user, adapter, tmp_path / "staging")
    api["check"](home, user, adapter)
    api["install"](home, user, adapter, tmp_path / "staging")
    api["check"](home, user, adapter)
    assert not (home / "skills/tdd").exists()
    assert not (home / "agents/scientist.md").exists()
    api["remove"](home, user, adapter)
    assert not adapter.exists()
    assert user.read_bytes() == before_user
    assert {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    with pytest.raises(AssertionError, match="OMC absent"):
        api["check"](home, user, adapter)


@pytest.mark.parametrize(
    "name", ["skills/ralph/SKILL.md", "agents/executor.md", "hooks/pre-tool-use.mjs"]
)
def test_omc_remove_refuses_modified_owned_file_before_mutating_settings(tmp_path, name):
    api, home, user = fake_omc_home(tmp_path)
    path = home / name
    path.write_text("Owner changed this asset")
    settings = (home / "settings.json").read_bytes()
    with pytest.raises(ValueError, match="modified OMC file"):
        api["remove"](home, user, tmp_path / "adapter")
    assert (home / "settings.json").read_bytes() == settings
    assert path.read_text() == "Owner changed this asset"


def test_omc_remove_preserves_other_hooks_in_mixed_group(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    settings = api["read"](home / "settings.json")
    other = {"type": "command", "command": "printf other-hook"}
    settings["hooks"]["Stop"][1]["hooks"].append(other)
    settings["new-setting"] = True
    api["write"](home / "settings.json", settings)
    api["remove"](home, user, tmp_path / "adapter")
    removed = api["read"](home / "settings.json")
    assert removed["new-setting"] is True
    assert other in [h for group in removed["hooks"]["Stop"] for h in group["hooks"]]


def test_omc_install_refuses_a_colliding_user_asset_before_writing_settings(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    adapter = tmp_path / "adapter"
    api["remove"](home, user, adapter)
    adapter.write_bytes(OMC_ADAPTER.read_bytes())
    path = home / "agents/executor.md"
    path.parent.mkdir()
    path.write_text("Owner's executor")
    before = (home / "settings.json").read_bytes()
    with pytest.raises(ValueError, match="existing user asset"):
        api["install"](home, user, adapter, tmp_path / "staging")
    assert (home / "settings.json").read_bytes() == before
    assert path.read_text() == "Owner's executor"


def test_omc_remove_cleans_only_its_new_runtime_version_cache(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    cache = home / ".omc/update-check.json"
    api["write"](cache, {"lastCheck": "synthetic"})
    api["remove"](home, user, tmp_path / "adapter")
    assert not cache.exists()


@pytest.mark.parametrize("event", ["SessionStart", "PreToolUse", "PostToolUseFailure"])
def test_omc_checks_require_direct_commands_for_events_without_adapter_logic(tmp_path, event):
    api, home, user = fake_omc_home(tmp_path)
    settings = api["read"](home / "settings.json")
    command = settings["hooks"][event][-1]["hooks"][0]
    assert command["command"].startswith("node ")
    command["command"] = f"python3 adapter hook {event} " + command["command"][5:]
    api["write"](home / "settings.json", settings)
    with pytest.raises(AssertionError, match="missing or duplicate OMC"):
        api["check"](home, user, tmp_path / "adapter")


@pytest.mark.parametrize(
    "damage", ["missing-skill", "extra-skill", "extra-agent", "disabled-skill"]
)
def test_omc_checks_require_exact_active_lifecycle_set(tmp_path, damage):
    api, home, user = fake_omc_home(tmp_path)
    if damage == "missing-skill":
        (home / "skills/ralph/SKILL.md").unlink()
    elif damage == "extra-skill":
        path = home / "skills/tdd/.omc-managed"
        path.parent.mkdir()
        path.touch()
    elif damage == "extra-agent":
        (home / "agents/scientist.md").write_text("synthetic scientist")
    else:
        settings = api["read"](home / "settings.json")
        settings["skillOverrides"]["ralph"] = "off"
        api["write"](home / "settings.json", settings)
    with pytest.raises(AssertionError):
        api["check"](home, user, tmp_path / "adapter")


def test_omc_remove_command_leaves_claude_and_hud_checks_passing(tmp_path):
    api, home, _ = fake_omc_home(tmp_path)
    local = tmp_path / ".local/bin"
    local.mkdir(parents=True)
    adapter = local / "meridian-omc"
    adapter.write_bytes(OMC_ADAPTER.read_bytes())
    api["configure"](home, adapter)
    wrapper = local / "meridian-claude-hud"
    wrapper.write_text("#!/bin/sh\nprintf 'fixture hud\\n'\n")
    wrapper.chmod(0o755)
    claude = local / "claude"
    claude.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'[{"id":"claude-hud@claude-hud","enabled":true}]\'\n'
    )
    claude.chmod(0o755)
    reporter = tmp_path / ".orca/agent-hooks/claude-statusline.sh"
    reporter.parent.mkdir(parents=True)
    reporter.write_text("#!/bin/sh\nexit 0\n")
    reporter.chmod(0o755)
    launcher = home / "plugins/claude-hud/statusline.mjs"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    (home / "plugins/cache/claude-hud/claude-hud/fixture").mkdir(parents=True)
    checkout = home / "plugins/marketplaces/claude-hud"
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    settings = json.loads(
        claude_settings_filter("claude_settings", api["read"](home / "settings.json")).stdout
    )
    settings["statusLine"] = {"type": "command", "command": str(wrapper)}
    settings["extraKnownMarketplaces"] = {
        "claude-hud": {"source": {"ref": "fixture"}, "autoUpdate": False}
    }
    api["write"](home / "settings.json", settings)
    driver = tmp_path / "deploy/wsl/driver.sh"
    driver.parent.mkdir(parents=True)
    (driver.parent / "meridian-omc.py").write_bytes(OMC_ADAPTER.read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    exclude = tmp_path / ".git/info/exclude"
    exclude.write_text("keep-this\n/.omc/\n")
    functions = [
        "cmd_omc_remove",
        "omc_unignore_state",
        "check_claude",
        "check_claude_hud",
        "check_omc",
    ]
    program = "set -euo pipefail\n" + "\n".join(
        f"{name}() {{\n{setup_function_body(name)}\n}}" for name in functions
    )
    # Binary/version/managed-policy fixtures; the real settings and HUD guards run.
    program += '\nfail() { echo "$*" >&2; exit 1; }\nok() { echo "$*"; }\n'
    program += "version_ge() { return 0; }\nclaude_version() { echo fixture; }\n"
    program += "check_claude_managed() { return 0; }\n"
    program += (
        'npm() { [ "$*" = "uninstall -g --ignore-scripts --no-audit '
        '--no-fund oh-my-claude-sisyphus" ]; }\n'
    )
    program += "CLAUDE_MODEL=model\nCLAUDE_VERSION=floor\n"
    program += "CLAUDE_HUD_VERSION=fixture\nCLAUDE_HUD_REF=fixture\n"
    program += f"CLAUDE_HUD_COMMIT={commit}\n"
    program += 'CLAUDE_HUD_WRAPPER="${HOME}/.local/bin/meridian-claude-hud"\n'
    program += "cmd_omc_remove\ncheck_claude\ncheck_claude_hud\n(check_omc) && exit 9\nexit 0\n"
    driver.write_text(program)
    result = subprocess.run(
        ["bash", str(driver)],
        env=dict(os.environ, HOME=str(tmp_path)),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OMC absent" in result.stderr
    assert "Orca's usage reporter still fed" in result.stdout
    assert exclude.read_text() == "keep-this\n"


def run_ocr_step(tmp_path, step, version="1.13.9", provider=False):
    # cmd_ocr and check_ocr on a fake home with a fake curl that copies a local fake binary;
    # nothing is downloaded and the real home is untouched.
    fake = tmp_path / "ocr-release"
    fake.write_text(f'#!/bin/sh\necho "open-code-review v{version} (0e9060d) linux/amd64"\n')
    sha = subprocess.run(
        ["sha256sum", str(fake)], check=True, capture_output=True, text=True
    ).stdout.split()[0]
    home = tmp_path / "home"
    if provider:
        (home / ".opencodereview").mkdir(parents=True)
        (home / ".opencodereview" / "config.json").write_text("{}")
    script = (DEPLOY / "setup.sh").read_text()
    one_liner = re.search(r"^ocr_version\(\) \{.*\}$", script, re.M)
    assert one_liner, "setup.sh has no ocr_version"
    functions = "\n".join(
        [one_liner[0]]
        + [f"{f}() {{\n{setup_function_body(f)}\n}}" for f in ("cmd_ocr", "check_ocr")]
    )
    program = (
        'HOME=$1; PATH="$HOME/.local/bin:$PATH"; RELEASE=$2; CALLS=$3\n'
        f"OCR_VERSION=1.13.9\nOCR_SHA256={sha}\nOCR_URL=https://example.invalid/ocr\n"
        'fail() { echo "FAIL: $*" >&2; exit 1; }\nok() { echo "ok:   $*"; }\n'
        'curl() { echo "$@" >> "$CALLS"; cp "$RELEASE" "$2"; }\n' + functions + f"\n{step}"
    )
    calls = tmp_path / "curl-calls"
    result = subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", program, "t", str(home), str(fake), str(calls)],
        capture_output=True,
        text=True,
        check=False,
    )
    count = len(calls.read_text().splitlines()) if calls.exists() else 0
    return result, count


def test_the_ocr_step_installs_the_release_binary_once(tmp_path):
    first, downloads = run_ocr_step(tmp_path, "cmd_ocr")
    assert first.returncode == 0, first.stderr
    assert downloads == 1 and (tmp_path / "home/.local/bin/ocr").is_file()
    assert "ok:   open-code-review 1.13.9 in ~/.local/bin" in first.stdout
    again, downloads = run_ocr_step(tmp_path, "cmd_ocr")
    assert again.returncode == 0 and downloads == 1  # already there: no second download


def test_the_ocr_check_fails_on_another_version_or_a_provider_of_its_own(tmp_path):
    missing, _ = run_ocr_step(tmp_path, "check_ocr")
    assert missing.returncode == 1 and "is not 1.13.9" in missing.stderr
    other, _ = run_ocr_step(tmp_path, "cmd_ocr", version="1.13.8")
    assert other.returncode == 1 and "is not 1.13.9" in other.stderr
    run_ocr_step(tmp_path, "cmd_ocr")
    configured, _ = run_ocr_step(tmp_path, "check_ocr", provider=True)
    assert configured.returncode == 1 and "without a model provider" in configured.stderr


def test_ocr_comes_from_the_release_binary_not_the_self_updating_npm_package():
    assert (
        setup_value("OCR_URL")
        .strip('"')
        .endswith("/releases/download/v${OCR_VERSION}/opencodereview-linux-amd64")
    )
    assert "@alibaba-group/open-code-review" not in (DEPLOY / "setup.sh").read_text()


def start_shim(*command: str) -> subprocess.Popen[bytes]:
    # The client's input stays open, as dsh-lsp-stdio keeps it until shutdown.
    return subprocess.Popen(
        [sys.executable, "-I", str(DEPLOY / "dsh-lsp-root.py"), "/", *command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def finish(shim: subprocess.Popen[bytes], timeout: float) -> int:
    try:
        return shim.wait(timeout=timeout)
    finally:
        if shim.poll() is None:
            shim.kill()
            shim.wait()
        for stream in (shim.stdin, shim.stdout, shim.stderr):
            if stream:
                stream.close()


def test_the_shim_exits_with_the_server_while_the_client_keeps_its_input_open():
    started = time.monotonic()
    assert finish(start_shim("/bin/true"), timeout=5) == 0
    assert time.monotonic() - started < 2, "the shim outlived its server"
    assert finish(start_shim("sh", "-c", "exit 3"), timeout=5) == 3


def test_a_header_block_without_content_length_ends_the_session_cleanly():
    shim = start_shim("cat")
    assert shim.stdin is not None
    shim.stdin.write(b"X-Other: 1\r\n\r\n")
    shim.stdin.flush()
    # The shim closes the server's input; cat ends, and the shim returns its status.
    assert finish(shim, timeout=5) == 0


def test_sigterm_ends_the_shim_and_its_server():
    shim = start_shim("sh", "-c", "echo $$; exec sleep 30")
    assert shim.stdout is not None
    server = int(shim.stdout.readline())
    shim.send_signal(signal.SIGTERM)
    assert finish(shim, timeout=5) == 128 + signal.SIGTERM
    with pytest.raises(ProcessLookupError):
        os.kill(server, 0)
