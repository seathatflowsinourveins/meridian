#!/usr/bin/env bash
# meridian: user-level setup inside the distro, after cloud-init has finished.
# Run as the owner user, never as root.
#
#   deploy/wsl/setup.sh check    verify what deploy/wsl/meridian.user-data was meant to do
#   deploy/wsl/setup.sh uv       install uv (pinned; installer checksum verified first)
#   deploy/wsl/setup.sh claude   install Claude Code with the native installer (pinned)
#   deploy/wsl/setup.sh repo     clone the repo to ~/src/meridian and run `uv sync --locked`
#
# Order: check, uv, repo. `claude` comes only after the Sextant harvest is done or skipped.
# Versions, checksums and the pages they were read from: UPSTREAM.md.
set -euo pipefail

UV_VERSION=0.13.7
UV_INSTALLER_SHA256=d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4
CLAUDE_VERSION=2.1.322
NODE_VERSION=v24.22.3
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
  ok "service user paper (no login)"
  case ":${PATH}:" in
    *:/mnt/c/*) fail "Windows PATH is appended (appendWindowsPath should be false)" ;;
  esac
  ok "Windows PATH not appended"
  for pkg in git gh build-essential curl jq unzip; do
    dpkg -s "${pkg}" >/dev/null 2>&1 || fail "package ${pkg} is missing"
  done
  ok "packages: git gh build-essential curl jq unzip"
  [ "$(node --version)" = "${NODE_VERSION}" ] || fail "node is $(node --version 2>/dev/null), expected ${NODE_VERSION}"
  ok "node ${NODE_VERSION}"
  jq -e '.disableClaudeAiConnectors == true' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "disableClaudeAiConnectors is not true in ~/.claude/settings.json"
  ok "claude.ai connectors disabled in ~/.claude/settings.json"
}

cmd_uv() {
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSLo "${tmp}/uv-installer.sh" "https://astral.sh/uv/${UV_VERSION}/install.sh"
  echo "${UV_INSTALLER_SHA256}  ${tmp}/uv-installer.sh" | sha256sum -c -
  sh "${tmp}/uv-installer.sh"
  rm -rf "${tmp}"
  "${HOME}/.local/bin/uv" --version
}

cmd_claude() {
  # The installer checks the binary against the release manifest's SHA256 itself.
  curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}"
  "${HOME}/.local/bin/claude" --version
  jq -e '.disableClaudeAiConnectors == true' "${HOME}/.claude/settings.json" >/dev/null \
    || fail "disableClaudeAiConnectors is no longer true after the install"
  ok "claude.ai connectors still disabled"
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

case "${1:-}" in
  check) cmd_check ;;
  uv) cmd_uv ;;
  claude) cmd_claude ;;
  repo) cmd_repo ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac
