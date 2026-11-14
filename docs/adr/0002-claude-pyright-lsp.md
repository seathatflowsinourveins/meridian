# ADR 0002: pyright-lsp for Claude Code (plan 8.6)

**Status: not adopted.** Decided 2026-11-13.

## Candidate

[anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/f75f5b25ae94f4332be4ff5f18435741d2589bdb/plugins/pyright-lsp), plugin `pyright-lsp`, manifest version 1.0.0, pinned by marketplace commit `f75f5b25ae94f4332be4ff5f18435741d2589bdb` (2026-11-13T00:10:35Z, `main` that day; the repository has no tags or releases). Three files: `.claude-plugin/plugin.json` (sha256 `2cf083ce0ec6aa27c25ba7dd3b1cc37868f899f1bd77a9431949703e888c4c1d`), `LICENSE`, `README.md`. Apache-2.0. Maintained by Anthropic (the repository's README: "Internal plugins developed and maintained by Anthropic"). It ships no language server: it runs `pyright-langserver` (pyright, MIT), here from pyright-python 1.1.414 in each worktree's `.venv`. Open in anthropics/claude-code: #93321 (diagnostics not awaited after Edit or Write), #95507 (Hint diagnostics pushed unfiltered), #84125 (LSP tool pruned from subagents in interactive sessions).

## Decision

Not adopted. As pre-registered, one valid plugin run cannot meet either condition; with every run scored, both arms passed 3 of 3 and the plugin's arm used 7.1% more median tokens; and no tested route gives Orca's launches the venv's language server. On R1 the plugin mostly did nothing: its server started in 1 of 3 runs and its LSP tool was never called. Type checking stays with `uv run pyright` in CI and the check line. A later look needs a task where the model edits through Edit or Write or navigates, and a tested PATH route; an own `.lsp.json` (the venv's binary, Hints off) would be a different addition with its own ADR.

Full record: [data/0002-record.md](data/0002-record.md)
