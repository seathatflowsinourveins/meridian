#!/usr/bin/env bash
# meridian: user-level setup inside the distro, after cloud-init has finished.
# Run as the owner user, never as root.
#
#   deploy/wsl/setup.sh check         verify what deploy/wsl/meridian.user-data was meant to do
#   deploy/wsl/setup.sh uv            install uv (pinned; installer checksum verified first)
#   deploy/wsl/setup.sh gh            install the GitHub CLI from GitHub's release, in place of Ubuntu's
#   deploy/wsl/setup.sh gitleaks      install the pinned gitleaks CI uses, for the lead's merge gate
#   deploy/wsl/setup.sh ocr           install open-code-review's `ocr`, a second reviewer's file list and rules
#   deploy/wsl/setup.sh repo          clone the repo to ~/src/meridian and run `uv sync --locked`
#   deploy/wsl/setup.sh gateway       install IB Gateway (pinned build; never starts it or logs in)
#   deploy/wsl/setup.sh agents        all of the following, in this order:
#     claude        Claude Code, from Anthropic's signed release manifest
#     codex         Codex CLI and its worker stack, ADR 0018 (npm, a local plugin marketplace)
#     agy           Antigravity CLI (its GitHub release asset)
#     dsh           DeepSeek Harness and the terminal UI Orca launches for it (npm, pnpm)
#     orca          Orca server, a loopback-only systemd user service (sudo for /opt)
#     codex-bridge  the Codex review plugin for Claude Code
#     claude-hud    the claude-hud status line for Claude Code, beside Orca's usage reporter
#     omc           Claude lifecycle in user scope (also called by claude); ADR 0019
#     omc-remove    remove only Meridian-owned OMC assets; retain other Claude settings
#   deploy/wsl/setup.sh agents-check  verify the agent runtimes and their settings
#   deploy/wsl/setup.sh drift         installed against pinned; exit 0 when upkeep is due (changes nothing)
#   deploy/wsl/setup.sh upkeep        bring this machine to the pins, Orca's server last (not while
#                                     ~/.cache/meridian/upkeep.hold holds a reason)
#   deploy/wsl/setup.sh orca-automation  the weekly Orca automation that moves the pins, lands and applies them
#   deploy/wsl/setup.sh codex-requirements  write /etc/codex/requirements.toml from meridian.user-data (sudo)
#   deploy/wsl/setup.sh signins       list the sign-ins left for the owner, with their commands
#   deploy/wsl/setup.sh orca-pair     owner, once, in Windows Terminal: pair the Windows Orca app
#   deploy/wsl/setup.sh unattended    (sudo) install or update the unattended Alpaca lane; timers enabled once
#   deploy/wsl/setup.sh unattended-check  its units, timers, last results and hold file (read only)
#
# Order: check, uv, gh, gitleaks, ocr, repo, gateway, then agents. Sign-ins are the owner's: see UPSTREAM.md.
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
# The same build and checksum as .github/workflows/ci.yml (tests/test_agent_config.py compares them).
GITLEAKS_VERSION=8.30.1
GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
GITLEAKS_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
# open-code-review (ADR 0020), the release binary by its SHA-256 from the release's sha256sum.txt.
# Not the npm package: its wrapper installs the newest release over itself in the background.
OCR_VERSION=1.13.9
OCR_SHA256=2db294981624d6fae9bcfb4df7f9ebfd7f92c40b3a552873dff5887116931d3e
OCR_URL="https://github.com/alibaba/open-code-review/releases/download/v${OCR_VERSION}/opencodereview-linux-amd64"

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
CLAUDE_VERSION=2.1.325
CLAUDE_SHA256=0dc4f4a9a165fc60746d7ae8489712e5fc352f1e7ad4eb22e7141bd0812eb0cf
CLAUDE_RELEASE_SIGNER=31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE
CLAUDE_RELEASES=https://downloads.claude.ai/claude-code-releases
CLAUDE_MODEL=claude-fable-5-2
# ADR 0019: standalone lifecycle, no plugin/MCP registration or OMC HUD.
OMC_VERSION=5.8.4
OMC_INTEGRITY=sha512-6J2v4YomI8vK4mmhDTMV8SqS2Bj4dUvPz3ApapKsYVN6P04rGs0/L78p3/Rda0mq1UuHOYII8ubj+ehlgmxxwA==
# Codex CLI: OpenAI's npm package and its linux-x64 build, by their registry integrity values.
CODEX_VERSION=0.169.0
CODEX_INTEGRITY=sha512-KhzYlkKPxoNssR8CEm45IjqnFWn7UtlF4CiD3tOJPea51xBs7MaHy0UQG9GSbCqk6Lrjn5QdJDV0QD1/FgWlGw==
CODEX_LINUX_INTEGRITY=sha512-o05NyAOCDygSPRo1yinzxvkRSdmsZyBD9E7mbpmjRanSfM8lypqWtQgEo4XfNkwhuCR2aFu8mlGOsQGFXVbVww==
CODEX_MODEL=gpt-6-astra
# The Codex worker stack (ADR 0018). oh-my-codex by npm's integrity value; ponytail at its v5.3.3
# release commit, served from a local marketplace; OpenAI's docs server at the URL and name that
# Codex's own openai-docs skill uses. /etc/codex/requirements.toml allows that server by name.
OMX_VERSION=0.22.6
OMX_INTEGRITY=sha512-ZpMHipwnaiHV/T8rp/czmF5U+ugqVdUOb28obL5U61q9WQwvfKAmzP4k1V82EnUXYMvsBgZIzFl0I3HADBbFEQ==
PONYTAIL_COMMIT=7801d061243d7b753bad0e0b3c057cd250b11755
PONYTAIL_MARKET=meridian-ponytail
CODEX_DOCS_MCP=https://developers.openai.com/mcp
# serena (code navigation and diagnostics over MCP): PyPI's file by its SHA-256, then uv installs
# that release (its dependencies resolve on the day of the install). Only these tools are served,
# and Codex starts it with exactly these arguments; the requirements name its command, `serena`.
SERENA_VERSION=2.1.0
SERENA_FILE=serena_agent-2.1.0-py3-none-any.whl
SERENA_SHA256=cc6ae542c39b4de5d98cdf35a4ceb0b551f316c5f22e9d0f0b0c5f35d6b95d87
SERENA_TOOLS="get_symbols_overview, find_symbol, find_referencing_symbols, find_implementations, find_declaration, get_diagnostics_for_file, get_diagnostics_for_symbol"
SERENA_MCP_ARGS='["start-mcp-server", "--project-from-cwd", "--context=codex"]'
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
# The session model (plan 8.8: DeepSeek V4.1 Flash, which DeepSeek serves as `deepseek-flash`).
# It is dsh-base's own default today; the pin keeps it if that default moves.
DSH_MODEL=deepseek-flash
# The only install scripts dsh's tree may run (terminal, FFI, its process helper, two SDKs).
DSH_ALLOW_SCRIPTS=node-pty,koffi,@deepseek-ai/dsh-subprocess-local,@google/genai,protobufjs
# DeepSeek Harness's worker stack (docs/adr/0016-dsh-worker-stack.md), for dsh only. None of
# these updates itself: a new pin here updates it.
# Skills: "repository commit folder...", each at the commit of the repository's latest release
# tag, copied to ~/.dsh/skills/<folder name>. Every file of each folder was read at its pin.
DSH_SKILLS=(
  "addyosmani/agent-skills 8bfcc1f9916f2eea55494d8c1fa7f4bde867dd9e skills/spec-driven-development skills/code-review-and-quality skills/source-driven-development"
  "obra/superpowers 22f0b463e7a5e579904dd6211a520321035526f7 skills/test-driven-development skills/systematic-debugging skills/verification-before-completion"
  "mattpocock/skills d1478fcb140db0b93c0c8df17bcfd311844749d0 skills/engineering/research skills/engineering/pr"
)
# Code navigation: DeepSeek's own LSP packages at the engine's version (the seam, the stdio
# provider that runs each worktree's own pyright-langserver, and the read-only `lsp` tool),
# installed in the dsh-tui profile. Registry integrity values.
DSH_LSP_INTEGRITY=sha512-pEh5ErmCK52WJjOrKWQne1ojdImjf9zLNAclaCI4uOwEB8tdGwuXHSNud16gVHSID+0PdK2nm6dJjZNgfp47ig==
DSH_LSP_STDIO_INTEGRITY=sha512-2lC3pw/DyNkOLT42POj48J02L+2JBM3HJJQts467B/JrTEOJwc29gDYEzhID3mceePMrO/n/K1duVLS/So3mXw==
DSH_TOOL_LSP_INTEGRITY=sha512-y+OHzHOcvh3mCHMZ8bbICxPZjNBhKeCFBfDffR4GkNlT7DHcOeyzwa0mX9XBnJ7dbaAGCbZ8PQZO5EhOSmtOGw==
# ast-grep and agentsview: GitHub release assets, by the SHA-256 digest GitHub shows for each.
AST_GREP_VERSION=0.51.2
AST_GREP_SHA256=40604c21c38d4c7581c56bdddeef277c56bf3c0113620aa96e78ae87e82366df
AST_GREP_URL="https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-x86_64-unknown-linux-gnu.zip"
AGENTSVIEW_VERSION=0.47.0
AGENTSVIEW_SHA256=a49876edf9fe8d0641978afe69d776540175852a446a5d42a6d439215eb0dc45
AGENTSVIEW_URL="https://github.com/kenn-io/agentsview/releases/download/v${AGENTSVIEW_VERSION}/agentsview_${AGENTSVIEW_VERSION}_linux_amd64.tar.gz"
# Orca server: the server-only release tarball (orcad, its own Node, the orca-ide CLI), by the
# SHA-256 in the release's checksum file. It does not update itself; a new pin here updates it.
ORCA_VERSION=1.4.258
ORCA_SHA256=fd7f23f5fb6fe43fb2982d17438d772fac7cc65c8208a212d0ffb224b504e311
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
# Claude Code status line (ADR 0015): jarrodwatts/claude-hud at a tag and its commit, the last
# release signed by its maintainer. It does not follow upstream: later releases are cut by an
# unattended bot. A new pin here moves it.
CLAUDE_HUD_REF=v0.15.0
CLAUDE_HUD_VERSION=0.15.0
CLAUDE_HUD_COMMIT=b86e1c3e5255880578de4b7cc87dc383228c2a18
# Antigravity CLI (`agy`): the GitHub release asset of this version, by the SHA-256 digest
# GitHub shows for it. (Google's install.sh and agy's own updater take the build named in their
# updater service's manifest instead, checked against the SHA-512 in that manifest.)
AGY_VERSION=1.5.8
AGY_SHA256=905d4accfbd61bc00bee84bfaf24c59b85d334cabd786cf99237b66cfe06ab98
AGY_URL="https://github.com/google-antigravity/antigravity-cli/releases/download/${AGY_VERSION}/agy_cli_linux_x64.tar.gz"
# agy's default model, by the label `agy models` prints (plan 8.8: Gemini 4 Carbon, at its
# highest effort). A label agy no longer offers falls back to its own default, with a warning.
AGY_MODEL='Gemini 4 Carbon (High)'

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
USER_DATA="$(dirname "$(readlink -f "$0")")/meridian.user-data"
# The unattended Alpaca lane (M7): release, settings, state and units, as deploy/systemd/ names
# them. MERIDIAN_FAKE_ROOT is for tests only: a folder that stands in for /, with fake sudo,
# systemctl and uv first on PATH. Unset, every path below is the real one.
UA_ROOT="${MERIDIAN_FAKE_ROOT:-}"
UNATTENDED_ROOT="${UA_ROOT}/opt/meridian"
UNATTENDED_CONFIG="${UA_ROOT}/etc/meridian-alpaca-paper"
UNATTENDED_STATE="${UA_ROOT}/var/lib/meridian-alpaca-paper"
UNATTENDED_UNIT_DIR="${UA_ROOT}/etc/systemd/system"
UNATTENDED_UNITS="meridian-alpaca-paper@.service meridian-alpaca-restart.timer meridian-alpaca-order.timer"
UNATTENDED_TIMERS="meridian-alpaca-restart.timer meridian-alpaca-order.timer"

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

