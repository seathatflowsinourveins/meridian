"""Only admitted agent configuration is committed; setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code has MCP off machine-wide
and Codex allows only the servers ADR 0018 names (``deploy/wsl/meridian.user-data``);
Antigravity has no such setting. So the only agent files git may list are shared skills and
their Claude links, plus ADR 0019's exact OMC stage schedule (checked below). Runtime state
remains forbidden. This catches accidental commits; branches outside the owner's sessions stay
out under docs/HANDBOOK.md (Rules).
"""

import hashlib
import importlib.util
import json
import os
import re
import runpy
import shutil
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
# Also the project folders of serena (the MCP server dsh runs, ADR 0016, and Codex's, ADR 0018),
# oh-my-codex (ADR 0018) and beads.
AGENT_FOLDERS = (
    ".agents/",
    ".claude/",
    ".codex/",
    ".gemini/",
    ".dsh/",
    ".omx/",
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
        ".omx/setup-scope.json",
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
    body = script.split(f"{function}() {{\n", 1)[1].split("\n}\n\n", 1)[0]
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
    return (DEPLOY / "setup.sh").read_text().split(f"{name}() {{\n", 1)[1].split("\n}\n\n", 1)[0]


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
            f"fixture_root=$1\nCODEX_MODEL=model\nDSH_MODEL={model}\nCODEX_DOCS_MCP={DOCS_MCP}\n"
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


def codex_trust_hash(event, handler, matcher=None):
    # Codex's hook trust identity, written out again for the fixtures (hooks crate, discovery.rs
    # `hook_hash`, and config/src/fingerprint.rs at rust-v0.167.2 and rust-v0.169.0).
    timeout = handler.get("timeout")
    if event in ("SessionEnd", "Interrupt"):
        timeout = min(max(timeout or 1, 1), 3)
    else:
        timeout = max(600 if timeout is None else timeout, 1)
    normalized = {"type": "command", "command": handler["command"], "timeout": timeout}
    normalized["async"] = bool(handler.get("async"))
    if "statusMessage" in handler:
        normalized["statusMessage"] = handler["statusMessage"]
    identity = {"event_name": hook_label(event), "hooks": [normalized]}
    if matcher is not None and event not in ("UserPromptSubmit", "Stop", "Interrupt"):
        identity["matcher"] = matcher
    text = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def bundle_hash(root):
    # codex-rs/hooks/src/engine/plugin_fingerprint.rs: names and contents, depth first, sorted.
    digest = hashlib.sha256(b"codex-plugin-bundle-v1")
    pending = [root]
    while pending:
        path = pending.pop()
        name = str(path.relative_to(root)).encode() if path != root else b""
        digest.update(len(name).to_bytes(8, "little") + name)
        if path.is_dir():
            digest.update(b"directory")
            pending.extend(sorted(path.iterdir(), key=lambda p: p.name.encode(), reverse=True))
        else:
            data = path.read_bytes()
            digest.update(b"file" + len(data).to_bytes(8, "little") + data)
    return "sha256:" + digest.hexdigest()


PONYTAIL_HOOKS = {
    "SessionStart": [
        {
            "matcher": "startup|resume",
            "hooks": [
                {
                    "type": "command",
                    "command": "node a.js",
                    "timeout": 15,
                    "statusMessage": "Loading",
                }
            ],
        }
    ],
    "SubagentStart": [{"hooks": [{"type": "command", "command": "node b.js", "timeout": 15}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "node c.js", "timeout": 15}]}],
}


PONYTAIL_SKILLS = (
    "ponytail",
    "ponytail-audit",
    "ponytail-debt",
    "ponytail-gain",
    "ponytail-help",
    "ponytail-review",
)


def ponytail_bundle(plugin):
    (plugin / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "ponytail", "version": "5.3.3", "skills": "./skills/"})
    )
    for name in PONYTAIL_SKILLS:
        folder = plugin / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(f"synthetic {name}\n")


def codex_home(tmp_path, ponytail_trusted=0, orca=True, enabled=None):
    # What setup leaves in ~/.codex: Orca's 9 hooks (on a fresh distro, not yet: Orca is set up
    # after Codex), then oh-my-codex's 8 in the group after them, each with its trust entry at
    # its current hash, the ponytail plugin's installed copy, and oh-my-codex's user file.
    if enabled is None:
        enabled = ponytail_trusted == 3
    write_codex_config(tmp_path)
    run_config_writer("omx_config", tmp_path)
    home = tmp_path / ".codex"
    hooks: dict[str, list] = {}
    for event in ORCA_EVENTS if orca else ():
        hooks.setdefault(event, []).append({"hooks": [{"command": ": orca-agent-hook-form=1"}]})
    for event in OMX_EVENTS:
        command = '"node" "/x/oh-my-codex/dist/scripts/codex-native-hook.js"'
        hooks.setdefault(event, []).append({"hooks": [{"command": command}]})
    (home / "hooks.json").write_text(json.dumps({"hooks": hooks}))
    state = [
        f'[hooks.state."{home}/hooks.json:{hook_label(event)}:{g}:0"]\n'
        f'trusted_hash = "{codex_trust_hash(event, group["hooks"][0])}"\n'
        for event, groups in hooks.items()
        for g, group in enumerate(groups)
    ]
    plugin = home / "plugins/cache" / PONYTAIL.split("@")[1] / "ponytail" / "5.3.3"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "hooks/claude-codex-hooks.json").write_text(json.dumps({"hooks": PONYTAIL_HOOKS}))
    (plugin / "README.md").write_text("ponytail\n")
    ponytail_bundle(plugin)
    content = bundle_hash(plugin)
    for event in list(PONYTAIL_HOOKS)[:ponytail_trusted]:
        group = PONYTAIL_HOOKS[event][0]
        state.append(
            f'[hooks.state."{PONYTAIL}:hooks/claude-codex-hooks.json:{hook_label(event)}:0:0"]\n'
            f'trusted_hash = "{codex_trust_hash(event, group["hooks"][0], group.get("matcher"))}"\n'
            f'trusted_content_hash = "{content}"\n'
        )
    with (home / "config.toml").open("a") as f:
        f.write(
            f'\n[plugins."{PONYTAIL}"]\nenabled = {str(enabled).lower()}\n\n' + "\n".join(state)
        )
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


