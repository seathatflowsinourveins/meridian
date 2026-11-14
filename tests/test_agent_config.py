"""No agent configuration is committed here, apart from the shared skills, and setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code has MCP off machine-wide
and Codex allows only the servers ADR 0018 names (``deploy/wsl/meridian.user-data``);
Antigravity has no such setting. So the only
agent files git may list are the skills in ``.agents/skills/`` and their links in
``.claude/skills/``. This catches an accidental commit. It cannot stop a branch from outside the
owner's own sessions, which carries its own tests: AGENTS.md keeps such branches out of worktrees.
"""

import json
import re
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

# Folders the four agents (or Gemini CLI, whose layout Antigravity shares) read in a project, and
# the per-project state of oh-my-codex and serena.
AGENT_FOLDERS = (".agents/", ".claude/", ".codex/", ".gemini/", ".dsh/", ".omx/", ".serena/")
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
        ".omx/setup-scope.json",
        ".serena/project.yml",
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
    display = json.loads(file.read_text())["display"]
    assert display == {
        "showTools": True,
        "showAgents": True,
        "showTodos": True,
        "showAuth": False,
        "showAuthUser": False,
    }
    file.write_text('{"display": {"showTools": false}}')
    run_config_writer("claude_hud_config", tmp_path)
    assert json.loads(file.read_text()) == {"display": {"showTools": False}}


def setup_function_body(name):
    return (DEPLOY / "setup.sh").read_text().split(f"{name}() {{\n", 1)[1].split("\n}", 1)[0]


def setup_constant(name):
    found = re.search(
        rf"^{name}=(\S+|'[^']*'|\"[^\"]*\")$", (DEPLOY / "setup.sh").read_text(), re.M
    )
    assert found, f"setup.sh has no {name}"
    return found[1].strip("'\"")


DOCS_MCP = setup_constant("CODEX_DOCS_MCP")
PONYTAIL = f"ponytail@{setup_constant('PONYTAIL_MARKET')}"
SERENA_ARGS = setup_constant("SERENA_MCP_ARGS")
SERENA_TOOLS = setup_constant("SERENA_TOOLS")
SERENA = {
    "command": "serena",
    "args": ["start-mcp-server", "--project-from-cwd", "--context=codex"],
    "startup_timeout_sec": 15,
    "env": {"SERENA_USAGE_REPORTING": "false"},
}


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
            f"fixture_root=$1\nCODEX_MODEL=model\nDSH_MODEL=model\nCODEX_DOCS_MCP={DOCS_MCP}\n"
            f"SERENA_MCP_ARGS='{SERENA_ARGS}'\nSERENA_TOOLS='{SERENA_TOOLS}'\n"
            'fail() { echo "$*" >&2; exit 1; }\n' + functions + f"\n{name}",
            "test-config",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def write_codex_config(tmp_path):
    run_config_writer("codex_config", tmp_path, ("codex_config_file", "codex_setting"))


ORCA_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "Interrupt",
)
OMX_EVENTS = (
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "PreCompact",
    "PostCompact",
    "SubagentStop",
    "Stop",
)


def hook_label(event):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def codex_home(tmp_path, ponytail_trusted=0):
    # What setup leaves in ~/.codex: Orca's 9 hooks, then oh-my-codex's 8 in the group after them,
    # each with its trust entry, the ponytail plugin, and oh-my-codex's user file.
    write_codex_config(tmp_path)
    run_config_writer("omx_config", tmp_path)
    home = tmp_path / ".codex"
    hooks: dict[str, list] = {}
    for event in ORCA_EVENTS:
        hooks.setdefault(event, []).append({"hooks": [{"command": ": orca-agent-hook-form=1"}]})
    for event in OMX_EVENTS:
        command = '"node" "/x/oh-my-codex/dist/scripts/codex-native-hook.js"'
        hooks.setdefault(event, []).append({"hooks": [{"command": command}]})
    (home / "hooks.json").write_text(json.dumps({"hooks": hooks}))
    state = [
        f'[hooks.state."{home}/hooks.json:{hook_label(event)}:{g}:0"]\ntrusted_hash = "sha256:x"\n'
        for event, groups in hooks.items()
        for g in range(len(groups))
    ]
    state += [
        f'[hooks.state."{PONYTAIL}:hooks/claude-codex-hooks.json:{label}:0:0"]\n'
        'trusted_hash = "sha256:x"\n'
        for label in ("session_start", "subagent_start", "user_prompt_submit")[:ponytail_trusted]
    ]
    with (home / "config.toml").open("a") as f:
        f.write(f'\n[plugins."{PONYTAIL}"]\nenabled = true\n\n' + "\n".join(state))
    return home / "config.toml"


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
    program = "import" + body.split("<<'PY'", 1)[1].split("\nimport", 1)[1].split("\nPY", 1)[0]
    home = path.parent
    return subprocess.run(
        [sys.executable, "-I", "-", str(path), "model", str(home / "hooks.json")]
        + [str(home / ".omx-config.json"), DOCS_MCP, PONYTAIL, SERENA_ARGS],
        input=program,
        capture_output=True,
        text=True,
        check=False,
    )


