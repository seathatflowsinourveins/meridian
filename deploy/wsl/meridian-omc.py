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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "5.8.4"
SKILLS = {
    "autopilot",
    "ralplan",
    "omc-plan",
    "ralph",
    "team",
    "verify",
    "cancel",
    "ai-slop-cleaner",
    "pr",
    "deep-interview",
    "autoresearch",
}
AGENTS = {
    "analyst",
    "architect",
    "code-reviewer",
    "critic",
    "debugger",
    "designer",
    "executor",
    "explore",
    "planner",
    "security-reviewer",
    "test-engineer",
    "verifier",
    "writer",
}
WRAPPED = {"UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"}
ENV = {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1", "OMC_NOTIFY": "0", "OMC_OPENCLAW": "0"}
INSTALL = ".meridian-omc-install.json"
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
Use the named four-stage profile. The interview's autoresearch dependency is available only
when explicitly requested within scope; never infer authorization for scheduled work.
Planner's obsolete /start-work reference is not shipped upstream;
return its plan to the current profile's execution stage, never install a replacement skill.
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


def hook_command(home, adapter, event, name):
    script = str(home / "hooks" / name)
    args = (
        ["python3", str(adapter), "hook", event, script] if event in WRAPPED else ["node", script]
    )
    return shlex.join(args)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keys_before(value, keys):
    return {key: value[key] for key in keys if key in value}


def restore_keys(value, keys, before):
    for key in keys:
        if key in before:
            value[key] = before[key]
        else:
            value.pop(key, None)


def stage(home, staging):
    """Seed upstream setup with hooks/status only, never auth or arbitrary env."""
    write(staging / "settings.json", foreign_settings(read(home / "settings.json"), home))
    prepare(staging, staging.parent / "config/claude-omc/config.jsonc")


def owned_files(staging):
    paths = [staging / ".omc-version.json"]
    for folder in [staging / "hooks", *(staging / "skills" / name for name in sorted(SKILLS))]:
        paths.extend(p for p in folder.rglob("*") if p.is_file())
    paths.extend(staging / "agents" / f"{name}.md" for name in sorted(AGENTS))
    return {str(p.relative_to(staging)): digest(p) for p in paths}


def validate_owned(home, record):
    """Refuse changed owned payloads before removal/reinstall; retain user additions."""
    for name, expected in record.get("files", {}).items():
        path = home / name
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        assert not any(p.is_symlink() for p in [path, *path.parents] if p != home.parent)
        if name == ".omc-version.json" and path.exists():
            assert read(path)["version"] == VERSION  # lastCheckAt is runtime-maintained.
            continue
        if path.exists() and digest(path) != expected:
            raise ValueError(f"modified OMC file; preserve and resolve before removal: {name}")
    suffix = record.get("instruction_suffix", "")
    if suffix and suffix not in (home / "CLAUDE.md").read_text():
        raise ValueError("OMC instruction blocks changed; preserve and resolve before removal")


def install(home, user_config, adapter, staging):
    """Project only the admitted assets from upstream's isolated standalone setup."""
    record = read(home / INSTALL)
    files = owned_files(staging)
    validate_owned(home, record)
    if record and (home / ".omc-version.json").exists():
        files[".omc-version.json"] = digest(home / ".omc-version.json")
    for name in files:
        path = home / name
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError(f"refusing symlink in OMC destination: {name}")
        if path.exists() and name not in record.get("files", {}):
            raise ValueError(f"existing user asset; not overwritten: {name}")
    settings = read(home / "settings.json")
    if not record:
        text = (home / "CLAUDE.md").read_text() if (home / "CLAUDE.md").exists() else ""
        if "<!-- OMC:START -->" in text or "<!-- MERIDIAN-OMC:START -->" in text:
            raise ValueError("untracked OMC installation; inspect ownership before setup")
        record = {
            "env": keys_before(settings.get("env", {}), ENV),
            "env_existed": "env" in settings,
            "overrides": keys_before(settings.get("skillOverrides", {}), SKILLS),
            "overrides_existed": "skillOverrides" in settings,
            "hook_events": list(settings.get("hooks", {})),
            "hooks_existed": "hooks" in settings,
            "claude_existed": (home / "CLAUDE.md").exists(),
            "update_cache_existed": (home / ".omc/update-check.json").exists(),
            "config_existed": user_config.exists(),
            "keyword_existed": "keywordDetector" in read(user_config),
            "disabled": keys_before(read(user_config).get("keywordDetector", {}), ["disabled"]),
            "omc_config_existed": (home / ".omc-config.json").exists(),
            "omc_config": keys_before(
                read(home / ".omc-config.json"),
                ["hudEnabled", "silentAutoUpdate", "autoUpgradePrompt"],
            ),
        }
    prepare(home, user_config)
    # settings are merged by individual hook, preserving mixed/foreign groups.
    for event, names in HOOKS.items():
        groups = settings.setdefault("hooks", {}).setdefault(event, [])
        for name in names:
            if not any(
                str(home / "hooks" / name) in h.get("command", "")
                for group in groups
                for h in group["hooks"]
            ):
                source = next(
                    h
                    for group in read(staging / "settings.json")["hooks"][event]
                    for h in group["hooks"]
                    if str(staging / "hooks" / name) in h.get("command", "")
                )
                groups.append(
                    {"hooks": [source | {"command": hook_command(home, adapter, event, name)}]}
                )
    settings.setdefault("skillOverrides", {}).update({name: "on" for name in SKILLS})
    write(home / "settings.json", settings)
    for name in files:
        target = home / name
        if name == ".omc-version.json" and record.get("files") and target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging / name, target)
    path = home / "CLAUDE.md"
    text = path.read_text() if path.exists() else ""
    if record.get("instruction_suffix"):
        text = text.replace(record["instruction_suffix"], "", 1)
    # Only public upstream instructions are recorded, not the owner's text.
    suffix = "\n\n" + (staging / "CLAUDE.md").read_text().rstrip() + "\n\n" + POLICY
    path.write_text(text + suffix)
    record.update(
        files=files,
        instruction_suffix=suffix,
        adapter_sha256=digest(adapter),
        excluded_agents={
            p.name: digest(p) for p in (staging / "agents").glob("*.md") if p.stem not in AGENTS
        },
    )
    write(home / INSTALL, record)
    configure(home, adapter)


