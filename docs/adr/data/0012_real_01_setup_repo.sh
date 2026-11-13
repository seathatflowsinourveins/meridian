#!/usr/bin/env bash
# 01_setup_repo.sh : the addition at its pin (as data), the task's base repository, seed caches.
# Network: unauthenticated git to github.com (two repositories) and PyPI once (uv sync).
# No model call, no dsh profile.
set -euo pipefail
. "$(dirname "$0")/00_env.sh"
[ "$(dsh --version </dev/null)" = "$WANT_VER" ] || { echo 'STOP: dsh changed'; exit 1; }
install -d -m 0700 "$EV/addition" "$EV/setup" "$EV/r" "$EV/w" "$EV/grade"

# 1. The addition, fetched as data at its pin, in its own folder outside ~/.dsh.
D="$EV/addition/dsh-early-stop-guard"
git init -q "$D"
GITC -C "$D" fetch -q --depth 1 "$ADD_URL" "$PIN"
git -C "$D" -c advice.detachedHead=false checkout -q FETCH_HEAD
[ "$(git -C "$D" rev-parse HEAD)" = "$PIN" ] || { echo "addition: not the pin"; exit 1; }
[ "$(git -C "$D" rev-parse 'HEAD^{tree}')" = "$PIN_TREE" ] || { echo "addition: tree differs"; exit 1; }
(cd "$D" && sha256sum lib/*.js package.json cordis.patch.yml) >"$EV/addition.sha256"
# Its two bare imports (@deepseek-ai/schemastery in config.js, @deepseek-ai/dsh-llm in index.js and
# providers.js) resolve by Node's own lookup from the clone: give each by symlink to the copy the
# installed dsh itself uses, so the host and the addition share one module instance.
install -d "$EV/addition/node_modules/@deepseek-ai"
for peer in schemastery dsh-llm; do
  src="$HOME/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/$peer"
  [ -d "$src" ] || { echo "missing peer $peer"; exit 1; }
  ln -s "$src" "$EV/addition/node_modules/@deepseek-ai/$peer"
done

# 2. The base repository: the task's base commit alone, plus one local commit T with the fix
#    commit's tests/ laid over it (the task sheet's "git checkout <fix> -- tests/"). The clone
#    that holds the fix commit is used for this and for the reference check, then deleted.
F="$EV/setup/fixsrc"; git init -q "$F"; GITC -C "$F" fetch -q --depth 1 "$URL" "$FIX"
Bq="$EV/base"; git init -q "$Bq"; GITC -C "$Bq" fetch -q --depth 1 "$URL" "$BASE"
git -C "$Bq" -c advice.detachedHead=false checkout -q FETCH_HEAD
git -C "$Bq" checkout -q -b task
[ "$(git -C "$Bq" rev-parse HEAD)" = "$BASE" ]
git -C "$F" archive "$FIX" tests/ | tar -x -C "$Bq"
git -C "$Bq" add -A tests
git -C "$Bq" -c user.name=ab-setup -c user.email=ab-setup@invalid commit -q -m 'Task setup: tests'
git -C "$Bq" rev-parse HEAD >"$EV/T.txt"
if git -C "$Bq" cat-file -e "$FIX^{commit}" 2>/dev/null; then echo "base holds the fix commit"; exit 1; fi
echo "T=$(cat "$EV/T.txt") tests tree T=$(git -C "$Bq" rev-parse HEAD:tests) fix=$(git -C "$F" rev-parse FETCH_HEAD:tests)" | tee "$EV/setup/base.txt"
git -C "$F" show "$FIX:meridian/boundary.py" >"$EV/setup/ref-boundary.py"   # reference fix, setup only

# 3. Seed caches, made once and copied into every run and grade folder (so no run downloads).
S="$EV/setup/seed"; V="$EV/setup/seedwt"; install -d -m 0700 "$S"
git clone -q --no-local "$Bq" "$V"; git -C "$V" remote remove origin
(cd "$V" && UV_CACHE_DIR="$S/uv" uv sync --locked -q)
(cd "$V" && env $(task_env "$EV/setup/seed-probe") UV_CACHE_DIR="$S/uv" uv run pyright --version)
[ ! -e "$EV/setup/seed-probe" ]   # pyright wrote no cache of its own
du -sh "$S/uv"
# 4. The brief: ADR 0012's published copy of the task sheet's R2 brief, no final newline.
cp "$HOME/src/meridian-worktrees/l2-adr-ecosystem/docs/adr/data/0012-brief-R2.txt" "$EV/brief.txt"
[ "$(sha256sum <"$EV/brief.txt" | cut -d' ' -f1)" = "$BRIEF_SHA" ] || { echo "brief: sha256 differs"; exit 1; }
echo "setup_repo done $(date -Is)"
