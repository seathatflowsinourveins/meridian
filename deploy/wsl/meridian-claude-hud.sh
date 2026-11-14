#!/bin/sh
# Claude Code's status line command in the meridian distro (deploy/wsl/setup.sh claude-hud
# installs it as ~/.local/bin/meridian-claude-hud). Own design; two jobs on one payload:
#   1. hand the status JSON to Orca's reporter, which prints nothing and feeds Orca's usage
#      figures. Detached, so a slow or stopped Orca never delays the line;
#   2. print claude-hud's lines, or one plain line if claude-hud is missing or prints nothing.
# It never fails and never writes to stderr: Claude Code blanks the line on a non-zero exit.
# The installed name holds "claude-hud" (claude-hud's own doctor looks for it) and not
# "agent-hooks/claude-statusline" (Orca would take the command for its own and may rewrite it).
payload=
[ -t 0 ] || payload=$(cat 2>/dev/null)
orca="${HOME}/.orca/agent-hooks/claude-statusline.sh"
if [ -n "${payload}" ] && [ -x "${orca}" ]; then
  printf '%s' "${payload}" | setsid /bin/sh "${orca}" >/dev/null 2>&1 &
fi
hud="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/plugins/claude-hud/statusline.mjs"
out=
if [ -n "${payload}" ] && [ -r "${hud}" ]; then
  out=$(printf '%s' "${payload}" | timeout 5 node "${hud}" 2>/dev/null) || :
fi
if [ -z "${out}" ] && [ -n "${payload}" ]; then
  out=$(printf '%s' "${payload}" | jq -r '
    "[\(.model.display_name // "?")] \(.effort.level // "-")"
    + " | ctx \(.context_window.used_percentage // 0 | floor)%"
    + " | 5h \(.rate_limits.five_hour.used_percentage // "-")%"
    + " | 7d \(.rate_limits.seven_day.used_percentage // "-")%"
  ' 2>/dev/null) || :
fi
printf '%s\n' "${out}"
exit 0