# pypi_pinned PACKAGE VERSION FILE SHA256: PyPI serves FILE for that release with that digest.
pypi_pinned() {
  curl -fsS "https://pypi.org/pypi/$1/$2/json" | python3 -I -c '
import json, sys
files = {f["filename"]: f["digests"]["sha256"] for f in json.load(sys.stdin)["urls"]}
sys.exit(0 if files.get(sys.argv[1]) == sys.argv[2] else 1)' "$3" "$4" \
    || fail "$1 $2 on PyPI is not the pinned build"
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
  ok "Codex: ChatGPT apps off and only the MCP servers ADR 0018 names, machine-wide"
  for source in linux wsl_setup ubuntu_release_upgrader; do
    ubuntu-insights consent "${source}" 2>/dev/null | grep -qx "${source}: false" \
      || fail "Ubuntu Insights consent for ${source} is not recorded as false"
  done
  for timer in ubuntu-insights-collect.timer ubuntu-insights-upload.timer; do
    [ "$(systemctl --user is-enabled "${timer}" 2>/dev/null)" != enabled ] \
      || fail "${timer} is enabled"
  done
  ok "Ubuntu Insights declined, its timers off"
  case "$(systemctl is-enabled wsl-pro.service 2>/dev/null)" in
    enabled*) fail "wsl-pro.service is enabled (it looks for an Ubuntu Pro agent on Windows that is not installed)" ;;
  esac
  case "$(systemctl is-active wsl-pro.service 2>/dev/null)" in
    inactive | failed) ;;
    *) fail "wsl-pro.service is running or waiting to restart" ;;
  esac
  ok "wsl-pro.service off"
  check_unattended
}

check_unattended() {
  # One read-only line for `check`; not installed is not a failure. Details: unattended-check.
  if [ ! -L "${UNATTENDED_ROOT}/current" ]; then
    echo "note: the unattended Alpaca lane is not installed (deploy/wsl/setup.sh unattended)"
    return
  fi
  local timer states=""
  for timer in ${UNATTENDED_TIMERS}; do
    states="${states} ${timer}=$(systemctl is-active "${timer}" 2>/dev/null || true)"
  done
  ok "unattended Alpaca lane: release $(basename "$(readlink "${UNATTENDED_ROOT}/current")");${states}"
}

cmd_unattended() {
  # Non-interactive and idempotent: a second run at the same commit changes nothing. Installs
  # the checked-out commit, the settings and rows files from the templates if absent (values
  # null; it never sets one, consent included), the state directory and the units. It enables
  # and starts a timer only on its first install: an update leaves a timer the owner disabled or
  # stopped as it is. It reads no credential and starts no lane run itself.
  local src commit release cache name timer link state changed=0
  src="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
  [ -z "$(git -C "${src}" status --porcelain)" ] || fail "the checkout has uncommitted changes"
  id paper >/dev/null 2>&1 || fail "service user 'paper' is missing"
  commit="$(git -C "${src}" rev-parse HEAD)"
  release="${UNATTENDED_ROOT}/releases/${commit}"
  # A release counts only once its marker exists, written last, after a successful sync: a
  # failed sync leaves no marker, so a rerun synchronises again before anything is activated.
  if [ ! -e "${release}/.meridian-release-complete" ]; then
    sudo install -d -m 0755 "${release}"
    git -C "${src}" archive "${commit}" | sudo tar -x -C "${release}" --no-same-owner
    cache="$(mktemp -d)"
    # The interpreter goes under /opt too: `paper` cannot read a home (ProtectHome=yes).
    sudo env UV_CACHE_DIR="${cache}" UV_PYTHON_INSTALL_DIR="${UNATTENDED_ROOT}/python" \
      "${HOME}/.local/bin/uv" sync --locked --no-default-groups --managed-python --project "${release}"
    sudo rm -rf "${cache}"
    sudo touch "${release}/.meridian-release-complete"
  fi
  [ "$(readlink "${UNATTENDED_ROOT}/current" || true)" = "${release}" ] \
    || sudo ln -sfn "${release}" "${UNATTENDED_ROOT}/current"
  ok "release ${commit} in ${UNATTENDED_ROOT}/current"
  [ -d "${UNATTENDED_CONFIG}" ] || sudo install -d -o root -g paper -m 0750 "${UNATTENDED_CONFIG}"
  for name in alpaca-lane alpaca-order-budget; do
    sudo test -e "${UNATTENDED_CONFIG}/${name}.json" || sudo install -o root -g paper -m 0640 \
      "${release}/deploy/${name}.template.json" "${UNATTENDED_CONFIG}/${name}.json"
  done
  ok "settings in ${UNATTENDED_CONFIG}: root-owned, read by paper; values are filled there"
  [ -d "${UNATTENDED_STATE}" ] || sudo install -d -o paper -g paper -m 0700 "${UNATTENDED_STATE}"
  for name in ${UNATTENDED_UNITS}; do
    cmp -s "${release}/deploy/systemd/${name}" "${UNATTENDED_UNIT_DIR}/${name}" && continue
    sudo install -m 0644 "${release}/deploy/systemd/${name}" "${UNATTENDED_UNIT_DIR}/${name}"
    changed=1
  done
  [ "${changed}" = 0 ] || sudo systemctl daemon-reload
  # No [Install] section in the units: the wants link is added here, on the first install only
  # (systemctl(1)), and a marker under /opt records it once both steps succeeded. On an update a
  # timer the owner stopped with `systemctl disable --now` stays disabled and stopped.
  for timer in ${UNATTENDED_TIMERS}; do
    if [ ! -e "${UNATTENDED_ROOT}/timers-enabled/${timer}" ]; then
      [ -L "${UNATTENDED_UNIT_DIR}/timers.target.wants/${timer}" ] \
        || sudo systemctl add-wants timers.target "${timer}"
      sudo systemctl start "${timer}"
      sudo install -D -m 0644 /dev/null "${UNATTENDED_ROOT}/timers-enabled/${timer}"
      ok "${timer}: first install, enabled and started (stop: sudo systemctl disable --now ${timer})"
    else
      link=disabled
      [ -L "${UNATTENDED_UNIT_DIR}/timers.target.wants/${timer}" ] && link=enabled
      state="$(systemctl is-active "${timer}" 2>/dev/null || true)"
      ok "${timer}: update, left as it is (${link}, ${state:-unknown})"
    fi
  done
  cmd_unattended_check
}

cmd_unattended_check() {
  # Read only: unit files, timers, the services' last results and the hold file's presence. It
  # reads no credential and no settings value.
  local name timer mode service hold
  if [ -L "${UNATTENDED_ROOT}/current" ]; then
    echo "release: $(basename "$(readlink "${UNATTENDED_ROOT}/current")")"
  else
    echo "release: not installed"
  fi
  for name in ${UNATTENDED_UNITS}; do
    if [ ! -e "${UNATTENDED_UNIT_DIR}/${name}" ]; then
      echo "${name}: not installed"
    elif cmp -s "${UNATTENDED_ROOT}/current/deploy/systemd/${name}" "${UNATTENDED_UNIT_DIR}/${name}"; then
      echo "${name}: installed"
    else
      echo "${name}: installed, differs from the release"
    fi
  done
  for timer in ${UNATTENDED_TIMERS}; do
    if [ -L "${UNATTENDED_UNIT_DIR}/timers.target.wants/${timer}" ]; then
      echo "${timer}: enabled, $(systemctl is-active "${timer}" 2>/dev/null || true), next $(systemctl show -p NextElapseUSecRealtime --value "${timer}" 2>/dev/null || true)"
    else
      echo "${timer}: not enabled"
    fi
  done
  for mode in restart order; do
    service="meridian-alpaca-paper@${mode}.service"
    echo "${service}: last result $(systemctl show -p Result --value "${service}" 2>/dev/null || true), exit status $(systemctl show -p ExecMainStatus --value "${service}" 2>/dev/null || true), at $(systemctl show -p ExecMainExitTimestamp --value "${service}" 2>/dev/null || true)"
  done
  if ! sudo -n test -d "${UNATTENDED_STATE}" 2>/dev/null; then
    hold="unknown (no state directory, or no sudo)"
  elif sudo -n test -e "${UNATTENDED_STATE}/hold"; then
    hold="PRESENT: unattended orders refuse until the owner removes it"
  else
    hold="none"
  fi
  echo "hold file: ${hold}"
  if sudo -n test -e "${UNATTENDED_STATE}/run-marker" 2>/dev/null; then
    echo "run marker: PRESENT (a run is active, or one crashed or was killed; order refuses)"
  fi
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

# gh with its telemetry off for this call as well (GH_TELEMETRY outranks gh's config file).
gh_cli() { GH_TELEMETRY=0 "${HOME}/.local/bin/gh" "$@" </dev/null; }
gh_version() { gh_cli --version 2>/dev/null | sed -n 's/^gh version \([^ ]*\).*/\1/p'; }
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
  # This gh sends usage telemetry by default, and `gh auth login` reports every run. Off in its
  # config file, which every gh run as the owner reads; the random id it keeps for it goes too.
  [ "$(gh_cli config get telemetry 2>/dev/null)" = disabled ] || gh_cli config set telemetry disabled
  rm -f "${HOME}/.local/state/gh/device-id"
  check_gh
}

check_gh() {
  version_ge "$(gh_version)" "${GH_VERSION}" \
    || fail "the GitHub CLI is older than ${GH_VERSION} or missing (run: deploy/wsl/setup.sh gh)"
  [ "$(command -v gh)" = "${HOME}/.local/bin/gh" ] \
    || fail "gh resolves to $(command -v gh || echo nothing), not ~/.local/bin/gh"
  [ "$(gh_package_state)" != installed ] \
    || fail "Ubuntu's gh package is installed (run: deploy/wsl/setup.sh gh)"
  [ "$(gh_cli config get telemetry 2>/dev/null)" = disabled ] \
    || fail "gh's telemetry is not disabled (run: deploy/wsl/setup.sh gh)"
  ok "GitHub CLI $(gh_version), GitHub's own build in ~/.local/bin, telemetry off; no Ubuntu gh package"
}

# The release build prints its bare version (`gitleaks version`; goreleaser's {{.Version}}).
gitleaks_version() { "${HOME}/.local/bin/gitleaks" version 2>/dev/null </dev/null | head -n 1 | sed 's/^v//'; }

cmd_gitleaks() {
  # The lead's merge gate runs it as the fifth check on the trial-merged tree, as CI does.
  if [ "$(gitleaks_version)" != "${GITLEAKS_VERSION}" ]; then
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/gitleaks.tar.gz" "${GITLEAKS_URL}"
    echo "${GITLEAKS_SHA256}  ${tmp}/gitleaks.tar.gz" | sha256sum -c -
    tar -xzf "${tmp}/gitleaks.tar.gz" -C "${tmp}" gitleaks
    install -D -m 0755 "${tmp}/gitleaks" "${HOME}/.local/bin/gitleaks"
    rm -rf "${tmp}"
  fi
  check_gitleaks
}

check_gitleaks() {
  [ "$(gitleaks_version)" = "${GITLEAKS_VERSION}" ] \
    || fail "gitleaks is not ${GITLEAKS_VERSION} in ~/.local/bin (run: deploy/wsl/setup.sh gitleaks)"
  [ "$(command -v gitleaks)" = "${HOME}/.local/bin/gitleaks" ] \
    || fail "gitleaks resolves to $(command -v gitleaks || echo nothing), not ~/.local/bin/gitleaks"
  ok "gitleaks ${GITLEAKS_VERSION} in ~/.local/bin, the build CI uses"
}

# open-code-review, in its delegation mode only: `ocr delegate preview` lists the files of a diff
# that a review has to cover and `ocr delegate rule` gives the rules for them; the reviewing
# agent reads the diff and writes the findings. That mode needs no model provider, key or
# account, so a provider configuration of its own is refused here (ADR 0020).
ocr_version() { "${HOME}/.local/bin/ocr" --version 2>/dev/null </dev/null | sed -n '1s/^open-code-review v\([^ ]*\).*/\1/p'; }

cmd_ocr() {
  if [ "$(ocr_version)" != "${OCR_VERSION}" ]; then
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/ocr" "${OCR_URL}"
    echo "${OCR_SHA256}  ${tmp}/ocr" | sha256sum -c -
    install -D -m 0755 "${tmp}/ocr" "${HOME}/.local/bin/ocr"
    rm -rf "${tmp}"
  fi
  check_ocr
}

check_ocr() {
  [ "$(ocr_version)" = "${OCR_VERSION}" ] \
    || fail "open-code-review is not ${OCR_VERSION} in ~/.local/bin (run: deploy/wsl/setup.sh ocr)"
  [ ! -e "${HOME}/.opencodereview/config.json" ] \
    || fail "~/.opencodereview/config.json exists: open-code-review runs here without a model provider of its own"
  ok "open-code-review ${OCR_VERSION} in ~/.local/bin, delegation mode only: no provider of its own"
}

