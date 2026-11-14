"""Native Codex hooks and verification for ADR 0018; no plugin host required."""

import copy
import filecmp
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

PONYTAIL_SKILLS = (
    "ponytail",
    "ponytail-audit",
    "ponytail-debt",
    "ponytail-gain",
    "ponytail-help",
    "ponytail-review",
)
EXTRA_SKILLS = ("test-driven-development", "systematic-debugging", "verification-before-completion")
MARKER = "MERIDIAN_PONYTAIL_HOOK=1"
BEGIN = "# BEGIN Meridian ponytail trust\n"
END = "# END Meridian ponytail trust\n"
OMX_BEGIN = (
    "# ============================================================\n"
    "# oh-my-codex (OMX) Configuration\n"
)
PLUGIN = "ponytail@meridian-ponytail"

# Codex's normalized hook identity at rust-v0.167.2 and rust-v0.169.0.
MATCHER_EVENTS = {
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "SessionStart",
    "SessionEnd",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
}
CONTEXT_EVENTS = {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart"}


def event_label(event):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def hook_hash(event, group, handler):
    if handler.get("type", "command") != "command" or not str(handler.get("command", "")).strip():
        return None
    timeout = handler.get("timeout")
    if event in ("SessionEnd", "Interrupt"):
        timeout = min(max(1 if timeout is None else timeout, 1), 3)
    else:
        timeout = max(600 if timeout is None else timeout, 1)
    normalized = dict(
        type="command",
        command=handler["command"],
        timeout=timeout,
        **{"async": bool(handler.get("async", False))},
    )
    if handler.get("statusMessage") is not None:
        normalized["statusMessage"] = handler["statusMessage"]
    limit = handler.get("additionalContextLimit")
    if event in CONTEXT_EVENTS and limit is not None and limit != 2500:
        normalized["additionalContextLimit"] = limit
    identity = {"event_name": event_label(event), "hooks": [normalized]}
    if event in MATCHER_EVENTS and group.get("matcher") is not None:
        identity["matcher"] = group["matcher"]
    text = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def write_changed(path, text):
    if path.exists() and path.read_text() == text:
        return
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(text)
    temporary.chmod(0o600)
    temporary.replace(path)


def source_dir(home):
    return home / ".local/share/meridian/ponytail-src"


def native_groups(home):
    src = source_dir(home)
    groups = json.loads((src / "hooks/claude-codex-hooks.json").read_text())["hooks"]
    if set(groups) != {"SessionStart", "SubagentStart", "UserPromptSubmit"}:
        raise ValueError("ponytail must declare exactly three hook events")
    groups = copy.deepcopy(groups)
    for event, entries in groups.items():
        if len(entries) != 1 or len(entries[0]["hooks"]) != 1:
            raise ValueError(f"unexpected ponytail hook shape: {event}")
        handler = entries[0]["hooks"][0]
        prefix = " ".join(
            (
                MARKER,
                "CLAUDE_PLUGIN_ROOT=" + shlex.quote(str(src)),
                "PLUGIN_DATA=" + shlex.quote(str(home / ".local/share/meridian/ponytail-data")),
            )
        )
        handler["command"] = prefix + " " + handler["command"]
    return groups


def owned(handler):
    return MARKER in shlex.split(handler.get("command", ""))


def install(home):
    config = home / ".codex/config.toml"
    hooks_file = home / ".codex/hooks.json"
    text = config.read_text()
    cfg = tomllib.loads(text)
    document = json.loads(hooks_file.read_text()) if hooks_file.exists() else {"hooks": {}}
    hooks = document.setdefault("hooks", {})
    # Trust is confined to an explicit block. Everything outside it stays byte-for-byte.
    if BEGIN in text:
        before, rest = text.split(BEGIN, 1)
        previous, after = rest.split(END, 1)
        prior = tomllib.loads(previous)
        if set(prior) - {"hooks"} or set(prior.get("hooks", {})) - {"state"}:
            raise ValueError("foreign settings inside Meridian ponytail trust block")
        prior_keys = set(prior.get("hooks", {}).get("state", {}))
    else:
        # OMX regenerates its managed block at EOF. Put ours before it from the first run.
        before, separator, tail = text.partition(OMX_BEGIN)
        after = "\n" + separator + tail if separator else ""
        prior_keys = set()
    foreign_keys = set()
    for event, groups in hooks.items():
        for g, group in enumerate(groups):
            handlers = group.get("hooks", [])
            if any(owned(h) for h in handlers):
                if not all(owned(h) for h in handlers):
                    raise ValueError(
                        "mixed ponytail/foreign hook group; refusing to move foreign hooks"
                    )
                # Retain an empty slot until the tail: foreign positional trust must not move.
                groups[g] = {"hooks": []}
            else:
                foreign_keys.update(
                    f"{hooks_file}:{event_label(event)}:{g}:{h}" for h in range(len(handlers))
                )
        while groups and groups[-1] == {"hooks": []}:
            groups.pop()
    if prior_keys & foreign_keys:
        raise ValueError("foreign trust entered Meridian ponytail block; refusing to rewrite it")
    trust = []
    for event, entries in native_groups(home).items():
        groups = hooks.setdefault(event, [])
        key = f"{hooks_file}:{event_label(event)}:{len(groups)}:0"
        if key in cfg.get("hooks", {}).get("state", {}) and key not in prior_keys:
            raise ValueError(f"refusing to replace foreign trust entry: {key}")
        group = entries[0]
        groups.append(group)
        trust.append(
            f"[hooks.state.{json.dumps(key)}]\n"
            f"trusted_hash = {json.dumps(hook_hash(event, group, group['hooks'][0]))}\n"
            "enabled = true\n"
        )
    # One separator on first install; later replacements preserve the prefix verbatim.
    if BEGIN not in text and not before.endswith("\n\n"):
        before = before.rstrip("\n") + "\n\n"
    new = before + BEGIN + "\n".join(trust) + END + after
    tomllib.loads(new)
    write_changed(hooks_file, json.dumps(document, indent=2) + "\n")
    write_changed(config, new)


def equal_tree(left, right):
    if left.is_symlink() or right.is_symlink() or not left.is_dir() or not right.is_dir():
        return False
    a = {p.relative_to(left): p for p in left.rglob("*")}
    b = {p.relative_to(right): p for p in right.rglob("*")}
    return a.keys() == b.keys() and all(
        not p.is_symlink()
        and not b[k].is_symlink()
        and (
            p.is_dir()
            and b[k].is_dir()
            or p.is_file()
            and b[k].is_file()
            and filecmp.cmp(p, b[k], shallow=False)
        )
        for k, p in a.items()
    )


def check_checkout(path, commit):
    head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(path), "status", "--porcelain"], text=True
    ).strip()
    if head != commit or dirty:
        raise ValueError(f"checkout differs from pinned source: {path}")


