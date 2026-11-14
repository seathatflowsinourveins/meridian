# Meridian handbook

How this harness works: its purpose, its lanes, its rules, the re-entry rules it will carry,
its rate budgets, its run records, how a strategy is added and how a goal is set. `AGENTS.md`
holds the rules every agent follows and points here for the rest. At most 400 lines
(`size-budget.toml`).

## Purpose

In the owner's words, as the approved plan of 2026-11-12 records them (its section 2):

- "All three order lanes (engine sandbox, IBKR paper, Alpaca paper). TradingView through
  every path." All venues "seamlessly", from "sota strategies templates upstream", and
  TradingView's "full landscape".
- "Dormant project trees cleared; one new project. [...] the new repo replaces the sextant line
  on this PC."
- "Memory and retrieval with local embeddings, at upstream quality. Every addition lands with
  an evidence ADR."

The plan reads this as one paper-trading harness on NautilusTrader whose first job was a
reconciled paper order (M1, reached on 2026-11-12), then the three lanes in the order IBKR,
sandbox, Alpaca, then the owner's mover strategy and its re-entry rules, then TradingView as a
display. Paper only throughout: no lane, agent or tool reaches a real-money account.

Milestones (plan 9.2); each ends in a committed, scrubbed run record:

| Milestone | What | State |
|---|---|---|
| M1 | one engine-placed IBKR paper order, reconciled | reached (`evidence/M1-*`) |
| M2 | the sandbox lane on IBKR data; the order budget with its soak; this handbook; the size budget | built; the sandbox's run on IBKR data is the owner's |
| M3 | Alpaca paper: data client and execution adapter, reconciliation against recorded history | adapter merged; entry point built; owner run pending |
| M4 | ranking, the mover strategy and its protection: sandbox, then paper | not started |
| M5 | re-entry and rotation in paper; thresholds calibrated by replay | not started |
| M6, M7 | TradingView display; unattended operation | not started |

## Lanes

| Lane | Orders go to | Market data | What keeps it off a real-money account |
|---|---|---|---|
| IBKR paper (M1) | the IB Gateway logged in to Paper Trading, `127.0.0.1:4002` | the same Gateway | `meridian/boundary.py` refuses unless the Gateway is a paper login, before and after every run |
| Sandbox (M2) | the engine's sandbox execution client, a simulated venue inside the engine | the IB Gateway, data only | no broker at all: no IBKR execution client in its configuration, and a test that fails if one is added |
| Alpaca paper (M3) | Alpaca's paper endpoint | Alpaca | the paper endpoint hard-coded; `tests/test_paper_only.py` fails on a live endpoint or live key name |

No agent starts a lane, in any mode: every run is started and attended by the owner. A run's
terminal check (typing PAPER) only proves a terminal, and agents have terminals too.

### IBKR paper lane (owner only)

Before a run:

- IB Gateway is installed by `deploy/wsl/setup.sh gateway`. The owner starts it with
  `~/Jts/ibgateway/1050/ibgateway` (its window shows through WSLg) and logs in to
  **Paper Trading**. The lane connects to `127.0.0.1:4002` and nowhere else.
- In the Gateway, Configure > Settings > API > Settings: socket port 4002, **Read-Only API
  unticked**, "Allow connections from localhost only" ticked. The Gateway listens on every
  interface (`*:4002`) and the machine uses mirrored networking, so that box is what keeps
  other hosts out. `~/Jts/jts.ini` lists `TrustedIPs=127.0.0.1` only; the box itself is stored
  in the Gateway's encrypted settings and can only be checked in its window.
