# ADR 0002: pyright-lsp for Claude Code (plan 8.6)

**Status: not adopted.** Decided 2026-11-13.

Evidence: the plugin read at the pin (2026-11-12, re-checked 2026-11-13), an independent verification (2026-11-13: 47 checks, 42 confirmed, 4 corrected, 1 refuted; its corrections are applied) and the measurement below. The assessment, verification and measurement notes hold local paths and are not published; the raw runs (streams, transcripts, debug logs) stay on the owner's machine.

## Need

Agents check types with `uv run pyright` (pyright 1.1.414 from `uv.lock`), which CI (`ci.yml` line 29) and the check line of `AGENTS.md` run project-wide. The plugin adds two things: pyright's diagnostics pushed into context after each Edit or Write of a Python file, and symbol navigation (definitions, references, hover, call hierarchy) through Claude Code's built-in LSP tool. No runtime in the stack has a language-server client without a plugin; pyright runs as a command-line checker (`uv run pyright`). Overlap: type checking is done in full by that command; for navigation, ADR 0001 measured ripgrep on 30 questions at 20, 25 and 26 at top 1, 3 and 5, and ripgrep with pyright's lookups at 19, 24 and 26.

## Candidate

[anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/f75f5b25ae94f4332be4ff5f18435741d2589bdb/plugins/pyright-lsp), plugin `pyright-lsp`, manifest version 1.0.0, pinned by marketplace commit `f75f5b25ae94f4332be4ff5f18435741d2589bdb` (2026-11-13T00:10:35Z, `main` that day; the repository has no tags or releases). Three files: `.claude-plugin/plugin.json` (sha256 `2cf083ce0ec6aa27c25ba7dd3b1cc37868f899f1bd77a9431949703e888c4c1d`), `LICENSE`, `README.md`. Apache-2.0. Maintained by Anthropic (the repository's README: "Internal plugins developed and maintained by Anthropic"). It ships no language server: it runs `pyright-langserver` (pyright, MIT), here from pyright-python 1.1.414 in each worktree's `.venv`. Open in anthropics/claude-code: #93321 (diagnostics not awaited after Edit or Write), #95507 (Hint diagnostics pushed unfiltered), #84125 (LSP tool pruned from subagents in interactive sessions).

## Advisories (GitHub, 2026-11-13)

None for the plugin or its chain: 0 repository advisories for anthropics/claude-plugins-official, microsoft/pyright and RobertCraigie/pyright-python; 0 in GitHub's advisory database for npm and pip `pyright`, `nodejs-wheel-binaries`, `nodeenv` and `typing-extensions`. `@anthropic-ai/claude-code` has 30, none affecting 2.1.322; anthropics/claude-code's 36 repository advisories name no LSP or language-server issue.

## What it installs, writes and sends

- One stdio language server, `pyright-langserver --stdio`, for `.py` and `.pyi`; no hooks, MCP servers, skills, agents or commands. It turns on Claude Code's read-only `LSP` tool and per-edit diagnostics: after an Edit or Write of a Python file, at most 10 per file and 30 per delivery, Hints included, sent as a `<system-reminder>` (2.1.322 binary). `claude plugin validate --strict` passed. The plugin has no network code.
- The server starts at the first Edit or Write of a matching file, looked up on the PATH Claude Code starts with. `pyright-langserver` is not on the distro's login PATH, only in each worktree's `.venv/bin`; no route that puts that folder on the PATH of the Claude Code sessions Orca 1.4.257 starts was found in Orca's installed server or the `orca.yaml` keys it reads, and none was tested. The README's global installs (`npm install -g`, `pip`, `pipx`, unpinned) would add a second pyright outside `uv.lock`.
- Side finding: `uv run pyright` asks pypi.org for its latest version unless `PYRIGHT_PYTHON_IGNORE_WARNINGS` is set (CI sets it, `ci.yml` line 16), in both arms alike.
- The runs used the owner's sign-in and wrote worktree entries under the main checkout's `.git/worktrees`; a session-only plugin load left a `pluginUsage` entry in `~/.claude.json`. Here it also left a top-level key `pluginUsageLspGraceAppliedIds` naming `pyright-lsp@inline`, and an empty `~/.claude/plugins/data/pyright-lsp-inline/`, removed after each sitting. The owner's `settings.json`, `installed_plugins.json` and `known_marketplaces.json` hashed the same before and after.

## Always-on context

- Measured: input plus cache tokens of a one-turn `OK` run, 3 runs per arm, each in a fresh worktree at `main` `9c5daaa`: without 22,743 in all three, with 22,747 in all three, **+4 (+0.02%)**: one deferred-tool line, `LSP`. `/context`: "System tools (deferred)" 13,844 to 14,484 (+640, the tool's definition, sent only after a ToolSearch for it).
- Static, in o200k_base tokens as a proxy ([counter](data/0002_count_tokens.py), give it `--vocab-dir`): the deferred line 4 characters (3 tokens); the tool definition 2,305 to 2,723 characters (510 to 627); diagnostics at the caps 4,124 characters (1,239 tokens) per delivery.

## Method

- Measured on Claude Code 2.1.322 with `claude-opus-5-5`; the stack's lead model `claude-fable-5-2` was not measured. The shared [method](data/ab-claude-code.md) and task R1 of the [task list](data/ab-tasks.md), with the [brief](data/0002-brief-R1.txt), [arm key](data/0002-key.txt), [deny rules](data/0002-deny.json) and [leak patterns](data/0002-leak-patterns.txt). Both arms: the versioned 2.1.322 binary, `--effort high`, bypass permissions, a fresh memory folder, `PATH="$WT/.venv/bin:$PATH"` with `VIRTUAL_ENV` unset, `--debug-file` in the run folder, the method's 6 deny rules plus `npm install`, `pip install` and `pipx install`. The plugin's arm adds `--plugin-dir` on a copy of `plugins/pyright-lsp` at the pin.
- R1, the replay of safety fix `5d51c9c`: a fresh detached worktree at `27aa964` with `5d51c9c`'s `tests/`; order a-1 b-1 b-2 a-2 a-3 b-3 (a is the plugin). Graded on a fresh worktree from the run's `meridian/` and `.gitignore` patch: ruff, `ruff format --check`, pyright and pytest exit 0, `tests/` unchanged.
- Fixed before the runs: [0002-prereg.txt](data/0002-prereg.txt) (sha256 `94e025a8552afd31542a7f63d6a8ab11a8437b60d2a8986049f0d992942c7e5a`), assembled after the series from records written by 01:54 ET; the first run (a-k1) started at 01:55:13 ET. These times come from the owner's machine and cannot be proved from the repository. Its rule: adopt only if the plugin's arm passes at least 2 of 3 where the other passes at most 1, or both pass at least 2 of 3 and the plugin's arm uses at least 25% fewer median tokens; the always-on delta at most 2,000 unless the first holds; and the venv's `pyright-langserver` reachable by Orca's launches. A plugin run is valid only if its debug log shows the server loaded, started and at least one diagnostics delivery; an invalid run is repeated. Changed after the first run: 2.1.322 writes the start marker as `plugin:pyright-lsp:pyright`, and that wording was counted.
- Before every run a guard checked that nothing listened on the paper Gateway's port and that no Gateway process ran. The first sitting's guard matched command lines and stopped this series falsely at 02:04:08 ET, before b-2; the resumed runs (04:07 to 04:23 ET) used the test of the published [guard](data/0003_gateway_guard.sh) with port 4002 only. Records of what ran: the runners of the [first](data/0002_ab.sh) and [resumed](data/0002_ab_r2.sh) sittings (home written as `~`, leak scan corrected after the series), the exports ([always-on](data/0002_collect.sh), [R1](data/0002_collect_r2.sh)), the [results](data/0002-results.json), the [aggregator](data/0002_aggregate.py) that recomputes the figures below, and the [rescan](data/0002_rescan.py) of each run's tool calls. The runners add worktrees of the main checkout, whose history holds the fix, so they are no re-run recipe.

## Results (2026-11-13)

| Arm | Passed | Turns | Tokens per run | Median tokens | Median time | Language server |
|---|---|---|---|---|---|---|
| without | 3 of 3 | 17, 18, 25 | 926,212; 953,252; 1,361,185 | 953,252 | 191.6 s | none |
| with pyright-lsp | 3 of 3 | 36, 17, 14 | 1,296,504; 1,020,523; 870,411 | 1,020,523 (+7.1%) | 200.7 s | started in a-1 only; 1 diagnostic delivered |

- Every run changed the same four files and passed 281 tests with pyright at 0 errors; `claude-opus-5-5` only, 0 API retries. No run called the LSP tool. In a-2, a-3 and all three runs without, the model edited only through Python heredocs in Bash, so in a-2 and a-3 the server never started. a-1 moved to Read and Edit after the deny rule `Bash(*ibgateway*)` refused a heredoc quoting a docstring that names the Gateway's folder (the same text passed in the other five runs); its one diagnostic, a deprecation Hint, was followed by an edit outside the reference fix.
- As pre-registered, only a-1 is valid: condition 1 fails whatever replacements do (the arm without passed 3 of 3), and condition 2 would need two replacements each at most 714,939 tokens, below every run of the series (lowest 870,411). The replacements were not run: they would select runs by the model's choice of edit tool and could not change the result. With every run scored (post hoc), condition 1 fails and the plugin's arm used 7.1% more median tokens, not 25% fewer. The PATH condition is not shown to hold.
- No run handed work to Codex (0 calls, sessions or tokens). The leak scan found no read of the fix, git history or another run, so no run is void. Its patterns left out `~/Jts`: in a-3 the model read `~/Jts/jts.ini` with a Python one-liner and printed its section names and the section holding `tradingMode`, no values; the rescan with `Jts|jts\.ini` added finds no other read of that folder.
- Cost: 6,564,581 Claude tokens, always-on runs included, about $7.97 (client-side estimate).

## Decision

Not adopted. As pre-registered, one valid plugin run cannot meet either condition; with every run scored, both arms passed 3 of 3 and the plugin's arm used 7.1% more median tokens; and no tested route gives Orca's launches the venv's language server. On R1 the plugin mostly did nothing: its server started in 1 of 3 runs and its LSP tool was never called. Type checking stays with `uv run pyright` in CI and the check line. A later look needs a task where the model edits through Edit or Write or navigates, and a tested PATH route; an own `.lsp.json` (the venv's binary, Hints off) would be a different addition with its own ADR.

## Install and removal

- Not installed. A pinned install would follow `ab-claude-code.md`, "Adopting after a passing ADR", with plugin `pyright-lsp`, `path` `plugins/pyright-lsp`, `url` `https://github.com/anthropics/claude-plugins-official.git` and `sha` `f75f5b25ae94f4332be4ff5f18435741d2589bdb`, plus the PATH route; never the README's global pyright installs, nor `pyright-lsp@claude-plugins-official`, which follows `main` with auto-update on.
- Removal: `claude plugin uninstall pyright-lsp@meridian-pinned --scope user && claude plugin marketplace remove meridian-pinned --scope user`, check `claude plugin list --json`, delete the `meridian-pinned` keys from `~/.claude/settings.json`, revert `check_claude` and the PATH change, and remove the `pyright-lsp@…` entries under `pluginUsage` and `pluginUsageLspGraceAppliedIds` in `~/.claude.json`.
