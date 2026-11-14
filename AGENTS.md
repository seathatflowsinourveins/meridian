# Meridian

A paper-trading harness on NautilusTrader. One repo, one WSL2 distro (`meridian`). Paper only.
Lanes, rules, budgets and run records: `docs/HANDBOOK.md`. Size limits: `size-budget.toml`.

## Boundaries (set by the owner; not yours to change)

- **Paper trading only.** Never create, enable or test a route to a real-money account.
  `tests/test_paper_only.py` fails the build if a real-money endpoint, port, trading mode or
  key name appears. That scan is a tripwire; the boundary itself is `meridian/boundary.py`.
- **`risk/` and `*.contract.json` belong to the owner.** Read them. Never create or edit them.
- **Only the engine places orders**, in a run the owner starts and attends in a terminal Orca
  did not start, or in the Alpaca units enabled on the owner's instruction (`docs/HANDBOOK.md`).
  No agent, script or tool call submits, changes or cancels an order, and no agent starts the
  lane in any mode or works around its typed-word check. That check only proves a terminal, and
  any Orca session can type into one (`orca-ide terminal send`).
- **Never read, print, copy or move a credential or key value.**
- **Account ids stay out of the repo and out of `evidence/`.** The allowlist holds SHA-256
  hashes. A hash of a short id can be reversed by trying every id, so treat
  `risk/boundary.contract.json` as if it held the id itself; git ignores it.
- **This repository is public.** Nothing derived from an account and no calibrated parameter
  goes in it: account ids, raw order or fill history, reconciliation fixtures and tuned
  thresholds go to the private `meridian-evidence` repository (clone it as
  `~/src/meridian-evidence`). Scrubbed run records may stay in `evidence/` here.
  `tests/test_public_tree.py` fails the build if an IBKR-style account id appears.
- **CI stays fork-safe:** no self-hosted runner, no `pull_request_target` workflow, no secret a
  fork's pull request could reach. The same test checks the workflow files.
- **A branch from outside the owner's sessions** (a fork's pull request) is read on GitHub, never
  opened in an Orca worktree or agent session: its setup and hooks would run as the owner unread.
- Ask the owner before adding a paid service or an account.

## Working rules

- Everything installed or integrated has a row in `UPSTREAM.md`, added in the same commit:
  version or commit, the URL that was read, the date, what it is for, "upstream" or "own design".
- Start from upstream's own example. Files under `upstream/` are verbatim copies and are never
  edited (its `NOTICE.md` is the one file written here); `tests/test_upstream_unmodified.py`
  checks them. No licence is chosen for this repo's own code: that is the owner's decision.
- Check a finding at its source before acting on it. Find the root cause before disabling a check.
- Run the checks before saying something works. Report a failure as a failure.
- Add nothing the current milestone does not need.

## Layout

