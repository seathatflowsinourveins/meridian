# ADR 0001: semble for code search (plan 8.7, retrieval slot 2)

**Status: not adopted.** Decided 2026-11-12 by measurement at `f65d835` (`main`). The [questions](data/0001-questions.json), the [plans](data/0001-plans.json) and the decision rule were committed in `78dedd5` before either method ran; [harness](data/0001_measure.py), [results](data/0001-results.json).

## Need

Agents here find code with slot 1: ripgrep (Claude Code 2.1.322 bundles ripgrep 14.1.1 as its Grep tool) and pyright 1.1.414 (the repo's own dev dependency, used through its language server). Slot 2 is semantic code search, kept only if it beats slot 1 on a fixed question set by a margin set in advance. Prior evidence is against such additions: a 2026 benchmark found 11 of 12 memory-system pairings did not beat a memory-off baseline for coding agents.

## Candidate

[MinishLab/semble](https://github.com/MinishLab/semble) **0.7.2**: tag commit `bb746c9`, on PyPI 2026-11-03 (0.7.3, of 2026-11-08, is inside the 7-day wait). MIT. Maintainers Thomas van Dongen and Stéphan Tulkens (MinishLab). Read 2026-11-12. It ranks tree-sitter chunks by BM25 plus static embeddings from [`minishlab/potion-code-16M-v2`](https://huggingface.co/minishlab/potion-code-16M-v2) (MIT, revision `e9d2a44`), on CPU.

## Advisories (GitHub, 2026-11-12)

None for semble, in its repository or in the global database. None for any of the 52 packages at the versions resolved with the 7-day cutoff: 32 for the CLI, plus 20 for the `mcp` extra, which resolves to `mcp` 2.3.0, above the four October advisories against `mcp` below 2.2.0. Queried as `affects=<name>@<version>`; known-vulnerable control versions did return advisories. semble publishes no security policy.

## What it installs, writes and sends

Read in the 0.7.2 source and its dependencies; checked with an audit hook in every semble process (network, process starts, files opened for writing).
- One CLI with 32 packages (115 MB) in its own environment; no hooks. `semble search` starts no process or service. `semble` with no subcommand is an MCP server on stdio; `--http` serves on 127.0.0.1:8000.
- First use only: the model, 33.6 MB, from huggingface.co; its large file comes through hf_xet from `cas-server.xethub.hf.co` and `us.aws.cdn.hf.co`. huggingface_hub 2.4.0 also fetches `/api/agent-harnesses` and adds `agent/<name>` to its User-Agent when it sees an agent's variables (`CLAUDECODE`, `CODEX_THREAD_ID`, `DSH_SHELL` and others); `HF_HUB_DISABLE_TELEMETRY=1` stops that. The 186 later semble processes made no network call.
- Writes: the model, `.agent_harnesses.json` and an hf_xet log under `$HF_HOME` (default `~/.cache/huggingface`); native grammar libraries, extracted from the package with a checksum check, to `~/.cache/semble/grammars/` and loaded from there; for each indexed folder, `~/.cache/semble/<sha256 of its path>/index*/`, whose `chunks.json` is a second copy of the indexed text (0.86 MB here); `savings.jsonl`, one line of counts per search. Outside those, only temporary files in `/tmp`, removed at once.
- `semble install` (not run) would add an MCP entry to `~/.claude.json`, a block to `~/.claude/CLAUDE.md` and `~/.claude/agents/semble-search.md`.
- Indexed here with `--content all`: 24 of the 35 tracked files. Not indexed: `deploy/wsl/meridian.user-data`, `evidence/*.json`, `uv.lock`, the dotfiles and the licence texts.

## Always-on context

Without semble: nothing added. Grep is built into Claude Code, and pyright runs only as a tool. With semble's default install for Claude Code (MCP, instructions, sub-agent), every session loads:
- 3,868 characters of MCP tool definitions (1,017 tokens) and 439 of server instructions (95);
- the 2,021-character CLAUDE.md block (480);
- the 236-character sub-agent description (44).

That is 6,564 characters, 1,636 tokens. The skill variant is 354 characters (78 tokens). Tokens are counted with o200k_base, OpenAI's vocabulary (sha256 `446a9538…1a2d`), as a proxy, because Claude's tokenizer is not available offline.

## Method (fixed in `78dedd5`)

30 questions an agent would ask here (10 where-is-this-check, 4 callers, 2 vendored upstream, 5 run record, 5 tests, 4 ops), each answered as file and symbol and checked by hand. A separate agent, given only the questions and AGENTS.md (no code, no tool use), wrote each method's moves. For slot 1: one to three ripgrep searches (with `--hidden`, as the Grep tool does) and at most one pyright definition or references lookup. For semble: one query and content type, top 5. The corpus is the frozen commit's 35 tracked files, checked blob by blob. A result counts when it is in the answer's file and its lines overlap the answer's span. Slot 1's hit lines are grouped by their enclosing def, class or paragraph and ranked by how many searches hit them; the lookup goes first. **Rule: adopt only if semble answers at least 5 more questions within the top 3, and no fewer within the top 1 and the top 5.**

## Results (30 questions; identical over 3 repeats and 3 separate runs from empty caches)

| | top 1 | top 3 | top 5 | median time per question | median text returned |
|---|---|---|---|---|---|
| **slot 1: ripgrep + pyright** | **19** | **24** | **26** | 0.011 s (pyright ready once, 1.4 s) | 1,243 chars |
| **semble, the plan's query** | **16** | **21** | **23** | 0.66 s per CLI call (0.9 ms in process) | 4,610 chars |
| slot 1, unranked printed order | 11 | 19 | 21 | | |
| semble, question verbatim, all content | 13 | 15 | 16 | | |

Within the top 3, semble did better on where-is-this-check (10 of 10 against 7). It did worse on tests (1 of 5 against 4), callers (3 of 4 against 4, where pyright's references are exact), vendored upstream (0 of 2 against 1) and ops (2 of 4 against 3). It ties on run record (5 of 5). Its ranking scales test and `examples/` files by 0.3, and it misses files it does not index. Index: 365 chunks, built in 0.10 s with the model loaded; the first CLI call takes 1.3 s, and first use with the download 3.3 s.

## Decision

Not adopted. semble answers 3 fewer questions than slot 1 at top 1, top 3 and top 5, against a required lead of 5 at top 3. Even against ripgrep's unranked output its lead at top 3 is 2. It would also cost about 60 times the time per CLI call, 3.7 times the text to read, about 1,600 tokens in every session, and a second copy of the code in `~/.cache`. Slot 3 (a context store) is therefore measured against slot 1. Look at semble again only if a question set on a larger repo shows slot 1 failing.

## Commands

- Throwaway environment used here, removed afterwards: `UV_CACHE_DIR=$T/uv-cache uv venv --python 3.14 $T/venv && UV_CACHE_DIR=$T/uv-cache uv pip install --python $T/venv/bin/python --exclude-newer 2026-11-05T00:00:00Z 'semble[mcp]==0.7.2'`. It was run with `HF_HOME`, `SEMBLE_CACHE_LOCATION` and `XDG_CACHE_HOME` inside `$T`, by the harness's `run` command.
- Pinned install, if a later ADR adopts it: `uv tool install --exclude-newer 2026-11-05T00:00:00Z 'semble==0.7.2'`, used with `HF_HUB_DISABLE_TELEMETRY=1`.
- Removal: `semble uninstall --agent claude --yes`, then `~/.local/share/uv/tools/semble/bin/hf cache rm model/minishlab/potion-code-16M-v2 -y`, `uv tool uninstall semble`, and `rm -rf ~/.cache/semble`.
