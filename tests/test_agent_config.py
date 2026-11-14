"""No agent configuration is committed here, apart from the shared skills, and setup stays runnable.

Claude Code, Codex, Antigravity and DeepSeek Harness each load configuration from the folder they
start in: MCP servers, hooks, plugins and feature switches. Claude Code has MCP off machine-wide
and Codex allows only the servers ADR 0018 names (``deploy/wsl/meridian.user-data``);
Antigravity has no such setting. So the only
agent files git may list are the skills in ``.agents/skills/`` and their links in
``.claude/skills/``. This catches an accidental commit. It cannot stop a branch from outside the
owner's own sessions, which carries its own tests: docs/HANDBOOK.md (Rules) keeps such branches
out of worktrees.
"""

import hashlib
import json
import os
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


def codex_home(tmp_path, ponytail_trusted=0, orca=True):
    # What setup leaves in ~/.codex: Orca's 9 hooks (on a fresh distro, not yet: Orca is set up
    # after Codex), then oh-my-codex's 8 in the group after them, each with its trust entry at
    # its current hash, the ponytail plugin's installed copy, and oh-my-codex's user file.
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
    content = bundle_hash(plugin)
    for event in list(PONYTAIL_HOOKS)[:ponytail_trusted]:
        group = PONYTAIL_HOOKS[event][0]
        state.append(
            f'[hooks.state."{PONYTAIL}:hooks/claude-codex-hooks.json:{hook_label(event)}:0:0"]\n'
            f'trusted_hash = "{codex_trust_hash(event, group["hooks"][0], group.get("matcher"))}"\n'
            f'trusted_content_hash = "{content}"\n'
        )
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


def codex_config_check(path, mode="full"):
    body = setup_function_body("check_codex")
    program = "import" + body.split("<<'PY'", 1)[1].split("\nimport", 1)[1].split("\nPY", 1)[0]
    home = path.parent
    return subprocess.run(
        [sys.executable, "-I", "-", str(path), "model", str(home / "hooks.json")]
        + [str(home / ".omx-config.json"), DOCS_MCP, PONYTAIL, SERENA_ARGS, mode],
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
    assert "wait for the owner's /hooks" in result.stdout
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


def test_cmd_codex_runs_the_install_check_and_agents_check_the_full_one():
    assert setup_function_body("cmd_codex").rstrip().endswith("check_codex install")
    script = (DEPLOY / "setup.sh").read_text()
    agents_check = script.split("  agents-check)\n", 1)[1].split(";;", 1)[0]
    assert re.search(r"^\s*check_codex$", agents_check, re.M)


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
def test_a_stale_ponytail_trust_entry_still_shows_the_owners_reminder(tmp_path, stale):
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
    assert result.returncode == 0, result.stderr
    # Any change to the installed copy changes its content hash, which all three entries hold.
    waiting = 1 if stale in ("stored hash", "content entry missing") else 3
    assert f"{waiting} of ponytail's 3 hooks wait for the owner's /hooks" in result.stdout
