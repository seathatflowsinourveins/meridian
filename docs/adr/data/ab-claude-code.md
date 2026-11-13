# Claude Code with/without method for ADRs 0002 to 0006 (plan 8.6)

This sheet is a description, revised on 2026-11-13 after the series; each ADR's pre-registration and scripts record what its series ran, and win where this sheet differs.

For Claude Code 2.1.322 in the `meridian` distro: measured on Claude Code 2.1.322 with `claude-opus-5-5`; the stack's lead model `claude-fable-5-2` was not measured. Checked 2026-11-12 against code.claude.com/docs, the 2.1.322 changelog at tag `v2.1.322` (`6e1e44f`) and the installed binary's `--help`, and on 2026-11-13 against what the runs of ADRs 0002 to 0006 did. Nothing is installed: an addition is loaded for one session with `--plugin-dir` (ADR 0004 copied its two skills into each worktree instead, under `.agents/skills` with links from `.claude/skills`). The runs used the owner's sign-in and wrote worktree entries under the main checkout's `.git/worktrees`; a session-only plugin load left a `pluginUsage` entry in `~/.claude.json`. The tasks and the Gateway guard are in [ab-tasks.md](ab-tasks.md); the Codex and DeepSeek Harness methods are [ab-codex.md](ab-codex.md) and [ab-dsh.md](ab-dsh.md).

## Every run

```bash
CB="$(readlink -f ~/.local/bin/claude)"; "$CB" --version   # one binary for the whole series; start from a login shell
WT=~/src/meridian-worktrees/ab-$ADR-$ARM-$N; OUT=~/src/meridian-ab/$ADR/$ARM-$N; MEM=~/.cache/claude-ab-mem/$ADR-$ARM-$N
git -C ~/src/meridian worktree add --detach "$WT" "$BASE"; mkdir -p "$OUT" "$MEM"
DENY='["Bash(*meridian.ibkr_paper*)","Bash(*meridian.ib_probe*)","Bash(*meridian.boundary contract*)","Bash(*ibgateway*)","Read(~/Jts/**)","Read(~/src/meridian/**)","Read(~/src/meridian-ab/**)"]'
SET=$(jq -nc --arg m "$MEM" --argjson d "$DENY" '{autoMemoryDirectory:$m, permissions:{deny:$d}}')   # fresh memory per run
RUN=(env -u CLAUDE_CODE_EFFORT_LEVEL -u CLAUDE_CODE_SUBAGENT_EFFORT -u ANTHROPIC_MODEL DISABLE_AUTOUPDATER=1 "$CB")   # every -u before the first NAME=value
FLAGS=(--model claude-opus-5-5 --effort high --permission-mode bypassPermissions --settings "$SET" --output-format stream-json --verbose)
ADD=(); [ "$ARM" = "$WITH" ] && ADD=(--plugin-dir "$D/<plugin-subdir>")   # $D: the addition at its pinned commit
```

- Fetch the addition as data with unauthenticated git at the pinned commit, read every file before the first run (its hooks run under `--plugin-dir`), and check it with `"$CB" plugin validate "$D/<plugin-subdir>" --strict`. A skill alone is wrapped as a plugin (`.claude-plugin/plugin.json` plus `skills/<name>/SKILL.md`). A manifest with `defaultEnabled: false` also needs `enabledPlugins: {"<name>@inline": true}` in `SET`.
- The deny rules sit in `SET`, where they hold in bypass mode (ADR 0005 checked with a probe), so no command line carries them; ADR 0003's series passed them on the command line instead. They match a command as written: `Bash(*ibgateway*)` denied one heredoc edit that quoted `boundary.py`'s docstring (ADR 0002, run a-1, which then used the Edit tool the addition acts on) and let the same text through in other runs, so a rule can steer a run. The Gateway guard and the leak scan below are the real guards.
- `-p` silently ignores a settings file that fails validation. Every run's `init` event must show the same `claude_code_version`, the addition in `plugins` in its arm only, no `plugin_errors`, and `MEM` as its memory directory (ADR 0005 read it there).
- In both arms Orca's hooks (16 events in `~/.claude/settings.json`), Claude Code's built-in `cc-plugin-*` plugins and the stack's `codex@openai-codex` (openai/codex-plugin-cc 1.0.6) load. That plugin's `codex:codex-rescue` agent is told to hand substantial tasks to Codex on its own initiative, through `codex-companion.mjs task`, write-capable by default, and `/codex:rescue` is open to the model; Codex's tokens are not in `modelUsage`. Record for every run the Agent, Skill and command calls naming codex, Bash calls of `codex` or `codex-companion`, Codex processes whose cwd is in the worktree, and rollouts under `~/.codex/sessions` with that cwd, and report their tokens separately; ADRs 0002, 0004 and 0006 found none. ADR 0006 set `CODEX_HOME` to an empty folder for its R1 runs in both arms, so a hand-off would fail. The plugin's Stop hook runs in every run and returns at once while its review gate is off (the default; `setup.sh` keeps it off).
- Where an addition writes temporary or cache files, both arms set `TMPDIR` (and `UV_CACHE_DIR`, `npm_config_cache`) to a fresh folder per run outside `OUT`, whose reads are denied (ADR 0003).

