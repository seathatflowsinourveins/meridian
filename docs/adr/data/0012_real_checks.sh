#!/usr/bin/env bash
# checks.sh DIR OUTDIR : the task's four checks in DIR, every one run, each exit code printed.
# The grade passes when all four exit 0 (the same as the task sheet's && chain exiting 0).
cd "$1" || exit 99
out=$2; all=0; i=0
for c in "uv run ruff check ." "uv run ruff format --check ." "uv run pyright" "uv run pytest"; do
  i=$((i + 1))
  $c >"$out/check$i.out" 2>&1; rc=$?
  echo "check$i rc=$rc cmd=$c"
  [ "$rc" -eq 0 ] || all=1
done
echo "all=$all"
exit "$all"
