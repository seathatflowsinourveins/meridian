#!/usr/bin/env bash
# meridian: user-level setup inside the distro, after cloud-init has finished.
# Run as the owner user, never as root.
#
#   deploy/wsl/setup.sh check    verify what deploy/wsl/meridian.user-data was meant to do
#   deploy/wsl/setup.sh uv       install uv (pinned; installer checksum verified first)
#   deploy/wsl/setup.sh claude   install Claude Code with the native installer
#   deploy/wsl/setup.sh repo     clone the repo to ~/src/meridian and run `uv sync --locked`
#   deploy/wsl/setup.sh gateway  install IB Gateway (pinned build; never starts it or logs in)
#
# Order: check, uv, repo, gateway, then claude last.
# Versions, checksums and the pages they were read from: UPSTREAM.md.
set -euo pipefail

UV_VERSION=0.13.7
UV_INSTALLER_SHA256=d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4
CLAUDE_VERSION=2.1.322
NODE_VERSION=v24.22.3
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
  for pkg in git gh build-essential curl jq unzip; do
    dpkg -s "${pkg}" >/dev/null 2>&1 || fail "package ${pkg} is missing"
  done
  ok "packages: git gh build-essential curl jq unzip"
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
  jq -e '.disableClaudeAiConnectors == true' /etc/claude-code/managed-settings.json >/dev/null \
    || fail "disableClaudeAiConnectors is not true in /etc/claude-code/managed-settings.json"
  ok "claude.ai connectors disabled for Claude Code in this distro (user and machine-wide settings)"
  echo "note: that setting does not cover connectors the Claude desktop app itself attaches to a session"
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
  # No shell files are edited: Ubuntu's ~/.profile already puts ~/.local/bin on PATH.
  UV_NO_MODIFY_PATH=1 sh "${tmp}/uv-installer.sh"
  rm -rf "${tmp}"
  "${HOME}/.local/bin/uv" --version
}

cmd_claude() {
  # Asks the installer for this version. The installer script itself is whatever
  # claude.ai serves, and Claude Code updates itself afterwards, so this is the version
  # at install time, not a lasting pin.
  curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}"
  "${HOME}/.local/bin/claude" --version
  jq -e '.disableClaudeAiConnectors == true' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "disableClaudeAiConnectors is no longer true after the install"
  ok "claude.ai connectors still disabled for terminal sessions"
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
  claude) cmd_claude ;;
  repo) cmd_repo ;;
  gateway) cmd_gateway ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