def test_codex_config_sets_the_stack_and_keeps_other_tables(tmp_path):
    write_codex_config(tmp_path)
    path = tmp_path / ".codex/config.toml"
    original = path.read_text()
    assert tomllib.loads(original)["check_for_update_on_startup"] is False
    for setting in (
        "",
        "check_for_update_on_startup = true\n",
        '"check_for_update_on_startup" = true\n',
    ):
        text = original.replace("check_for_update_on_startup = false\n", setting)
        text = text.replace("apps = false", "apps = true").replace("plugins = true", "plugins = 0")
        text = text.replace('model_reasoning_effort = "high"', 'model_reasoning_effort = "medium"')
        text = text.replace(f'url = "{DOCS_MCP}"', 'url = "https://example.com/mcp"')
        text += (
            '\n[hooks.state.test]\ncommand = "keep"\n'
            '[projects."/example"]\ntrust_level = "trusted"\n'
        )
        path.write_text(text)
        write_codex_config(tmp_path)
        expected = tomllib.loads(text)
        expected["check_for_update_on_startup"] = False
        expected["model_reasoning_effort"] = "high"
        expected["features"] |= {"apps": False, "plugins": True}
        expected["mcp_servers"] = {"openaiDeveloperDocs": {"url": DOCS_MCP}, "serena": SERENA}
        assert tomllib.loads(path.read_text()) == expected
        once = path.read_bytes()
        write_codex_config(tmp_path)
        assert path.read_bytes() == once


def test_codex_check_accepts_the_stack_and_waits_for_ponytails_hooks(tmp_path):
    path = codex_home(tmp_path)
    result = codex_config_check(path)
    assert result.returncode == 0, result.stderr
    assert "3 of ponytail's 3 hooks wait for the owner's /hooks" in result.stdout
    path = codex_home(tmp_path / "trusted", ponytail_trusted=3)
    result = codex_config_check(path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


ADD = "[analytics]"


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ("check_for_update_on_startup = false\n", "", "check_for_update_on_startup"),
        ("check_for_update_on_startup = false", "check_for_update_on_startup = true", "startup"),
        ("apps = false", "apps = true", "[features] apps"),
        ("plugins = true", "plugins = false", "[features] plugins"),
        ('model_reasoning_effort = "high"', 'model_reasoning_effort = "medium"', "effort"),
        (ADD, '[mcp_servers.broker]\ncommand = "broker-mcp"\n\n' + ADD, "MCP servers"),
        (f'url = "{DOCS_MCP}"', 'url = "https://example.com/mcp"', "openaiDeveloperDocs"),
        ('"--context=codex"', '"--context=agent"', "[mcp_servers.serena]"),
        ('command = "serena"', 'command = "/tmp/serena"', "[mcp_servers.serena]"),
        (
            'SERENA_USAGE_REPORTING = "false"',
            'SERENA_USAGE_REPORTING = "true"',
            "[mcp_servers.serena]",
        ),
        (ADD, '[plugins."broker@example"]\nenabled = true\n\n' + ADD, "plugins ["),
        (ADD, '[profiles.x.mcp_servers.y]\nurl = "https://example.com"\n\n' + ADD, "a profile"),
        ('trusted_hash = "sha256:x"\n', "", "hooks without trust"),
    ],
)
def test_codex_check_rejects_what_the_stack_does_not_name(tmp_path, old, new, named):
    path = codex_home(tmp_path)
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))
    result = codex_config_check(path)
    assert result.returncode != 0
    assert named in result.stderr


