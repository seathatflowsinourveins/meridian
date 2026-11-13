#!/usr/bin/env bash
# Published copy (docs/adr/data/0003_coverage.sh): ran on 2026-11-13 as scripts/coverage.sh in the operator's
# work folder, written here as $WORK (a Windows temp folder, seen from WSL under /mnt/c; set WORK
# before running); the operator's home directory is written as $HOME. Otherwise unchanged.
# coverage.sh FILE... : which of the 18 package names appear (S1)
cat "$@" > /tmp/.cov.$$ 2>/dev/null
n=0
while IFS='|' read -r label re; do
  if grep -qiP "$re" /tmp/.cov.$$; then n=$((n+1)); else echo "MISSING $label"; fi
done <<'EOF'
colorama|colorama
iniconfig|iniconfig
nautilus-trader|nautilus[-_. ]?trader
nodeenv|nodeenv
nodejs-wheel-binaries|nodejs[-_.]wheel[-_.]binaries
packaging|(?<![\w-])packaging(?![\w-])
pluggy|pluggy
pygments|pygments
pyright|pyright
pytest|pytest
ruff|(?<![\w-])ruff(?![\w-])
typing-extensions|typing[-_.]extensions
@openai/codex|openai/codex
pnpm|(?<![\w-])pnpm(?![\w-])
@deepseek-ai/dsh|(deepseek-ai/dsh(?![\w-])|(?<![\w/@-])dsh(?![\w-]))
dsh-tui|dsh-tui
dsh-hooks-claude-code|dsh-hooks-claude-code
dsh-hook-protocol|dsh-hook-protocol
EOF
echo "covered=$n/18"
rm -f /tmp/.cov.$$