claude_settings() {
  # Merged into the file, never written over it: Claude Code and Orca keep their own keys there.
  # Bypass mode is the owner's choice for this distro. The deny rules stop Claude Code's file
  # tools at the owner's files; a shell command can still reach them.
  # Display: thinking summaries in the conversation and the Ctrl+O transcript, a time on each
  # message, the fullscreen renderer. Compaction is left at Claude Code's defaults (the "auto"
  # window, idle compaction, precompute); check_claude refuses a file that switches one off.
  # autoCompactEnabled is written out because Claude Code still reads an old value of it from
  # ~/.claude.json when this file has none.
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
      showThinkingSummaries: true,
      showMessageTimestamps: true,
      tui: "fullscreen",
      autoCompactEnabled: true,
      enabledPlugins: {
        "codex@openai-codex": true,
        "cc-plugin-you-should-know@builtin": true,
        "claude-hud@claude-hud": true
      },
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
    cmd_omc
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
  cmd_omc
  check_claude
}

check_claude() {
  version_ge "$(claude_version)" "${CLAUDE_VERSION}" \
    || fail "Claude Code is older than ${CLAUDE_VERSION} or missing (run: deploy/wsl/setup.sh claude)"
  # Only Codex review (setup.sh codex-bridge), the built-in You should know and claude-hud
  # (setup.sh claude-hud) are allowed.
  jq -e --arg model "${CLAUDE_MODEL}" --arg floor "${CLAUDE_VERSION}" '
    .disableClaudeAiConnectors == true and .syncClaudeAiPlugins == false
    and .syncClaudeAiSkills == false and .minimumVersion == $floor
    and .autoUpdatesChannel == "latest"
    and .model == $model and .modelSettings[$model].effortLevel == "high"
    and .permissions.defaultMode == "bypassPermissions"
    and .skipDangerousModePermissionPrompt == true
    and .showThinkingSummaries == true and .showMessageTimestamps == true
    and .tui == "fullscreen"
    and .autoCompactEnabled == true
    and ([.idleCompaction, .precomputeCompactionEnabled, .autoContinueAtUsageLimit]
      | all(. != false))
    and (["Edit(//**/risk/**)", "Edit(//**/*.contract.json)", "Read(//**/.env)", "Read(//**/.env.*)"]
      - (.permissions.deny // []) == [])
    and ([.enabledPlugins // {} | to_entries[] | select(.value == true) | .key]
      - ["codex@openai-codex", "cc-plugin-you-should-know@builtin", "claude-hud@claude-hud"]
      == [])
  ' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "~/.claude/settings.json is not what deploy/wsl/setup.sh claude writes"
  check_claude_managed
  if [ -f "${HOME}/.claude/.meridian-omc-install.json" ]; then check_omc; fi
  ok "Claude Code $(claude_version): ${CLAUDE_MODEL} at high effort, no claude.ai connectors, sync or MCP server; thinking shown, fullscreen, compaction at its defaults"
}

cmd_omc() {
  npm_user_prefix
  npm_pinned "oh-my-claude-sisyphus@${OMC_VERSION}" "${OMC_INTEGRITY}"
  npm install -g --ignore-scripts --no-audit --no-fund "oh-my-claude-sisyphus@${OMC_VERSION}"
  local adapter="${HOME}/.local/bin/meridian-omc" tmp
  install -m 0755 "$(dirname "${BASH_SOURCE[0]}")/meridian-omc.py" "${adapter}"
  install -d "${HOME}/.cache/meridian"
  tmp="$(mktemp -d "${HOME}/.cache/meridian/omc-setup.XXXXXX")"
  python3 "${adapter}" stage "${HOME}/.claude" "${HOME}/.config/claude-omc/config.jsonc" "${tmp}/claude"
  # Prevent setup's unified MCP registry from reading either runtime's user config.
  # No account/auth file is copied into this scratch registry or consulted by setup.
  printf '{}\n' > "${tmp}/empty.json"
  (
    cd "${tmp}"
    CLAUDE_CONFIG_DIR="${tmp}/claude" XDG_CONFIG_HOME="${tmp}/config" \
      OMC_HOME="${tmp}/omc" OMC_STATE_DIR="${tmp}/state" \
      CLAUDE_MCP_CONFIG_PATH="${tmp}/empty.json" OMC_MCP_REGISTRY_PATH="${tmp}/empty.json" \
      CODEX_HOME="${tmp}/codex" "${HOME}/.local/bin/omc" setup --no-plugin --force --quiet </dev/null
  )
  python3 "${adapter}" install "${HOME}/.claude" "${HOME}/.config/claude-omc/config.jsonc" "${adapter}" "${tmp}/claude"
  rm -rf "${tmp}"
  omc_ignore_state "$(dirname "${BASH_SOURCE[0]}")/../.."
  check_omc
}

omc_ignore_state() {
  local common
  common="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
  install -d "${common}/info"
  touch "${common}/info/exclude"
  grep -qxF '/.omc/' "${common}/info/exclude" \
    || printf '/.omc/\n' >> "${common}/info/exclude"
}

cmd_omc_remove() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/meridian-omc.py" remove \
    "${HOME}/.claude" "${HOME}/.config/claude-omc/config.jsonc" "${HOME}/.local/bin/meridian-omc"
  npm uninstall -g --ignore-scripts --no-audit --no-fund oh-my-claude-sisyphus
  omc_unignore_state "$(dirname "${BASH_SOURCE[0]}")/../.."
  check_claude
  check_claude_hud
  ok "OMC absent; Orca hooks, claude-hud and other Claude settings retained"
}

omc_unignore_state() {
  local common
  common="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir)"
  python3 - "${common}/info/exclude" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
if path.exists():
    path.write_text(''.join(line for line in path.read_text().splitlines(keepends=True)
                            if line.rstrip('\r\n') != '/.omc/'))
PY
}

check_omc() {
  [ -f "${HOME}/.claude/.meridian-omc-install.json" ] \
    || fail "OMC absent (run: deploy/wsl/setup.sh omc)"
  python3 "${HOME}/.local/bin/meridian-omc" check \
    "${HOME}/.claude" "${HOME}/.config/claude-omc/config.jsonc" "${HOME}/.local/bin/meridian-omc" "${1:---before-orca}" \
    || fail "OMC lifecycle settings or coexisting hooks differ from ADR 0019 (run: deploy/wsl/setup.sh omc)"
  check_claude_managed
  ok "OMC ${OMC_VERSION}: standalone, HUD and MCP off, explicit workflows, boundary stops guarded"
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
  cmd_omx
  codex_ponytail
  codex_serena
  # Orca adds its hooks when it prepares Codex, after this step on a fresh distro (`agents`).
  check_codex install
}

# codex_setting FILE NAME TABLE VALUE: `NAME = VALUE` (VALUE in TOML) in TABLE, a dotted name
# (empty means the root; a missing table is added at the end, or into its parent when that holds
# it inline). An old value is replaced whole, a multi-line one included. Other tables, Orca's
# [hooks.state.*] and [projects.*] among them, are kept, the result is parsed before it replaces
# the file, and a value already set changes no byte.
codex_setting() {
  python3 -I - "$@" <<'PY' || fail "cannot set $2 = $4 in table '$3' of $1"
import json
import os
import re
import sys
import tomllib

path, name, table, value = sys.argv[1:]
parts = table.split(".") if table else []
if not all(re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in [*parts, name]):
    sys.exit(f"{table}.{name} is not a dotted name of bare keys")
want = tomllib.loads(f"v = {value}")["v"]


def current(cfg):
    for part in parts:
        cfg = cfg.get(part, {})
        if not isinstance(cfg, dict):
            return None
    got = cfg.get(name)
    return (type(got), got)


def scan(lines):
    # Table headers by line, and statements as (table, first line, line after the value, key,
    # value): a value may span lines (a multi-line array or string), and a line inside one is
    # never read as a header.
    headers, found, under, i = {}, [], "", 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if stripped.startswith("["):
            m = re.fullmatch(r"\[\s*([^\[\]\"']+?)\s*\]\s*(#.*)?", stripped)
            under = re.sub(r"\s*\.\s*", ".", m[1]) if m else None
            headers[i] = under
            i += 1
            continue
        for j in range(i + 1, len(lines) + 1):
            try:
                parsed = tomllib.loads("".join(lines[i:j]))
            except tomllib.TOMLDecodeError:
                continue
            break
        else:
            sys.exit(f"{path}: line {i + 1} does not parse")
        ((key, val),) = parsed.items()
        found.append((under, i, j, key, val))
        i = j
    return headers, found


def dump(v):
    # Inline TOML for the kinds of value a Codex setting holds.
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, str)):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(dump(x) for x in v) + "]"
    if isinstance(v, dict):
        pairs = [
            f"{k if re.fullmatch(r'[A-Za-z0-9_-]+', k) else json.dumps(k)} = {dump(x)}"
            for k, x in v.items()
        ]
        return "{ " + ", ".join(pairs) + " }" if pairs else "{}"
    sys.exit(f"{path}: cannot write {v!r} inline")


with open(path, encoding="utf-8") as f:
    text = f.read()
if current(tomllib.loads(text)) == (type(want), want):
    sys.exit(0)
lines = text.splitlines(keepends=True)
headers, found = scan(lines)
line = f"{name} = {value}\n"
header = -1 if not table else next((i for i, t in headers.items() if t == table), None)
# The table written in its parent, inline (`env = { ... }`) or as dotted keys (`env.X = ...`).
inline = [
    s for s in found if parts and s[0] == ".".join(parts[:-1]) and s[3] == parts[-1] and isinstance(s[4], dict)
]
if header is None and inline:
    merged = {k: v for s in inline for k, v in s[4].items()} | {name: want}
    for _, start, stop, _, _ in reversed(inline[1:]):
        del lines[start:stop]
    lines[inline[0][1] : inline[0][2]] = [f"{parts[-1]} = {dump(merged)}\n"]
elif header is None:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines += ["\n", f"[{table}]\n", line]
else:
    hits = [(start, stop) for under, start, stop, key, _ in found if under == table and key == name]
    for start, stop in reversed(hits):
        del lines[start:stop]
    lines.insert(hits[0][0] if hits else header + 1, line)
new = "".join(lines)
try:
    done = current(tomllib.loads(new)) == (type(want), want)
except tomllib.TOMLDecodeError as error:
    sys.exit(f"{path}: {table}.{name} is written in a form this script does not edit ({error})")
if not done:
    sys.exit(f"{path}: {name} is set outside table '{table}'")
with open(f"{path}.new", "w", encoding="utf-8") as f:
    f.write(new)
os.chmod(f"{path}.new", 0o600)
os.replace(f"{path}.new", path)
PY
}