def check(home, model, docs_url, serena_args, mode, ponytail_commit, superpowers_commit):
    config, hooks_file = home / ".codex/config.toml", home / ".codex/hooks.json"
    cfg = tomllib.loads(config.read_text())
    features = cfg.get("features", {})
    servers = cfg.get("mcp_servers", {})
    state = cfg.get("hooks", {}).get("state", {})
    hooks = json.loads(hooks_file.read_text()).get("hooks", {}) if hooks_file.exists() else {}
    omx_file = home / ".codex/.omx-config.json"
    omx = json.loads(omx_file.read_text()) if omx_file.exists() else {}
    expected = native_groups(home)
    count = {"orca": 0, "omx": 0, "ponytail": 0, "unknown": 0}
    untrusted, mismatches = [], []
    for event, groups in hooks.items():
        for g, group in enumerate(groups):
            for h, handler in enumerate(group.get("hooks", [])):
                command = handler.get("command", "")
                owner = (
                    "ponytail"
                    if owned(handler)
                    else "orca"
                    if "orca-agent-hook-form" in command
                    else "omx"
                    if "/oh-my-codex/" in command
                    else "unknown"
                )
                count[owner] += 1
                if owner == "ponytail" and (expected.get(event) != [group] or g != len(groups) - 1):
                    mismatches.append(event)
                key = f"{hooks_file}:{event_label(event)}:{g}:{h}"
                entry = state.get(key, {})
                current = hook_hash(event, group, handler)
                if (
                    current is None
                    or entry.get("trusted_hash") != current
                    or entry.get("enabled") is False
                ):
                    untrusted.append(f"{event} {g}:{h}")
    wanted = {"orca": 9, "omx": 8, "ponytail": 3, "unknown": 0}
    serena = dict(
        command="serena",
        args=tomllib.loads(f"v = {serena_args}")["v"],
        startup_timeout_sec=15,
        env={"SERENA_USAGE_REPORTING": "false"},
    )
    problems = [
        name
        for name, bad in [
            ("model", cfg.get("model") != model),
            ("model_reasoning_effort", cfg.get("model_reasoning_effort") != "high"),
            ("approval_policy", cfg.get("approval_policy") != "never"),
            ("sandbox_mode", cfg.get("sandbox_mode") != "danger-full-access"),
            ("check_for_update_on_startup", cfg.get("check_for_update_on_startup") is not False),
            *[
                (f"[features] {name}", features.get(name) is not False)
                for name in (
                    "apps",
                    "plugins",
                    "remote_plugin",
                    "plugin_sharing",
                    "skill_mcp_dependency_install",
                    "memories",
                )
            ],
            ("[features] connectors (the old name of apps)", "connectors" in features),
            (f"MCP servers {sorted(servers)}", set(servers) != {"openaiDeveloperDocs", "serena"}),
            ("openaiDeveloperDocs", servers.get("openaiDeveloperDocs", {}) != {"url": docs_url}),
            ("[mcp_servers.serena]", servers.get("serena", {}) != serena),
            (f"plugins {sorted(cfg.get('plugins', {}))}", "plugins" in cfg),
            ("marketplaces tables", "marketplaces" in cfg),
            (
                "a profile sets features, MCP servers or plugins",
                any(
                    key in p
                    for p in cfg.get("profiles", {}).values()
                    for key in ("features", "mcp_servers", "plugins", "marketplaces")
                ),
            ),
            ("[analytics] enabled", cfg.get("analytics", {}).get("enabled") is not False),
            ("[feedback] enabled", cfg.get("feedback", {}).get("enabled") is not False),
            ("[otel] metrics_exporter", cfg.get("otel", {}).get("metrics_exporter") != "none"),
            (
                f"hooks.json entries {count}",
                count != wanted and not (mode == "install" and count == wanted | {"orca": 0}),
            ),
            (f"hooks without trust: {untrusted}", bool(untrusted)),
            (f"ponytail hook mismatch: {mismatches}", bool(mismatches)),
            (".omx-config.json teamMode", omx.get("teamMode") != "disabled"),
            (
                ".omx-config.json prompt triage",
                omx.get("promptRouting", {}).get("triage", {}).get("enabled") is not False,
            ),
        ]
        if bad
    ]
    cache = home / ".codex/plugins/cache"
    if cache.exists() and any(cache.iterdir()):
        problems.append("plugin cache is not empty")
    if (home / ".local/share/meridian/codex-market").exists():
        problems.append("legacy ponytail marketplace remains")
    if problems:
        raise ValueError("Codex config: " + ", ".join(problems))
    omx_skills = home / ".local/lib/node_modules/oh-my-codex/skills"
    for name in PONYTAIL_SKILLS:
        if (omx_skills / name).exists():
            raise ValueError(f"ponytail/oh-my-codex skill collision: {name}")
    superpowers = home / ".local/share/meridian/dsh-skill-src/obra__superpowers"
    check_checkout(source_dir(home), ponytail_commit)
    check_checkout(superpowers, superpowers_commit)
    for src, names in ((source_dir(home), PONYTAIL_SKILLS), (superpowers, EXTRA_SKILLS)):
        for name in names:
            source = (
                omx_skills / name
                if name in EXTRA_SKILLS and (omx_skills / name).exists()
                else src / "skills" / name
            )
            if not (source / "SKILL.md").is_file() or not equal_tree(
                source, home / ".codex/skills" / name
            ):
                raise ValueError(f"native skill differs from source: {name}")
    if count["orca"] == 0:
        print(
            "note: Orca's 9 Codex hooks are not there yet; "
            "Orca adds them, and agents-check requires them"
        )