## Always-on context (3 runs per arm, each in a fresh worktree at the ADR's base commit)

`cd "$WT" && "${RUN[@]}" -p 'Reply with the single word OK. Do not use any tools.' "${FLAGS[@]}" "${ADD[@]}" --max-turns 1 --session-id "$(cat /proc/sys/kernel/random/uuid)" > "$OUT/ok.jsonl"`

The always-on size is `usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens` of the `result` event, valid when `num_turns` is 1, `is_error` is false and `terminal_reason` is `completed`. It holds the system prompt, tools, `CLAUDE.md` with its `@AGENTS.md` import, the skill and agent listing, the git status snapshot and any text a SessionStart hook injects. Delta = median(with) − median(without), reported in tokens and as a share of without; per-session tax = delta × the median `num_turns` of the arm without on the task. At `main` `9c5daaa` the arm without measured 22,743 tokens (22,751 in ADR 0003), the same in every repeat. Skill copies left uncommitted in a worktree add lines to the git snapshot: ADR 0004's control with `includeGitInstructions: false` in both arms gave a delta of 121 instead of 182.

For the split by category, run the same command with `-p '/context'` and no `--max-turns`, and read `context_usage.categories`; it makes no model call. It is an estimate: its total did not move when an addition added skills, because it takes the listing out of the System tools row (ADRs 0003, 0004, 0006), and a SessionStart hook's text shows under Messages (ADR 0005). `claude plugin details <name>` is an estimate too: it leaves out hooks and MCP servers, and on skill listings it was 1% low to 19% high (ADRs 0003, 0005, 0006).

## Real task (3 runs per arm, order a1 b1 b2 a2 a3 b3)

`cd "$WT" && "${RUN[@]}" -p "$(cat ~/src/meridian-ab/briefs/R<n>.txt)" "${FLAGS[@]}" "${ADD[@]}" --max-turns 100 --session-id "$SID" </dev/null > "$OUT/stream.jsonl" 2> "$OUT/stderr.txt"`

- `SID=$(cat /proc/sys/kernel/random/uuid)`. Copy the transcript `~/.claude/projects/<working directory with every non-alphanumeric character as ->/$SID.jsonl` and its `$SID/` folder at once; Claude Code deletes them after 30 days.
- From the `result` event: `subtype`, `is_error`, `terminal_reason`, `num_turns`, `duration_ms`. Tokens: the sum over `modelUsage` of input, cache-creation, cache-read and output tokens, which includes subagents; `total_cost_usd` is a client-side estimate and is only reported.
- Not scored and re-run later: `terminal_reason` `api_error`, `blocking_limit`, `rapid_refill_breaker` or `aborted_*`, a usage or rate limit, or a `modelUsage` key exactly `claude-opus-4-8` or `claude-opus-5` (an automatic fallback model).
- Leak scan: `jq -c '..|objects|select(.type?=="tool_use")|{name,input}'` over the stream, the transcript and `$SID/subagents/*.jsonl`, then search the calls, with the run's own `WT` and `MEM` masked, for `~/src/meridian`, other runs' worktrees and outputs, `.claude/projects`, `.git/`, git history (`log --all`, `reflog`, `main`, `origin`, the fix's hash), `Jts`, `ibgateway` and `:4002`. A real read of the fix or of another run's folder voids the run: a void run is one whose result is not counted for its arm because a stated rule was broken; a void in the arm with the addition counts against it.
- Grade as [ab-tasks.md](ab-tasks.md) says, then remove the worktree: `git -C ~/src/meridian worktree remove --force "$WT"`, and the run's `MEM`.

## /goal

No run starts one. What a goal is and how it starts is in `docs/HANDBOOK.md`'s Goals section: in 2.1.322 a goal is a session-scoped Stop hook, `claude -p "/goal ..."` runs one in any folder, and a non-interactive run never gets the ProposeGoal tool.

## Default adoption rule (an ADR may set a stricter one)

Adopt only if the arm with the addition passes in at least 2 of 3 runs and the arm without in at most 1; or both pass in at least 2 of 3 and the arm with the addition uses at least 25% fewer median tokens; and in either case the always-on delta is at most 2,000 tokens unless the first condition holds.

## Adopting after a passing ADR (this writes the owner's configuration)

- Pinned to a commit: an inline marketplace in `~/.claude/settings.json`, `{"extraKnownMarketplaces": {"meridian-pinned": {"source": {"source": "settings", "name": "meridian-pinned", "plugins": [{"name": "<p>", "source": {"source": "git-subdir", "url": "https://github.com/<o>/<r>.git", "path": "<subdir>", "sha": "<40 hex>"}}]}, "autoUpdate": false}}, "enabledPlugins": {"<p>@meridian-pinned": true}}`, then `claude plugin install <p>@meridian-pinned --scope user`. A marketplace added as `<o>/<r>#<tag>` pins only a tag, which its publisher can move.
- `setup.sh agents-check` (on `main` since #1) fails on any enabled plugin other than `codex@openai-codex`, so an adoption changes `deploy/wsl/setup.sh` in the same pull request.
- Removal: `claude plugin uninstall <p>@<marketplace> --scope user`, then `claude plugin marketplace remove <marketplace> --scope user`; check with `claude plugin list --json`.
