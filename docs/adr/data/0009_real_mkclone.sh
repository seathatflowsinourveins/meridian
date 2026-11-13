#!/usr/bin/env bash
# mkclone.sh DEST -- a fresh tree of the public repository built from the task base alone
# (git init, shallow fetch of the base commit, checkout), then uv sync --locked.
# Later history, which holds the fix, is not in the clone.
set -euo pipefail
. "$(dirname "$0")/common.sh"
dest=$1
[ ! -e "$dest" ] || { echo "mkclone: $dest exists" >&2; exit 1; }
mkdir -p "$dest"; cd "$dest"
GITC init -q .
GITC fetch -q --depth 1 "$REPO_URL" "$BASE"
GITC -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
[ "$(git rev-parse HEAD)" = "$BASE" ] || { echo "mkclone: wrong HEAD" >&2; exit 2; }
[ "$(git rev-list --all | wc -l)" = 1 ] || { echo "mkclone: more than one commit" >&2; exit 2; }
if git cat-file -e "$FIX" 2>/dev/null; then echo "mkclone: the fix is in the object store" >&2; exit 2; fi
[ ! -e .env ] || { echo "mkclone: .env present" >&2; exit 2; }
uv sync --locked -q
echo "clone $dest HEAD $(git rev-parse HEAD) commits $(git rev-list --all | wc -l) status-lines $(git status --porcelain=v1 | wc -l)"
