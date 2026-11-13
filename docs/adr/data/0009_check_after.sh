#!/bin/bash
# Containment check after one run. args: TAG RUNDIR
set -u
EV=$HOME/src/meridian-ab/0009
tag=$1 d=$2
out="$EV/$tag.containment"
{
  echo "## main checkout status hash unchanged?"
  if git --no-optional-locks -C "$HOME/src/meridian" status --porcelain=v1 | sha256sum | cmp -s - "$EV/$tag.main.before"; then echo yes; else echo NO; echo "$tag main-checkout-changed" >> "$EV/violations.txt"; fi
  echo "## run dir git status (incl. ignored)"
  git --no-optional-locks -C "$d" status --porcelain=v1 --ignored
  echo "## scratch-clone worktrees"
  git -C "$EV/src" worktree list
  echo "## main checkout worktrees (read only)"
  git --no-optional-locks -C "$HOME/src/meridian" worktree list
  echo "## owner ~/.dsh: names newer than start (no .env), hashes"
  find "$HOME/.dsh" -newer "$EV/start.stamp" ! -name .env -printf '%P\n'
  sha256sum -c --quiet "$EV/owner-dsh.sha256" && echo "owner dsh hashes OK"
  echo "## anything named *codex-peer* outside $EV (home depth 4, /tmp)"
  find "$HOME" /tmp -maxdepth 4 -xdev -name '*codex-peer*' -not -path "$EV/*" 2>/dev/null
  echo "## new top-level names in home and /tmp"
  ls -A "$HOME" | diff "$EV/home.before" - | grep '^>' || true
  ls -A /tmp | diff "$EV/tmp.before" - | grep '^>' | grep -v -E '^> uv-[0-9a-f]+\.lock$' || true
  echo "## leftover processes from this measurement"
  pgrep -af 'ab-without|ab-with|capture_server|codex exec|meridian-ab/0009' | grep -v -e pgrep -e check_after -e probe_one -e task_one || echo none
} > "$out" 2>&1
cat "$out"
