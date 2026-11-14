#!/usr/bin/env python3
"""Meridian's standalone OMC settings and boundary-stop adapter (ADR 0019).

Upstream owns the hook programs; this adapter never edits them. All paths are
explicit so the same installer can be exercised against an unsigned scratch home.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "5.8.4"
HOOKS = {
    "UserPromptSubmit": ["keyword-detector.mjs"],
    "SessionStart": ["session-start.mjs"],
    "PreToolUse": ["pre-tool-use.mjs"],
    "PostToolUse": ["post-tool-use.mjs"],
    "PostToolUseFailure": ["post-tool-use-failure.mjs"],
    "Stop": ["persistent-mode.mjs", "code-simplifier.mjs"],
    "SessionEnd": ["session-end.mjs"],
}
DISABLED = [
    "ralph",
    "autopilot",
    "ultragoal",
    "ralplan",
    "deep-interview",
    "ai-slop-cleaner",
    "tdd",
    "code-review",
    "security-review",
    "ultrathink",
    "deepsearch",
    "analyze",
    "wiki",
]
POLICY = """<!-- MERIDIAN-OMC:START -->
OMC workflows start only on an explicit slash command; ignore prose trigger suggestions.
Standalone installation: use unprefixed agent names; plan is /omc-plan. Resolve plugin-prefixed
skill references to the installed ~/.claude/skills/ folder; do not install a plugin to fix them.
Repository and owner boundaries outrank OMC persistence, delegation and write permissions.
Orca owns the fleet: never use `omc team` panes, factory chains or OMC provider/ask launchers.
Native Claude in-session teams are permitted only within the assigned delegation scope;
MCP state tools are unavailable: report that limitation rather than installing a server.
Before a required owner decision, end with [MERIDIAN_WAIT]; never assume boundary approval.
An Orca worker uses orchestration ask, then ends its turn; worker_done ends the task.
After a reply, resume only within the reply's authorization. Keep cross-family merge review.
<!-- MERIDIAN-OMC:END -->
"""


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def omc_hook(hook, home):
    command = hook.get("command", "")
    return any(str(home / "hooks" / name) in command for names in HOOKS.values() for name in names)


def foreign_settings(settings, home):
    return {
        "statusLine": settings.get("statusLine"),
        "hooks": {
            event: [g for g in groups if not all(omc_hook(h, home) for h in g["hooks"])]
            for event, groups in settings.get("hooks", {}).items()
        },
    }


def prepare(home, user_config):
    settings = read(home / "settings.json")
    write(home / ".meridian-omc-before.json", foreign_settings(settings, home))
    cfg = read(home / ".omc-config.json")
    cfg.update(hudEnabled=False, silentAutoUpdate=False, autoUpgradePrompt=False)
    write(home / ".omc-config.json", cfg)
    cfg = read(user_config)
    cfg["keywordDetector"] = {"disabled": DISABLED}
    write(user_config, cfg)


def configure(home, adapter):
    settings = read(home / "settings.json")
    before = read(home / ".meridian-omc-before.json")
    if before["statusLine"] != settings.get("statusLine"):
        raise ValueError("OMC changed the status line")
    for event, groups in before["hooks"].items():
        if any(group not in settings.get("hooks", {}).get(event, []) for group in groups):
            raise ValueError(f"OMC removed another component's {event} hook")
    for event, groups in settings["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                if omc_hook(hook, home):
                    name = next(
                        n for n in HOOKS[event] if str(home / "hooks" / n) in hook["command"]
                    )
                    hook["command"] = shlex.join(
                        [
                            "python3",
                            str(adapter),
                            "hook",
                            event,
                            str(home / "hooks" / name),
                        ]
                    )
    settings.setdefault("env", {}).update(
        CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS="1",
        OMC_NOTIFY="0",
        OMC_OPENCLAW="0",
    )
    write(home / "settings.json", settings)
    path = home / "CLAUDE.md"
    text = path.read_text()
    text = re.sub(
        r"<!-- MERIDIAN-OMC:START -->.*?<!-- MERIDIAN-OMC:END -->\n?", "", text, flags=re.S
    )
    # Upstream inserts this header when our block is the only user customization.
    # Remove only an empty trailing header; preserve a header with owner text.
    text = re.sub(r"\n<!-- User customizations -->\s*$", "", text)
    path.write_text(text.rstrip() + "\n\n" + POLICY)


def check(home, user_config, adapter, require_orca=True):
    settings = read(home / "settings.json")
    cfg = read(home / ".omc-config.json")
    assert cfg.get("hudEnabled") is False
    assert cfg.get("silentAutoUpdate") is False
    assert cfg.get("autoUpgradePrompt") is False
    assert read(home / ".omc-version.json")["version"] == VERSION
    assert read(user_config)["keywordDetector"]["disabled"] == DISABLED
    assert not settings.get("mcpServers")
    assert settings["env"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"
    assert settings["env"]["OMC_NOTIFY"] == "0"
    assert settings["env"]["OMC_OPENCLAW"] == "0"
    assert POLICY in (home / "CLAUDE.md").read_text()
    previous_status = read(home / ".meridian-omc-before.json")["statusLine"]
    if previous_status is not None:
        assert settings["statusLine"] == previous_status
    for event, names in HOOKS.items():
        groups = settings["hooks"][event]
        commands = [h.get("command", "") for g in groups for h in g["hooks"]]
        had_orca = any(
            ".orca/agent-hooks/" in h.get("command", "")
            for g in read(home / ".meridian-omc-before.json")["hooks"].get(event, [])
            for h in g["hooks"]
        )
        if require_orca or had_orca:
            assert any(".orca/agent-hooks/" in c for c in commands), f"missing Orca {event}"
        for name in names:
            command = shlex.join(
                ["python3", str(adapter), "hook", event, str(home / "hooks" / name)]
            )
            assert commands.count(command) == 1, f"missing or duplicate OMC {event}/{name}"
            assert (home / "hooks" / name).is_file()
    for name in ("autopilot", "ralph", "ralplan", "team", "verify", "cancel"):
        assert (home / "skills" / name / "SKILL.md").is_file(), name


def hook(event, script, payload):
    """Latch an Orca handoff until the next prompt; never read a transcript."""
    if event == "SessionEnd":
        # Upstream can enqueue and spawn a factory worker here; Orca owns that job.
        return 0
    data = json.loads(payload)
    home = script.parent.parent
    session = data.get("session_id") or data.get("sessionId")
    marker = None
    if isinstance(session, str) and session:
        digest = hashlib.sha256(session.encode()).hexdigest()
        marker = home / ".meridian-omc-wait" / digest
    command = data.get("tool_input", {}).get("command", "")
    if event == "UserPromptSubmit" and marker:
        marker.unlink(missing_ok=True)
    if (
        event == "PostToolUse"
        and marker
        and (
            re.search(r"\borchestration\s+ask\b", command)
            or ("orchestration send" in command and "worker_done" in command)
        )
    ):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    message = data.get("last_assistant_message", "")
    if event == "Stop" and (
        marker is None
        or marker.exists()
        or not isinstance(message, str)
        or not message.strip()
        or "?" in message
        or "[MERIDIAN_WAIT]" in message
        or re.search(r"\b(waiting|awaiting|blocked|need.{0,30}approval)\b", message, re.I)
    ):
        return 0
    result = subprocess.run(["node", str(script)], input=payload, text=True, check=False)
    return result.returncode


def probe(home, user_config):
    """Run the installed detector in disposable state; input is a dispatch text."""
    with tempfile.TemporaryDirectory(prefix="omc-probe-") as folder:
        root = Path(folder)
        cfg = read(user_config)
        cfg.update(read(Path.cwd() / ".claude/omc.jsonc"))
        write(root / ".claude/omc.jsonc", cfg)
        transcript = root / "projects/dispatch-probe.jsonl"
        transcript.parent.mkdir()
        transcript.touch()
        env = dict(
            os.environ,
            CLAUDE_CONFIG_DIR=str(root),
            OMC_STATE_DIR=str(root / "state"),
            OMC_HOME=str(root / "omc"),
            XDG_CONFIG_HOME=str(root / "config"),
        )
        payload = json.dumps(
            {
                "prompt": sys.stdin.read(),
                "cwd": folder,
                "session_id": "dispatch-probe",
                "transcript_path": str(transcript),
            }
        )
        result = subprocess.run(
            ["node", str(home / "hooks/keyword-detector.mjs")],
            input=payload,
            text=True,
            env=env,
            cwd=folder,
            check=False,
        )
        return result.returncode


def main():
    action, *args = sys.argv[1:]
    if action == "hook":
        try:
            return hook(args[0], Path(args[1]), sys.stdin.read())
        except OSError, ValueError, TypeError, AttributeError:
            # Broken input must release Stop, never manufacture authorization.
            return 0
    home, user_config = map(Path, args[:2])
    if action == "prepare":
        prepare(home, user_config)
    elif action == "configure":
        configure(home, Path(args[2]))
    elif action == "check":
        check(home, user_config, Path(args[2]), "--before-orca" not in args[3:])
    elif action == "probe":
        return probe(home, user_config)
    else:
        raise ValueError(f"unknown operation: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