- Optional: the allowlist in `risk/boundary.contract.json`, created as `AGENTS.md` shows.
- The rc9 source (nautilus_trader@da6b57a:
  crates/adapters/interactive_brokers/src/execution/reports.rs:L204-211) requests all open
  orders with either `fetch_all_open_orders` value; the startup AAPL.XNAS cache check
  includes reconciled external orders and account positions. The order request is a
  snapshot (https://www.interactivebrokers.com/docs/tws-api/doc/order-management/open-orders),
  so it does not guarantee visibility of later orders. Only reports returned and successfully
  cached are visible; Client Portal/mobile coverage remains unverified. Before `fill`, check
  all paper-account AAPL orders and positions by hand in IBKR, across every entry route.

The clean-account condition, the run commands and what a pass looks like are in `AGENTS.md`,
under "The IBKR paper lane (owner only)", not in this file.

### Sandbox lane (M2)

The engine's sandbox execution client is a venue simulated inside NautilusTrader: its own
matching engine fills the strategy's orders against live market data, in a simulated cash
account. Here it takes the IB Gateway's market data and runs upstream's built-in `ExecTester`
strategy on 1 share of AAPL, as upstream's sandbox example does (`meridian/sandbox_node.py`).
The node has one data client, IB's, and the sandbox as its only execution client:
`tests/test_sandbox_lane.py` fails if any other execution client is added, and runs the lane
offline on a fake feed.

Before a run: the Gateway set-up of the IBKR lane above. The account needs no particular
state, because no order goes to it.

```bash
uv run python -m meridian.sandbox_lane run      # owner only, attended; about 90 seconds
```

It runs the IBKR lane's paper checks, asks for PAPER at the terminal, checks again, runs the
node for a minute (the engine's output goes to `runs/...-engine.log`), checks again, and
writes the record. In that minute `ExecTester` buys 1 share at market on the first quote, keeps
a LIMIT buy resting 5.00 USD under the bid, and on stop cancels it and sells the share. A pass
is: the paper checks passed again after the run; the node ran its full time and stopped without
an error (a stop before its time fails the run); the trader started; AAPL.XNAS came from IB and
quotes arrived; the engine registered the sandbox and no other execution client; the strategy
placed orders and the simulated venue accepted one; every order went to the sandbox, was booked
on the simulated account and ended filled, cancelled or expired; none was denied or rejected;
nothing was open at stop. The record is `evidence/M2-sandbox-<stamp>-run.json`.

The lane asks IB for delayed-frozen data, upstream's default, so outside regular hours it
trades against the last quote IB has; the sandbox keeps no trading calendar. A run in which no
quote arrives fails. After a run the owner can check in IB's own window that the paper account
shows no new order. Optional and not yet tried: with Read-Only API ticked the Gateway refuses
orders from every API client; the IBKR lane needs it unticked, and whether market data still
flows with it ticked has not been checked.

### Alpaca paper lane (M3, owner only)

`meridian.alpaca_lane` wires IEX quotes and the [execution adapter](m3-alpaca.md#3-current-adapter-carried-changed-and-omitted) with the [order budget](#rate-budgets).
Quotes carry prices only: Alpaca documents round-lot sizes but its Asset model has no
per-symbol shares-per-lot field ([Asset](https://alpaca.markets/sdks/python/api_reference/trading/models.html#asset),
[quotes](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), read 2026-11-13).
The client validates then drops sizes, publishing zero as unknown following rc9's CoinAPI and
IB adapters (paths and lines in `UPSTREAM.md`); **no consumer may use this lane's quote sizes**.

Before a run: stop the previous writer and confirm it is stopped;
check that AAPL has no open order or position, across every entry route on the paper account.
AAPL is the same equity as upstream's IBKR stock example. Reconciliation claims AAPL.ALPACA;
working orders outside that universe or from another writer refuse. No agent starts either mode.
Copy `deploy/alpaca-lane.template.json` to ignored `local/alpaca-lane.json`; fill its two null fields: `order_budget_rows_path`
(relative to that file or absolute) and `quote_max_age_ns` (positive integer; no code default).
Both files belong outside the tree or under `local/` (backups there are ignored too); [rows must pass the production loader](#rate-budgets).
Missing/invalid values refuse without printing paths or values; `--settings` selects the settings file.

#### Alpaca credentials

The owner creates the two encrypted files in a distro terminal (no TPM, so the host key):
```bash
sudo systemd-creds setup
systemd-ask-password -n "Alpaca paper key id:" | sudo systemd-creds encrypt --with-key=host --name=alpaca-paper-key-id - /etc/credstore.encrypted/alpaca-paper-key-id
systemd-ask-password -n "Alpaca paper secret key:" | sudo systemd-creds encrypt --with-key=host --name=alpaca-paper-secret-key - /etc/credstore.encrypted/alpaca-paper-secret-key
```
`deploy/systemd/meridian-alpaca-paper.service` is prepared, not installed/enabled, and has no `[Install]` section. It runs as `paper`, loads both credentials by absolute path (missing files prevent startup), and runs only `python -m meridian.alpaca.credentials`: presence/format checks, no socket. M7 installs `/opt/meridian`. The loader refuses missing credentials; key values come only from their files, whose directory is named by `CREDENTIALS_DIRECTORY`.

From the repository root, in a distro terminal the owner started outside Orca, use the system
manager (the existing encrypted credentials target it, not the per-user manager):

```bash
sudo systemd-run --pty --wait --collect --service-type=exec \
  --unit=meridian-alpaca-attended --uid="$(id -u)" --gid="$(id -g)" \
  --working-directory="$PWD" --property=UMask=0077 \
  --property=LoadCredentialEncrypted=alpaca-paper-key-id:/etc/credstore.encrypted/alpaca-paper-key-id \
  --property=LoadCredentialEncrypted=alpaca-paper-secret-key:/etc/credstore.encrypted/alpaca-paper-secret-key \
  "$PWD/.venv/bin/python" -m meridian.alpaca_lane restart
```

Replace the final `restart` with `order` for the one-order run; append `--settings /absolute/path`
for another local settings file. `--pty` supplies the terminal for PAPER; `--wait` waits even
if the PTY is detached. The fixed unit name prevents overlapping instances of this command,
but cannot exclude another writer. `--uid` uses the owner's current checkout permissions.
This command follows installed systemd 259's systemd-run(1) and systemd.exec(5), read 2026-11-13.
It was **not run**: credential loading/decryption, TTY attachment, sudo policy and the actual
paper connection remain untested; only the owner may perform that attended check.

`restart` reconciles, sends no order or cancel, stops, and passes only with the instrument clean
and execution coverage complete. `order` asks for PAPER, repeats all local checks, then buys
one share with a DAY LIMIT 2% below a fresh bid, rounded down to the venue tick. It checks
`quote_age_ns` before pricing and again at paced submission; missing/stale quotes place nothing.
It requests cancellation once accepted. A pass is accepted, then cancelled, nothing filled,
flat with no open or in-flight order at stop. Any fill fails and sends no second order; the
owner inspects and closes any share by hand. An unresolved order also fails: inspect it before
acting; there is no stop-time cancel or close. The M1 time limits apply (25 s restart, 60 s order).
All local checks run again after the run. Engine output and failures stay in `runs/`; passing
records go to `evidence/M3-alpaca-paper-<stamp>-<mode>.json`. Public records contain no broker
text or identifiers, include commission citations and counts of paper-default/reviewed budget
rows (also shown at the terminal), and record only the quote-age limit's presence. No real run has been performed.

`uv run python -m meridian.alpaca_sim` is a simulation, not a lane; no typed word. It exercises the unchanged one-order strategy and native engine order flow, excluding the Alpaca adapter, order budget, credentials, streams and venue.
Quotes are synthetic, generated in process: no market or recorded data, no real price.
PASS means accepted, then cancelled, nothing filled and flat at stop; any fill means FAIL.
Records go only to `runs/*-simulation.json`, never `evidence/`; it is offline and keyless.

## Rules

| Rule | Where it is held | How |
|---|---|---|
| Paper only: no route to a real-money account is created, enabled or tested | `meridian/boundary.py` for IBKR; the sandbox's wiring; Alpaca's hard-coded paper endpoint (M3) | refused at run time |
| | `tests/test_paper_only.py`: live endpoints, ports, trading modes, key names | CI tripwire |
| Only the engine places orders; no agent, script, skill or MCP server gets an order tool or broker connector; no agent starts a lane | `AGENTS.md` | rule |
| `risk/` and `*.contract.json` belong to the owner | `AGENTS.md`; `.gitignore` keeps every contract copy out of git | rule |
| No credential or key value is read, printed, copied or moved | `AGENTS.md`; gitleaks over the whole history in CI | rule; CI tripwire |
| Nothing derived from an account and no calibrated parameter in this public repository; such data goes to the private `meridian-evidence` | `tests/test_public_tree.py` (account-id shapes, allowlist copies); run records scrubbed before writing | CI tripwire |
| CI is fork-safe: no self-hosted runner, no `pull_request_target`, no secret a fork could reach | `tests/test_public_tree.py` | CI tripwire |
| Every install or integration has an `UPSTREAM.md` row, marked upstream or own design | `AGENTS.md` | rule |
| Upstream files are verbatim copies; harvested own-design files say what changed | `tests/test_upstream_unmodified.py`, `tests/test_order_budget_harvest.py` | CI |
| New Python releases wait 7 days; the engine is pinned exactly | `pyproject.toml` (`exclude-newer`), Dependabot's cooldown | resolver |
| One evidence ADR per ecosystem addition, at most 60 lines | `docs/adr/README.md`, `tests/test_size_budget.py` | rule; CI |
| The size budget | `size-budget.toml`, `tests/test_size_budget.py` | CI tripwire |
| The owner sets goals; a goal never names a lane run, an order, the IB Gateway, port 4002 or a step only the owner takes | "Goals" below | rule |
| Work is reviewed by a different model family before it merges; findings are fixed or closed with a reason; nothing auto-files issues | plan 9.5 | rule |
| One writer per account; plain DAY LIMIT entries, no brackets | plan 9.1 | rule; the M1 record fails an order that is not a DAY LIMIT |

A tripwire catches a mistake, not a determined change: agents here run in bypass mode and can
edit the tests too. The owner's GitHub settings are the lock, where GitHub offers one.

## Re-entry and rotation (own design; thresholds uncalibrated)

The owner's own design, carried from Sextant's ADR-0006 (`seathatflowsinourveins/sextant` at
`33cdee7b`, `docs/adr/0006-reentry-and-rotation.md`), itself from the owner's earlier repos.
No upstream ships these rules. Nothing of them is built here yet (M5). **Every threshold is
uncalibrated**: Sextant's replay registry gives each one as a named parameter with no value,
and its Paper B registry has one value, marked `UNCALIBRATED`. M5 calibrates them by replay;
tuned values go to `meridian-evidence`, never into this repository.

- **R1, flat first, then a cooldown.** Re-enter only after a broker-flat receipt (net zero, and
  every entry, protective and replacement order final; unknown or partial is not flat), and
  only `cooldown_seconds` after that receipt, not after the sell.
- **R2, retry, rotate or wait.** Retry the same symbol if its setup fires and its parent rank is
  within `retry_rank_band`; else rotate into the best unheld, independently qualified name
  within `rotation_rank_band`; else wait.
- **R3, reclaim.** Within `reclaim_lookback_s` since our sell the name traded at or below the
  sell trigger or the segment VWAP, then above it for `reclaim_trades_count` trades over
  `reclaim_trades_span_s`, with covered flow. Buy at most `reclaim_max_above_buffers` above the level after a held
  higher-low retest of `reclaim_hold_s`. Never the first print.
- **R3a, whipsaw.** After `whipsaw_stopouts_max` stop-outs in a row before the gain lock arms,
  the next entry on that symbol needs a capped reclaim or a qualifying OVERSELL; rising alone
  is not enough.
- **R3b, OVERSELL flush.** A flush below the sell price by `flush_min_depth` within
  `flush_window_s`, a selling climax (`climax_ratio` over `climax_window_s`), a held higher low
  (`oversell_hold_s`) and buy flow (`buy_flow_ratio` over `flow_window_s`), with a live
  catalyst if there is one and a rank within `retry_rank_band`; buy at most
  `oversell_max_above_buffers` above the higher low. Shadow only until the trade classifier's
  coverage is shown.
- **Confidence and size.** A same-symbol re-entry needs `reentry_min_confidence`; a missing
  confidence is refused before sizing, never taken as 1. Its size is scaled by
  `confidence_size_floor + (1 - confidence_size_floor) x confidence`.
- **R4, held rotation.** Swap a held name only if the pair's expected lift exceeds
  `2 x round-trip cost / price + rotation_lift_margin_bps / 10,000`, and the target scores at
  least `rotation_score_ratio` times the weakest holding.
- **R5, freshness.** A missing, stale or ambiguous ranking means wait: no stale fallback.
- **R6, modes.** Paper re-entry has no count cap. IBKR paper re-entry stays off. The capped,
  non-renewing mode is for a live lane and does not apply in this repository.

They serve the mover strategy (M4, own design): long-only US equities ranked live by price
move times dollar-volume ratio against each symbol's time-matched baseline, entered on the
first rising leg with a LIMIT at the ask, protected by a rising sell trigger. In Sextant's
replay, holding each entry to 15:55 ET beat all 96 active-exit variants (plan 9.1); that is a
replay, not a walk-forward validation.

## Rate budgets

| Venue | Its limit | The budget here | Held by |
|---|---|---|---|
| Alpaca (M3) | 200 requests per minute per account, every request counted; 429 past it | documented fixture: 180 paced requests in any 60 s window, burst 18; production uses owner rows below; CANCEL > REDUCE > MODIFY > QUERY > SUBMIT | `meridian/order_budget/` |
| IBKR | 50 messages per second from all clients of one Gateway together; error 100 past it, and a likely disconnect | none yet: a run of the M1 or the sandbox lane sends a few messages | n/a |
| Sandbox | none: the venue is simulated inside the engine | none needed | n/a |

The order budget is the owner's account pacer, harvested from Sextant (see `UPSTREAM.md`).
Every request takes a token; with the fixture rows, the bucket holds 18 and refills one token every
370,370,371 ns. A request past the budget waits in the pacer's queue, most urgent kind first;
its caller can withdraw it, and then it is dropped without being sent. An entry also waits
until the bucket holds more tokens than its protection reserve, so protective orders keep room;
only an entry whose reserve would reach the whole burst is refused (`PacerRefused` when it is
requested, `refuse(reason)` if it gets there while queued), and one whose reserve cannot be
worked out is dropped, so a caller checks reserve authority in its own admission. The soak
(`uv run python -m meridian.order_budget.soak`: offline, one simulated hour against a venue that
answers 429 past 200 a minute, with quiet spells in which the bucket fills up again) measured
at most 179 in any window, before and after each quiet spell, 161 to 163 a minute under steady
overload, no 429, no withdrawn entry sent, and every cancel and reduce sent. The budget holds
within one pacer: a new one starts with a full burst, so a lane that restarts within a minute
of its last request can add up to 18 to that window; Alpaca starts each new pacer empty, including after reconnect.

For Alpaca, copy `deploy/alpaca-order-budget.template.json` to the owner-held `order_budget_rows_path`; fill all fields of its 16 rows
with truthful sources and `REVIEWED` or unreviewed `PAPER_DEFAULT` scopes; optional null reserves may use `UNAVAILABLE`.
`meridian/alpaca/pacing.py` maps `PAPER_DEFAULT` for M2's unchanged validation and returns separate scope counts; missing/invalid or `FIXTURE_ONLY` rows refuse without values.
The venue limit must be 200 per 60 s; this repo supplies no production values. Fixture 429 backoff starts at 1 s and doubles to 30 s; production uses its rows.

The engine's own limits are only a backstop: its risk engine throttles submits and modifies
(100 a second each by default) and denies the excess, but a strategy's cancels and queries
pass unthrottled.

## Run records

Every run that passes writes one record to `evidence/`; a failed run writes to `runs/` only,
which git ignores and which may hold account ids.

- Name: `<milestone>-<lane>-<UTC stamp>-<mode>.json`, for example
  `M1-ibkr-paper-20261113T004629Z-order.json`.
- JSON with sorted keys, a two-space indent and one trailing newline.
- Every record has `schema` (`meridian.run-record/1`), `milestone`, `lane`, `mode`, `result`
  (`pass` or `fail`), `problems` (empty on a pass), `run_started_utc` and `run_ended_utc`.
- The rest is the lane's. IBKR paper: `boundary`, `gateway` (its `port` and how that port is
  bound, `bind`), `engine`, `startup_reconciliation`, `orders_refused` (a count, in every
  mode), `order`, `close_order` (fill mode only), `events`, `at_stop`, `engine_error`; the
  four M1 records of 2026-11-12 and 13 were written before `bind` and `orders_refused` and
  lack them. The order budget's soak: `budget`, `simulated_venue`, `demand`, `observed`,
  `component`, `offline`. The sandbox lane: `gateway`, `boundary`, `engine`, `node` (its
  clients), `strategy`, `trader_started`, `market_data`, `orders` (each with the execution
  client that took it), `events`, `at_stop`, `engine_error`.
- Scrubbed: normalised fields only. No account id, no hash of one, no broker or engine free
  text; those stay in `runs/`. `meridian/ibkr_paper.py` refuses to write a record that holds
  the account id or its hash.
- Checked by `tests/test_evidence_records.py` (every committed record: its name, this format,
  the common fields, a pass), `tests/test_run_record.py` and `tests/test_sandbox_lane.py` (the
  writers), `tests/test_order_budget_soak.py` and `tests/test_public_tree.py` (account-id
  shapes anywhere). The soak keeps one record, the latest: a fresh run must reproduce it field
  for field, and a passing run replaces it.

## How to add a strategy

1. Start from an upstream template: a NautilusTrader example or built-in strategy at the pinned
   version, or a cited published method. Name it in the strategy file's docstring (repository,
   path, version or commit). If no upstream fits, write "own design" and why.
2. Never edit an upstream file. Vendor it verbatim under `upstream/` with its licence and
   subclass it, as `meridian/ibkr_node.py` does with upstream's `IbV2OrderStrategy`.
3. Add its `UPSTREAM.md` row in the same commit.
4. Parameters: the template's defaults. Tuned values go to `meridian-evidence`, not here.
5. Tests: it builds offline against the pinned engine, and it runs in the sandbox lane on the
   fake feed, as `tests/test_sandbox_lane.py` does with upstream's strategy. A strategy never
   adds an execution client.
6. Sandbox first, then paper (plan 9.2). Every paper run is the owner's, attended, and ends in
   a run record.

## Goals

A goal makes an agent runtime keep taking turns on its own until a stated end state holds. The
owner sets goals. That is a rule, not a lock: an agent with a shell can start one (Claude Code,
below). Whether Claude Code's model may propose one rests first on a feature flag of
Anthropic's; the owner can only narrow it (`modelProposedGoals`, below), and nothing in this
repository changes either. A goal here:

- names one measurable end state, proved by a command whose exit code decides and whose output
  the session prints: no runtime below runs a check of its own, so the decision rests on what
  the session has shown;
- carries a turn bound, "or stop after N turns";
- never names a lane run, an order, the IB Gateway or port 4002, or a step only the owner takes
  (a trust dialog, a key, a merge, an attended run).

```text
/goal on this branch uv sync --locked and the check line under "Commands" in AGENTS.md exit 0, their last lines printed; or stop after 20 turns
/goal uv run pytest -q tests/test_size_budget.py exits 0 and git diff --quiet <start> -- size-budget.toml tests/test_size_budget.py; echo "exit $?" prints exit 0, both outputs printed; or stop after 10 turns
```

`<start>` is the full hash of the commit the goal starts from. With no base, `git diff` compares
with the index only, so a raised limit passes once it is staged; a branch name moves with the
agent's commits. `git diff --quiet` prints nothing, hence the `echo`. The test file is guarded
too; a change elsewhere that alters its run, such as a `conftest.py` skipping it, is not caught.

| Runtime, version read | Set; stop | Who decides it is met; its own bound | Source, read 2026-11-13 |
|---|---|---|---|
| Claude Code 2.1.322 | `/goal <condition>`; `/goal clear`; also `claude -p "/goal ..."` | a small fast model after each turn, from the conversation only; no turn cap | https://code.claude.com/docs/en/goal and https://code.claude.com/docs/en/permissions, "Project allow rules and workspace trust" and "What runs before you trust a folder" (both unversioned); the settings schema and the ProposeGoal tool in `~/.local/share/claude/versions/2.1.322` |
| Codex CLI 0.167.2 | `/goal <objective>`; `/goal pause`, `resume`, `clear` | the working model (`update_goal`); an optional token budget | https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex (unversioned); `codex-rs/ext/goal/src/spec.rs` and `codex-rs/features/src/lib.rs` at tag `rust-v0.167.2` |
| DeepSeek Harness 0.2.2-rc.1 | `/goal` to create, edit, pause, resume or clear | the working model, no independent evaluator; 256 rounds by default (`defaultMaxGoalRounds`) | `deepseek-ai/deepseek-harness` at `66491b0` (tag `dsh-v0.2.2-rc.1`), `packages/bundle/base/cordis.patch.yml` lines 327-334; the `dsh-goal`, `dsh-command-goal` and `dsh-tool-goal` READMEs in the installed package |
| Antigravity CLI 1.5.7 | `/goal <objective>`; ask it to stop, or start another `/goal` | the working model, told at each stop to audit its own work; no iteration cap | https://antigravity.google/docs/commands/goal.md and https://antigravity.google/docs/cli/reference.md (unversioned) |

Claude Code runs a goal as a session-scoped Stop hook and offers `/goal` under the trust rule
for hooks in settings files. An interactive session needs the repository trusted: Claude Code
keys trust on the repository root, in a worktree on the main checkout's root, so trusting
`~/src/meridian` covers the clone and every worktree, and a trusted folder above a checkout
(`~/src`, `~/src/meridian-worktrees`) does not count. Accepting that dialog is the owner's step.
`claude -p` and SDK runs never show the dialog and run `/goal` in any folder, so trust does not
stop an agent from starting a goal. `/goal` is off while `disableAllHooks` is true or managed
settings set `allowManagedHooksOnly`. Its model gets a ProposeGoal tool only when the feature
flag `tengu_propose_goal` is on, and never in a non-interactive run; that flag is off by default
in 2.1.322 and was not among the flags cached in the distro's `~/.claude.json` on 2026-11-13.
`modelProposedGoals` can narrow the tool but not turn it on: `auto` (the default; the model
chooses whether to ask first), `alwaysAsk` or `disabled`. A typed `/goal` is unaffected. Claude
Code takes that key's value from user, managed and command-line settings only, and a project's
files cannot loosen it; the key is marked internal in the 2.1.322 settings schema and is not on
the docs pages read.

Codex's `create_goal` tool tells its model to start a goal only when the user or the
instructions ask; DeepSeek Harness refuses a model-created goal without a direct human request
in that turn. `codex features list` shows `goals` stable and on.

## Size budget, ADRs and this file

- `size-budget.toml` sets the limits and `tests/test_size_budget.py` checks them: `AGENTS.md`
  at most 120 lines and `CLAUDE.md` 1, this handbook at most 400, each ADR at most 60, and
  totals for agent instructions, prose, config, workflows and skills; every tracked file must be
  of a kind the file names. It is a tripwire: see the file's header for why GitHub cannot lock
  it while every push comes from the owner's account. The open-issue count is not checked:
  without a token CI can read only issues and pull requests together.
- ADRs: `docs/adr/README.md` (format and index).
- The IBKR lane's run commands, clean-account condition and pass criteria are in `AGENTS.md`
  ("The IBKR paper lane (owner only)"), not in this file.