def upkeep_hold(tmp_path, reason, step):
    # upkeep_held alone, then the first lines of cmd_upkeep up to its hold check, on a fake
    # home: no installer is reached.
    hold = tmp_path / ".cache" / "meridian" / "upkeep.hold"
    hold.parent.mkdir(parents=True, exist_ok=True)
    if reason is not None:
        hold.write_text(reason)
    body = setup_function_body("cmd_upkeep")
    guard = body[: body.index('"${HOME}/.local/bin/claude" update')]
    program = (
        f'UPKEEP_HOLD="{hold}"\nfail() {{ echo "FAIL: $*" >&2; exit 1; }}\n'
        f"upkeep_held() {{\n{setup_function_body('upkeep_held')}\n}}\n"
        f"guarded_upkeep() {{\n{guard}\n  echo installers-would-run\n}}\n{step}"
    )
    return subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_hold_file_with_a_reason_stops_upkeep_and_says_why(tmp_path):
    held = upkeep_hold(tmp_path, "ponytail off by hand until the fix lands\n", "guarded_upkeep")
    assert held.returncode == 1 and "installers-would-run" not in held.stdout
    assert "ponytail off by hand until the fix lands" in held.stdout
    assert "installs nothing while it is on hold" in held.stderr


@pytest.mark.parametrize("reason", [None, ""])
def test_no_hold_file_or_an_empty_one_lets_upkeep_run(tmp_path, reason):
    free = upkeep_hold(tmp_path, reason, "guarded_upkeep")
    assert free.returncode == 0 and free.stdout == "installers-would-run\n"


def test_drift_does_not_start_the_weekly_run_while_on_hold():
    drift = setup_function_body("cmd_drift")
    # The hold is asked after the table and the issue line, and before the "due" verdict.
    assert drift.index("upkeep_held") > drift.index("drift_report <<EOF")
    assert drift.index("upkeep_held") < drift.index("drift: there is upkeep to do")
    held = drift[drift.index("if upkeep_held; then") :].split("fi", 1)[0]
    assert "return 1" in held


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
        "register BRANCH --builder claude --task TASK_ID",
        "auto BRANCH --builder claude TITLE BODY.md",
        "The gate runs the Codex review",
        "holds `~/.cache/meridian/landing.lock` itself from `trial` through `land`",
        "run the gate without an outer flock",
        "never go around it",
        "git -C ~/src/meridian pull --ff-only",
        "~/src/meridian/deploy/wsl/setup.sh upkeep",
        "~/src/meridian/deploy/wsl/setup.sh agents-check",
        "~/src/meridian/deploy/wsl/setup.sh drift",
    ):
        assert phrase in steps, phrase
    assert "flock ~/.cache/meridian/landing.lock" not in steps
    assert "codex review --base origin/main" not in steps
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


def codex_config_check(path, mode="full"):
    body = setup_function_body("codex_config_check")
    program = "import" + body.split("<<'PY'", 1)[1].split("\nimport", 1)[1].split("\nPY", 1)[0]
    home = path.parent
    return subprocess.run(
        [sys.executable, "-I", "-", str(path), "model", str(home / "hooks.json")]
        + [str(home / ".omx-config.json"), DOCS_MCP, PONYTAIL, SERENA_ARGS, mode, "5.3.3"],
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
    assert "ponytail installed and disabled; owner: outside Orca" in result.stdout
    path = codex_home(tmp_path / "trusted", ponytail_trusted=3)
    result = codex_config_check(path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "damage", ["bundle", "manifest", "skills", "one-skill", "version", "old-cache"]
)
def test_codex_check_rejects_missing_or_wrong_ponytail_bundle(tmp_path, damage):
    path = codex_home(tmp_path)
    plugin = path.parent / "plugins/cache/meridian-ponytail/ponytail/5.3.3"
    if damage == "bundle":
        shutil.rmtree(plugin)
    elif damage == "manifest":
        (plugin / ".codex-plugin/plugin.json").unlink()
    elif damage == "skills":
        shutil.rmtree(plugin / "skills")
    elif damage == "one-skill":
        (plugin / "skills/ponytail-review/SKILL.md").unlink()
    elif damage == "version":
        (plugin / ".codex-plugin/plugin.json").write_text('{"name":"ponytail","version":"5.3.2"}')
    else:
        plugin.rename(plugin.with_name("5.3.2"))
    result = codex_config_check(path)
    assert result.returncode != 0
    assert "ponytail 5.3.3 bundle missing or incomplete" in result.stderr


def test_codex_check_rejects_enabled_ponytail_with_untrusted_hooks(tmp_path):
    result = codex_config_check(codex_home(tmp_path, enabled=True))
    assert result.returncode != 0
    assert "Codex workers cannot start under Orca" in result.stderr


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
        ('trusted_hash = "sha256:', 'trusted_hash = "sha256:0', "hooks without trust"),
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
    assert requirements["features"] == {
        "apps": False,
        "remote_plugin": False,
        "plugin_sharing": False,
    }
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
        ("initial_instructions, ", ""),
        ("fixed_tools: [", "fixed_tools: [execute_shell_command, "),
        ("fixed_tools: [", "fixed_tools: [replace_symbol_body, "),
        ("fixed_tools: [", "fixed_tools: [read_memory, "),
        ("fixed_tools: [", "fixed_tools: [write_memory, "),
        ("projects: []", "projects: []\nincluded_optional_tools: [open_dashboard]"),
        ("ls_path: .venv/bin/pyright-langserver", "ls_path: pyright-langserver"),
    ],
)
def test_serena_config_serves_only_manual_navigation_and_diagnostics(tmp_path, old, new):
    pytest.importorskip("yaml")
    run_config_writer("serena_config", tmp_path)
    path = tmp_path / ".serena/serena_config.yml"
    path.write_text(path.read_text().replace(old, new, 1))
    assert (serena_config_check(tmp_path).returncode == 0) == (old == new)


