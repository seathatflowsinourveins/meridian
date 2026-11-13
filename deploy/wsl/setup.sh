#!/usr/bin/env bash
# meridian: user-level setup inside the distro, after cloud-init has finished.
# Run as the owner user, never as root.
#
#   deploy/wsl/setup.sh check         verify what deploy/wsl/meridian.user-data was meant to do
#   deploy/wsl/setup.sh uv            install uv (pinned; installer checksum verified first)
#   deploy/wsl/setup.sh gh            install the GitHub CLI from GitHub's release, in place of Ubuntu's
#   deploy/wsl/setup.sh repo          clone the repo to ~/src/meridian and run `uv sync --locked`
#   deploy/wsl/setup.sh gateway       install IB Gateway (pinned build; never starts it or logs in)
#   deploy/wsl/setup.sh agents        all of the following, in this order:
#     claude        Claude Code, from Anthropic's signed release manifest
#     codex         Codex CLI (npm)
#     agy           Antigravity CLI (its GitHub release asset)
#     dsh           DeepSeek Harness and the terminal UI Orca launches for it (npm, pnpm)
#     orca          Orca server, a loopback-only systemd user service (sudo for /opt)
#     codex-bridge  the Codex review plugin for Claude Code
#   deploy/wsl/setup.sh agents-check  verify the agent runtimes and their settings
#   deploy/wsl/setup.sh signins       list the sign-ins left for the owner, with their commands
#   deploy/wsl/setup.sh orca-pair     owner, once, in Windows Terminal: pair the Windows Orca app
#
# Order: check, uv, gh, repo, gateway, then agents. Sign-ins are the owner's: see UPSTREAM.md.
# Versions, checksums and the pages they were read from: UPSTREAM.md.
set -euo pipefail
# The tools below go to ~/.local/bin. Ubuntu's ~/.profile puts that on PATH only when it existed
# at login, which on a fresh distro it did not.
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) export PATH="${HOME}/.local/bin:${PATH}" ;;
esac

UV_VERSION=0.13.7
UV_INSTALLER_SHA256=d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4
NODE_VERSION=v24.22.3
# GitHub CLI: GitHub's release tarball, by the SHA-256 in the release's checksums file (the same
# value GitHub shows as the asset's digest). Ubuntu's package (2.46.0) is inside two high
# advisories, GHSA-8xvp-7hj6-mcj9 and GHSA-p2h2-3vg9-4p87, so it is not installed. gh does not
# update itself: a new pin here updates it.
GH_VERSION=2.104.0
GH_SHA256=98cb101ad87dbbd3f6b2f2bfcbd43197ccd07643140121d8a9cfaa91eadbc24e
GH_URL="https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz"

# Agent runtimes. By the owner's decision of 2026-11-12 they update themselves where the tool
# can, in sessions the owner starts (Orca's own launches switch the updaters off). What is
# pinned here is the release each one starts from: an exact version whose own download is
# checked against its publisher's checksum or registry integrity value before it runs. The
# dependencies of an npm package resolve from the registry on the day of the install.
# `agents-check` accepts the pinned version or newer.
# (The 7-day wait for new releases still applies to the Python dependencies in pyproject.toml.)
#
# Claude Code: 2.1.321 is the first release that runs the lead model. The checksum is the
# linux-x64 entry of Anthropic's signed manifest.
CLAUDE_VERSION=2.1.322
CLAUDE_SHA256=bfb3703ad5380242328459bc62ada4bde8ae7ba57c6e1eeadb9c00e08874c478
CLAUDE_RELEASE_SIGNER=31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE
CLAUDE_RELEASES=https://downloads.claude.ai/claude-code-releases
CLAUDE_MODEL=claude-fable-5-2
# Codex CLI: OpenAI's npm package and its linux-x64 build, by their registry integrity values.
CODEX_VERSION=0.167.2
CODEX_INTEGRITY=sha512-6OFkr2ndzTdFb32OEiUlM9BgpeY8+wnMe8vRhuvt+22TnxVR39KnJ22Ghay98IY9OmEltoNgFN4GALUkxFQCOw==
CODEX_LINUX_INTEGRITY=sha512-2Rw3VkWonMxwCSgOw+NkiKLOuOzyoQNWmxU7x8GniesdMfhKc4asNqOzTgQwJLKCrSlPc4/6fYTaH7fYcuGWGQ==
CODEX_MODEL=gpt-6-astra
# DeepSeek Harness: the engine (`dsh`), pnpm (dsh installs its profiles with it, and pins the
# 11.x line), the community terminal UI that Orca launches for it (`dsh-tui`), and the two hook
# packages that give Orca its status events (at the engine's version). Registry integrity values.
DSH_VERSION=0.2.2-rc.1
DSH_INTEGRITY=sha512-ijR9UEVYkG15Q/Q79JzvzLBzQOQfc63VLr9n6flpwHPhr5IKn2UxthnSoto/P9l7qGd7pPvI1Ra6TW7LH3oKpg==
DSH_HOOKS_INTEGRITY=sha512-OhLHJRIlF6a8I0/P12liMzuss/6oeGplI1FM7IhOEPTzeI8BxMRdG7PmmeMik3s9QGt4OXpu5wO83WqoKf2o+A==
DSH_HOOK_PROTOCOL_INTEGRITY=sha512-RbhsR5Y28PmkAEckKbBi1N666cF/Qjta2lfAYJNgN77y/tyfhjH6LtuXbOFO8RrgVojYiQZnrWEWBv41Hi5h3A==
DSH_TUI_VERSION=0.20.0
DSH_TUI_INTEGRITY=sha512-04K4E9nGBiefTerV2SaRjLYcDRGjwYXVNL0+tH/FCEdRhTnVDwMEADyC3a/etQ/NzoM2Sh1B+inb23T5Aqxcqw==
PNPM_VERSION=11.28.9
PNPM_INTEGRITY=sha512-NUIc6icg7KP1rXIrZ+jvGPTTzUdF7S/P6w3CiNTpQ3+tOHDZHuboPyaPD29+D2JyMxexlhe7Re5DMxcu9RFZ+A==
# The only install scripts dsh's tree may run (terminal, FFI, its process helper, two SDKs).
DSH_ALLOW_SCRIPTS=node-pty,koffi,@deepseek-ai/dsh-subprocess-local,@google/genai,protobufjs
# Orca server: the server-only release tarball (orcad, its own Node, the orca-ide CLI), by the
# SHA-256 in the release's checksum file. It does not update itself; a new pin here updates it.
ORCA_VERSION=1.4.257
ORCA_SHA256=72f42c1f5e66d828375d70a54fda5a5f910b90471948d93eedbc3a9ed19bc840
ORCA_ROOT=/opt/orca-server
# Loopback only, on a port of its own: with mirrored networking a listener on every interface
# is reachable from the network, and 6768 is the Windows app's default port.
ORCA_PORT=6790
# The orca-serve unit's environment, which its terminal daemon and so every agent inherits:
# telemetry off; DeepSeek Harness in the owner's bypass mode (Orca passes it no flag) and in
# English; DeepSeek's two API endpoints fixed at the packages' own defaults, because the launch
# environment outranks a .env file in the directory an agent starts in.
ORCA_UNIT_ENV=(
  ORCA_TELEMETRY_DISABLED=1
  DSH_PERMISSION_MODE=danger-full-access
  DSH_TUI_LANG=en
  DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic
  DEEPSEEK_SEARCH_BASE_URL=https://api.deepseek.com/anthropic/v1
)
# Claude Code plugin for cross-family review (/codex:review): openai/codex-plugin-cc from its
# default branch. Its first install here was this commit (tag v1.0.6); it updates with upstream.
CODEX_BRIDGE_COMMIT=db52e28f4d9ded852ab3942cea316258ae4ef346
# Antigravity CLI (`agy`): the GitHub release asset of this version, by the SHA-256 digest
# GitHub shows for it. (Google's install.sh and agy's own updater take the build named in their
# updater service's manifest instead, checked against the SHA-512 in that manifest.)
AGY_VERSION=1.5.7
AGY_SHA256=d6150a8d2a9e29a3d171b2325d6f66b6e7059628f4799a20c069b8ed8f78fdbb
AGY_URL="https://github.com/google-antigravity/antigravity-cli/releases/download/${AGY_VERSION}/agy_cli_linux_x64.tar.gz"

