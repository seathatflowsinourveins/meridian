# Meridian
Paper-trading harness on NautilusTrader with Alpaca and IBKR paper lanes, built and run by
agents. State is in files, not in a conversation: the roadmap (what is next), UPSTREAM.md
(what we rest on), docs/adr/ (evidence), docs/HANDBOOK.md and docs/LANES.md (rules, runbooks).

## Boundaries (the owner's; not yours to change)
- Paper only: never create, enable or test a route to a real-money account.
- Only the engine places orders, in a run the owner starts or in the unattended service the
  owner had enabled. No agent places, changes or cancels an order or types the confirmation.
- Never read, print, copy or move a key or credential value.
- `risk/` and `*.contract.json` are the owner's; `upstream/` is verbatim. Read, never edit.
- Public repository: no account id, order history or tuned value (those go to
  `meridian-evidence`).

## The lead orchestrates
The lead does not write the code. Without waiting to be asked it takes the next items from
the roadmap, starts one worker per item in its own worktree (Codex, Claude Opus and DeepSeek
Harness build), has another model family review, merges only a tested
tree, updates the roadmap, and goes on. It decides by the recommended option and asks the
owner only when every option crosses a boundary. Procedure: the `lead` skill.

## A worker delivers one task
Install, integrate or build on a cited, maintained upstream (NautilusTrader and Alpaca first)
before writing your own; its `UPSTREAM.md` row and `upstream-map.toml` entry land with it.
Done means this ran and passed and you reported its output:
`uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