def test_serena_tools_hold_no_shell_edit_or_memory_tool(tmp_path):
    yaml = pytest.importorskip("yaml")
    run_config_writer("serena_config", tmp_path)
    cfg = yaml.safe_load((tmp_path / ".serena/serena_config.yml").read_text())
    assert cfg["fixed_tools"] == [
        "initial_instructions",
        "get_symbols_overview",
        "find_symbol",
        "find_referencing_symbols",
        "find_implementations",
        "find_declaration",
        "get_diagnostics_for_file",
        "get_diagnostics_for_symbol",
    ]


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
    for name in (
        "DSH_LSP_INTEGRITY",
        "DSH_LSP_STDIO_INTEGRITY",
        "DSH_TOOL_LSP_INTEGRITY",
        "DSH_HOOKS_INTEGRITY",
        "DSH_HOOK_PROTOCOL_INTEGRITY",
    ):
        assert re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", setup_pin(name)), f"{name} is not sha512"
        assert setup_pin(name) in upstream, f"{name} has no UPSTREAM.md row"


def test_code_navigation_is_the_read_only_lsp_tool_on_the_worktrees_own_pyright(tmp_path):
    run_config_writer("dsh_home_files", tmp_path)
    block = (tmp_path / ".dsh/cordis.patch.yml").read_text(encoding="utf-8")
    for package in ("dsh-lsp", "dsh-lsp-stdio", "dsh-tool-lsp"):
        assert f"      name: '@deepseek-ai/{package}'\n" in block
    assert "dsh-mcp-client" not in block, "the stack adds no MCP server"


def setup_array(name):
    block = re.search(rf"^{name}=\((.*?)\)$", SETUP, re.M | re.S)
    assert block, f"setup.sh has no {name} list"
    return block[1].split()


FAKE_DSH = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
calls = Path(os.environ["DSH_CALLS"])
with calls.open("a") as log:
    log.write(" ".join(args) + "\\n")
home = Path(os.environ["HOME"])


def manifest(profile):
    path = home / ".dsh" / "profiles" / profile / "package.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": "dsh-profile-" + profile, "dependencies": {},
                                    "dsh": {"profile": {"bundles": []}}}) + "\\n")
    return path


if args[:1] == ["--profile"]:
    if "--dump-config" in args:
        manifest(args[1])
elif args[:1] == ["plugin"]:
    assert args[1] == "--profile" and args[3] == "add", args
    path = manifest(args[2])
    data = json.loads(path.read_text())
    for spec in args[4:]:
        name, _, version = spec.rpartition("@")
        data.setdefault("dependencies", {})[name] = version
    path.write_text(json.dumps(data) + "\\n")
else:
    sys.exit("unexpected fake dsh arguments: " + " ".join(args))
