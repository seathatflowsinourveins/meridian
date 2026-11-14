#!/usr/bin/env bash
# Completion gate for DeepSeek Harness (own design; docs/adr/0016-dsh-worker-stack.md): a Stop
# hook, run by a second mount of @deepseek-ai/dsh-hooks-claude-code beside Orca's. setup.sh dsh
# installs a copy as ~/.dsh/hooks/dsh-check-gate.sh.
#
# When a dsh turn ends in this repository with uncommitted changes, run the check line. A pass,
# a clean tree or another repository lets the turn end. A failure blocks the stop once with the
# failing output as the reason, which dsh gives the model as its next step. The bridge has no cap
# of its own (stop_hook_active is always false), so the gate counts its blocks per session and
# lets the turn end after DSH_GATE_MAX_BLOCKS of them (2); a pass resets the count. If the count
# cannot be kept (a read-only git directory), the gate does not block.
#
# stdin: the hook's JSON (session_id, cwd). stdout: nothing, or one block decision.
set -uo pipefail

max="${DSH_GATE_MAX_BLOCKS:-2}"
input="$(cat)"
session="$(jq -r '.session_id // empty' <<<"${input}" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"${input}" 2>/dev/null)"
top="$(git -C "${cwd:-.}" rev-parse --show-toplevel 2>/dev/null)" || exit 0
# This repository only: its check line is the one below.
[ -f "${top}/meridian/boundary.py" ] && [ -f "${top}/size-budget.toml" ] || exit 0
[ -n "$(git -C "${top}" status --porcelain 2>/dev/null)" ] || exit 0

state="$(git -C "${top}" rev-parse --absolute-git-dir)/meridian-check-gate"
count_file="${state}/$(printf '%s' "${session:-unknown}" | tr -c 'A-Za-z0-9_-' '_')"
count="$(cat "${count_file}" 2>/dev/null || echo 0)"
case "${count}" in '' | *[!0-9]*) count=0 ;; esac

output="$(cd "${top}" && {
  uv sync --locked -q && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
} 2>&1)"
if [ $? -eq 0 ]; then
  rm -f "${count_file}"
  exit 0
fi
if [ "${count}" -ge "${max}" ]; then
  echo "dsh-check-gate: the check line still fails after ${max} blocks; letting the turn end" >&2
  exit 0
fi
mkdir -p "${state}" 2>/dev/null && printf '%s\n' $((count + 1)) > "${count_file}" 2>/dev/null || exit 0
jq -n --arg tail "$(tail -n 40 <<<"${output}")" --arg n "$((count + 1))" --arg max "${max}" '{
  decision: "block",
  reason: ("The check line fails on your uncommitted changes (gate block \($n) of \($max)). Fix the cause and run it again: uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest\n\nLast lines of its output:\n" + $tail)
}'