| Path | What it is |
|---|---|
| `deploy/wsl/` | the distro definition (cloud-init) and the user-level setup script |
| `meridian/boundary.py`, `meridian/ib_probe.py` | the paper checks (Gateway login mode, ports, account form, optional allowlist) and the probe that asks the Gateway which accounts it manages (own design) |
| `meridian/ibkr_paper.py`, `meridian/ibkr_node.py` | IBKR paper lane: gate, owner confirmation, run record; the engine side, built on upstream's example |
| `meridian/order_budget/`, `meridian/sandbox_*.py` | M2: the order budget (the owner's pacer, from Sextant) and the sandbox lane (no broker) |
| `meridian/alpaca/` | Alpaca paper execution adapter (M3 groundwork, own design); study in `docs/m3-alpaca.md` |
| `deploy/systemd/` | the Alpaca lane's unit for `paper`, prepared and not enabled; keys only as systemd credentials |
| `upstream/` | upstream example files, unmodified |
| `.agents/skills/` | skills every agent reads; each has a link in `.claude/skills/` for Claude Code |
| `orca.yaml`, `.worktreeinclude` | Orca: the setup script and tabs of each new worktree; nothing ignored is copied |
| `risk/boundary.contract.json` | optional: the owner's allowlist of paper accounts |
| `evidence/` | scrubbed run records: one per attended run that passed, and the latest offline soak |
| `runs/` | local run output, ignored by git; may hold account ids |

## Commands

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

## Agents and worktrees

- Four agent runtimes run here through Orca, one git worktree per task: Claude Code leads
  (`claude-fable-5-2`; its workers run `claude-opus-5-5`), Codex (`gpt-6-astra`, `gpt-6.1-sol`
  for bulk) and Antigravity work and review, DeepSeek Harness takes mechanical tasks only.
- Work is reviewed by a different model family before it merges (`/codex:review` in Claude
  Code). Findings are fixed in the pull request or closed with a reason.
- Orca's `orca-cli` and `orchestration` skills are in `.agents/skills/`; the command is
  `orca-ide`. Its runtime is the `orca-serve` user service on 127.0.0.1:6790: if it is down,
  report that or run `systemctl --user start orca-serve`, never `orca-ide open`, `serve` or
  `serve service install`, which can listen on every interface. Agents' servers bind 127.0.0.1.
- MCP servers are off machine-wide for Claude Code and Codex. A skill, plugin or MCP server is
  added only by an evidence record (plan 8.6), and none gets an order tool or broker connector.

## The IBKR paper lane (owner only)

Before a run, the owner sets up the Gateway as `docs/HANDBOOK.md` describes. Then:
- The lane refuses unless the Gateway's `~/Jts/jts.ini` says `tradingMode=p`, the Gateway
  listens on port 4002 only, and it reports one account whose id has the paper form (a D
  prefix, as in NautilusTrader's IB guide examples: a convention, not a documented rule).
  Details in `meridian/boundary.py`.
- Optional, stricter: an allowlist in `risk/boundary.contract.json`. To create it, the owner
  runs this; it shows the reported account and prints the contract only after PAPER is typed:
  `mkdir -p risk && C="$(uv run python -m meridian.boundary contract)" && printf '%s\n' "$C" > risk/boundary.contract.json`
- The paper account has no open order or position in AAPL. The lane refuses to submit if it sees one.

```bash
uv run python -m meridian.ibkr_paper order      # reconcile, one DAY LIMIT order, stop
uv run python -m meridian.ibkr_paper fill       # regular hours: buy 1 that fills, close it
uv run python -m meridian.ibkr_paper restart    # reconcile only; places nothing
```

`order` places one DAY LIMIT BUY of 1 share, 2% under the bid, and cancels it once the venue
accepts it. A pass is "accepted, then cancelled, nothing filled". If the order ever fills, the
run fails, the lane sends no second order, and the owner closes the share by hand.
`fill` runs only on weekdays from 09:30 to 15:55 New York time. It places one DAY LIMIT BUY of
1 share 2% above the ask, so it fills, and on that fill one DAY LIMIT SELL of the filled
quantity 2% under the lower of the bid and the fill price, so the run ends flat. A pass is
"both filled, flat at stop". If an order is still working when the run stops, the run fails and
says so: run `restart` (its record shows any open order or share) before closing anything by hand.
The engine's own output goes to `runs/…-engine.log`, which can show the account id and stays on
this machine; the terminal shows only the lane's lines, and `evidence/` is scrubbed. In order
and fill mode every check runs again after PAPER is typed, and a change to the Gateway in the
meantime (a restart, a re-login, another port) refuses.

## Dependencies

- `uv.lock` is committed. New releases wait 7 days (`exclude-newer`); the engine is the one
  named exception and is pinned exactly.
- The agent runtimes start from checksummed pins in `deploy/wsl/setup.sh` and update themselves
  in sessions the owner starts (Orca's launches do not); `setup.sh agents-check` verifies them.
- NautilusTrader 2.0 is a release-candidate line with breaking changes between candidates.
  Read its release notes before moving the pin, and never answer an API question from memory:
  read the installed package or the tagged source.