"""


def run_dsh_package_install(fixture):
    home = fixture / "home"
    calls = fixture / "calls"
    fake = home / ".local/bin/dsh"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(FAKE_DSH)
    fake.chmod(0o755)
    lsp, hook = setup_array("DSH_LSP_PACKAGES"), setup_array("DSH_HOOK_PACKAGES")
    functions = "\n".join(
        f"{name}() {{\n{setup_function_body(name)}\n}}"
        for name in (
            "dsh_profile_init",
            "dsh_profile_package",
            "dsh_lsp_packages",
            "dsh_hook_packages",
        )
    )
    program = (
        "set -euo pipefail\n"
        'HOME=$1; DSH_CALLS=$2; PATH="$HOME/.local/bin:$PATH"; export DSH_CALLS\n'
        f"DSH_VERSION={setup_pin('DSH_VERSION')}\n"
        f"DSH_LSP_PACKAGES=({' '.join(lsp)})\n"
        f"DSH_HOOK_PACKAGES=({' '.join(hook)})\n"
        f"DSH_LSP_INTEGRITY={setup_pin('DSH_LSP_INTEGRITY')}\n"
        f"DSH_LSP_STDIO_INTEGRITY={setup_pin('DSH_LSP_STDIO_INTEGRITY')}\n"
        f"DSH_TOOL_LSP_INTEGRITY={setup_pin('DSH_TOOL_LSP_INTEGRITY')}\n"
        f"DSH_HOOKS_INTEGRITY={setup_pin('DSH_HOOKS_INTEGRITY')}\n"
        f"DSH_HOOK_PROTOCOL_INTEGRITY={setup_pin('DSH_HOOK_PROTOCOL_INTEGRITY')}\n"
        'version_ge() { [ -n "${1:-}" ] && [ "$1" = "$2" ]; }\n'
        'npm_pinned() { printf "pinned %s %s\\n" "$1" "$2" >> "$DSH_CALLS"; }\n'
        'fail() { echo "FAIL: $*" >&2; exit 1; }\n'
        + functions
        + "\ndsh_lsp_packages dsh-tui\ndsh_lsp_packages headless\n"
        "dsh_hook_packages dsh-tui\ndsh_hook_packages headless\n"
    )
    subprocess.run(
        ["bash", "-c", program, "test-dsh-install", str(home), str(calls)],
        check=True,
        capture_output=True,
        text=True,
    )
    return home, calls, lsp, hook


def test_the_lsp_and_hook_packages_are_installed_in_both_profiles(tmp_path):
    home, calls, lsp, hook = run_dsh_package_install(tmp_path)
    version = setup_pin("DSH_VERSION")
    for profile in ("dsh-tui", "headless"):
        manifest = json.loads((home / f".dsh/profiles/{profile}/package.json").read_text())
        for package in (*lsp, *hook):
            assert manifest["dependencies"][f"@deepseek-ai/{package}"] == version
    logged = calls.read_text().splitlines()
    assert "--profile headless --dump-config" in logged, (
        "headless was not created from its template"
    )
    expected = {
        "dsh-lsp": setup_pin("DSH_LSP_INTEGRITY"),
        "dsh-lsp-stdio": setup_pin("DSH_LSP_STDIO_INTEGRITY"),
        "dsh-tool-lsp": setup_pin("DSH_TOOL_LSP_INTEGRITY"),
        "dsh-hooks-claude-code": setup_pin("DSH_HOOKS_INTEGRITY"),
        "dsh-hook-protocol": setup_pin("DSH_HOOK_PROTOCOL_INTEGRITY"),
    }
    for profile in ("dsh-tui", "headless"):
        for package in (*lsp, *hook):
            assert any(
                line.startswith(f"plugin --profile {profile} add")
                and f"@deepseek-ai/{package}@{version}" in line
                for line in logged
            ), (profile, package)
    for package, integrity in expected.items():
        assert f"pinned @deepseek-ai/{package}@{version} {integrity}" in logged, package
    before = calls.read_text()
    run_dsh_package_install(tmp_path)
    assert calls.read_text() == before, "a second install changed an up-to-date profile"


def dsh_stack_config(home):
    args = (
        "        args: ['-c', 'top=\"$(git rev-parse --show-toplevel)\" && "
        f"exec python3 -I {home}/.dsh/lsp/dsh-lsp-root.py "
        '"$top" "$top/.venv/bin/pyright-langserver" --stdio\']\n'
    )
    return (
        "- id: meridian-lsp\n"
        "  name: '@deepseek-ai/dsh-lsp'\n"
        "- id: meridian-lsp-pyright\n"
        "  name: '@deepseek-ai/dsh-lsp-stdio'\n"
        "  config:\n"
        "    servers:\n"
        "      pyright:\n"
        "        command: sh\n" + args + "        extensionToLanguage:\n"
        "          '.py': python\n"
        "- id: meridian-tool-lsp\n"
        "  name: '@deepseek-ai/dsh-tool-lsp'\n"
        "- id: meridian-check-gate\n"
        "  name: '@deepseek-ai/dsh-hooks-claude-code'\n"
    )


def run_dsh_profile_check(tmp_path, name, profile, packages, missing_row=None):
    root = tmp_path / name
    home = root / "home"
    profile_dir = home / ".dsh/profiles" / profile
    profile_dir.mkdir(parents=True)
    version = setup_pin("DSH_VERSION")
    (profile_dir / "package.json").write_text(
        json.dumps({"dependencies": {f"@deepseek-ai/{p}": version for p in packages}})
    )
    shim = home / ".dsh/lsp/dsh-lsp-root.py"
    shim.parent.mkdir(parents=True)
    shim.write_bytes((DEPLOY / "dsh-lsp-root.py").read_bytes())
    driver_dir = root / "deploy/wsl"
    driver_dir.mkdir(parents=True)
    (driver_dir / "dsh-lsp-root.py").write_bytes((DEPLOY / "dsh-lsp-root.py").read_bytes())
    config = dsh_stack_config(home)
    if missing_row is not None:
        config = config.replace(f"- id: {missing_row}\n", "")
    config_path = root / "config.yml"
    config_path.write_text(config)
    one_liner = re.search(r"^dsh_row\(\) \{.*\}$", SETUP, re.M)
    assert one_liner, "setup.sh has no dsh_row"
    functions = "\n".join(
        [one_liner[0]]
        + [
            f"{name}() {{\n{setup_function_body(name)}\n}}"
            for name in ("dsh_profile_package", "dsh_rows_named", "check_dsh_profile")
        ]
    )
    driver = driver_dir / "driver.sh"
    driver.write_text(
        "set -euo pipefail\n"
        f"DSH_VERSION={version}\n"
        f"DSH_LSP_PACKAGES=({' '.join(setup_array('DSH_LSP_PACKAGES'))})\n"
        f"DSH_HOOK_PACKAGES=({' '.join(setup_array('DSH_HOOK_PACKAGES'))})\n"
        'version_ge() { [ -n "${1:-}" ] && [ "$1" = "$2" ]; }\n'
        'fail() { echo "FAIL: $*" >&2; exit 1; }\n'
        'ok() { echo "ok: $*"; }\n' + functions + '\ncheck_dsh_profile "$1" "$(cat "$2")"\n'
    )
    return subprocess.run(
        ["bash", str(driver), profile, str(config_path)],
        env=dict(os.environ, HOME=str(home)),
        capture_output=True,
        text=True,
        check=False,
    )


def test_agents_check_verifies_the_five_packages_and_four_rows_in_both_profiles(tmp_path):
    packages = [*setup_array("DSH_LSP_PACKAGES"), *setup_array("DSH_HOOK_PACKAGES")]
    for profile in ("dsh-tui", "headless"):
        result = run_dsh_profile_check(tmp_path, f"ok-{profile}", profile, packages)
        assert result.returncode == 0, result.stderr
    missing = run_dsh_profile_check(tmp_path, "missing-package-headless", "headless", packages[:-1])
    assert missing.returncode == 1
    assert "@deepseek-ai/dsh-hook-protocol" in missing.stderr and "headless" in missing.stderr
    row = run_dsh_profile_check(
        tmp_path, "missing-gate-tui", "dsh-tui", packages, missing_row="meridian-check-gate"
    )
    assert row.returncode == 1
    assert "meridian-check-gate" in row.stderr and "dsh-tui" in row.stderr


def test_check_dsh_dumps_both_profiles_and_checks_each():
    check = setup_function_body("check_dsh")
    assert "--profile headless --dump-config" in check
    assert 'check_dsh_stack "${config}" "${headless_config}"' in check
    stack = setup_function_body("check_dsh_stack")
    assert 'check_dsh_profile dsh-tui "${config_tui}"' in stack
    assert 'check_dsh_profile headless "${config_headless}"' in stack


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


def test_the_install_check_lets_a_fresh_distro_finish_before_orca_prepares_codex(tmp_path):
    # `setup.sh agents` runs cmd_codex before cmd_orca: Orca's hooks are not there yet.
    path = codex_home(tmp_path, orca=False)
    result = codex_config_check(path, "install")
    assert result.returncode == 0, result.stderr
    assert "Orca's 9 Codex hooks are not there yet" in result.stdout
    assert "ponytail installed and disabled" in result.stdout
    # agents-check still requires them.
    assert "hooks.json entries" in codex_config_check(path).stderr
    # Installed and trusted later, both checks pass.
    path = codex_home(tmp_path / "later")
    assert codex_config_check(path, "install").returncode == 0
    assert codex_config_check(path).returncode == 0


@pytest.mark.parametrize(
    "break_", ["untrusted omx hook", "unknown hook", "no hooks.json", "orca partly"]
)
def test_the_install_check_still_rejects_what_setup_did_not_write(tmp_path, break_):
    path = codex_home(tmp_path, orca=False)
    hooks_file = path.parent / "hooks.json"
    hooks = json.loads(hooks_file.read_text())
    if break_ == "untrusted omx hook":
        path.write_text(
            path.read_text().replace('trusted_hash = "sha256:', 'trusted_hash = "sha256:0', 1)
        )
    elif break_ == "unknown hook":
        hooks["hooks"]["Stop"].append({"hooks": [{"command": "curl https://example.com"}]})
    elif break_ == "orca partly":
        hooks["hooks"]["Stop"].insert(0, {"hooks": [{"command": ": orca-agent-hook-form=1"}]})
    if break_ == "no hooks.json":
        hooks_file.unlink()
    else:
        hooks_file.write_text(json.dumps(hooks))
    result = codex_config_check(path, "install")
    assert result.returncode != 0
    assert "hooks" in result.stderr


def test_cmd_codex_runs_the_install_check():
    assert setup_function_body("cmd_codex").rstrip().endswith("check_codex install")


def set_codex(path, name, table, value):
    body = setup_function_body("codex_setting")
    program = body.split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY", 1)[0]
    return subprocess.run(
        [sys.executable, "-I", "-", str(path), name, table, value],
        input=program,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "before",
    [
        # A multi-line array, one with a nested array whose lines open with "[", a comment inside.
        '[mcp_servers.serena]\nargs = [\n  "start-mcp-server",\n  "--context=agent",\n]\n'
        'command = "serena"\n',
        '[mcp_servers.serena]\nargs = [\n  ["x"],\n  # old\n  "y",\n]\ncommand = "serena"\n',
        '[mcp_servers.serena]\nargs = """\nmulti\nline\n"""\ncommand = "serena"\n',
    ],
)
def test_the_setting_writer_replaces_a_multi_line_value_whole(tmp_path, before):
    path = tmp_path / "config.toml"
    after = '\n[hooks.state."/x/hooks.json:stop:0:0"]\ntrusted_hash = "sha256:x"\n'
    path.write_text('model = "m"\n\n' + before + after)
    result = set_codex(path, "args", "mcp_servers.serena", SERENA_ARGS)
    assert result.returncode == 0, result.stderr
    cfg = tomllib.loads(path.read_text())
    assert cfg["mcp_servers"]["serena"] == {"args": SERENA["args"], "command": "serena"}
    assert cfg["hooks"]["state"] == {"/x/hooks.json:stop:0:0": {"trusted_hash": "sha256:x"}}
    once = path.read_bytes()
    assert set_codex(path, "args", "mcp_servers.serena", SERENA_ARGS).returncode == 0
    assert path.read_bytes() == once


@pytest.mark.parametrize(
    "env",
    [
        'env = { SERENA_USAGE_REPORTING = "true", OTHER = "keep" }\n',
        'env = { OTHER = "keep" }\n',
        'env.SERENA_USAGE_REPORTING = "true"\nenv.OTHER = "keep"\n',
        '\n[mcp_servers.serena.env]\nSERENA_USAGE_REPORTING = "true"\nOTHER = "keep"\n',
    ],
)
def test_the_setting_writer_sets_a_key_of_an_inline_or_dotted_env_table(tmp_path, env):
    path = tmp_path / "config.toml"
    path.write_text(
        '[mcp_servers.serena]\ncommand = "serena"\n' + env + "\n[analytics]\nenabled = false\n"
    )
    result = set_codex(path, "SERENA_USAGE_REPORTING", "mcp_servers.serena.env", '"false"')
    assert result.returncode == 0, result.stderr
    cfg = tomllib.loads(path.read_text())
    assert cfg["mcp_servers"]["serena"]["env"] == {
        "SERENA_USAGE_REPORTING": "false",
        "OTHER": "keep",
    }
    assert cfg["analytics"] == {"enabled": False}
    once = path.read_bytes()
    assert (
        set_codex(path, "SERENA_USAGE_REPORTING", "mcp_servers.serena.env", '"false"').returncode
        == 0
    )
    assert path.read_bytes() == once


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
def test_omc_checks_require_expected_commands_for_node_events(tmp_path, event):
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


@pytest.mark.parametrize(
    "change",
    ["command", "timeout", "matcher", "statusMessage", "async", "entry removed", "disabled"],
)
@pytest.mark.parametrize("owner", ["orca", "omx"])
def test_codex_check_rejects_a_hook_changed_after_its_trust_entry_was_written(
    tmp_path, owner, change
):
    # Codex compares the stored hash with the hook's current identity: a hook edited after
    # approval keeps its entry but no longer runs, and the check must say so.
    path = codex_home(tmp_path)
    assert codex_config_check(path).returncode == 0
    hooks_file = path.parent / "hooks.json"
    hooks = json.loads(hooks_file.read_text())
    group = hooks["hooks"]["PreToolUse"][0 if owner == "orca" else 1]
    handler = group["hooks"][0]
    if change == "command":
        handler["command"] += " --changed"
    elif change == "timeout":
        handler["timeout"] = 30
    elif change == "matcher":
        group["matcher"] = "Bash"
    elif change == "statusMessage":
        handler["statusMessage"] = "new"
    elif change == "async":
        handler["async"] = True
    hooks_file.write_text(json.dumps(hooks))
    key = f'[hooks.state."{hooks_file}:pre_tool_use:{0 if owner == "orca" else 1}:0"]\n'
    text = path.read_text()
    assert key in text
    if change == "entry removed":
        text = re.sub(re.escape(key) + r'trusted_hash = "[^"]*"\n', "", text)
    elif change == "disabled":
        text = text.replace(key, key + "enabled = false\n")
    path.write_text(text)
    result = codex_config_check(path)
    assert result.returncode != 0
    assert "hooks without trust: ['PreToolUse" in result.stderr


def test_a_hook_without_a_timeout_hashes_with_codexs_default_per_event(tmp_path):
    # Interrupt (and SessionEnd) default to 1 second and are capped at 3; other events default
    # to 600. An explicit value equal to the default keeps the same hash.
    path = codex_home(tmp_path)
    hooks_file = path.parent / "hooks.json"
    hooks = json.loads(hooks_file.read_text())
    hooks["hooks"]["Interrupt"][0]["hooks"][0]["timeout"] = 1
    hooks["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 600
    hooks_file.write_text(json.dumps(hooks))
    assert codex_config_check(path).returncode == 0
    hooks["hooks"]["Interrupt"][0]["hooks"][0]["timeout"] = 9  # clamped to 3: another hash
    hooks_file.write_text(json.dumps(hooks))
    assert "Interrupt" in codex_config_check(path).stderr


@pytest.mark.parametrize(
    "stale", ["declaration", "stored hash", "content", "content entry missing"]
)
def test_a_stale_ponytail_trust_entry_blocks_enabled_plugin(tmp_path, stale):
    path = codex_home(tmp_path, ponytail_trusted=3)
    assert codex_config_check(path).stdout == ""
    plugin = path.parent / "plugins/cache" / PONYTAIL.split("@")[1] / "ponytail" / "5.3.3"
    if stale == "declaration":
        hooks = json.loads((plugin / "hooks/claude-codex-hooks.json").read_text())
        hooks["hooks"]["SubagentStart"][0]["hooks"][0]["command"] = "node other.js"
        (plugin / "hooks/claude-codex-hooks.json").write_text(json.dumps(hooks))
    elif stale == "content":
        (plugin / "README.md").write_text("changed\n")
    elif stale == "stored hash":
        key = f'[hooks.state."{PONYTAIL}:hooks/claude-codex-hooks.json:subagent_start:0:0"]\n'
        path.write_text(
            path.read_text().replace(
                key + 'trusted_hash = "sha256:', key + 'trusted_hash = "sha256:0'
            )
        )
    else:
        path.write_text(re.sub(r'trusted_content_hash = "[^"]*"\n', "", path.read_text(), count=1))
    result = codex_config_check(path)
    assert result.returncode != 0
    # Any change to the installed copy changes its content hash, which all three entries hold.
    waiting = 1 if stale in ("stored hash", "content entry missing") else 3
    assert f"ponytail enabled with {waiting} untrusted hooks" in result.stderr


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


def fixture_commit(folder):
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    subprocess.run(["git", "-C", str(folder), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(folder),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return subprocess.check_output(
        ["git", "-C", str(folder), "rev-parse", "HEAD"], text=True
    ).strip()


def run_ponytail_install(tmp_path, commit):
    names = ("codex_ponytail", "codex_config_check", "codex_setting")
    program = "\n".join(f"{name}() {{\n{setup_function_body(name)}\n}}" for name in names)
    program += '\nfail() { echo "$*" >&2; exit 1; }\n'
    program += (
        f"PONYTAIL_COMMIT={commit}\nPONYTAIL_VERSION=5.3.3\nPONYTAIL_MARKET=meridian-ponytail\n"
    )
    program += f"CODEX_MODEL=model\nCODEX_DOCS_MCP={DOCS_MCP}\nSERENA_MCP_ARGS='{SERENA_ARGS}'\n"
    program += "codex_ponytail\n"
    return subprocess.run(
        ["bash", "-euc", program],
        text=True,
        capture_output=True,
        env=dict(os.environ, HOME=str(tmp_path), CODEX_HOME=str(tmp_path / ".codex")),
    )


@pytest.mark.parametrize("damage", ["none", "bundle", "manifest", "one-skill"])
def test_ponytail_install_repairs_cache_despite_config_marker(tmp_path, damage):
    config = codex_home(tmp_path)
    plugin = config.parent / "plugins/cache/meridian-ponytail/ponytail/5.3.3"
    src = tmp_path / ".local/share/meridian/ponytail-src"
    shutil.copytree(plugin, src)
    commit = fixture_commit(src)
    market = src.parent / "codex-market"
    shutil.copytree(plugin, market / "plugins/ponytail")
    (market / ".agents/plugins").mkdir(parents=True)
    with config.open("a") as f:
        f.write('\n[marketplaces.meridian-ponytail]\nsource = "fixture"\n')
    binary = tmp_path / ".local/bin/codex"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, shutil, sys\n"
        "assert sys.argv[1:] == ['plugin', 'add', 'ponytail@meridian-ponytail']\n"
        "home = pathlib.Path(os.environ['HOME'])\n"
        "with (home / 'add-calls').open('a') as f: f.write('add\\n')\n"
        "shutil.copytree(home / '.local/share/meridian/codex-market/plugins/ponytail', "
        "home / '.codex/plugins/cache/meridian-ponytail/ponytail/5.3.3', dirs_exist_ok=True)\n"
    )
    binary.chmod(0o755)
    if damage == "bundle":
        shutil.rmtree(plugin)
    elif damage == "manifest":
        (plugin / ".codex-plugin/plugin.json").unlink()
    elif damage == "one-skill":
        (plugin / "skills/ponytail/SKILL.md").unlink()
    result = run_ponytail_install(tmp_path, commit)
    assert result.returncode == 0, result.stderr
    assert (plugin / ".codex-plugin/plugin.json").is_file()
    assert (plugin / "skills/ponytail/SKILL.md").is_file()
    assert tomllib.loads(config.read_text())["plugins"][PONYTAIL]["enabled"] is False
    calls = tmp_path / "add-calls"
    assert (calls.read_text() if calls.exists() else "") == ("" if damage == "none" else "add\n")
    again = run_ponytail_install(tmp_path, commit)
    assert again.returncode == 0, again.stderr
    assert (calls.read_text() if calls.exists() else "") == ("" if damage == "none" else "add\n")


def test_ponytail_install_enables_only_after_all_hooks_are_trusted(tmp_path):
    config = codex_home(tmp_path, ponytail_trusted=3, enabled=False)
    plugin = config.parent / "plugins/cache/meridian-ponytail/ponytail/5.3.3"
    src = tmp_path / ".local/share/meridian/ponytail-src"
    shutil.copytree(plugin, src)
    commit = fixture_commit(src)
    market = src.parent / "codex-market"
    shutil.copytree(plugin, market / "plugins/ponytail")
    (market / ".agents/plugins").mkdir(parents=True)
    with config.open("a") as f:
        f.write('\n[marketplaces.meridian-ponytail]\nsource = "fixture"\n')
    result = run_ponytail_install(tmp_path, commit)
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(config.read_text())["plugins"][PONYTAIL]["enabled"] is True
    assert codex_config_check(config).returncode == 0


def run_codex_inventory_check(tmp_path, installed, *, output=None, exit_code=0, warning=""):
    codex_home(tmp_path)
    binary = tmp_path / ".local/bin/codex"
    binary.parent.mkdir(parents=True)
    payload = json.dumps({"installed": installed, "available": []}) if output is None else output
    binary.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "assert sys.argv[1:] == ['plugin', 'list', '--json']\n"
        f"sys.stderr.write({warning!r})\nprint({payload!r})\nsys.exit({exit_code})\n"
    )
    binary.chmod(0o755)
    omx = binary.with_name("omx")
    omx.write_text("#!/bin/sh\necho 'Results: 18 passed, 1 warnings, 0 failed'\n")
    omx.chmod(0o755)
    names = ["check_codex", "codex_config_check"]
    if "codex_plugins_check() {" in (DEPLOY / "setup.sh").read_text():
        names.append("codex_plugins_check")
    program = "\n".join(f"{name}() {{\n{setup_function_body(name)}\n}}" for name in names)
    program += '\nfail() { echo "$*" >&2; exit 1; }\nok() { echo "$*"; }\n'
    program += "version_ge() { return 0; }\ncodex_version() { echo 0.169.0; }\n"
    program += "omx_version() { echo 0.22.6; }\nserena_version() { echo 2.1.0; }\n"
    program += "serena_python() { echo python3; }\nserena_config_check() { return 0; }\n"
    program += "check_codex_requirements() { return 0; }\ndsh_skills_check() { return 0; }\n"
    program += "CODEX_VERSION=0.169.0\nOMX_VERSION=0.22.6\nSERENA_VERSION=2.1.0\n"
    program += "PONYTAIL_VERSION=5.3.3\nPONYTAIL_MARKET=meridian-ponytail\n"
    program += f"CODEX_MODEL=model\nCODEX_DOCS_MCP={DOCS_MCP}\n"
    program += f"SERENA_MCP_ARGS='{SERENA_ARGS}'\ncheck_codex\n"
    return subprocess.run(
        ["bash", "-euc", program],
        capture_output=True,
        text=True,
        env=dict(os.environ, HOME=str(tmp_path), CODEX_HOME=str(tmp_path / ".codex")),
    )


def listed_plugin(name="ponytail", market="meridian-ponytail", enabled=False):
    return {
        "pluginId": f"{name}@{market}",
        "name": name,
        "marketplaceName": market,
        "version": "5.3.3",
        "installed": True,
        "enabled": enabled,
        "source": {"source": "local", "path": "./plugins/ponytail"},
        "installPolicy": "AVAILABLE",
        "authPolicy": "ON_INSTALL",
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_codex_check_rejects_remote_plugin_absent_from_config(tmp_path, enabled):
    result = run_codex_inventory_check(
        tmp_path, [listed_plugin(), listed_plugin("extra", "openai-curated-remote", enabled)]
    )
    assert result.returncode != 0
    assert "plugin inventory" in result.stderr


@pytest.mark.parametrize("output,exit_code", [("{}", 0), ("not json", 0), ("", 1)])
def test_codex_check_fails_when_plugin_inventory_is_unavailable(tmp_path, output, exit_code):
    result = run_codex_inventory_check(tmp_path, [], output=output, exit_code=exit_code)
    assert result.returncode != 0
    assert "plugin inventory" in result.stderr


def test_codex_check_accepts_only_pinned_ponytail_in_inventory(tmp_path):
    result = run_codex_inventory_check(tmp_path, [listed_plugin()])
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("feature", ["remote_plugin", "plugin_sharing"])
def test_codex_config_disables_remote_plugin_routes(tmp_path, feature):
    write_codex_config(tmp_path)
    config = tmp_path / ".codex/config.toml"
    assert tomllib.loads(config.read_text())["features"].get(feature) is False
    config.write_text(config.read_text().replace(f"{feature} = false", f"{feature} = true"))
    write_codex_config(tmp_path)
    assert tomllib.loads(config.read_text())["features"][feature] is False
    path = codex_home(tmp_path / "check")
    path.write_text(path.read_text().replace(f"{feature} = false", f"{feature} = true"))
    assert feature in codex_config_check(path).stderr


@pytest.mark.parametrize("broken", [True, False])
def test_agents_check_runs_every_check_and_collects_failures(tmp_path, broken):
    setup = (DEPLOY / "setup.sh").read_text()
    branch = setup.split("  agents-check)\n", 1)[1].split("    ;;", 1)[0]
    checks = [
        "check_gh",
        "check_gitleaks",
        "check_ocr",
        "check_claude",
        "check_omc",
        "check_codex",
        "check_agy",
        "check_dsh",
        "check_orca",
        "check_codex_bridge",
        "check_claude_hud",
        "check_orca_automation",
    ]
    program = 'fail() { echo "$*" >&2; exit 1; }\n'
    for name in checks:
        program += f'{name}() {{ echo "{name} $*"; }}\n'
    if broken:
        program += 'check_codex() { fail "Codex fixture failed"; }\n'
        program += 'check_dsh() { echo "dsh fixture failed" >&2; false; echo "errexit lost"; }\n'
    if "agents_check() {" in setup:
        program += f"agents_check() {{\n{setup_function_body('agents_check')}\n}}\n"
    result = subprocess.run(
        ["bash", "-euc", program + branch],
        capture_output=True,
        text=True,
        env=dict(os.environ, HOME=str(tmp_path), CODEX_HOME=str(tmp_path / ".codex")),
    )
    assert result.returncode == (1 if broken else 0)
    assert "check_omc --require-orca" in result.stdout
    assert "check_orca_automation" in result.stdout
    assert "errexit lost" not in result.stdout
    if not broken:
        assert "check_codex " in result.stdout.splitlines()
    if broken:
        assert "Codex fixture failed" in result.stderr and "dsh fixture failed" in result.stderr
        assert "agent checks failed: check_codex check_dsh" in result.stderr


@pytest.mark.parametrize("damage", ["missing", "version", "enabled"])
def test_codex_check_rejects_wrong_ponytail_inventory(tmp_path, damage):
    installed = [listed_plugin()]
    if damage == "missing":
        installed = []
    elif damage == "version":
        installed[0]["version"] = "5.3.2"
    else:
        installed[0]["enabled"] = True
    result = run_codex_inventory_check(tmp_path, installed)
    assert result.returncode != 0
    assert "plugin inventory" in result.stderr


def test_codex_check_rejects_incomplete_inventory_after_remote_warning(tmp_path):
    result = run_codex_inventory_check(
        tmp_path,
        [listed_plugin()],
        warning="Warning: failed to list remote marketplace plugins: fixture unavailable\n",
    )
    assert result.returncode != 0
    assert "plugin inventory" in result.stderr