codex_config() {
  # Written once; Orca later adds its own [hooks.state.*] and [projects.*] tables to this file,
  # and oh-my-codex its instructions, hooks and trust entries. The settings below are re-applied
  # on every run. /etc/codex/requirements.toml pins apps off and names the MCP servers allowed.
  local file="${HOME}/.codex/config.toml" feature
  if [ ! -e "${file}" ]; then
    codex_config_file
  fi
  # The startup menu is independent of --no-daemon; tasks typed later do not skip it.
  codex_setting "${file}" check_for_update_on_startup "" false
  codex_setting "${file}" model_reasoning_effort "" '"high"'
  for feature in apps skill_mcp_dependency_install memories; do
    codex_setting "${file}" "${feature}" features false
  done
  codex_setting "${file}" plugins features true
  codex_setting "${file}" url mcp_servers.openaiDeveloperDocs "\"${CODEX_DOCS_MCP}\""
  codex_setting "${file}" command mcp_servers.serena '"serena"'
  codex_setting "${file}" args mcp_servers.serena "${SERENA_MCP_ARGS}"
  codex_setting "${file}" startup_timeout_sec mcp_servers.serena 15
  # serena reports each start to its maker's server unless this is set (serena/agent.py).
  codex_setting "${file}" SERENA_USAGE_REPORTING mcp_servers.serena.env '"false"'
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
check_for_update_on_startup = false

[features]
# ChatGPT apps (account connectors) stay off, as claude.ai connectors do for Claude Code, so no
# account-linked tool (a broker connector among them) reaches an agent here. Plugins are on for
# the one plugin of ADR 0018; the MCP servers a skill can ask for and Codex's own memory stay off.
apps = false
plugins = true
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

omx_version() { "${HOME}/.local/bin/omx" --version 2>/dev/null </dev/null | sed -n 's/^oh-my-codex v//p' | head -n 1; }

# oh-my-codex (ADR 0018): the pinned package without its install script (it fetches a native
# helper this setup does not use), set up in user scope with no MCP server and no team mode.
cmd_omx() {
  local tmp exclude
  if [ "$(omx_version)" != "${OMX_VERSION}" ]; then
    npm_pinned "oh-my-codex@${OMX_VERSION}" "${OMX_INTEGRITY}"
    npm install -g --ignore-scripts --no-audit --no-fund "oh-my-codex@${OMX_VERSION}"
  fi
  # Its setup writes .omx/setup-scope.json in the folder it runs in.
  tmp="$(mktemp -d)"
  (cd "${tmp}" && OMX_AUTO_UPDATE=0 OMX_NATIVE_AUTO_FETCH=0 "${HOME}/.local/bin/omx" setup \
    --scope user --install-mode legacy --mcp none --team-mode disabled </dev/null)
  rm -rf "${tmp}"
  omx_config
  # Its setup writes "medium" where the key is missing.
  codex_setting "${HOME}/.codex/config.toml" model_reasoning_effort "" '"high"'
  # It keeps a .omx/ folder in each project; the line goes to the repository's shared exclude.
  exclude="$(git -C "${REPO_DIR}" rev-parse --path-format=absolute --git-common-dir)/info/exclude" \
    || fail "no repository at ${REPO_DIR} for oh-my-codex's ignore line (run: deploy/wsl/setup.sh repo)"
  install -d "$(dirname "${exclude}")"
  grep -qxF '.omx/' "${exclude}" 2>/dev/null || printf '%s\n' '.omx/' >> "${exclude}"
}

# What its setup flag does not keep at run time: team mode off, read from the user file when the
# project has no setup file; and prompt triage off, because the lead names the workflow.
omx_config() {
  local file="${HOME}/.codex/.omx-config.json" tmp
  tmp="$(mktemp)"
  { [ -s "${file}" ] && cat "${file}" || echo '{}'; } \
    | jq '.teamMode = "disabled" | .promptRouting.triage.enabled = false' > "${tmp}"
  install -m 0600 "${tmp}" "${file}"
  rm -f "${tmp}"
}

# ponytail (ADR 0018) as a Codex plugin, from a local marketplace holding the files of its release
# commit (its own marketplace installs from `main`). Codex runs its hooks once the owner trusts
# them in /hooks.
codex_ponytail() {
  local src="${HOME}/.local/share/meridian/ponytail-src" market="${HOME}/.local/share/meridian/codex-market"
  local codex="${HOME}/.local/bin/codex" tmp changed=0
  if [ "$(git -C "${src}" rev-parse HEAD 2>/dev/null)" != "${PONYTAIL_COMMIT}" ]; then
    rm -rf "${src}"
    git init -q "${src}"
    git -C "${src}" fetch -q --depth 1 https://github.com/DietrichGebert/ponytail.git "${PONYTAIL_COMMIT}"
    git -C "${src}" checkout -q --detach FETCH_HEAD
  fi
  [ "$(git -C "${src}" rev-parse HEAD)" = "${PONYTAIL_COMMIT}" ] && [ -z "$(git -C "${src}" status --porcelain)" ] \
    || fail "the ponytail checkout is not ${PONYTAIL_COMMIT} as fetched"
  tmp="$(mktemp -d)"
  tar -C "${src}" --exclude=.git -cf - . | tar -C "${tmp}" -xf -
  if ! diff -r "${tmp}" "${market}/plugins/ponytail" >/dev/null 2>&1; then
    rm -rf "${market}/plugins/ponytail"
    install -d "${market}/plugins" "${market}/.agents/plugins"
    mv "${tmp}" "${market}/plugins/ponytail"
    changed=1
  fi
  rm -rf "${tmp}"
  cat > "${market}/.agents/plugins/marketplace.json" <<JSON
{
  "name": "${PONYTAIL_MARKET}",
  "interface": { "displayName": "ponytail ${PONYTAIL_COMMIT:0:7} (deploy/wsl/setup.sh)" },
  "plugins": [
    { "name": "ponytail", "source": { "source": "local", "path": "./plugins/ponytail" }, "category": "Productivity" }
  ]
}
JSON
  grep -qxF "[marketplaces.${PONYTAIL_MARKET}]" "${HOME}/.codex/config.toml" \
    || "${codex}" plugin marketplace add "${market}" </dev/null
  if [ "${changed}" = 1 ] || ! grep -qxF "[plugins.\"ponytail@${PONYTAIL_MARKET}\"]" "${HOME}/.codex/config.toml"; then
    "${codex}" plugin add "ponytail@${PONYTAIL_MARKET}" </dev/null
  fi
}

serena_version() { "${HOME}/.local/bin/serena" --version 2>/dev/null </dev/null | sed -n 's/^Serena //p' | tail -n 1; }
serena_python() { printf '%s\n' "$("${HOME}/.local/bin/uv" tool dir)/serena-agent/bin/python"; }

# serena (ADR 0018), Codex's code navigation: the pinned release through uv, its global config,
# and the repository's shared exclude for the .serena/ folder it keeps in each project.
codex_serena() {
  local exclude
  if [ "$(serena_version)" != "${SERENA_VERSION}" ]; then
    pypi_pinned serena-agent "${SERENA_VERSION}" "${SERENA_FILE}" "${SERENA_SHA256}"
    "${HOME}/.local/bin/uv" tool install "serena-agent==${SERENA_VERSION}"
  fi
  # serena adds its defaults, its project list and a secret to the file when it starts, so the
  # file is written only when a setting below has changed.
  serena_config_check "$(serena_python)" >/dev/null 2>&1 || serena_config
  exclude="$(git -C "${REPO_DIR}" rev-parse --path-format=absolute --git-common-dir)/info/exclude" \
    || fail "no repository at ${REPO_DIR} for serena's ignore line (run: deploy/wsl/setup.sh repo)"
  grep -qxF '.serena/' "${exclude}" 2>/dev/null || printf '%s\n' '.serena/' >> "${exclude}"
}

serena_config() {
  install -d -m 0700 "${HOME}/.serena"
  cat > "${HOME}/.serena/serena_config.yml.new" <<YAML
# Written by deploy/wsl/setup.sh codex (ADR 0018); serena adds its defaults when it starts.
language_backend: LSP
# One MCP tool per operation, so the list below is what Codex sees (the REPL interface runs Python).
agent_interface: tools
gui_log_window: false
web_dashboard: false
web_dashboard_open_on_launch: false
fixed_tools: [${SERENA_TOOLS}]
# The project's own pyright (relative to the project root), not one that uvx downloads.
ls_specific_settings:
  python:
    ls_path: .venv/bin/pyright-langserver
projects: []
YAML
  chmod 0600 "${HOME}/.serena/serena_config.yml.new"
  mv "${HOME}/.serena/serena_config.yml.new" "${HOME}/.serena/serena_config.yml"
}

# serena_config_check PYTHON: the settings serena_config writes, read with PyYAML in serena's
# own environment (it depends on it).
serena_config_check() {
  "$1" -I - "${HOME}/.serena/serena_config.yml" "${SERENA_TOOLS}" <<'PY'
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
want = dict(
    language_backend="LSP",
    agent_interface="tools",
    gui_log_window=False,
    web_dashboard=False,
    web_dashboard_open_on_launch=False,
    fixed_tools=sys.argv[2].split(", "),
    ls_specific_settings={"python": {"ls_path": ".venv/bin/pyright-langserver"}},
)
problems = [key for key, value in want.items() if cfg.get(key) != value]
problems += [key for key in ("excluded_tools", "included_optional_tools") if cfg.get(key)]
sys.exit(f"serena_config.yml: {', '.join(problems)}" if problems else 0)
PY
}

# check_codex [install]: the state setup writes. With `install`, Orca's hooks may be missing
# still (agents-check, without it, requires them).
check_codex() {
  version_ge "$(codex_version)" "${CODEX_VERSION}" \
    || fail "Codex CLI is older than ${CODEX_VERSION} or missing (run: deploy/wsl/setup.sh codex)"
  python3 -I - "${HOME}/.codex/config.toml" "${CODEX_MODEL}" "${HOME}/.codex/hooks.json" \
    "${HOME}/.codex/.omx-config.json" "${CODEX_DOCS_MCP}" "ponytail@${PONYTAIL_MARKET}" "${SERENA_MCP_ARGS}" "${1:-full}" <<'PY' \
    || fail "~/.codex is not what deploy/wsl/setup.sh codex writes"
import glob
import hashlib
import json
import os
import re
import sys
import tomllib

config, model, hooks_file, omx_file, docs_url, plugin, serena_args, mode = sys.argv[1:]
serena = dict(
    command="serena",
    args=tomllib.loads(f"v = {serena_args}")["v"],
    startup_timeout_sec=15,
    env={"SERENA_USAGE_REPORTING": "false"},
)
with open(config, "rb") as f:
    cfg = tomllib.load(f)
features = cfg.get("features", {})
profiles = cfg.get("profiles", {})
servers = cfg.get("mcp_servers", {})
plugins = {name for name, p in cfg.get("plugins", {}).items() if p.get("enabled", True) is not False}
state = cfg.get("hooks", {}).get("state", {})


# Codex's hook trust identity (codex-rs/hooks/src/engine/discovery.rs `hook_hash` and
# config/src/fingerprint.rs at rust-v0.167.2 and rust-v0.169.0): SHA-256 of the sorted, compact
# JSON of the normalized hook. A trust entry counts only when its hash is the current one, so a
# hook whose command, matcher or timeout changed after approval is untrusted, as Codex sees it.
MATCHER_EVENTS = {"PreToolUse", "PermissionRequest", "PostToolUse", "SessionStart", "SessionEnd",
                  "SubagentStart", "SubagentStop", "PreCompact", "PostCompact"}
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
    normalized = dict(type="command", command=handler["command"], timeout=timeout, **{"async": bool(handler.get("async", False))})
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


def plugin_content_hash(root):
    # codex-rs/hooks/src/engine/plugin_fingerprint.rs at the same tags.
    digest, pending = hashlib.sha256(b"codex-plugin-bundle-v1"), [root]
    while pending:
        path = pending.pop()
        relative = os.path.relpath(path, root) if path != root else ""
        base = os.path.basename(relative)
        if base in ("__pycache__", ".venv") or base.endswith((".pyc", ".egg-info")):
            continue
        name = os.fsencode(relative)
        digest.update(len(name).to_bytes(8, "little") + name)
        if os.path.isdir(path) and not os.path.islink(path):
            digest.update(b"directory")
            pending.extend(sorted((os.path.join(path, e) for e in os.listdir(path)), key=lambda p: os.fsencode(os.path.basename(p)), reverse=True))
        else:
            with open(path, "rb") as f:
                data = f.read()
            digest.update(b"file" + len(data).to_bytes(8, "little") + data)
    return "sha256:" + digest.hexdigest()


def trusted(key, current):
    entry = state.get(key, {})
    return current is not None and entry.get("trusted_hash") == current and entry.get("enabled") is not False


# Every hook entry in hooks.json is Orca's or oh-my-codex's, and each has its trust entry.
count, untrusted = {"orca": 0, "omx": 0, "unknown": 0}, []
try:
    with open(hooks_file, encoding="utf-8") as f:
        hooks = json.load(f).get("hooks", {})
except (OSError, ValueError):
    hooks = {}
for event, groups in hooks.items():
    label = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
    for g, group in enumerate(groups):
        for h, handler in enumerate(group.get("hooks", [])):
            command = handler.get("command", "")
            owner = "orca" if "orca-agent-hook-form" in command else "omx" if "/oh-my-codex/" in command else "unknown"
            count[owner] += 1
            if not trusted(f"{hooks_file}:{label}:{g}:{h}", hook_hash(event, group, handler)):
                untrusted.append(f"{event} {g}:{h}")
try:
    with open(omx_file, encoding="utf-8") as f:
        omx = json.load(f)
except (OSError, ValueError):
    omx = {}
problems = [
    name
    for name, bad in [
        ("model", cfg.get("model") != model),
        ("model_reasoning_effort", cfg.get("model_reasoning_effort") != "high"),
        ("approval_policy", cfg.get("approval_policy") != "never"),
        ("sandbox_mode", cfg.get("sandbox_mode") != "danger-full-access"),
        ("check_for_update_on_startup", cfg.get("check_for_update_on_startup") is not False),
        *[(f"[features] {name}", features.get(name) is not False) for name in ("apps", "skill_mcp_dependency_install", "memories")],
        ("[features] plugins", features.get("plugins") is not True),
        ("[features] connectors (the old name of apps)", "connectors" in features),
        (f"MCP servers {sorted(servers)}", set(servers) != {"openaiDeveloperDocs", "serena"}),
        ("openaiDeveloperDocs", servers.get("openaiDeveloperDocs", {}) != {"url": docs_url}),
        ("[mcp_servers.serena]", servers.get("serena", {}) != serena),
        (f"plugins {sorted(plugins)}", plugins != {plugin}),
        (
            "a profile sets features, MCP servers or plugins",
            any(key in p for p in profiles.values() for key in ("features", "mcp_servers", "plugins")),
        ),
        ("[analytics] enabled", cfg.get("analytics", {}).get("enabled") is not False),
        ("[feedback] enabled", cfg.get("feedback", {}).get("enabled") is not False),
        ("[otel] metrics_exporter", cfg.get("otel", {}).get("metrics_exporter") != "none"),
        (
            f"hooks.json entries {count}",
            count not in ({"orca": 9, "omx": 8, "unknown": 0}, *([{"orca": 0, "omx": 8, "unknown": 0}] if mode == "install" else [])),
        ),
        (f"hooks without trust: {untrusted}", bool(untrusted)),
        (".omx-config.json teamMode", omx.get("teamMode") != "disabled"),
        (
            ".omx-config.json prompt triage",
            omx.get("promptRouting", {}).get("triage", {}).get("enabled") is not False,
        ),
    ]
    if bad
]
if problems:
    sys.exit(f"Codex config: {', '.join(problems)}")
if count["orca"] == 0:
    print("note: Orca's 9 Codex hooks are not there yet; Orca adds them, and agents-check requires them")
# Ponytail's hooks: each trust entry (`<plugin>:<file>:<event>:<group>:<handler>`) must hold the
# current hash of its declaration in the installed copy, and of that copy's files.
market, name = plugin.split("@")[1], plugin.split("@")[0]
roots = glob.glob(os.path.join(os.path.dirname(hooks_file), "plugins", "cache", market, name, "*", ""))
root = roots[0].rstrip("/") if len(roots) == 1 else None
content = plugin_content_hash(root) if root else None
current_plugin = 0
for key, entry in state.items():
    if not key.startswith(f"{plugin}:") or root is None or entry.get("trusted_content_hash") != content:
        continue
    file, label, g, h = key[len(plugin) + 1 :].rsplit(":", 3)
    event = "".join(part.capitalize() for part in label.split("_"))
    try:
        with open(os.path.join(root, file), encoding="utf-8") as f:
            group = json.load(f)["hooks"][event][int(g)]
        current_plugin += trusted(key, hook_hash(event, group, group["hooks"][int(h)]))
    except (OSError, ValueError, KeyError, IndexError):
        continue
waiting = 3 - current_plugin
if waiting > 0:
    print(f"note: {waiting} of ponytail's 3 hooks wait for the owner's /hooks in codex; its skills work meanwhile")
PY
  check_codex_requirements
  [ "$(omx_version)" = "${OMX_VERSION}" ] || fail "oh-my-codex is not ${OMX_VERSION} (run: deploy/wsl/setup.sh codex)"
  [ "$(serena_version)" = "${SERENA_VERSION}" ] || fail "serena is not ${SERENA_VERSION} (run: deploy/wsl/setup.sh codex)"
  serena_config_check "$(serena_python)" || fail "~/.serena/serena_config.yml is not what deploy/wsl/setup.sh codex writes"
  # omx doctor exits 0 whatever it finds; its summary line says what failed.
  local tmp doctor
  tmp="$(mktemp -d)"
  doctor="$(cd "${tmp}" && OMX_AUTO_UPDATE=0 "${HOME}/.local/bin/omx" doctor </dev/null 2>&1)" || true
  rm -rf "${tmp}"
  grep -qE '^Results: [0-9]+ passed, [0-9]+ warnings, 0 failed$' <<<"${doctor}" \
    || fail "omx doctor: $(grep -E '^ *\[XX\]|^Results:' <<<"${doctor}" | tr -s ' ' | tr '\n' ';')"
  ok "Codex CLI $(codex_version): ${CODEX_MODEL} at high effort, no ChatGPT apps or memories; oh-my-codex ${OMX_VERSION} (omx doctor: 0 failed), the ponytail plugin, serena ${SERENA_VERSION} (navigation and diagnostics only) and OpenAI's docs server"
}

# /etc/codex/requirements.toml: the text in deploy/wsl/meridian.user-data, byte for byte. It pins
# ChatGPT apps off in every config layer and names the MCP servers Codex may start: a server
# starts only when its name and identity (its command, or its URL) both match.
check_codex_requirements() {
  cmp -s <(codex_requirements_text "${USER_DATA}") /etc/codex/requirements.toml \
    || fail "/etc/codex/requirements.toml is not the text in deploy/wsl/meridian.user-data (run: deploy/wsl/setup.sh codex-requirements)"
}

# codex_requirements_text USER_DATA: the content of the requirements file in the definition (a
# YAML literal block: indentation removed, trailing blank lines dropped).
codex_requirements_text() {
  awk '
    $0 == "  - path: /etc/codex/requirements.toml" { file = 1; next }
    file && $0 == "    content: |" { body = 1; next }
    body && /^$/ { blank++; next }
    body && /^      / { for (; blank > 0; blank--) print ""; print substr($0, 7); found = 1; next }
    body { exit }
    END { exit !found }
  ' "$1"
}

cmd_codex_requirements() {
  local tmp
  tmp="$(mktemp)"
  codex_requirements_text "${USER_DATA}" > "${tmp}" || fail "no requirements text in ${USER_DATA}"
  sudo install -D -m 0644 -o root -g root "${tmp}" /etc/codex/requirements.toml
  rm -f "${tmp}"
  check_codex_requirements
  ok "/etc/codex/requirements.toml is the text in deploy/wsl/meridian.user-data"
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

# claude-hud (ADR 0015). Claude Code has one status line command, and Orca holds it with a
# reporter that prints nothing. deploy/wsl/meridian-claude-hud.sh runs both: Orca keeps its
# usage figures and the line shows claude-hud. Orca rewrites only a command it recognises as
# its own (one naming agent-hooks/claude-statusline), so it leaves the wrapper alone.
CLAUDE_HUD_WRAPPER="${HOME}/.local/bin/meridian-claude-hud"

claude_hud_config() {
  # Written once; afterwards the file is the owner's (`/hud`, `hud set`). The owner's choice of
  # 2026-11-13 is every informative display: activity (tools, skills, MCP, agents with their
  # effort, todos), the model's effort, output speed, the prompt cache (expiry, hit rate),
  # tokens, cost, compactions, both usage windows with their pace. The account labels stay off:
  # they are the two display options that read ~/.claude.json.
  local file="${HOME}/.claude/plugins/claude-hud/config.json"
  [ ! -e "${file}" ] || return 0
  mkdir -p "$(dirname "${file}")"
  jq -n '
    [ "showTools", "showSkills", "showMcp", "showAgents", "showAgentEffort", "showTodos",
      "showEffortLevel", "showSpeed", "showPromptCache", "showCacheHitRate", "showSessionTokens",
      "showCompactions", "showConfigCounts", "showDuration", "usagePace", "showCost",
      "showDailyCost", "showWeeklyCost", "showClaudeCodeVersion", "showSessionName",
      "showLastResponseAt", "showMemoryUsage", "showAdvisor" ] as $on
    | { gitStatus: {showAheadBehind: true, showFileStats: true},
        display: (($on | map({(.): true}) | add)
          + {showAuth: false, showAuthUser: false, sevenDayThreshold: 0, contextValue: "both"}) }
  ' > "${file}"
}

claude_statusline() {
  # The wrapper replaces no status line, Orca's reporter, claude-hud's own command or itself.
  # Any other command is someone's choice: setup stops instead of overwriting it.
  local settings="${HOME}/.claude/settings.json" wrapper="${CLAUDE_HUD_WRAPPER}" tmp
  tmp="$(mktemp)"
  jq --arg wrapper "${wrapper}" '
    (.statusLine.command // "") as $now
    | if $now == "" or $now == $wrapper
         or ($now | test("agent-hooks/claude-statusline|plugins/claude-hud/statusline"))
      then .statusLine = {type: "command", command: $wrapper}
      else error("statusLine runs another command") end
  ' "${settings}" > "${tmp}" \
    || { rm -f "${tmp}"; fail "~/.claude/settings.json has a status line command that is not Orca's or claude-hud's; remove it, then rerun: deploy/wsl/setup.sh claude-hud"; }
  install -m 0644 "${tmp}" "${settings}"
  rm -f "${tmp}"
}

cmd_claude_hud() {
  local claude="${HOME}/.local/bin/claude" mp="${HOME}/.claude/plugins/marketplaces/claude-hud"
  local hud="${HOME}/.claude/plugins/claude-hud" path
  export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1
  # A checkout at another commit is an older pin: the plugin and its marketplace are removed and
  # added again at the new one, so that the cache holds the pinned version only.
  if [ -d "${mp}/.git" ] && [ "$(git -C "${mp}" rev-parse HEAD)" != "${CLAUDE_HUD_COMMIT}" ]; then
    "${claude}" plugin uninstall claude-hud@claude-hud --scope user --keep-data </dev/null >/dev/null 2>&1 || true
    "${claude}" plugin marketplace remove claude-hud </dev/null >/dev/null
    rm -rf "${HOME}/.claude/plugins/cache/claude-hud"
  fi
  # The marketplace at the pinned tag; the plugin is installed only once its commit is checked.
  [ -d "${mp}/.git" ] \
    || "${claude}" plugin marketplace add "jarrodwatts/claude-hud#${CLAUDE_HUD_REF}" --scope user </dev/null
  [ "$(git -C "${mp}" rev-parse HEAD)" = "${CLAUDE_HUD_COMMIT}" ] \
    || fail "the claude-hud checkout is not at ${CLAUDE_HUD_COMMIT} (${CLAUDE_HUD_REF}); nothing was installed from it"
  if ! "${claude}" plugin list --json </dev/null | jq -e '.[] | select(.id == "claude-hud@claude-hud")' >/dev/null; then
    "${claude}" plugin install claude-hud@claude-hud --scope user </dev/null
  fi
  # claude-hud's launcher runs the newest claude-hud in the plugin cache. Its own `hud install`
  # would copy it here too; setup does it so that no session has to run /hud first.
  path="$(jq -r '.plugins["claude-hud@claude-hud"][0].installPath' "${HOME}/.claude/plugins/installed_plugins.json")"
  [ -r "${path}/scripts/statusline.mjs" ] || fail "claude-hud's launcher is not at ${path}/scripts/statusline.mjs"
  install -D -m 0644 "${path}/scripts/statusline.mjs" "${hud}/statusline.mjs"
  install -D -m 0755 "$(dirname "$(readlink -f "$0")")/meridian-claude-hud.sh" "${CLAUDE_HUD_WRAPPER}"
  claude_hud_config
  claude_statusline
  check_claude_hud
}

check_claude_hud() {
  local plugins="${HOME}/.claude/plugins" settings="${HOME}/.claude/settings.json" file
  "${HOME}/.local/bin/claude" plugin list --json </dev/null \
    | jq -e '.[] | select(.id == "claude-hud@claude-hud" and .enabled)' >/dev/null \
    || fail "claude-hud is not installed in Claude Code (run: deploy/wsl/setup.sh claude-hud)"
  [ "$(git -C "${plugins}/marketplaces/claude-hud" rev-parse HEAD 2>/dev/null)" = "${CLAUDE_HUD_COMMIT}" ] \
    || fail "the claude-hud checkout is not at the pinned ${CLAUDE_HUD_COMMIT}"
  # The launcher runs the highest claude-hud version under any marketplace in the plugin cache,
  # enabled or not, so the pinned one must be the only one there.
  [ "$(printf '%s\n' "${plugins}"/cache/*/claude-hud/*)" = "${plugins}/cache/claude-hud/claude-hud/${CLAUDE_HUD_VERSION}" ] \
    || fail "the plugin cache holds a claude-hud other than ${CLAUDE_HUD_VERSION} from the claude-hud marketplace: $(printf '%s ' "${plugins}"/cache/*/claude-hud/*)"
  jq -e --arg wrapper "${CLAUDE_HUD_WRAPPER}" --arg ref "${CLAUDE_HUD_REF}" '
    .statusLine == {type: "command", command: $wrapper}
    and .extraKnownMarketplaces["claude-hud"].source.ref == $ref
    and .extraKnownMarketplaces["claude-hud"].autoUpdate != true
  ' "${settings}" >/dev/null \
    || fail "the status line is not the wrapper, or claude-hud is not held at ${CLAUDE_HUD_REF} (run: deploy/wsl/setup.sh claude-hud)"
  [ -x "${CLAUDE_HUD_WRAPPER}" ] && [ -r "${plugins}/claude-hud/statusline.mjs" ] \
    || fail "the status line wrapper or claude-hud's launcher is missing (run: deploy/wsl/setup.sh claude-hud)"
  [ -x "${HOME}/.orca/agent-hooks/claude-statusline.sh" ] \
    || fail "Orca's usage reporter ~/.orca/agent-hooks/claude-statusline.sh is missing (run: deploy/wsl/setup.sh orca)"
  # Neither config file may switch on an account label or point the usage figures at a file.
  for file in "${plugins}/claude-hud/config.json" "${HOME}/.claude/claude-hud.json"; do
    [ ! -e "${file}" ] || jq -e '
      [.display.showAuth, .display.showAuthUser, .display.authUserFullEmail] | all(. != true)
    ' "${file}" >/dev/null || fail "${file} switches on an account label"
    [ ! -e "${file}" ] || jq -e '
      [.display.externalUsagePath, .display.externalUsageWritePath] | all(. == null or . == "")
    ' "${file}" >/dev/null || fail "${file} reads or writes usage figures in another file"
  done
  [ -n "$(printf '%s' '{"model":{"display_name":"check"}}' | "${CLAUDE_HUD_WRAPPER}" 2>/dev/null)" ] \
    || fail "the status line wrapper printed nothing for a sample payload"
  ok "claude-hud ${CLAUDE_HUD_VERSION} at its pinned commit behind ${CLAUDE_HUD_WRAPPER}; Orca's usage reporter still fed; no account label"
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
  else
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/agy.tar.gz" "${AGY_URL}"
    echo "${AGY_SHA256}  ${tmp}/agy.tar.gz" | sha256sum -c -
    [ "$(tar -tzf "${tmp}/agy.tar.gz")" = antigravity ] || fail "the agy archive is not one file named antigravity"
    tar -xzf "${tmp}/agy.tar.gz" -C "${tmp}" antigravity
    install -D -m 0755 "${tmp}/antigravity" "${HOME}/.local/bin/agy"
    rm -rf "${tmp}"
  fi
  agy_settings
  check_agy
}

# agy's own settings file: the default model, merged in, because Orca keeps the workspaces it
# trusts in the same file. agy saves its settings with mode 0600, and so does this.
agy_settings() {
  local file="${HOME}/.gemini/antigravity-cli/settings.json" tmp
  mkdir -p "${file%/*}"
  tmp="$(mktemp "${file}.XXXXXX")"
  if [ -s "${file}" ]; then
    jq --arg model "${AGY_MODEL}" '.model = $model' "${file}" > "${tmp}" \
      || { rm -f "${tmp}"; fail "cannot merge the model into ${file}"; }
  else
    jq -n --arg model "${AGY_MODEL}" '{model: $model}' > "${tmp}"
  fi
  mv "${tmp}" "${file}"
}

check_agy() {
  version_ge "$(agy_version)" "${AGY_VERSION}" \
    || fail "Antigravity CLI is older than ${AGY_VERSION} or missing (run: deploy/wsl/setup.sh agy)"
  # No MCP server, and no plugin or hook beyond what agy ships (its built-in `swarm` plugin, which
  # agy enables on its first start, and 14 built-in skills, none naming an MCP server): nothing
  # here may give an agent a broker or an order tool. agy has no machine-wide setting for that,
  # so its user config and every worktree of the repo are checked. (~/.gemini/config/hooks.json is Orca's status hook once Orca has started
  # an agy session.) agy writes an empty ~/.gemini/config/mcp_config.json on its first full
  # start: that file may exist, but only empty or naming no server (jq refuses comments, so a
  # commented file fails as well).
  local path tree mcp="${HOME}/.gemini/config/mcp_config.json"
  [ ! -s "${mcp}" ] || jq -e '. == {} or . == {"mcpServers": {}}' "${mcp}" >/dev/null 2>&1 \
    || fail "${mcp} names MCP servers: agy would start them"
  for path in "${HOME}/.gemini/config/plugins" "${HOME}/.gemini/settings.json"; do
    [ ! -e "${path}" ] || fail "${path} exists: agy would load plugins or MCP servers from it"
  done
  while read -r tree; do
    for path in "${tree}/.agents/mcp_config.json" "${tree}/.agents/plugins" "${tree}/.agents/hooks.json"; do
      [ ! -e "${path}" ] || fail "${path} exists: agy would load MCP servers, plugins or hooks from it"
    done
  done < <(git -C "${REPO_DIR}" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')
  jq -e --arg model "${AGY_MODEL}" '.model == $model' "${HOME}/.gemini/antigravity-cli/settings.json" >/dev/null 2>&1 \
    || fail "agy's default model is not ${AGY_MODEL} (run: deploy/wsl/setup.sh agy)"
  # Its telemetry is an account setting kept by Google, with no local file to check (UPSTREAM.md).
  ok "Antigravity CLI $(agy_version): ${AGY_MODEL}; no MCP server, and no plugin or hook beyond agy's built-in ones, in its config or the repo's worktrees"
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
  dsh_stack
  check_dsh
}

dsh_home_files() {
  # Both are written once and left alone afterwards, apart from the Meridian block below: Orca
  # appends its own marked hooks block to cordis.patch.yml, and the TUI's updater edits the
  # profile's pnpm-workspace.yaml.
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
  # The Meridian block (ADR 0016), rewritten whole on every run and kept above Orca's own marked
  # block, whose lines are never touched: the model row (a row's config replaces the default's
  # as a whole, so it names the provider too), code navigation through DeepSeek's LSP packages,
  # and the completion gate's Stop hook, a second mount of the hook bridge beside Orca's. The
  # provider starts the server in the session's working directory and sends it as the workspace;
  # the server row finds the worktree root with git from there, runs that worktree's own
  # pyright-langserver, and gives it the root as its workspace (deploy/wsl/dsh-lsp-root.py), so
  # navigation resolves the repository's imports from any subdirectory.
  # A model row that an older run wrote outside the block is moved into it.
  local block
  block="$(cat <<YAML
# >>> meridian-managed (deploy/wsl/setup.sh dsh; docs/adr/0016-dsh-worker-stack.md) >>>
- id: agent-default-model
  config:
    model: ${DSH_MODEL}
    provider: deepseek-official
- insert:
    - id: meridian-lsp
      name: '@deepseek-ai/dsh-lsp'
    - id: meridian-lsp-pyright
      name: '@deepseek-ai/dsh-lsp-stdio'
      config:
        servers:
          pyright:
            command: sh
            args: ['-c', 'top="\$(git rev-parse --show-toplevel)" && exec python3 -I ${HOME}/.dsh/lsp/dsh-lsp-root.py "\$top" "\$top/.venv/bin/pyright-langserver" --stdio']
            extensionToLanguage:
              '.py': python
              '.pyi': python
    - id: meridian-tool-lsp
      name: '@deepseek-ai/dsh-tool-lsp'
- insert:
    - id: meridian-check-gate
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: '${HOME}/.dsh/meridian-hooks.json'
# <<< meridian-managed <<<
YAML
)"
  python3 -I - "${HOME}/.dsh/cordis.patch.yml" "${block}" <<'PY' \
    || fail "cannot write the Meridian block in ~/.dsh/cordis.patch.yml"
import os
import sys

path, block = sys.argv[1], sys.argv[2] + "\n"
begin, end, orca = "# >>> meridian-managed", "# <<< meridian-managed", "# >>> orca-managed-dsh-hooks"
with open(path, encoding="utf-8") as f:
    text = f.read()
lines = text.splitlines(keepends=True)
if lines and not lines[-1].endswith("\n"):
    lines[-1] += "\n"
at = next((i for i, line in enumerate(lines) if line.startswith(orca)), len(lines))
head, tail = lines[:at], lines[at:]
if sum(line.startswith(begin) for line in head) != sum(line.startswith(end) for line in head):
    sys.exit("the Meridian block is not closed")
kept, inside, i = [], False, 0
while i < len(head):
    line = head[i]
    inside = inside or line.startswith(begin)
    if not inside and line == "- id: agent-default-model\n":
        i += 1
        while i < len(head) and head[i].startswith(" "):
            i += 1
        continue
    if not inside:
        kept.append(line)
    if line.startswith(end):
        inside = False
    i += 1
new = "".join(kept) + block + "".join(tail)
if new != text:
    with open(f"{path}.new", "w", encoding="utf-8") as f:
        f.write(new)
    os.chmod(f"{path}.new", 0o600)
    os.replace(f"{path}.new", path)
PY
  # dsh-tui 0.20.0's guide is home-wide UI state, outside the Cordis patch layer.
  # Escape skips without recording completion. Keep unrelated prefs and newer revisions.
  local guide="${HOME}/.dsh-tui/onboarding.json"
  install -d -m 0700 "${HOME}/.dsh-tui"
  { if [ -e "${guide}" ]; then cat "${guide}"; else echo '{}'; fi; } | jq '
    .completed = true |
    .version = (if (.version | type) == "number" and .version >= 1 then .version else 1 end)
  ' > "${guide}.new"
  chmod 0600 "${guide}.new"
  mv "${guide}.new" "${guide}"
}

# The worker stack of ADR 0016, for dsh only: skills, the LSP packages, ast-grep, agentsview, the
# completion gate.
dsh_stack() {
  dsh_skills
  dsh_lsp_packages
  dsh_release_binaries
  # The completion gate: a copy of the tracked script, and the hooks file the Meridian block's
  # second hook-bridge mount reads (Stop only; Orca's own hooks file is never touched).
  install -D -m 0755 "$(dirname "$(readlink -f "$0")")/dsh-check-gate.sh" "${HOME}/.dsh/hooks/dsh-check-gate.sh"
  install -D -m 0644 "$(dirname "$(readlink -f "$0")")/dsh-lsp-root.py" "${HOME}/.dsh/lsp/dsh-lsp-root.py"
  jq -n --arg command "${HOME}/.dsh/hooks/dsh-check-gate.sh" \
    '{hooks: {Stop: [{hooks: [{type: "command", command: $command, timeout: 1800}]}]}}' \
    > "${HOME}/.dsh/meridian-hooks.json.new"
  chmod 0600 "${HOME}/.dsh/meridian-hooks.json.new"
  mv "${HOME}/.dsh/meridian-hooks.json.new" "${HOME}/.dsh/meridian-hooks.json"
}

# Each skill folder from a sparse, shallow checkout of its repository at the pinned commit, then
# copied whole to ~/.dsh/skills/<folder name>, which only dsh reads. A copy that differs from
# its checkout is replaced.
dsh_skills() {
  local sources="${HOME}/.local/share/meridian/dsh-skill-src" entry repo commit path dir paths_line
  local -a paths
  install -d "${sources}"
  install -d -m 0700 "${HOME}/.dsh/skills"
  for entry in "${DSH_SKILLS[@]}"; do
    read -r repo commit paths_line <<<"${entry}"
    read -r -a paths <<<"${paths_line}"
    dir="${sources}/${repo/\//__}"
    if [ "$(git -C "${dir}" rev-parse HEAD 2>/dev/null)" != "${commit}" ] \
      || [ -n "$(git -C "${dir}" status --porcelain 2>/dev/null)" ]; then
      rm -rf "${dir}"
      git init -q "${dir}"
      git -C "${dir}" remote add origin "https://github.com/${repo}.git"
      git -C "${dir}" sparse-checkout set --no-cone "${paths[@]/#//}"
      git -C "${dir}" fetch -q --depth 1 --filter=blob:none origin "${commit}"
      git -C "${dir}" -c advice.detachedHead=false checkout -q FETCH_HEAD
      [ "$(git -C "${dir}" rev-parse HEAD)" = "${commit}" ] || fail "${repo} did not check out at ${commit}"
    fi
    for path in "${paths[@]}"; do
      [ -f "${dir}/${path}/SKILL.md" ] || fail "${repo} has no skill at ${path}"
      if ! diff -rq "${dir}/${path}" "${HOME}/.dsh/skills/${path##*/}" >/dev/null 2>&1; then
        rm -rf "${HOME}/.dsh/skills/${path##*/}"
        cp -R "${dir}/${path}" "${HOME}/.dsh/skills/${path##*/}"
      fi
    done
  done
}

dsh_skill_names() {
  local entry path
  for entry in "${DSH_SKILLS[@]}"; do
    for path in ${entry#* * }; do printf '%s\n' "${path##*/}"; done
  done | sort
}

DSH_LSP_PACKAGES=(dsh-lsp dsh-lsp-stdio dsh-tool-lsp)
# dsh_profile_package NAME: the version of @deepseek-ai/NAME the dsh-tui profile depends on.
dsh_profile_package() {
  jq -r --arg name "@deepseek-ai/$1" '.dependencies[$name] // empty' \
    "${HOME}/.dsh/profiles/dsh-tui/package.json" 2>/dev/null
}

# The three LSP packages declare no dsh bundle: they go into the profile as plain dependencies,
# as the hook packages do, and the Meridian block's rows mount them.
dsh_lsp_packages() {
  local name missing=0
  for name in "${DSH_LSP_PACKAGES[@]}"; do
    version_ge "$(dsh_profile_package "${name}")" "${DSH_VERSION}" || missing=1
  done
  [ "${missing}" = 1 ] || return 0
  npm_pinned "@deepseek-ai/dsh-lsp@${DSH_VERSION}" "${DSH_LSP_INTEGRITY}"
  npm_pinned "@deepseek-ai/dsh-lsp-stdio@${DSH_VERSION}" "${DSH_LSP_STDIO_INTEGRITY}"
  npm_pinned "@deepseek-ai/dsh-tool-lsp@${DSH_VERSION}" "${DSH_TOOL_LSP_INTEGRITY}"
  "${HOME}/.local/bin/dsh" plugin --profile dsh-tui add "@deepseek-ai/dsh-lsp@${DSH_VERSION}" \
    "@deepseek-ai/dsh-lsp-stdio@${DSH_VERSION}" "@deepseek-ai/dsh-tool-lsp@${DSH_VERSION}" </dev/null
}

ast_grep_version() { "${HOME}/.local/bin/ast-grep" --version 2>/dev/null </dev/null | sed -n 's/^ast-grep //p'; }
# agentsview_version PATH: the version a regular, executable agentsview file at PATH reports.
# The private binary is asked, not the launcher: a standalone agentsview the owner put at
# ~/.local/bin/agentsview must not stand in for the install the launcher points at.
agentsview_version() {
  [ -f "$1" ] && [ -x "$1" ] || return 0
  "$1" --version 2>/dev/null </dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1
}

# ast-grep and agentsview: the release asset at its checksum, one named member installed. Only
# the `ast-grep` name goes on PATH: its `sg` alias would shadow the system's sg(1). agentsview
# goes behind a wrapper that switches off its anonymous telemetry and update check, which it
# reads only from the environment (or a flag); it serves on 127.0.0.1 by default.
dsh_release_binaries() {
  local tmp
  if [ "$(ast_grep_version)" != "${AST_GREP_VERSION}" ]; then
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/ast-grep.zip" "${AST_GREP_URL}"
    echo "${AST_GREP_SHA256}  ${tmp}/ast-grep.zip" | sha256sum -c -
    python3 -I -m zipfile -e "${tmp}/ast-grep.zip" "${tmp}/x"
    install -D -m 0755 "${tmp}/x/ast-grep" "${HOME}/.local/bin/ast-grep"
    rm -rf "${tmp}"
  fi
  if [ "$(agentsview_version "${HOME}/.local/libexec/meridian/agentsview")" != "${AGENTSVIEW_VERSION}" ]; then
    tmp="$(mktemp -d)"
    curl -fsSLo "${tmp}/agentsview.tar.gz" "${AGENTSVIEW_URL}"
    echo "${AGENTSVIEW_SHA256}  ${tmp}/agentsview.tar.gz" | sha256sum -c -
    [ "$(tar -tzf "${tmp}/agentsview.tar.gz")" = agentsview ] || fail "the agentsview archive is not one file named agentsview"
    tar -xzf "${tmp}/agentsview.tar.gz" -C "${tmp}" agentsview
    install -D -m 0755 "${tmp}/agentsview" "${HOME}/.local/libexec/meridian/agentsview"
    rm -rf "${tmp}"
  fi
  cat > "${HOME}/.local/bin/agentsview.new" <<SH
#!/bin/sh
# Written by deploy/wsl/setup.sh dsh: agentsview ${AGENTSVIEW_VERSION} with its telemetry and update check off.
AGENTSVIEW_TELEMETRY_ENABLED=0 DO_NOT_TRACK=1 AGENTSVIEW_DISABLE_UPDATE_CHECK=1 exec '${HOME}/.local/libexec/meridian/agentsview' "\$@"
SH
  chmod 0755 "${HOME}/.local/bin/agentsview.new"
  mv "${HOME}/.local/bin/agentsview.new" "${HOME}/.local/bin/agentsview"
}

# dsh_row CONFIG ID: the lines of one row of `dsh --dump-config`, up to the next row.
dsh_row() { printf '%s\n' "$1" | awk -v id="- id: $2" '$0 == id { f = 1; next } /^- / { f = 0 } f'; }

check_dsh() {
  version_ge "$(dsh_version)" "${DSH_VERSION}" \
    || fail "DeepSeek Harness is older than ${DSH_VERSION} or missing (run: deploy/wsl/setup.sh dsh)"
  version_ge "$(dsh_tui_version)" "${DSH_TUI_VERSION}" \
    || fail "dsh-tui is older than ${DSH_TUI_VERSION} or not installed in its profile"
  jq -e '.completed == true and (.version | type) == "number" and .version >= 1' \
    "${HOME}/.dsh-tui/onboarding.json" >/dev/null \
    || fail "dsh-tui's first-run guide is not completed (run: deploy/wsl/setup.sh dsh)"
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
  # The session model: the pinned row, in effect. A /model pick in dsh-tui outranks it and is
  # kept in ~/.dsh-tui/model.json, so that file is absent or names the same route.
  grep -qxF -- '- id: agent-default-model' "${HOME}/.dsh/cordis.patch.yml" \
    || fail "the model is not pinned in ~/.dsh/cordis.patch.yml (run: deploy/wsl/setup.sh dsh)"
  [ "$(dsh_row "${config}" agent-default-model \
    | grep -c -x -e "    model: ${DSH_MODEL}" -e '    provider: deepseek-official')" = 2 ] \
    || fail "DeepSeek Harness's default model is not deepseek-official/${DSH_MODEL}"
  local pick="${HOME}/.dsh-tui/model.json"
  [ ! -e "${pick}" ] \
    || jq -e --arg model "${DSH_MODEL}" '.provider == "deepseek-official" and .model == $model' "${pick}" >/dev/null 2>&1 \
    || fail "${pick} picks another model than deepseek-official/${DSH_MODEL}"
  check_dsh_stack "${config}"
  ok "DeepSeek Harness $(dsh_version) with dsh-tui $(dsh_tui_version): ${DSH_MODEL}; uploads to DeepSeek off, no plugin tools"
}

# dsh_rows_named CONFIG PACKAGE: every row of `dsh --dump-config` that mounts PACKAGE.
dsh_rows_named() {
  printf '%s\n' "$1" | awk -v name="  name: '$2'" '
    /^- / { if (hit) printf "%s", row; row = ""; hit = 0 }
    { row = row $0 "\n"; if ($0 == name) hit = 1 }
    END { if (hit) printf "%s", row }'
}

# check_dsh_stack CONFIG: the worker stack of ADR 0016 is what setup.sh pins and writes.
check_dsh_stack() {
  local config="$1" entry repo commit path dir row patch="${HOME}/.dsh/cordis.patch.yml" run="run: deploy/wsl/setup.sh dsh"
  python3 -I - "${patch}" <<'PY' || fail "~/.dsh/cordis.patch.yml has no single Meridian block above Orca's block (${run})"
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
ours = [i for i, line in enumerate(lines) if line.startswith("# >>> meridian-managed")]
orca = [i for i, line in enumerate(lines) if line.startswith("# >>> orca-managed-dsh-hooks")]
sys.exit(0 if len(ours) == 1 and (not orca or ours[0] < orca[0]) else 1)
PY
  # No MCP server; the LSP rows and the gate are mounted, and none of them is switched off.
  [ -z "$(dsh_rows_named "${config}" @deepseek-ai/dsh-mcp-client)" ] \
    || fail "dsh's configuration names an MCP server (ADR 0016 adds none)"
  for row in meridian-lsp:dsh-lsp meridian-lsp-pyright:dsh-lsp-stdio meridian-tool-lsp:dsh-tool-lsp \
    meridian-check-gate:dsh-hooks-claude-code; do
    dsh_row "${config}" "${row%%:*}" | grep -qxF "  name: '@deepseek-ai/${row#*:}'" \
      || fail "the ${row%%:*} row is not in dsh's configuration (${run})"
    ! dsh_row "${config}" "${row%%:*}" | grep -qx '  disabled: true' \
      || fail "the ${row%%:*} row is switched off in the dsh-tui profile"
  done
  # The dump folds a long argument over lines, so the row's lines are joined before matching.
  dsh_row "${config}" meridian-lsp-pyright | tr -s ' \n' '  ' \
    | grep -qF "exec python3 -I ${HOME}/.dsh/lsp/dsh-lsp-root.py \"\$top\" \"\$top/.venv/bin/pyright-langserver\" --stdio" \
    && cmp -s "$(dirname "$(readlink -f "$0")")/dsh-lsp-root.py" "${HOME}/.dsh/lsp/dsh-lsp-root.py" \
    || fail "the LSP provider does not run the worktree's own pyright-langserver at its root (${run})"
  for row in "${DSH_LSP_PACKAGES[@]}"; do
    version_ge "$(dsh_profile_package "${row}")" "${DSH_VERSION}" \
      || fail "@deepseek-ai/${row} is not in the dsh-tui profile (${run})"
  done
  # dsh 0.2.2-rc.2 and newer delete a Session's eligible worktrees when it is archived, unless
  # the worktree plugin retains them. dsh updates itself, so this fails until that is set.
  if version_ge "$(dsh_version)" 0.2.2-rc.2 \
    && [ -n "$(dsh_rows_named "${config}" @deepseek-ai/dsh-experimental-worktree)" ] \
    && ! dsh_rows_named "${config}" @deepseek-ai/dsh-experimental-worktree | grep -qx '    retainOnArchive: true'; then
    fail "dsh $(dsh_version) deletes worktrees on archive: set retainOnArchive: true on its worktree plugin (ADR 0016)"
  fi
  # Skills: exactly the pinned folders, each the same as its checkout at the pinned commit.
  [ "$(find "${HOME}/.dsh/skills" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | sort)" = "$(dsh_skill_names)" ] \
    || fail "~/.dsh/skills does not hold exactly the pinned skills (${run})"
  for entry in "${DSH_SKILLS[@]}"; do
    read -r repo commit _ <<<"${entry}"
    dir="${HOME}/.local/share/meridian/dsh-skill-src/${repo/\//__}"
    [ "$(git -C "${dir}" rev-parse HEAD 2>/dev/null)" = "${commit}" ] && [ -z "$(git -C "${dir}" status --porcelain)" ] \
      || fail "the ${repo} checkout is not clean at ${commit} (${run})"
    for path in ${entry#* * }; do
      diff -rq "${dir}/${path}" "${HOME}/.dsh/skills/${path##*/}" >/dev/null \
        || fail "~/.dsh/skills/${path##*/} differs from ${repo} at ${commit} (${run})"
    done
  done
  [ "$(ast_grep_version)" = "${AST_GREP_VERSION}" ] || fail "ast-grep is not ${AST_GREP_VERSION} (${run})"
  [ ! -e "${HOME}/.local/bin/sg" ] || fail "~/.local/bin/sg exists: it would shadow the system's sg"
  [ "$(agentsview_version "${HOME}/.local/libexec/meridian/agentsview")" = "${AGENTSVIEW_VERSION}" ] \
    && grep -qF "exec '${HOME}/.local/libexec/meridian/agentsview'" "${HOME}/.local/bin/agentsview" \
    && grep -q 'AGENTSVIEW_TELEMETRY_ENABLED=0' "${HOME}/.local/bin/agentsview" \
    && [ "$("${HOME}/.local/bin/agentsview" --version 2>/dev/null </dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)" = "${AGENTSVIEW_VERSION}" ] \
    || fail "agentsview is not ${AGENTSVIEW_VERSION} behind its telemetry-off wrapper (${run})"
  cmp -s "$(dirname "$(readlink -f "$0")")/dsh-check-gate.sh" "${HOME}/.dsh/hooks/dsh-check-gate.sh" \
    && jq -e --arg command "${HOME}/.dsh/hooks/dsh-check-gate.sh" \
      '.hooks | keys == ["Stop"] and .Stop[0].hooks[0].command == $command' "${HOME}/.dsh/meridian-hooks.json" >/dev/null \
    || fail "the completion gate is not the repository's copy (${run})"
  ok "dsh stack: $(dsh_skill_names | wc -l) skills, the lsp tool, ast-grep ${AST_GREP_VERSION}, agentsview ${AGENTSVIEW_VERSION}, completion gate"
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
  say "GH_TELEMETRY=0 ${bin}/gh auth status" "GitHub" "gh auth login"
  say "${bin}/claude auth status" "Claude Code" "claude auth login"
  say "${bin}/codex login status" "Codex" "codex login --device-auth"
  say "[ -e ${HOME}/.gemini/antigravity-cli/antigravity-oauth-token ]" "Antigravity" "agy acp --login"
  echo "check  Antigravity telemetry, in the first interactive agy: under 'Terms of Service & Data Use' make sure 'Yes, I agree to help improve...' is not ticked, then /config: Enable Telemetry off (saved with the Google account; agents-check cannot see it)"
  say "[ -s ${HOME}/.dsh/.env ]" "DeepSeek API key" \
    "install -d -m 700 ~/.dsh && ( umask 077 && read -rsp 'DeepSeek API key: ' k && echo && printf 'DEEPSEEK_API_KEY=%s\\n' \"\$k\" > ~/.dsh/.env && unset k )"
  echo "once   Orca window, in Windows Terminal: deploy/wsl/setup.sh orca-pair   (the link it prints grants shell access: paste it only into the Windows app)"
}

cmd_repo() {
  if [ ! -d "${REPO_DIR}/.git" ]; then
    gh_cli auth status >/dev/null 2>&1 || fail "sign in first: gh auth login"
    mkdir -p "$(dirname "${REPO_DIR}")"
    gh_cli repo clone "${REPO}" "${REPO_DIR}"
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

# Upkeep. Three pieces close the loop the weekly landscape watch opens (deploy/landscape_watch.py
# reports new releases in the GitHub issue labelled `landscape`):
#   drift            installed against pinned and upstream's newest; exit 0 when something is due
#   upkeep           this machine to the pins, and Claude Code to its newest release
#   orca-automation  a weekly Orca automation: when drift says so, a worker moves the pins, has
#                    another model family review the change, lands it through the lead's merge
#                    gate (which owns the shared landing lock), and applies it with upkeep
drift_report() {
  # stdin: one "name installed pinned newest" line per runtime; "-" stands for "not installed"
  # or "not read". Returns 0 when a runtime is off its pin or upstream has a newer release.
  local name have pin newest state due=1
  while read -r name have pin newest; do
    if [ "${have}" = "${pin}" ]; then
      state="at the pin"
    elif [ "${have}" != "-" ] && version_ge "${have}" "${pin}"; then
      state="ahead of the pin"
      due=0
    else
      state="behind the pin"
      due=0
    fi
    if [ "${newest}" != "-" ] && [ "${newest}" != "${pin}" ] && version_ge "${newest}" "${pin}"; then
      state="${state}; upstream has ${newest}"
      due=0
    fi
    printf '%-12s installed %-12s pinned %-12s %s\n' "${name}" "${have}" "${pin}" "${state}"
  done
  return "${due}"
}

claude_hud_version() {
  jq -r '.plugins["claude-hud@claude-hud"][0].version // empty' "${HOME}/.claude/plugins/installed_plugins.json" 2>/dev/null
}

# The newest release of each runtime, read where its installer reads: Anthropic's release
# bucket, the npm registry, GitHub's latest release. A read that fails gives nothing.
newest_claude() { curl -fsS --max-time 20 "${CLAUDE_RELEASES}/latest"; }
newest_npm() { npm view "$1" version; }
newest_github() { gh_cli api "repos/$1/releases/latest" --jq '.tag_name | ltrimstr("v")'; }

cmd_drift() {
  # Nothing is installed or changed; it reads versions, upstream's newest releases and the list
  # of open issues. `drift --pull` is the scheduled precheck: it runs from the main checkout, so
  # it first fast-forwards that checkout and starts again from the script as it then is.
  local due=1 issue v
  if [ "${1:-}" = "--pull" ]; then
    git -C "$(dirname "$(readlink -f "$0")")" pull -q --ff-only \
      || echo "note: this checkout could not be fast-forwarded; its pins may be old"
    exec "$0" drift
  fi
  v() { local out; out="$("$@" 2>/dev/null </dev/null | head -n 1 || true)"; printf '%s' "${out:--}"; }
  drift_report <<EOF && due=0
claude-code $(v claude_version) ${CLAUDE_VERSION} $(v newest_claude)
codex $(v codex_version) ${CODEX_VERSION} $(v newest_npm @openai/codex)
agy $(v agy_version) ${AGY_VERSION} $(v newest_github google-antigravity/antigravity-cli)
dsh $(v dsh_version) ${DSH_VERSION} $(v newest_npm @deepseek-ai/dsh)
dsh-tui $(v dsh_tui_version) ${DSH_TUI_VERSION} $(v newest_npm @deepseek-harness-tui/dsh-tui)
orca $(v orca_version) ${ORCA_VERSION} $(v newest_github stablyai/orca)
gh $(v gh_version) ${GH_VERSION} $(v newest_github cli/cli)
ocr $(v ocr_version) ${OCR_VERSION} $(v newest_github alibaba/open-code-review)
claude-hud $(v claude_hud_version) ${CLAUDE_HUD_VERSION} $(v newest_github jarrodwatts/claude-hud)
EOF
  issue="$(cd "$(dirname "$(readlink -f "$0")")" && gh_cli issue list --label landscape --state open --json number --jq '.[0].number' 2>/dev/null || true)"
  if [ -n "${issue}" ]; then
    echo "the weekly landscape watch has an open report: issue #${issue}"
    due=0
  fi
  if upkeep_held; then
    echo "drift: on hold, so the weekly run does not start"
    return 1
  fi
  if [ "${due}" = 0 ]; then echo "drift: there is upkeep to do"; else echo "drift: nothing is due"; fi
  return "${due}"
}

# The hold: any session can pause upkeep and the weekly run while it has a hand-made state on
# this machine that an installer would undo. Write the reason into the file; remove it to resume.
UPKEEP_HOLD="${HOME}/.cache/meridian/upkeep.hold"
upkeep_held() {
  [ -s "${UPKEEP_HOLD}" ] || return 1
  echo "upkeep is on hold (${UPKEEP_HOLD}): $(head -n 3 "${UPKEEP_HOLD}")"
}

cmd_upkeep() {
  # Claude Code's own updater first (it checks its download itself, as in a session the owner
  # starts); then each installer, which does nothing when its runtime is at or ahead of the pin
  # and otherwise installs the pinned release with its checksum check. Orca's server goes last:
  # its service restarts for a few seconds, and the terminals stay, because they run in the
  # terminal daemon, whose scope outlives the service (cmd_orca; UPSTREAM.md, Weekly upkeep).
  if upkeep_held; then
    fail "upkeep installs nothing while it is on hold; remove the file when its reason is gone"
  fi
  "${HOME}/.local/bin/claude" update </dev/null || echo "note: claude update did not complete"
  cmd_gh
  cmd_ocr
  cmd_claude
  cmd_codex
  cmd_agy
  cmd_dsh
  cmd_codex_bridge
  cmd_claude_hud
  version_ge "$(orca_version)" "${ORCA_VERSION}" || cmd_orca
}

UPKEEP_NAME="Meridian upkeep"
UPKEEP_PRECHECK="${REPO_DIR}/deploy/wsl/setup.sh drift --pull"
UPKEEP_PROMPT='Weekly upkeep of the agent runtimes of this repository, from the report to the merged and applied change. You are the lead for this one change: read AGENTS.md and the `lead` skill first; their boundaries hold here.

Do this, in order:
1. Run `deploy/wsl/setup.sh upkeep`, then `deploy/wsl/setup.sh drift`. Read the open GitHub issue labelled `landscape`, if there is one. If nothing is due, say so and stop.
2. For each runtime that drift shows ahead of its pin or with a newer release upstream (Claude Code, Codex, Antigravity, DeepSeek Harness, dsh-tui, Orca, gh, open-code-review, claude-hud): read its release notes at the source, then move its pin in deploy/wsl/setup.sh with the checksum, integrity value or signed manifest its installer already checks, and bring its UPSTREAM.md row up to date in place. claude-hud moves only to a tag whose commit GitHub marks verified.
3. Claude Code: read its changelog between the old pin and the new one. For each setting or feature that is new, off by default and useful to this setup, either add it to claude_settings and check_claude with a test, or name it in the pull request as considered and left out, with the reason.
4. If Orca'"'"'s pin moves, the two copied skills move with it: after step 8 has installed the new server, refresh them the way .agents/skills/NOTICE.md describes, in a second small change landed the same way.
5. If a model newer than the lead or worker model ids in deploy/wsl/setup.sh is listed on its vendor'"'"'s models page, say so in the pull request. Do not change a model id.
6. Commit on this branch and prepare the pull request title and body file. The gate in the next step obtains the other model family review and records it.
7. Land it yourself through the merge gate from the main checkout `~/src/meridian` after `git pull --ff-only`. Register this branch with `register BRANCH --builder claude --task TASK_ID`, then run `auto BRANCH --builder claude TITLE BODY.md` as the `lead` skill describes. The gate runs the Codex review and holds `~/.cache/meridian/landing.lock` itself from `trial` through `land`; run the gate without an outer flock. Triage any `LEAD ACTION` candidates, record closures with `close`, fix confirmed defects, and retry `auto`; never go around it.
8. After the merge, fast-forward the main checkout (`git -C ~/src/meridian pull --ff-only`) and confirm it holds the merged pins. From there run `~/src/meridian/deploy/wsl/setup.sh upkeep`: it installs the moved pins, Orca'"'"'s server last (its service restarts for a few seconds; the terminals stay). Then run `~/src/meridian/deploy/wsl/setup.sh agents-check` and `~/src/meridian/deploy/wsl/setup.sh drift`, and put the three outputs in a closing comment on the pull request; a runtime that drift still shows behind its pin is a failure to report, not a success.

Never: merge or close any pull request but your own upkeep changes; start a lane (any `python -m meridian.` command); read or print a key or credential; edit anything under risk/ or a *.contract.json; add a plugin, skill or MCP server; change a model id; stop a process you did not start. Everything else a working session needs is allowed.'

upkeep_automation() {
  orca_cli automations list --json \
    | jq -c --arg name "${UPKEEP_NAME}" '[.result.automations // .automations // [] | .[] | select(.name == $name)][0] // empty'
}

cmd_orca_automation() {
  # Created once; afterwards its prompt and precheck follow this script, and its schedule is the
  # owner's to edit in Orca.
  local now id
  now="$(upkeep_automation)"
  if [ -z "${now}" ]; then
    orca_cli automations create --name "${UPKEEP_NAME}" \
      --trigger weekly --day 1 --time 07:00 --timezone America/New_York \
      --provider claude --extra-agent-args="--model claude-opus-5-5" \
      --repo "path:${REPO_DIR}" --setup run \
      --precheck "${UPKEEP_PRECHECK}" --precheck-timeout 120 \
      --prompt "${UPKEEP_PROMPT}" --enabled --json >/dev/null
  elif ! jq -e --arg prompt "${UPKEEP_PROMPT}" --arg precheck "${UPKEEP_PRECHECK}" \
      '.prompt == $prompt and .precheck.command == $precheck' <<<"${now}" >/dev/null; then
    id="$(jq -r '.id' <<<"${now}")"
    orca_cli automations edit "${id}" --precheck "${UPKEEP_PRECHECK}" --precheck-timeout 120 \
      --prompt "${UPKEEP_PROMPT}" --json >/dev/null
  fi
  check_orca_automation
}

check_orca_automation() {
  upkeep_automation | jq -e --arg prompt "${UPKEEP_PROMPT}" --arg precheck "${UPKEEP_PRECHECK}" '
    .enabled == true and .precheck.command == $precheck and .prompt == $prompt
  ' >/dev/null \
    || fail "the Orca automation \"${UPKEEP_NAME}\" is missing, disabled or not what this script sets (run: deploy/wsl/setup.sh orca-automation)"
  ok "Orca automation \"${UPKEEP_NAME}\": weekly, behind the drift precheck; it lands and applies its own change"
}

case "${1:-}" in
  check) cmd_check ;;
  uv) cmd_uv ;;
  gh) cmd_gh ;;
  gitleaks) cmd_gitleaks ;;
  ocr) cmd_ocr ;;
  claude) cmd_claude ;;
  codex) cmd_codex ;;
  agy) cmd_agy ;;
  dsh) cmd_dsh ;;
  orca) cmd_orca ;;
  codex-bridge) cmd_codex_bridge ;;
  codex-requirements) cmd_codex_requirements ;;
  claude-hud) cmd_claude_hud ;;
  omc) cmd_omc ;;
  omc-remove) cmd_omc_remove ;;
  drift) cmd_drift "${2:-}" ;;
  upkeep) cmd_upkeep ;;
  orca-automation) cmd_orca_automation ;;
  agents)
    cmd_claude
    cmd_codex
    cmd_agy
    cmd_dsh
    cmd_orca
    cmd_codex_bridge
    cmd_claude_hud
    ;;
  signins) cmd_signins ;;
  orca-pair) cmd_orca_pair ;;
  unattended) cmd_unattended ;;
  unattended-check) cmd_unattended_check ;;
  agents-check)
    check_gh
    check_gitleaks
    check_ocr
    check_claude
    check_omc --require-orca
    check_codex
    check_agy
    check_dsh
    check_orca
    check_codex_bridge
    check_claude_hud
    check_orca_automation
    ;;
  repo) cmd_repo ;;
  gateway) cmd_gateway ;;
  *) sed -n '2,34p' "$0"; exit 2 ;;
esac
