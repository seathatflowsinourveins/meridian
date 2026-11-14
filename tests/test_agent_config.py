"""Only admitted agent configuration is committed; setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code and Codex have MCP off
machine-wide (``deploy/wsl/meridian.user-data``); Antigravity has no such setting. So the only
agent files git may list are shared skills and their Claude links, plus ADR 0019's exact
OMC stage schedule (checked below). Runtime state remains forbidden. This catches accidental
commits; branches outside the owner's sessions stay out under docs/HANDBOOK.md (Rules).
"""

import json
import os
import re
import runpy
import subprocess
import sys
import time
import tomllib

import pytest
from test_paper_only import REPO_ROOT, git_files

DEPLOY = REPO_ROOT / "deploy" / "wsl"
# The newest first-patched version among GitHub's published advisories for the GitHub CLI
# (UPSTREAM.md, GitHub CLI row). The pin may not fall below it.
GH_NEWEST_FIX = (2, 97, 0)

# Folders the four agents (or Gemini CLI, whose layout Antigravity shares) read in a project.
AGENT_FOLDERS = (".agents/", ".claude/", ".codex/", ".gemini/", ".dsh/", ".omc/")
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


def run_wrapper(home, payload, launcher=None, reporter=None):
    # The wrapper under a fake home: no real Orca, claude-hud or settings file is touched.
    if launcher is not None:
        path = home / ".claude" / "plugins" / "claude-hud" / "statusline.mjs"
        path.parent.mkdir(parents=True)
        path.write_text(launcher)
    if reporter is not None:
        path = home / ".orca" / "agent-hooks" / "claude-statusline.sh"
        path.parent.mkdir(parents=True)
        path.write_text(reporter)
        path.chmod(0o755)
    environment = {"HOME": str(home), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    return subprocess.run(
        [str(DEPLOY / "meridian-claude-hud.sh")],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=20,
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
    received = tmp_path / "received"
    reporter = f'#!/bin/sh\ncat > "{received}"\nsleep 5\necho noise\necho noise >&2\n'
    started = time.monotonic()
    result = run_wrapper(tmp_path, PAYLOAD, reporter=reporter)
    assert time.monotonic() - started < 4, "the wrapper waited for Orca's reporter"
    assert (result.returncode, result.stdout, result.stderr) == (0, PLAIN_LINE, "")
    for _ in range(40):
        if received.exists() and received.read_text() == PAYLOAD:
            break
        time.sleep(0.05)
    assert received.read_text() == PAYLOAD


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


def test_the_upkeep_prompt_names_what_a_run_must_never_do():
    script = (DEPLOY / "setup.sh").read_text()
    prompt = script.split("UPKEEP_PROMPT='", 1)[1].split("\n\nupkeep_automation() {", 1)[0]
    never = prompt.split("Never:", 1)[1]
    for phrase in (
        "merge a pull request",
        "deploy/wsl/setup.sh orca",
        "orca-ide serve",
        "start a lane",
        "key or credential",
        "risk/",
        "plugin, skill or MCP server",
    ):
        assert phrase in never, phrase
    # upkeep leaves Orca's server to the owner: it restarts every session.
    upkeep = setup_function_body("cmd_upkeep")
    assert "cmd_orca\n" not in upkeep
    for installer in ("cmd_gh", "cmd_claude", "cmd_codex", "cmd_agy", "cmd_dsh", "cmd_claude_hud"):
        assert f"  {installer}\n" in upkeep, installer


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
    home = tmp_path / "claude"
    user = tmp_path / "config.jsonc"
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
    api["prepare"](home, user)
    for event, names in api["HOOKS"].items():
        for name in names:
            path = home / "hooks" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('console.log(JSON.stringify({decision:"block",reason:"upstream"}));\n')
            settings["hooks"][event].append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'node "{path}"',
                        }
                    ]
                }
            )
    api["write"](home / "settings.json", settings)
    api["write"](home / ".omc-version.json", {"version": api["VERSION"]})
    (home / "CLAUDE.md").write_text("upstream instructions\n")
    for name in ("autopilot", "ralph", "ralplan", "team", "verify", "cancel"):
        path = home / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.touch()
    api["configure"](home, OMC_ADAPTER)
    return api, home, user


def test_omc_configuration_is_idempotent_and_preserves_orca_and_hud(tmp_path):
    api, home, user = fake_omc_home(tmp_path)
    api["check"](home, user, OMC_ADAPTER)
    once = (home / "settings.json").read_bytes(), (home / "CLAUDE.md").read_bytes()
    api["prepare"](home, user)
    api["configure"](home, OMC_ADAPTER)
    api["check"](home, user, OMC_ADAPTER)
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
        api["check"](home, user, OMC_ADAPTER)


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
        api["check"](home, user, OMC_ADAPTER, require_orca=False)
    before = api["read"](home / ".meridian-omc-before.json")
    before["hooks"] = {}
    api["write"](home / ".meridian-omc-before.json", before)
    api["check"](home, user, OMC_ADAPTER, require_orca=False)
    with pytest.raises(AssertionError):
        api["check"](home, user, OMC_ADAPTER)


def test_omc_setup_ignores_state_once_without_replacing_existing_exclusions(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    exclude = tmp_path / ".git/info/exclude"
    exclude.write_text("keep-this\n")
    program = f"omc_ignore_state() {{\n{setup_function_body('omc_ignore_state')}\n}}"
    program += '\nomc_ignore_state "$1"\nomc_ignore_state "$1"\n'
    subprocess.run(["bash", "-euc", program, "fixture", str(tmp_path)], check=True)
    assert exclude.read_text() == "keep-this\n\n/.omc/\n"
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
