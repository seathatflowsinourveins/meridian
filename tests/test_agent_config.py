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
import sys
import tomllib

import pytest
from test_paper_only import REPO_ROOT, git_files

DEPLOY = REPO_ROOT / "deploy" / "wsl"
# The newest first-patched version among GitHub's published advisories for the GitHub CLI
# (UPSTREAM.md, GitHub CLI row). The pin may not fall below it.
GH_NEWEST_FIX = (2, 97, 0)

# Folders the four agents (or Gemini CLI, whose layout Antigravity shares) read in a project.
# Also the project folders of serena (the MCP server dsh runs, ADR 0016) and beads.
AGENT_FOLDERS = (".agents/", ".claude/", ".codex/", ".gemini/", ".dsh/", ".serena/", ".beads/")
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
        ".serena/project.yml",
        ".beads/issues.db",
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
    # The server starts in the session's working directory: `./.venv` is that worktree's own.
    assert "args: ['-c', 'exec ./.venv/bin/pyright-langserver --stdio']" in block
    assert "dsh-mcp-client" not in block, "the stack adds no MCP server"


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
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    (repo / "README").write_text("x\n")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    # A stand-in for uv: the gate's check line passes or fails as the test says.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text('#!/bin/sh\necho "uv $*"\n[ ! -e "$GATE_FAIL" ] || exit 1\n')
    (bin_dir / "uv").chmod(0o755)
    return repo, bin_dir


def run_gate(repo, bin_dir, session="session-1", fail=None) -> dict | None:
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(repo.parent),
        "GATE_FAIL": str(fail or repo.parent / "never"),
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
    assert "block 1 of 2" in blocked(run_gate(repo, bin_dir, fail=flag))["reason"]


def test_the_gate_script_is_executable_in_git():
    entry = subprocess.run(
        ["git", "ls-files", "-s", "--", "deploy/wsl/dsh-check-gate.sh"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert entry.startswith("100755 "), f"the gate script is not executable in git: {entry!r}"
