#!/usr/bin/env bash
# 0011r_mkwt.sh DEST CACHE
# A fresh checkout for R2 (ab-tasks.md): base 96e82e6 with the tests of 39cb68e, then uv sync --locked.
# SRC = an unauthenticated clone of the public repository that has a branch ab-r2-base at the base.
# The checkout is a shallow clone that holds the base commit only; tests/ comes from an archive of the
# fix commit taken in SRC and is staged, which gives the same index and files as
# "git checkout 39cb68e -- tests/" without putting the fix commit into the run's own .git.
# CACHE gets uv's cache and pyright's node package, so that a run needs neither the home folder
# nor a download for them.
set -euo pipefail
dest=$1 cache=$2
: "${SRC:?set SRC to the source clone}"
BASE=96e82e6b521cdb9c7d172176898d20e2658ec50b
FIX=39cb68ea3241caeececb6db0521a12ea2fa92fee
[ ! -e "$dest" ] || { echo "mkwt: $dest exists" >&2; exit 64; }
install -d -m 0700 "$cache/uv" "$cache/xdg"
GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c advice.detachedHead=false clone -q --no-local --depth 1 \
  --branch ab-r2-base "file://$SRC" "$dest"
git -C "$dest" checkout -q --detach
git -C "$dest" branch -q -D ab-r2-base
git -C "$dest" remote remove origin
[ "$(git -C "$dest" rev-parse HEAD)" = "$BASE" ] || { echo "mkwt: HEAD is not the base" >&2; exit 65; }
if git -C "$dest" cat-file -e "$FIX" 2>/dev/null; then echo "mkwt: the fix commit is in the checkout" >&2; exit 66; fi
git -C "$SRC" archive "$FIX" tests | tar -x -C "$dest"
git -C "$dest" add -A tests
# same tests/ tree as the fix commit
[ "$(git -C "$dest" write-tree --prefix=tests/)" = "$(git -C "$SRC" rev-parse "$FIX:tests")" ] \
  || { echo "mkwt: tests/ differs from the fix commit's" >&2; exit 67; }
( cd "$dest" && UV_CACHE_DIR="$cache/uv" uv sync --locked -q )
( cd "$dest" && UV_CACHE_DIR="$cache/uv" XDG_CACHE_HOME="$cache/xdg" PYRIGHT_PYTHON_IGNORE_WARNINGS=1 \
    uv run --no-sync pyright --version >/dev/null )
echo "mkwt: $dest ready at $(git -C "$dest" rev-parse --short HEAD), tests from ${FIX:0:7}"
