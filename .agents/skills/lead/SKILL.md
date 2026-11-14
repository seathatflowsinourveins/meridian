---
name: lead
description: The Meridian lead's procedure. Use when leading: dispatching roadmap items to Orca workers, answering their reports, or landing a branch through the merge gate.
---
# Lead
1. **Loop.** Take the next roadmap items. Start one worker per item in its own worktree through Orca (the `orchestration` skill). Codex and Claude Opus build; DeepSeek Harness does mechanical work; a model family other than the builder's reviews. On every worker report keep going: decide by the recommended option, ask the owner only for a boundary.
2. **Worker task rules.** The boundaries of `AGENTS.md` (name only what is forbidden), then "Everything else is allowed without asking". Always add: this machine is shared, so stop only a process you started, by its PID; never by name (`pkill`, `killall`, `kill` on a `pgrep` pattern).
3. **Land one branch at a time**, from the main checkout (`G="uv run python .agents/skills/lead/scripts/gate.py"`):
   - `$G trial BRANCH`: takes the lock, merges `origin/main` on the branch in its own worktree (a merge commit; refuses on uncommitted changes or a conflict, which go back to the worker), runs ruff check, ruff format check, pyright, pytest and gitleaks on that commit. FAIL: send the worker the failed check.
   - `$G open BRANCH "TITLE" BODY.md REVIEW.md`: pushes the tested branch as it is (a plain push; a branch rewritten after an earlier push is refused and goes back to the worker), opens the pull request with BODY, posts the review record REVIEW, waits for CI.
   - `$G land BRANCH [SQUASH.txt]`: squash-merges pinned to the tested head only if the merged tree still equals the tested one and CI is green, then compares main's tree with it. REFUSED: do what it says (usually `trial` again); FAIL after the merge: main moved during it, run the checks on main. `$G release` drops an abandoned landing's lock.
4. **After each merge**: update the roadmap and the manifest (the owner's files, outside the repository), then take the next item.