def test_codex_check_rejects_a_hook_that_is_neither_orcas_nor_oh_my_codexs(tmp_path):
    path = codex_home(tmp_path)
    hooks_file = path.parent / "hooks.json"
    hooks = json.loads(hooks_file.read_text())
    hooks["hooks"]["Stop"].append({"hooks": [{"command": "curl https://example.com"}]})
    hooks_file.write_text(json.dumps(hooks))
    with path.open("a") as f:
        f.write(f'\n[hooks.state."{hooks_file}:stop:2:0"]\ntrusted_hash = "sha256:x"\n')
    result = codex_config_check(path)
    assert result.returncode != 0
    assert "'unknown': 1" in result.stderr


@pytest.mark.parametrize("change", ["remove", "team", "triage"])
def test_codex_check_requires_oh_my_codex_team_mode_and_triage_off(tmp_path, change):
    path = codex_home(tmp_path)
    omx_file = path.parent / ".omx-config.json"
    if change == "remove":
        omx_file.unlink()
    else:
        settings = json.loads(omx_file.read_text())
        if change == "team":
            settings["teamMode"] = "enabled"
        else:
            settings["promptRouting"]["triage"]["enabled"] = True
        omx_file.write_text(json.dumps(settings))
    assert codex_config_check(path).returncode != 0


def test_omx_config_keeps_other_keys_and_is_stable(tmp_path):
    path = tmp_path / ".codex/.omx-config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"teamMode": "enabled", "other": 1, "promptRouting": {"x": 2}}))
    run_config_writer("omx_config", tmp_path)
    assert json.loads(path.read_text()) == {
        "teamMode": "disabled",
        "other": 1,
        "promptRouting": {"x": 2, "triage": {"enabled": False}},
    }
    once = path.read_bytes()
    run_config_writer("omx_config", tmp_path)
    assert path.read_bytes() == once


def user_data_requirements():
    # The literal block under the requirements file in the definition, read without the script.
    lines = (DEPLOY / "meridian.user-data").read_text().splitlines()
    start = lines.index("  - path: /etc/codex/requirements.toml")
    start = lines.index("    content: |", start) + 1
    block = []
    for line in lines[start:]:
        if line and not line.startswith("      "):
            break
        block.append(line[6:])
    return "\n".join(block).rstrip("\n") + "\n"


def test_codex_requirements_text_is_the_definitions_and_names_each_server(tmp_path):
    function = setup_function_body("codex_requirements_text")
    written = subprocess.run(
        ["bash", "-c", f"f() {{\n{function}\n}}\nf $1", "x", str(DEPLOY / "meridian.user-data")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert written == user_data_requirements()
    requirements = tomllib.loads(written)
    assert requirements["features"] == {"apps": False}
    write_codex_config(tmp_path)
    servers = tomllib.loads((tmp_path / ".codex/config.toml").read_text())["mcp_servers"]
    # Codex compares the identity with the configured command or URL exactly.
    assert requirements["mcp_servers"] == {
        name: {"identity": {key: server[key] for key in ("url", "command") if key in server}}
        for name, server in servers.items()
    }


def serena_config_check(tmp_path):
    body = setup_function_body("serena_config_check")
    program = body.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    return subprocess.run(
        [sys.executable, "-I", "-", str(tmp_path / ".serena/serena_config.yml"), SERENA_TOOLS],
        input=program,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("", ""),
        ("agent_interface: tools", "agent_interface: REPL"),
        ("web_dashboard: false", "web_dashboard: true"),
        ("web_dashboard_open_on_launch: false", "web_dashboard_open_on_launch: true"),
        ("fixed_tools: [", "fixed_tools: [execute_shell_command, "),
        ("projects: []", "projects: []\nincluded_optional_tools: [open_dashboard]"),
        ("ls_path: .venv/bin/pyright-langserver", "ls_path: pyright-langserver"),
    ],
)
def test_serena_config_serves_only_navigation_and_diagnostics(tmp_path, old, new):
    pytest.importorskip("yaml")
    run_config_writer("serena_config", tmp_path)
    path = tmp_path / ".serena/serena_config.yml"
    path.write_text(path.read_text().replace(old, new, 1))
    assert (serena_config_check(tmp_path).returncode == 0) == (old == new)


def test_serena_tools_hold_no_shell_edit_or_memory_tool():
    tools = SERENA_TOOLS.split(", ")
    assert len(tools) == 7
    assert all(t.startswith(("get_", "find_")) for t in tools), tools


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
