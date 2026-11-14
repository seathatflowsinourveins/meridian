"""Notice-only filtering must never discard a deny or unrelated hook output."""

import json
import shlex
import subprocess

import pytest
from test_agent_config import fake_omc_home

SUFFIX = (
    "\n\nRecommended: Delegate to executor agent instead:\n"
    '  Task(subagent_type="oh-my-claudecode:executor", model="sonnet", prompt="...")'
    "\n\nThis is a soft warning. Operation will proceed."
)


def notice(prefix="Bash command may modify source files: echo x > app.py"):
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "[DELEGATION NOTICE] " + prefix + SUFFIX,
        },
    }


@pytest.mark.parametrize(
    "prefix",
    ["Bash command may modify source files: echo x > app.py"]
    + [f"Direct {tool} on source file: app.py" for tool in ("Edit", "Write", "edit", "write")],
)
def test_notice_only_becomes_upstream_silent_continue(tmp_path, prefix):
    result = emit(tmp_path, json.dumps(notice(prefix)))
    assert result.stdout == '{"continue":true,"suppressOutput":true}\n'


def emit(tmp_path, output):
    api, home, _ = fake_omc_home(tmp_path)
    script = home / "hooks/pre-tool-use.mjs"
    script.write_text(
        f"console.log({json.dumps(output)});\nconsole.error('diagnostic');process.exitCode=7;\n"
    )
    command = api["hook_command"](home, tmp_path / "adapter", "PreToolUse", script.name)
    result = subprocess.run(shlex.split(command), capture_output=True, text=True, check=False)
    assert result.returncode == 7
    assert result.stderr == "diagnostic\n"
    return result


@pytest.mark.parametrize(
    "output",
    [
        "not JSON",
        "null",
        "[]",
        '{"continue":true,"suppressOutput":true}',
        json.dumps(notice() | {"continue": False}),
        json.dumps(notice() | {"decision": "block"}),
        json.dumps(notice() | {"reason": "additional information"}),
        json.dumps(notice() | {"systemMessage": "retain this"}),
        *[
            json.dumps(notice() | {"hookSpecificOutput": notice()["hookSpecificOutput"] | extra})
            for extra in [
                {"permissionDecision": "deny"},
                {"updatedInput": {"command": "true"}},
                {"hookEventName": "PostToolUse"},
                {
                    "additionalContext": notice()["hookSpecificOutput"]["additionalContext"]
                    + "\nMore"
                },
                {"additionalContext": "[DELEGATION NOTICE] unknown format"},
            ]
        ],
        json.dumps(notice()) + "\n" + json.dumps({"continue": False}),
    ],
)
def test_other_output_is_unchanged(tmp_path, output):
    assert emit(tmp_path, output).stdout == output + "\n"


@pytest.mark.parametrize("damage", ["direct", "python", "filter", "duplicate-direct"])
def test_check_requires_preload_and_its_exact_content(tmp_path, damage):
    api, home, user = fake_omc_home(tmp_path)
    api["check"](home, user, tmp_path / "adapter")
    if damage == "filter":
        (home / "hooks" / api["PRE_FILTER"]).write_text("// missing filter\n")
    else:
        settings = api["read"](home / "settings.json")
        hook = settings["hooks"]["PreToolUse"][-1]["hooks"][0]
        if damage == "duplicate-direct":
            hook = hook.copy()
            settings["hooks"]["PreToolUse"][-1]["hooks"].append(hook)
        hook["command"] = (
            f"node {home}/hooks/pre-tool-use.mjs"
            if damage in ("direct", "duplicate-direct")
            else f"python3 {tmp_path}/adapter hook PreToolUse {home}/hooks/pre-tool-use.mjs"
        )
        api["write"](home / "settings.json", settings)
    with pytest.raises(AssertionError):
        api["check"](home, user, tmp_path / "adapter")