def remove(home, user_config, adapter):
    record = read(home / INSTALL)
    if not record:
        raise ValueError("OMC absent (no Meridian ownership record)")
    validate_owned(home, record)
    if adapter.exists() and digest(adapter) != record["adapter_sha256"]:
        raise ValueError("modified OMC adapter; preserve and resolve before removal")
    settings = read(home / "settings.json")
    for event, groups in list(settings.get("hooks", {}).items()):
        retained = []
        for group in groups:
            hooks = [h for h in group["hooks"] if not omc_hook(h, home)]
            if hooks or not group["hooks"]:
                retained.append(group | {"hooks": hooks})
        if retained or event in record["hook_events"]:
            settings["hooks"][event] = retained
        else:
            settings["hooks"].pop(event)
    if not settings.get("hooks") and not record["hooks_existed"]:
        settings.pop("hooks", None)
    for key, names, old in [("env", ENV, "env"), ("skillOverrides", SKILLS, "overrides")]:
        restore_keys(settings.setdefault(key, {}), names, record[old])
        if not settings[key] and not record[old + "_existed"]:
            settings.pop(key)
    write(home / "settings.json", settings)
    cfg = read(user_config)
    restore_keys(cfg.setdefault("keywordDetector", {}), ["disabled"], record["disabled"])
    if not cfg["keywordDetector"] and not record["keyword_existed"]:
        cfg.pop("keywordDetector")
    if cfg or record["config_existed"]:
        write(user_config, cfg)
    else:
        user_config.unlink(missing_ok=True)
    path = home / ".omc-config.json"
    cfg = read(path)
    restore_keys(cfg, ["hudEnabled", "silentAutoUpdate", "autoUpgradePrompt"], record["omc_config"])
    if cfg or record["omc_config_existed"]:
        write(path, cfg)
    else:
        path.unlink(missing_ok=True)
    path = home / "CLAUDE.md"
    text = path.read_text().replace(record["instruction_suffix"], "", 1)
    if text or record["claude_existed"]:
        path.write_text(text)
    else:
        path.unlink()
    for name in record["files"]:
        path = home / name
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != home and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    shutil.rmtree(home / ".meridian-omc-wait", ignore_errors=True)
    if not record["update_cache_existed"]:
        (home / ".omc/update-check.json").unlink(missing_ok=True)
        cache = home / ".omc"
        if cache.is_dir() and not any(cache.iterdir()):
            cache.rmdir()
    (home / ".meridian-omc-before.json").unlink(missing_ok=True)
    (home / INSTALL).unlink()
    adapter.unlink(missing_ok=True)


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
    cfg.setdefault("keywordDetector", {})["disabled"] = DISABLED
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
                    hook["command"] = hook_command(home, adapter, event, name)
    settings.setdefault("env", {}).update(ENV)
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
    assert (home / INSTALL).exists(), "OMC absent (no Meridian ownership record)"
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
            command = hook_command(home, adapter, event, name)
            assert commands.count(command) == 1, f"missing or duplicate OMC {event}/{name}"
            assert (home / "hooks" / name).is_file()
    marked = {p.parent.name for p in (home / "skills").glob("*/.omc-managed")}
    assert marked == SKILLS, "OMC skill set differs from admitted lifecycle"
    record = read(home / INSTALL)
    assert {Path(n).stem for n in record["files"] if n.startswith("agents/")} == AGENTS
    for name, expected in record["excluded_agents"].items():
        path = home / "agents" / name
        assert not path.exists() or digest(path) != expected, f"unadmitted OMC agent: {name}"
    for name in AGENTS:
        assert (home / "agents" / f"{name}.md").is_file(), name
    for name in SKILLS:
        assert (home / "skills" / name / "SKILL.md").is_file(), name
        assert settings.get("skillOverrides", {}).get(name, "on") == "on", name


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
    elif action == "stage":
        stage(home, Path(args[2]))
    elif action == "install":
        install(home, user_config, Path(args[2]), Path(args[3]))
    elif action == "remove":
        remove(home, user_config, Path(args[2]))
    else:
        raise ValueError(f"unknown operation: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