def table_parts(header):
    value = tomllib.loads(f"[{header}]\n")
    parts = []
    while value:
        ((key, value),) = value.items()
        parts.append(key)
    return tuple(parts)


def clean_legacy(home):
    # Only prior Meridian-owned plugin tables/trust and the two explicitly retired caches.
    path = home / ".codex/config.toml"
    text = path.read_text()
    tomllib.loads(text)
    lines, result, under, i = text.splitlines(keepends=True), [], (), 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("["):
            match = re.fullmatch(r"\[(.*?)\]\s*(#.*)?", stripped)
            under = table_parts(match[1]) if match and not stripped.startswith("[[") else ()
            stop = i + 1
        elif not stripped or stripped.startswith("#"):
            stop = i + 1
        else:
            for stop in range(i + 1, len(lines) + 1):
                try:
                    tomllib.loads("".join(lines[i:stop]))
                    break
                except tomllib.TOMLDecodeError:
                    continue
            else:
                raise ValueError("cannot parse legacy config statement")
        remove = under[:2] in (("plugins", PLUGIN), ("marketplaces", "meridian-ponytail")) or (
            under[:2] == ("hooks", "state")
            and len(under) == 3
            and under[2].startswith(PLUGIN + ":")
        )
        if not remove:
            result.extend(lines[i:stop])
        i = stop
    cleaned = "".join(result)
    cfg = tomllib.loads(cleaned)
    # Codex removal may leave an empty parent table; retain every foreign child.
    for name in ("plugins", "marketplaces"):
        if name in cfg and cfg[name] == {}:
            cleaned = re.sub(r"(?m)^\[" + name + r"\]\s*(?:#.*)?$\n?", "", cleaned)
    tomllib.loads(cleaned)
    write_changed(path, cleaned)
    for target in (
        home / ".codex/plugins/cache/meridian-ponytail",
        home / ".codex/plugins/cache/openai-curated-remote",
        home / ".local/share/meridian/codex-market",
    ):
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)


def main():
    action, home_arg, *args = sys.argv[1:]
    home = Path(home_arg).absolute()
    if action == "install":
        install(home)
    elif action == "check":
        check(home, *args)
    elif action == "clean-legacy":
        clean_legacy(home)
    elif action == "legacy":
        cfg = tomllib.loads((home / ".codex/config.toml").read_text())
        if PLUGIN in cfg.get("plugins", {}):
            print("plugin")
        if "meridian-ponytail" in cfg.get("marketplaces", {}):
            print("marketplace")
    else:
        raise ValueError(f"unknown action: {action}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
