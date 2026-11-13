#!/usr/bin/env bash
# 0011r_grade.sh RUNDIR [PATCHFILE]
# Grades one R2 run by ab-tasks.md: the run's change to meridian/boundary.py, taken as a patch against
# the base, is applied to a fresh checkout set up the same way, and must pass
#   uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
# (pytest with HOME set to an empty folder). The run's own checkout must have tests/ equal to the fix
# commit's and no change outside meridian/boundary.py (the addition's .goal-gate/ is left out).
# A run passes when, in addition, dsh exited 0 and its final reason is "completed".
# With PATCHFILE (validation only) there is no run checkout: the patch is replayed and nothing else.
# Writes RUNDIR/grade.json and RUNDIR/patch.diff; logs in RUNDIR/grade/.
set -uo pipefail
R=$1; given=${2:-}
EV=$HOME/src/meridian-ab/0011/real; MY=$EV/scripts; SRC=$EV/src
BASE=96e82e6b521cdb9c7d172176898d20e2658ec50b
FIX=39cb68ea3241caeececb6db0521a12ea2fa92fee
W=$R/wt; G=$R/grade
[ ! -e "$G" ] || { echo "grade: $G exists" >&2; exit 64; }
install -d -m 0700 "$G/home"
tests_ok=null; scope_ok=null; exit_code=null; reason=null
if [ -z "$given" ]; then
  git -C "$W" diff --binary "$BASE" -- meridian/boundary.py >"$R/patch.diff"
  # tests/ file by file against the fix commit's tree (read in the source clone), and no extra file
  tests_ok=true; : >"$G/tests-diff.txt"
  while IFS=$' \t' read -r _mode _type oid path; do
    [ "$(git -C "$W" hash-object "$W/$path" 2>/dev/null)" = "$oid" ] || { tests_ok=false; echo "differs: $path" >>"$G/tests-diff.txt"; }
  done < <(git -C "$SRC" ls-tree -r "$FIX" -- tests)
  want=$(git -C "$SRC" ls-tree -r "$FIX" -- tests | wc -l)
  have=$(cd "$W" && find tests -type f ! -name '*.pyc' | wc -l)
  [ "$want" -eq "$have" ] || { tests_ok=false; echo "file count: fix $want, run $have" >>"$G/tests-diff.txt"; }
  other=$( { git -C "$W" diff --name-only "$BASE" --; git -C "$W" ls-files --others --exclude-standard; } \
    | sort -u | grep -v -E '^tests/|^meridian/boundary\.py$|^\.goal-gate/' || true )
  printf '%s\n' "$other" >"$G/other-changes.txt"
  if [ -z "$other" ]; then scope_ok=true; else scope_ok=false; fi
  exit_code=$(sed -n 's/^exit=//p' "$R/exit.txt")
  reason=$(jq -c 'select(.type=="final") | .reason.kind // null' "$R/out.jsonl" 2>/dev/null | tail -n 1)
  [ -n "$reason" ] || reason=null
else
  cp "$given" "$R/patch.diff"
fi
patch_bytes=$(wc -c <"$R/patch.diff")
apply_rc=null; rc_ruff_check=null; rc_ruff_format=null; rc_pyright=null; rc_pytest=null; pytest_tail=""
if SRC=$SRC "$MY/0011r_mkwt.sh" "$G/wt" "$G/cache" >"$G/mkwt.log" 2>&1; then
  if [ "$patch_bytes" -gt 0 ]; then
    git -C "$G/wt" apply --whitespace=nowarn "$R/patch.diff" >"$G/apply.log" 2>&1; apply_rc=$?
  else
    apply_rc=0
  fi
  E=(env HOME="$G/home" UV_CACHE_DIR="$G/cache/uv" PYRIGHT_PYTHON_IGNORE_WARNINGS=1)
  ( cd "$G/wt" && "${E[@]}" uv run ruff check . ) >"$G/ruff-check.log" 2>&1; rc_ruff_check=$?
  ( cd "$G/wt" && "${E[@]}" uv run ruff format --check . ) >"$G/ruff-format.log" 2>&1; rc_ruff_format=$?
  ( cd "$G/wt" && "${E[@]}" uv run pyright ) >"$G/pyright.log" 2>&1; rc_pyright=$?
  ( cd "$G/wt" && "${E[@]}" uv run pytest -q ) >"$G/pytest.log" 2>&1; rc_pytest=$?
  pytest_tail=$(tail -n 1 "$G/pytest.log")
else
  echo "grade: the fresh checkout could not be made" >&2
fi
rm -rf "$G/wt" "$G/cache" "$G/home"
jq -n --argjson patch_bytes "$patch_bytes" --argjson tests_ok "$tests_ok" --argjson scope_ok "$scope_ok" \
  --argjson exit_code "${exit_code:-null}" --argjson reason "$reason" --argjson apply_rc "$apply_rc" \
  --argjson ruff_check "$rc_ruff_check" --argjson ruff_format "$rc_ruff_format" \
  --argjson pyright "$rc_pyright" --argjson pytest "$rc_pytest" --arg pytest_tail "$pytest_tail" \
  --arg patch_sha256 "$(sha256sum <"$R/patch.diff" | cut -d' ' -f1)" --argjson validation "$([ -n "$given" ] && echo true || echo false)" '
  {patch_bytes: $patch_bytes, patch_sha256: $patch_sha256, tests_unchanged: $tests_ok, scope_ok: $scope_ok,
   dsh_exit: $exit_code, final_reason: $reason, replay: {apply: $apply_rc, ruff_check: $ruff_check,
   ruff_format: $ruff_format, pyright: $pyright, pytest: $pytest, pytest_tail: $pytest_tail}}
  | .checks_pass = ($patch_bytes > 0 and $apply_rc == 0 and $ruff_check == 0 and $ruff_format == 0 and $pyright == 0 and $pytest == 0)
  | .passed = (if $validation then .checks_pass
               else (.checks_pass and $tests_ok == true and $scope_ok == true and $exit_code == 0 and $reason == "completed") end)
' >"$R/grade.json"
cat "$R/grade.json"
