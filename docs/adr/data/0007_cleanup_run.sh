#!/bin/bash
# Remove one run's throwaway clone and stand-in home after grading; keeps out/<run> (raw data).
# usage: bash cleanup_run.sh <run name, e.g. ab-0007-a-2>
set -u
RUN=$1
case "$RUN" in ab-0007-a-[0-9]*) ;; *) echo "refused: $RUN"; exit 2;; esac
A=$HOME/src/meridian-ab/0007
for d in "$A/wt/$RUN" "$A/fh/$RUN"; do
  if [ -e "$d" ]; then rm -rf -- "$d" && echo "removed $d"; else echo "absent $d"; fi
done
rmdir "$A/wt" "$A/fh" 2>/dev/null && echo "removed empty wt/ fh/" || true
echo "processes naming the run: $(pgrep -af "$RUN" | grep -v -e pgrep -e cleanup_run.sh | wc -l)"
echo "main checkout worktrees naming 0007: $(git -C "$HOME/src/meridian" worktree list | grep -c 0007)"