# IBKR serves one file per channel and publishes no checksum. This is the SHA-256 of the
# stable build named here, taken when it was downloaded. When IBKR moves the stable channel
# the check below fails, on purpose: read the new version, then update both lines.
GATEWAY_VERSION=10.50.1g
GATEWAY_SHA256=13dc8bb05cbcec8d1b0bb0b25748447cf85863fb4b94361f57fcd350f35c7a9c
GATEWAY_URL=https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
GATEWAY_DIR="${HOME}/Jts/ibgateway/1050"
GATEWAY_LIBS="libgtk-3-0t64 libnss3 libnspr4 libasound2t64 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libcups2t64 xdg-utils"
REPO=seathatflowsinourveins/meridian
REPO_DIR="${HOME}/src/meridian"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok:   $*"; }
# version_ge A B: version A is B or newer, by semver (pre-releases included), with the semver
# module that ships inside npm. False when A is empty or not a version.
version_ge() {
  local semver
  semver="$(dirname "$(readlink -f "$(command -v npm)")")/../node_modules/semver"
  [ -n "${1:-}" ] && node -e \
    'process.exit(require(process.argv[1]).gte(process.argv[2], process.argv[3]) ? 0 : 1)' \
    "${semver}" "$1" "$2" 2>/dev/null
}

# Global npm installs, and the updates the tools make to themselves later, go to ~/.local
# (the owner's; on PATH from the next login, and in this script through the lines at the top),
# not into the Node tree under /opt.
npm_user_prefix() {
  [ "$(npm config get prefix)" = "${HOME}/.local" ] || npm config set prefix "${HOME}/.local"
  install -d "${HOME}/.local/lib" "${HOME}/.local/bin"
}

# npm_pinned PACKAGE@VERSION INTEGRITY: the registry serves the pinned build. npm then checks
# the tarball it downloads against that same value.
npm_pinned() {
  [ "$(npm view "$1" dist.integrity)" = "$2" ] || fail "$1 on the registry is not the pinned build"
}

[ "$(id -u)" -ne 0 ] || fail "run as the owner user, not root"

