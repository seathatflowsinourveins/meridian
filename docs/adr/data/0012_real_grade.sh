#!/usr/bin/env bash
# grade.sh NAME [PATCHFILE] : the task sheet's grade (R1's, applied to R2).
# A fresh clone of the base repository, set up as a run's checkout is; the patch (changes to
# meridian/boundary.py only) applied; then the four checks, run where the code under test can
# reach nothing of the owner's: its own mount namespace with the Windows drives, Windows interop
# and the real home hidden (only ~/.local, read-only, for uv and Python), no network, an empty
# HOME, and an environment built from scratch (no DSH_* and no key name in it).
set -euo pipefail
. "$(dirname "$0")/00_env.sh"
name=$1; patch=${2:-}
g="$EV/grade/$name"
[ ! -e "$g" ] || { echo "grade: $g exists" >&2; exit 64; }
install -d -m 0700 "$g" "$g/home" "$g/tmp" "$g/cache" "$g/out"
git clone -q --no-local "$EV/base" "$g/wt"
git -C "$g/wt" remote remove origin
cp -a "$EV/setup/seed/uv" "$g/cache/uv"
(cd "$g/wt" && env $(task_env "$g") uv sync --locked --offline -q) >"$g/out/sync.out" 2>&1
if [ -n "$patch" ] && [ -s "$patch" ]; then
  cp "$patch" "$g/patch.diff"
  # only meridian/boundary.py may be in the patch
  if [ "$(git -C "$g/wt" apply --numstat "$g/patch.diff" | cut -f3 | sort -u)" != "meridian/boundary.py" ]; then
    echo "apply=refused (the patch touches more than meridian/boundary.py)" | tee "$g/grade.txt"; exit 3
  fi
  git -C "$g/wt" apply "$g/patch.diff" || { echo "apply=failed" | tee "$g/grade.txt"; exit 3; }
  echo "apply=ok" >"$g/grade.txt"
else
  echo "apply=none (no change to grade)" >"$g/grade.txt"
fi
real=$(getent passwd "$(id -un)" | cut -d: -f6)
hide=(--tmpfs /mnt); [ -d /run/WSL ] && hide+=(--tmpfs /run/WSL)
set +e
bwrap --dev-bind / / "${hide[@]}" --tmpfs "$real" --ro-bind "$real/.local" "$real/.local" \
      --ro-bind "$SC" "$SC" --bind "$g" "$g" --unshare-net --die-with-parent -- \
  env -i PATH="$PATH" LANG=C.UTF-8 HOME="$g/home" TMPDIR="$g/tmp" UV_OFFLINE=1 $(task_env "$g") \
  timeout --signal=INT --kill-after=30 900 bash "$SC/checks.sh" "$g/wt" "$g/out" >>"$g/grade.txt" 2>&1
rc=$?
set -e
echo "grade_exit=$rc" >>"$g/grade.txt"
cat "$g/grade.txt"
exit "$rc"
