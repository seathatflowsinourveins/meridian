# Meridian

A paper-trading harness on NautilusTrader. One repo, one WSL2 distro (`meridian`). Paper only.

## Boundaries (set by the owner; not yours to change)

- **Paper trading only.** Never create, enable or test a route to a real-money account.
  `tests/test_paper_only.py` fails the build if a real-money endpoint, port, trading mode or
  key name appears. That scan is a tripwire; the boundary itself is `meridian/boundary.py`.
- **`risk/` and `*.contract.json` belong to the owner.** Read them. Never create or edit them.
- **Only the engine places orders**, in a run the owner starts and attends. No agent, script or
  tool call submits, changes or cancels an order directly. Order mode asks for a typed word at
  a terminal and refuses without one; do not work around that.
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
- Ask the owner before adding a paid service or an account.

## Working rules

- Everything installed or integrated has a row in `UPSTREAM.md`, added in the same commit:
  version or commit, the URL that was read, the date, what it is for, "upstream" or "own design".
- Start from upstream's own example. Files under `upstream/` are verbatim copies and are never
  edited; `tests/test_upstream_unmodified.py` checks them.
- Check a finding at its source before acting on it. Find the root cause before disabling a check.
- Run the checks before saying something works. Report a failure as a failure.
- Add nothing the current milestone does not need.

## Layout

| Path | What it is |
|---|---|
| `deploy/wsl/` | the distro definition (cloud-init) and the user-level setup script |
| `meridian/boundary.py` | the paper checks: Gateway login mode, ports, account form, optional allowlist (own design) |
| `meridian/ib_probe.py` | asks the Gateway which accounts it manages (own design) |
| `meridian/ibkr_paper.py` | IBKR paper lane: gate, owner confirmation, run record |
| `meridian/ibkr_node.py` | the engine side, built on upstream's example |
| `upstream/` | upstream example files, unmodified |
| `risk/boundary.contract.json` | optional: the owner's allowlist of paper accounts |
| `evidence/` | scrubbed run records, one per attended run that passed |
| `runs/` | local run output, ignored by git; may hold account ids |

## Commands

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

## The IBKR paper lane (owner only)

Before a run:

- IB Gateway is installed by `deploy/wsl/setup.sh gateway`. The owner starts it with
  `~/Jts/ibgateway/1050/ibgateway` (its window shows through WSLg) and logs in to
  **Paper Trading**. The lane connects to `127.0.0.1:4002` and nowhere else.
- In the Gateway, Configure > Settings > API > Settings: socket port 4002, **Read-Only API
  unticked**, "Allow connections from localhost only" ticked.
- The lane refuses unless the Gateway's `~/Jts/jts.ini` says `tradingMode=p`, the Gateway
  listens on port 4002 only, and it reports one account whose id has the paper form (a D
  prefix: an observed convention, not a documented rule). Details in `meridian/boundary.py`.
- Optional, stricter: an allowlist in `risk/boundary.contract.json`. To create it, the owner
  runs this; it shows the reported account and prints the contract only after PAPER is typed:
  `mkdir -p risk && C="$(uv run python -m meridian.boundary contract)" && printf '%s\n' "$C" > risk/boundary.contract.json`
- The paper account has no open order or position in AAPL. The lane refuses to submit if it does.

```bash
uv run python -m meridian.ibkr_paper order      # reconcile, one DAY LIMIT order, stop
uv run python -m meridian.ibkr_paper restart    # reconcile only; places nothing
```

`order` places one DAY LIMIT BUY of 1 share, 2% under the bid, and cancels it once the venue
accepts it. A pass is "accepted, then cancelled, nothing filled". If the order ever fills, the
run fails, the lane sends no second order, and the owner closes the share by hand.
The terminal output of a run can show the account id; only `evidence/` is scrubbed.

## Dependencies

- `uv.lock` is committed. New releases wait 7 days (`exclude-newer`); the engine is the one
  named exception and is pinned exactly.
- NautilusTrader 2.0 is a release-candidate line with breaking changes between candidates.
  Read its release notes before moving the pin, and never answer an API question from memory:
  read the installed package or the tagged source.