cmd_check() {
  [ "$(ps -p 1 -o comm=)" = systemd ] || fail "PID 1 is not systemd"
  ok "systemd is PID 1"
  sudo -n true 2>/dev/null || fail "passwordless sudo is not available"
  ok "passwordless sudo"
  id paper >/dev/null 2>&1 || fail "service user 'paper' is missing"
  [ "$(getent passwd paper | cut -d: -f7)" = /usr/sbin/nologin ] || fail "'paper' has a login shell"
  [ "$(getent passwd paper | cut -d: -f6)" = /nonexistent ] || fail "'paper' has a home directory"
  ok "service user paper (no login, no home)"
  case ":${PATH}:" in
    *:/mnt/c/*) fail "Windows PATH is appended (appendWindowsPath should be false)" ;;
  esac
  ok "Windows PATH not appended"
  for pkg in git build-essential curl jq unzip; do
    dpkg -s "${pkg}" >/dev/null 2>&1 || fail "package ${pkg} is missing"
  done
  ok "packages: git build-essential curl jq unzip"
  for pkg in ${GATEWAY_LIBS}; do
    dpkg -s "${pkg}" >/dev/null 2>&1 || fail "package ${pkg} is missing (IB Gateway window)"
  done
  ok "packages for the IB Gateway window"
  [ "$(node --version)" = "${NODE_VERSION}" ] || fail "node is $(node --version 2>/dev/null), expected ${NODE_VERSION}"
  ok "node ${NODE_VERSION}"
  [ "$(timedatectl show -p Timezone --value)" = America/New_York ] \
    || fail "time zone is $(timedatectl show -p Timezone --value), expected America/New_York"
  grep -qx 'useWindowsTimezone=false' /etc/wsl.conf \
    || fail "/etc/wsl.conf does not set useWindowsTimezone=false"
  ok "time zone America/New_York, not inherited from Windows"
  jq -e '.disableClaudeAiConnectors == true' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "disableClaudeAiConnectors is not true in ~/.claude/settings.json"
  check_claude_managed
  ok "claude.ai connectors and every MCP server off for Claude Code in this distro (user and machine-wide)"
  echo "note: that setting does not cover connectors the Claude desktop app itself attaches to a session"
  check_codex_requirements
  ok "Codex: every MCP server, ChatGPT apps, plugins and memories off machine-wide"
  for source in linux wsl_setup ubuntu_release_upgrader; do
    ubuntu-insights consent "${source}" 2>/dev/null | grep -qx "${source}: false" \
      || fail "Ubuntu Insights consent for ${source} is not recorded as false"
  done
  for timer in ubuntu-insights-collect.timer ubuntu-insights-upload.timer; do
    [ "$(systemctl --user is-enabled "${timer}" 2>/dev/null)" != enabled ] \
      || fail "${timer} is enabled"
  done
  ok "Ubuntu Insights declined, its timers off"
}

cmd_uv() {
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSLo "${tmp}/uv-installer.sh" "https://astral.sh/uv/${UV_VERSION}/install.sh"
  echo "${UV_INSTALLER_SHA256}  ${tmp}/uv-installer.sh" | sha256sum -c -
  # No shell files are edited: Ubuntu's ~/.profile puts ~/.local/bin on PATH from the next login.
  UV_NO_MODIFY_PATH=1 sh "${tmp}/uv-installer.sh"
  rm -rf "${tmp}"
  "${HOME}/.local/bin/uv" --version
}

gh_version() { "${HOME}/.local/bin/gh" --version 2>/dev/null </dev/null | sed -n 's/^gh version \([^ ]*\).*/\1/p'; }
# installed, or nothing: the state dpkg records for Ubuntu's gh package.
gh_package_state() { dpkg-query -W -f='${db:Status-Status}' gh 2>/dev/null || true; }

cmd_gh() {
  # GitHub's own build in ~/.local/bin, which comes before /usr/bin on PATH. Ubuntu's package is
  # removed, so that no older gh stays reachable (sudo's PATH, an absolute /usr/bin/gh).
  if ! version_ge "$(gh_version)" "${GH_VERSION}"; then
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/gh.tar.gz" "${GH_URL}"
    echo "${GH_SHA256}  ${tmp}/gh.tar.gz" | sha256sum -c -
    tar -xzf "${tmp}/gh.tar.gz" -C "${tmp}" "gh_${GH_VERSION}_linux_amd64/bin/gh"
    install -D -m 0755 "${tmp}/gh_${GH_VERSION}_linux_amd64/bin/gh" "${HOME}/.local/bin/gh"
    rm -rf "${tmp}"
  fi
  if [ "$(gh_package_state)" = installed ]; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y -o DPkg::Lock::Timeout=120 gh
  fi
  check_gh
}

check_gh() {
  version_ge "$(gh_version)" "${GH_VERSION}" \
    || fail "the GitHub CLI is older than ${GH_VERSION} or missing (run: deploy/wsl/setup.sh gh)"
  [ "$(command -v gh)" = "${HOME}/.local/bin/gh" ] \
    || fail "gh resolves to $(command -v gh || echo nothing), not ~/.local/bin/gh"
  [ "$(gh_package_state)" != installed ] \
    || fail "Ubuntu's gh package is installed (run: deploy/wsl/setup.sh gh)"
  ok "GitHub CLI $(gh_version), GitHub's own build in ~/.local/bin; Ubuntu's gh package not installed"
}

claude_settings() {
  # Merged into the file, never written over it: Claude Code and Orca keep their own keys there.
  # Bypass mode is the owner's choice for this distro. The deny rules stop Claude Code's file
  # tools at the owner's files; a shell command can still reach them.
  local file="${HOME}/.claude/settings.json" tmp
  tmp="$(mktemp)"
  jq --arg model "${CLAUDE_MODEL}" --arg floor "${CLAUDE_VERSION}" '
    . * {
      model: $model,
      modelSettings: {($model): {effortLevel: "high"}},
      permissions: {defaultMode: "bypassPermissions"},
      skipDangerousModePermissionPrompt: true,
      disableClaudeAiConnectors: true,
      syncClaudeAiSkills: false,
      syncClaudeAiPlugins: false,
      autoUpdatesChannel: "latest",
      minimumVersion: $floor
    }
    | .permissions.deny = ((.permissions.deny // []) + [
        "Edit(//**/risk/**)", "Edit(//**/*.contract.json)", "Read(//**/.env)", "Read(//**/.env.*)"
      ] | unique)
  ' "${file}" > "${tmp}"
  install -m 0644 "${tmp}" "${file}"
  rm -f "${tmp}"
}

claude_version() { "${HOME}/.local/bin/claude" --version 2>/dev/null | cut -d' ' -f1; }

# The machine-wide files deploy/wsl/meridian.user-data writes for Claude Code: no claude.ai
# connectors, and an empty managed MCP list, which takes exclusive control of MCP so that no
# server starts from a project's .mcp.json, the user's config, a plugin or --mcp-config.
check_claude_managed() {
  jq -e '.disableClaudeAiConnectors == true' /etc/claude-code/managed-settings.json >/dev/null 2>&1 \
    || fail "disableClaudeAiConnectors is not true in /etc/claude-code/managed-settings.json"
  jq -e '.mcpServers == {}' /etc/claude-code/managed-mcp.json >/dev/null 2>&1 \
    || fail "/etc/claude-code/managed-mcp.json does not switch every MCP server off (see meridian.user-data)"
}

cmd_claude() {
  # The pinned binary comes straight from the release bucket and is checked against Anthropic's
  # signed manifest; it then installs itself. Upstream's install.sh is not used: it runs
  # whichever release is newest that day to do the install. Afterwards Claude Code updates
  # itself; `minimumVersion` keeps it from going below the pinned release.
  if version_ge "$(claude_version)" "${CLAUDE_VERSION}"; then
    ok "Claude Code $(claude_version) is already installed"
    claude_settings
    check_claude
    return
  fi
  local tmp
  tmp="$(mktemp -d)"
  (
    cd "${tmp}"
    curl -fsSLO "${CLAUDE_RELEASES}/${CLAUDE_VERSION}/manifest.json"
    curl -fsSLO "${CLAUDE_RELEASES}/${CLAUDE_VERSION}/manifest.json.sig"
    curl -fsSLo claude-code.asc https://downloads.claude.ai/keys/claude-code.asc
    export GNUPGHOME="${tmp}/gnupg"
    mkdir -m 700 "${GNUPGHOME}"
    gpg --batch --quiet --import claude-code.asc
    gpg --batch --status-fd 1 --verify manifest.json.sig manifest.json 2>/dev/null \
      | grep -q "^\[GNUPG:\] VALIDSIG ${CLAUDE_RELEASE_SIGNER} " \
      || fail "the Claude Code manifest is not signed by ${CLAUDE_RELEASE_SIGNER}"
    [ "$(jq -r '.platforms["linux-x64"].checksum' manifest.json)" = "${CLAUDE_SHA256}" ] \
      || fail "the signed manifest does not carry the pinned checksum"
    curl -fsSLo claude "${CLAUDE_RELEASES}/${CLAUDE_VERSION}/linux-x64/claude"
    echo "${CLAUDE_SHA256}  claude" | sha256sum -c -
    chmod u+x claude
    ./claude install "${CLAUDE_VERSION}"
  )
  rm -rf "${tmp}"
  # `claude install` can exit 0 without installing, so the result is judged by what is on disk.
  echo "${CLAUDE_SHA256}  ${HOME}/.local/share/claude/versions/${CLAUDE_VERSION}" | sha256sum -c -
  [ "$(claude_version)" = "${CLAUDE_VERSION}" ] || fail "claude --version is not ${CLAUDE_VERSION}"
  claude_settings
  check_claude
}

check_claude() {
  version_ge "$(claude_version)" "${CLAUDE_VERSION}" \
    || fail "Claude Code is older than ${CLAUDE_VERSION} or missing (run: deploy/wsl/setup.sh claude)"
  # The one plugin allowed is the Codex review plugin (setup.sh codex-bridge).
  jq -e --arg model "${CLAUDE_MODEL}" --arg floor "${CLAUDE_VERSION}" '
    .disableClaudeAiConnectors == true and .syncClaudeAiPlugins == false
    and .syncClaudeAiSkills == false and .minimumVersion == $floor
    and .autoUpdatesChannel == "latest"
    and .model == $model and .modelSettings[$model].effortLevel == "high"
    and .permissions.defaultMode == "bypassPermissions"
    and .skipDangerousModePermissionPrompt == true
    and (["Edit(//**/risk/**)", "Edit(//**/*.contract.json)", "Read(//**/.env)", "Read(//**/.env.*)"]
      - (.permissions.deny // []) == [])
    and ([.enabledPlugins // {} | to_entries[] | select(.value == true) | .key]
      - ["codex@openai-codex"] == [])
  ' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "~/.claude/settings.json is not what deploy/wsl/setup.sh claude writes"
  check_claude_managed
  ok "Claude Code $(claude_version): ${CLAUDE_MODEL} at high effort, no claude.ai connectors, sync or MCP server"
}

codex_version() {
  "${HOME}/.local/bin/codex" --version 2>/dev/null </dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1
}

cmd_codex() {
  npm_user_prefix
  if ! version_ge "$(codex_version)" "${CODEX_VERSION}"; then
    npm_pinned "@openai/codex@${CODEX_VERSION}" "${CODEX_INTEGRITY}"
    npm_pinned "@openai/codex@${CODEX_VERSION}-linux-x64" "${CODEX_LINUX_INTEGRITY}"
    # Neither package has install scripts; --strict-allow-scripts fails the install if one appears.
    npm install -g --strict-allow-scripts "@openai/codex@${CODEX_VERSION}"
  fi
  codex_config
  check_codex
}

# codex_feature_off FILE NAME: `NAME = false` in the file's [features] table. A line that sets
# NAME there is rewritten, a missing one is added under the header, and the result is parsed
# before it replaces the file. A file without a [features] table is an error.
codex_feature_off() {
  python3 -I - "$1" "$2" <<'PY' || fail "cannot set $2 = false in the [features] table of $1"
import os
import re
import sys
import tomllib

path, name = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    text = f.read()
if tomllib.loads(text).get("features", {}).get(name) is False:
    sys.exit(0)
lines = text.splitlines(keepends=True)
header = next(
    (i for i, line in enumerate(lines) if re.fullmatch(r"\s*\[\s*features\s*\]\s*(#.*)?\n?", line)),
    None,
)
if header is None:
    sys.exit(f"{path} has no [features] table")
end = next((i for i in range(header + 1, len(lines)) if re.match(r"\s*\[", lines[i])), len(lines))
key = re.compile(rf"\s*{re.escape(name)}\s*=")
hits = [i for i in range(header + 1, end) if key.match(lines[i])]
for i in reversed(hits):
    del lines[i]
lines.insert(hits[0] if hits else header + 1, f"{name} = false\n")
new = "".join(lines)
if tomllib.loads(new).get("features", {}).get(name) is not False:
    sys.exit(f"{path}: {name} is set outside the [features] table")
with open(f"{path}.new", "w", encoding="utf-8") as f:
    f.write(new)
os.chmod(f"{path}.new", 0o600)
os.replace(f"{path}.new", path)
PY
}

codex_config() {
  # Written once; Orca later adds its own [hooks.state.*] and [projects.*] tables to this file.
  # The [features] switches are re-applied on every run. /etc/codex/requirements.toml pins the
  # same four off in every config layer, a project's .codex/config.toml included.
  local file="${HOME}/.codex/config.toml" feature
  if [ ! -e "${file}" ]; then
    codex_config_file
  fi
  for feature in apps plugins skill_mcp_dependency_install memories; do
    codex_feature_off "${file}" "${feature}"
  done
}

codex_config_file() {
  install -d -m 0700 "${HOME}/.codex"
  cat > "${HOME}/.codex/config.toml" <<TOML
# Codex CLI in the meridian distro, written by deploy/wsl/setup.sh codex (see UPSTREAM.md).
# Worker and reviewer of Claude-authored work. The bulk worker runs with: codex -m gpt-6.1-sol
model = "${CODEX_MODEL}"
model_reasoning_effort = "high"
# Bypass mode, the owner's choice for this distro (what --dangerously-bypass-approvals-and-sandbox sets).
approval_policy = "never"
sandbox_mode = "danger-full-access"

[features]
# ChatGPT apps (account connectors) stay off, as claude.ai connectors do for Claude Code, so no
# account-linked tool (a broker connector among them) reaches an agent here. Plugins, and the MCP
# servers a skill can ask for, stay off until an evidence record adds one (plan 8.6). So does
# Codex's own memory: the memory layer is chosen by evidence record too (plan 8.7).
apps = false
plugins = false
skill_mcp_dependency_install = false
memories = false

[analytics]
enabled = false

[feedback]
enabled = false

[otel]
metrics_exporter = "none"
TOML
  chmod 0600 "${HOME}/.codex/config.toml"
}

check_codex() {
  version_ge "$(codex_version)" "${CODEX_VERSION}" \
    || fail "Codex CLI is older than ${CODEX_VERSION} or missing (run: deploy/wsl/setup.sh codex)"
  python3 -I - "${HOME}/.codex/config.toml" "${CODEX_MODEL}" <<'PY' || fail "~/.codex/config.toml is not what deploy/wsl/setup.sh codex writes"
import sys
import tomllib

with open(sys.argv[1], "rb") as f:
    cfg = tomllib.load(f)
features = cfg.get("features", {})
profiles = cfg.get("profiles", {})
off = ("apps", "plugins", "skill_mcp_dependency_install", "memories")
problems = [
    name
    for name, bad in [
        ("model", cfg.get("model") != sys.argv[2]),
        ("model_reasoning_effort", cfg.get("model_reasoning_effort") != "high"),
        ("approval_policy", cfg.get("approval_policy") != "never"),
        ("sandbox_mode", cfg.get("sandbox_mode") != "danger-full-access"),
        *[(f"[features] {name}", features.get(name) is not False) for name in off],
        ("[features] connectors (the old name of apps)", "connectors" in features),
        ("MCP servers configured", bool(cfg.get("mcp_servers"))),
        (
            "a profile sets features or MCP servers",
            any("features" in p or "mcp_servers" in p for p in profiles.values()),
        ),
        ("[analytics] enabled", cfg.get("analytics", {}).get("enabled") is not False),
        ("[feedback] enabled", cfg.get("feedback", {}).get("enabled") is not False),
        ("[otel] metrics_exporter", cfg.get("otel", {}).get("metrics_exporter") != "none"),
    ]
    if bad
]
sys.exit(f"config.toml: {', '.join(problems)}" if problems else 0)
PY
  check_codex_requirements
  ok "Codex CLI $(codex_version): ${CODEX_MODEL} at high effort, no ChatGPT apps, plugins, memories or MCP server"
}

# /etc/codex/requirements.toml, written by deploy/wsl/meridian.user-data: an empty MCP allowlist
# (no server starts from any config layer) and the account-linked features pinned off.
check_codex_requirements() {
  python3 -I - <<'PY' || fail "/etc/codex/requirements.toml does not switch every MCP server and the account features off"
import sys
import tomllib

try:
    with open("/etc/codex/requirements.toml", "rb") as f:
        req = tomllib.load(f)
except (OSError, tomllib.TOMLDecodeError) as error:
    sys.exit(str(error))
features = req.get("features", {})
off = ("apps", "plugins", "skill_mcp_dependency_install", "memories")
sys.exit(0 if req.get("mcp_servers") == {} and all(features.get(name) is False for name in off) else 1)
PY
}

cmd_codex_bridge() {
  local claude="${HOME}/.local/bin/claude" mp="${HOME}/.claude/plugins/marketplaces/openai-codex"
  local settings="${HOME}/.claude/settings.json" tmp
  export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1
  # The marketplace first; the plugin is installed only once its history has been checked.
  [ -d "${mp}/.git" ] || "${claude}" plugin marketplace add openai/codex-plugin-cc --scope user </dev/null
  # Claude Code clones a marketplace with --depth 1, which hides the commit checked for.
  [ "$(git -C "${mp}" rev-parse --is-shallow-repository)" = false ] || git -C "${mp}" fetch --quiet --unshallow
  if ! git -C "${mp}" merge-base --is-ancestor "${CODEX_BRIDGE_COMMIT}" HEAD; then
    "${claude}" plugin disable codex@openai-codex --scope user </dev/null >/dev/null 2>&1 || true
    fail "the codex-plugin-cc checkout does not descend from ${CODEX_BRIDGE_COMMIT}; the plugin is left disabled"
  fi
  if ! "${claude}" plugin list --json </dev/null | jq -e '.[] | select(.id == "codex@openai-codex")' >/dev/null; then
    "${claude}" plugin install codex@openai-codex --scope user </dev/null
  fi
  # It follows upstream, as the runtimes do (the owner's decision of 2026-11-12).
  tmp="$(mktemp)"
  jq '.extraKnownMarketplaces["openai-codex"].autoUpdate = true' "${settings}" > "${tmp}"
  install -m 0644 "${tmp}" "${settings}"
  rm -f "${tmp}"
  check_codex_bridge
}

check_codex_bridge() {
  "${HOME}/.local/bin/claude" plugin list --json </dev/null \
    | jq -e '.[] | select(.id == "codex@openai-codex" and .enabled)' >/dev/null \
    || fail "the Codex plugin is not installed in Claude Code (run: deploy/wsl/setup.sh codex-bridge)"
  jq -e '.extraKnownMarketplaces["openai-codex"].autoUpdate == true' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "the openai-codex marketplace does not follow upstream (run: deploy/wsl/setup.sh codex-bridge)"
  # The plugin's automatic review gate stays off: it is on only where a state file says so.
  local state
  for state in "${HOME}/.claude/plugins/data/codex-openai-codex" /tmp/codex-companion; do
    [ ! -d "${state}" ] || ! grep -rqs '"stopReviewGate": *true' "${state}" \
      || fail "the codex-plugin-cc review gate is switched on under ${state}"
  done
  ok "Codex review plugin $(jq -r '.plugins["codex@openai-codex"][0].version' "${HOME}/.claude/plugins/installed_plugins.json") in Claude Code, review gate off"
}

# stdin is closed on purpose: before the owner has signed in, agy with a terminal attached can
# start its sign-in and terms screens, and those are the owner's to answer.
agy_version() {
  "${HOME}/.local/bin/agy" --version 2>/dev/null </dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1
}

cmd_agy() {
  # Google's install.sh always takes the newest release and then edits shell profiles
  # (`agy install`). Instead: the GitHub release asset of the pinned version at its checksum,
  # unpacked to ~/.local/bin/agy, no profile edits. agy then updates itself.
  if version_ge "$(agy_version)" "${AGY_VERSION}"; then
    ok "Antigravity CLI $(agy_version) is already installed"
    check_agy
    return
  fi
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSLo "${tmp}/agy.tar.gz" "${AGY_URL}"
  echo "${AGY_SHA256}  ${tmp}/agy.tar.gz" | sha256sum -c -
  [ "$(tar -tzf "${tmp}/agy.tar.gz")" = antigravity ] || fail "the agy archive is not one file named antigravity"
  tar -xzf "${tmp}/agy.tar.gz" -C "${tmp}" antigravity
  install -D -m 0755 "${tmp}/antigravity" "${HOME}/.local/bin/agy"
  rm -rf "${tmp}"
  check_agy
}

check_agy() {
  version_ge "$(agy_version)" "${AGY_VERSION}" \
    || fail "Antigravity CLI is older than ${AGY_VERSION} or missing (run: deploy/wsl/setup.sh agy)"
  # No MCP server and no plugin: nothing here may give an agent a broker or an order tool.
  # agy has no machine-wide setting for that, so its user config and every worktree of the
  # repo are checked. (~/.gemini/config/hooks.json is Orca's status hook once Orca has started
  # an agy session.)
  local path tree
  for path in "${HOME}/.gemini/config/mcp_config.json" "${HOME}/.gemini/config/plugins" \
    "${HOME}/.gemini/settings.json"; do
    [ ! -e "${path}" ] || fail "${path} exists: agy would load MCP servers or plugins from it"
  done
  while read -r tree; do
    for path in "${tree}/.agents/mcp_config.json" "${tree}/.agents/plugins" "${tree}/.agents/hooks.json"; do
      [ ! -e "${path}" ] || fail "${path} exists: agy would load MCP servers, plugins or hooks from it"
    done
  done < <(git -C "${REPO_DIR}" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')
  ok "Antigravity CLI $(agy_version): no MCP server, plugin or workspace hook, in its config or the repo's worktrees"
}

dsh_version() { "${HOME}/.local/bin/dsh" --version 2>/dev/null </dev/null | head -n 1; }
pnpm_version() { "${HOME}/.local/bin/pnpm" --version 2>/dev/null </dev/null | head -n 1; }
dsh_tui_version() {
  "${HOME}/.local/bin/dsh-tui" version 2>/dev/null </dev/null | sed -n 's/^profile: \([^ ]*\).*/\1/p'
}

cmd_dsh() {
  npm_user_prefix
  if ! version_ge "$(pnpm_version)" "${PNPM_VERSION}"; then
    npm_pinned "pnpm@${PNPM_VERSION}" "${PNPM_INTEGRITY}"
    npm install -g --strict-allow-scripts "pnpm@${PNPM_VERSION}"
  fi
  if ! version_ge "$(dsh_version)" "${DSH_VERSION}"; then
    npm_pinned "@deepseek-ai/dsh@${DSH_VERSION}" "${DSH_INTEGRITY}"
    npm install -g --strict-allow-scripts --allow-scripts="${DSH_ALLOW_SCRIPTS}" "@deepseek-ai/dsh@${DSH_VERSION}"
  fi
  dsh_home_files
  if ! version_ge "$(dsh_tui_version)" "${DSH_TUI_VERSION}"; then
    npm_pinned "@deepseek-harness-tui/dsh-tui@${DSH_TUI_VERSION}" "${DSH_TUI_INTEGRITY}"
    # The TUI lives in its own dsh profile; the global copy is the launcher on PATH (dsh-tui, dst).
    "${HOME}/.local/bin/dsh" plugin --profile dsh-tui add "@deepseek-harness-tui/dsh-tui@${DSH_TUI_VERSION}" </dev/null
    npm_pinned "@deepseek-ai/dsh-hooks-claude-code@${DSH_VERSION}" "${DSH_HOOKS_INTEGRITY}"
    npm_pinned "@deepseek-ai/dsh-hook-protocol@${DSH_VERSION}" "${DSH_HOOK_PROTOCOL_INTEGRITY}"
    "${HOME}/.local/bin/dsh" plugin --profile dsh-tui add \
      "@deepseek-ai/dsh-hooks-claude-code@${DSH_VERSION}" "@deepseek-ai/dsh-hook-protocol@${DSH_VERSION}" </dev/null
    npm install -g --strict-allow-scripts --legacy-peer-deps "@deepseek-harness-tui/dsh-tui@${DSH_TUI_VERSION}"
  fi
  check_dsh
}

dsh_home_files() {
  # Both are written once and left alone afterwards: Orca appends its own marked hooks block to
  # cordis.patch.yml, and the TUI's updater edits the profile's pnpm-workspace.yaml.
  local profile="${HOME}/.dsh/profiles/dsh-tui"
  install -d -m 0700 "${HOME}/.dsh" "${HOME}/.dsh/profiles" "${profile}"
  if [ ! -e "${profile}/pnpm-workspace.yaml" ]; then
    # Written before the profile exists, because dsh keeps an existing file. The first lines are
    # what dsh itself would write; allowBuilds is what the TUI's own updater seeds. No
    # minimumReleaseAge: under pnpm's default a release younger than a day still installs and is
    # recorded under minimumReleaseAgeExclude, which fits keeping the agent tools current.
    cat > "${profile}/pnpm-workspace.yaml" <<'YAML'
packages:
  - .

nodeLinker: hoisted
autoInstallPeers: false
allowBuilds:
  '@google/genai': false
  esbuild: false
  koffi: false
  protobufjs: false
YAML
  fi
  if [ ! -e "${HOME}/.dsh/cordis.patch.yml" ]; then
    cat > "${HOME}/.dsh/cordis.patch.yml" <<'YAML'
# DeepSeek Harness home patch layer, written by deploy/wsl/setup.sh dsh (see UPSTREAM.md).
# Off: the session-log and plugin-inventory uploads to DeepSeek, and the OTel feedback upload.
# Block-sequence style on purpose: Orca appends its own marked hooks block to this file.
- id: session-log-deepseek
  config:
    enabled: false
- id: plugin-package-inventory-deepseek
  config:
    enabled: false
- id: session-telemetry-otel
  config:
    mode: DISABLED
YAML
    chmod 0600 "${HOME}/.dsh/cordis.patch.yml"
  fi
}

# dsh_row CONFIG ID: the lines of one row of `dsh --dump-config`, up to the next row.
dsh_row() { printf '%s\n' "$1" | awk -v id="- id: $2" '$0 == id { f = 1; next } /^- / { f = 0 } f'; }

check_dsh() {
  version_ge "$(dsh_version)" "${DSH_VERSION}" \
    || fail "DeepSeek Harness is older than ${DSH_VERSION} or missing (run: deploy/wsl/setup.sh dsh)"
  version_ge "$(dsh_tui_version)" "${DSH_TUI_VERSION}" \
    || fail "dsh-tui is older than ${DSH_TUI_VERSION} or not installed in its profile"
  local config row
  config="$("${HOME}/.local/bin/dsh" --profile dsh-tui --dump-config </dev/null 2>/dev/null)" \
    || fail "dsh cannot build its configuration for the dsh-tui profile"
  for row in session-log-deepseek plugin-package-inventory-deepseek; do
    dsh_row "${config}" "${row}" | grep -qx '    enabled: false' || fail "the ${row} upload is not off"
  done
  dsh_row "${config}" session-telemetry-otel | grep -qx '    mode: DISABLED' \
    || fail "the OTel feedback upload is not off"
  # The profile ships the plugin manager's agent tools switched off; an agent could install
  # plugins with them.
  dsh_row "${config}" tool-plugin-manager | grep -qx '  disabled: true' \
    || fail "the plugin manager's tools are on in the dsh-tui profile"
  ok "DeepSeek Harness $(dsh_version) with dsh-tui $(dsh_tui_version): uploads to DeepSeek off, no plugin tools"
}

orca_cli() { "${ORCA_ROOT}/current/bin/orca-ide" "$@" </dev/null; }
orca_version() { orca_cli --version 2>/dev/null | head -n 1; }

cmd_orca() {
  local dir="${ORCA_ROOT}/${ORCA_VERSION}" tmp
  local dropins="${HOME}/.config/systemd/user/orca-serve.service.d"
  if [ ! -x "${dir}/bin/orca-ide" ]; then
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/orca-server.tar.gz" \
      "https://github.com/stablyai/orca/releases/download/v${ORCA_VERSION}/orca-server-linux-x64.tar.gz"
    echo "${ORCA_SHA256}  ${tmp}/orca-server.tar.gz" | sha256sum -c -
    sudo install -d -m 0755 "${dir}"
    sudo tar -xzf "${tmp}/orca-server.tar.gz" -C "${dir}" --strip-components=1 --no-same-owner
    rm -rf "${tmp}"
  fi
  sudo ln -sfn "${dir}" "${ORCA_ROOT}/current"
  ln -sfn "${ORCA_ROOT}/current/bin/orca-ide" "${HOME}/.local/bin/orca-ide"
  # ORCA_UNIT_ENV, as a drop-in, so `service install` keeps it. A change reaches agents only once
  # the terminal daemon restarts (its scope outlives a restart of the service), which ends the
  # sessions running in it.
  install -d "${dropins}"
  { echo '[Service]'; printf 'Environment=%s\n' "${ORCA_UNIT_ENV[@]}"; } > "${dropins}/meridian.conf"
  # Lingering starts the user service at boot without a login session. WSL still stops the whole
  # distro about 15 s after its last WSL session ends (instanceIdleTimeout in the owner's
  # .wslconfig on Windows); keeping it up is the owner's setting there (see UPSTREAM.md).
  [ "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes ] || sudo loginctl enable-linger "$(id -un)"
  # This writes the unit, reloads systemd and restarts the service.
  orca_cli serve service install --command "${ORCA_ROOT}/current/bin/orca-ide" \
    --port "${ORCA_PORT}" --bind 127.0.0.1 --pairing-address 127.0.0.1 --refuse-public
  orca_wait
  check_orca
}

# orca_wait: up to 30 s for a server that was just started to answer.
orca_wait() {
  local _
  for _ in $(seq 30); do
    orca_cli status --json 2>/dev/null | jq -e '.result.runtime.reachable == true' >/dev/null && return 0
    sleep 1
  done
}

cmd_orca_pair() {
  # The owner's one-time step that gives the Windows app access. `orca-ide pair` would first
  # open the server to the network, which the loopback-only service refuses, so the pairing link
  # comes from one foreground run on loopback instead, with the service's environment. The link
  # grants shell access as the owner: it is printed to this terminal only, never to a terminal
  # Orca started, whose output other Orca sessions can read (`orca-ide terminal read`).
  [ -t 0 ] && [ -t 1 ] || fail "run this in your own terminal: it prints a pairing link"
  [ "${TERM_PROGRAM:-}" != Orca ] && [ -z "${ORCA_TERMINAL_HANDLE:-}" ] \
    || fail "run this in Windows Terminal (wsl -d meridian), not in a terminal Orca started"
  systemctl --user stop orca-serve.service
  # However this ends (Ctrl+C, a closed window, a kill), the service starts again.
  trap 'systemctl --user start orca-serve.service' EXIT
  trap 'exit 129' HUP
  trap 'exit 143' TERM
  echo "Paste the pairing link below into the Windows app (Settings > Remote Orca Servers >"
  echo "Add Server), connect, then press Ctrl+C here to hand back to the service."
  trap 'true' INT
  env "${ORCA_UNIT_ENV[@]}" "${ORCA_ROOT}/current/bin/orca-ide" serve --port "${ORCA_PORT}" \
    --bind 127.0.0.1 --pairing-address 127.0.0.1 --refuse-public || true
  trap - INT
  systemctl --user start orca-serve.service
  orca_wait
  check_orca
}

check_orca() {
  version_ge "$(orca_version)" "${ORCA_VERSION}" \
    || fail "the Orca server is older than ${ORCA_VERSION} or missing (run: deploy/wsl/setup.sh orca)"
  systemctl --user is-active --quiet orca-serve.service || fail "the orca-serve user service is not running"
  local listeners pids exposed unit_env var
  listeners="$(ss -ltnH "( sport = :${ORCA_PORT} )" | awk '{print $4}' | sort -u | tr '\n' ' ')"
  [ "${listeners}" = "127.0.0.1:${ORCA_PORT} " ] \
    || fail "Orca must listen on 127.0.0.1:${ORCA_PORT} only; found: ${listeners:-nothing}"
  # Every other TCP or UDP socket of Orca's processes must be loopback too: the service, its
  # terminal daemon's scope, and the slices its terminals, and so every agent, run in.
  pids="$(grep -lE '/(orca-serve\.service|orca-daemon-[^/]*\.scope|orca_ptys_[^/]*\.slice)(/|$)' \
    /proc/[0-9]*/cgroup 2>/dev/null | cut -d/ -f3 | paste -sd'|' || true)"
  exposed="$(ss -ltunpH | grep -E "pid=(${pids:-0})," | awk '{print $1 " " $5}' \
    | grep -v -E ' (127\.[0-9.]+|\[::1\])(%[^:]*)?:' | tr '\n' ' ' || true)"
  [ -z "${exposed}" ] || fail "an Orca process or agent listens beyond loopback: ${exposed}"
  unit_env="$(systemctl --user show orca-serve.service -p Environment --value | tr ' ' '\n')"
  for var in "${ORCA_UNIT_ENV[@]}"; do
    grep -qxF -- "${var}" <<<"${unit_env}" \
      || fail "the orca-serve unit does not set ${var} (run: deploy/wsl/setup.sh orca)"
  done
  orca_cli status --json 2>/dev/null | jq -e '.result.runtime.reachable == true' >/dev/null \
    || fail "orca-ide status cannot reach the server"
  ok "Orca server $(orca_version) on 127.0.0.1:${ORCA_PORT} only, telemetry off, DeepSeek endpoints fixed"
}

cmd_signins() {
  # What only the owner can do, with the exact command for each. Nothing secret is read: the
  # checks use exit codes and file presence only.
  local bin="${HOME}/.local/bin"
  say() { if eval "$1" >/dev/null 2>&1 </dev/null; then echo "done   $2"; else echo "to do  $2: $3"; fi; }
  say "${bin}/gh auth status" "GitHub" "gh auth login"
  say "${bin}/claude auth status" "Claude Code" "claude auth login"
  say "${bin}/codex login status" "Codex" "codex login --device-auth"
  say "[ -e ${HOME}/.gemini/antigravity-cli/antigravity-oauth-token ]" "Antigravity" \
    "agy acp --login   (then in agy: /config, telemetry off; agy models)"
  say "[ -s ${HOME}/.dsh/.env ]" "DeepSeek API key" \
    "install -d -m 700 ~/.dsh && ( umask 077 && read -rsp 'DeepSeek API key: ' k && echo && printf 'DEEPSEEK_API_KEY=%s\\n' \"\$k\" > ~/.dsh/.env && unset k )"
  echo "once   Orca window, in Windows Terminal: deploy/wsl/setup.sh orca-pair   (the link it prints grants shell access: paste it only into the Windows app)"
}

cmd_repo() {
  if [ ! -d "${REPO_DIR}/.git" ]; then
    gh auth status >/dev/null 2>&1 || fail "sign in first: gh auth login"
    mkdir -p "$(dirname "${REPO_DIR}")"
    gh repo clone "${REPO}" "${REPO_DIR}"
  fi
  cd "${REPO_DIR}"
  if [ -f pyproject.toml ]; then
    "${HOME}/.local/bin/uv" sync --locked
  fi
}

cmd_gateway() {
  # Unattended install4j run (-q) into a fixed directory. No sudo. It does not start the
  # Gateway: the owner starts it and logs in to Paper Trading.
  [ ! -e "${GATEWAY_DIR}" ] || fail "already installed: ${GATEWAY_DIR}"
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSLo "${tmp}/ibgateway.sh" "${GATEWAY_URL}"
  echo "${GATEWAY_SHA256}  ${tmp}/ibgateway.sh" | sha256sum -c -
  chmod u+x "${tmp}/ibgateway.sh"
  (cd "${tmp}" && ./ibgateway.sh -q -dir "${GATEWAY_DIR}")
  rm -rf "${tmp}"
  [ -x "${GATEWAY_DIR}/ibgateway" ] || fail "the Gateway launcher is missing after the install"
  ok "IB Gateway ${GATEWAY_VERSION} in ${GATEWAY_DIR}"
  echo "start it with: ${GATEWAY_DIR}/ibgateway   (then log in to Paper Trading yourself)"
}

case "${1:-}" in
  check) cmd_check ;;
  uv) cmd_uv ;;
  gh) cmd_gh ;;
  claude) cmd_claude ;;
  codex) cmd_codex ;;
  agy) cmd_agy ;;
  dsh) cmd_dsh ;;
  orca) cmd_orca ;;
  codex-bridge) cmd_codex_bridge ;;
  agents)
    cmd_claude
    cmd_codex
    cmd_agy
    cmd_dsh
    cmd_orca
    cmd_codex_bridge
    ;;
  signins) cmd_signins ;;
  orca-pair) cmd_orca_pair ;;
  agents-check)
    check_gh
    check_claude
    check_codex
    check_agy
    check_dsh
    check_orca
    check_codex_bridge
    ;;
  repo) cmd_repo ;;
  gateway) cmd_gateway ;;
  *) sed -n '2,22p' "$0"; exit 2 ;;
esac
