#!/usr/bin/env bash
# Published copy (docs/adr/data/0003_r5_series.sh): ran on 2026-11-13 as scripts/r5_series.sh in the operator's
# work folder, written here as $WORK (a Windows temp folder, seen from WSL under /mnt/c; set WORK
# before running); the operator's home directory is written as $HOME. Otherwise unchanged.
# r5_series.sh "a 1 0" "b 1 1" ...  (letter n with)
S=$WORK/scripts
for spec in "$@"; do
  set -- $spec
  echo "=== $1-$2 start $(date -Is)"
  bash "$S/r5_run.sh" "$1" "$2" "$3"; rc=$?
  echo "=== $1-$2 rc=$rc end $(date -Is)"
  [ $rc = 3 ] && { echo "STOP: blocked: the IB Gateway came up"; exit 3; }
  [ $rc = 4 ] && { echo "STOP: abort"; exit 4; }
done
echo "=== series done $(date -Is)"
